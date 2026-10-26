"""Transactional WorkItem storage; items.json is a portable compatibility export.

The first schema keeps the existing task/decision documents and IDs. Source
connectors must use this store rather than treating the JSON export as writable.
"""
from contextlib import closing, contextmanager
import copy
import hashlib
import json
import re
import datetime as dt
from pathlib import Path
import shutil
import sqlite3
import fcntl
import threading

from .storage import atomic_json


class WorkItemConflict(ValueError):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def normalize(item):
    states = {'task': {'open', 'done'}, 'decision': {'proposed', 'accepted', 'superseded'}}
    if (item.get('kind') not in states or item.get('status') not in states[item['kind']]
            or not isinstance(item.get('text'), str) or not item['text'].strip()
            or not isinstance(item.get('id'), str) or not re.fullmatch(r'[a-f0-9]{1,64}', item['id'])
            or not isinstance(item.get('links'), list)):
        raise ValueError('Invalid legacy WorkItem; the original items.json was kept')
    item.setdefault('dismissed', False)
    item.setdefault('snoozed_until', None)
    if type(item['dismissed']) is not bool:
        raise ValueError('Invalid WorkItem disposition')
    for link in item['links']:
        if (not isinstance(link, dict) or not isinstance(link.get('meeting_id'), str)
                or not re.fullmatch(r'[a-f0-9]{32}', link['meeting_id'])
                or not isinstance(link.get('seen', {}), dict)):
            raise ValueError('Invalid WorkItem source link')
    if item['snoozed_until'] is not None:
        if dt.date.fromisoformat(item['snoozed_until']).isoformat() != item['snoozed_until']:
            raise ValueError('Invalid WorkItem snooze date')
    fields = ('text', 'status', 'owner', 'deadline', 'due_date') if item['kind'] == 'task' else ('text', 'status')
    item['field_authority'] = {field: 'user' if field in item.get('manual', []) or field == 'status'
                               else 'meeting_proposal' for field in fields}
    linked = {link['meeting_id'] for link in item.get('links', [])}
    evidence = {entry['id']: entry for entry in item.get('evidence', []) if entry.get('source_id') in linked}
    for link in item.get('links', []):
        source = dict(provider='meeting', account='local', external_id=link['meeting_id'])
        link['source'] = source
        quoted = link.get('seen', {}).get('task' if item['kind'] == 'task' else 'text')
        quote = quoted or item['text']
        snapshot = dict(source_id=link['meeting_id'], quote=quote, timestamp=link.get('evidence_timestamp'))
        revision = hashlib.sha256(canonical(snapshot).encode()).hexdigest()
        evidence[revision] = dict(snapshot, id=revision, provider='meeting', quote_kind='meeting_note' if quoted else 'item_text',
                                  revision=revision, revision_kind='mention_snapshot')
    item['evidence'] = list(evidence.values())
    return item


class WorkItemStore:
    def __init__(self, path: Path, export: Path):
        self.path, self.export = path, export
        path.parent.mkdir(parents=True, exist_ok=True)
        self._thread_lock = threading.RLock()
        self._lock_active = False
        with self.serialized():
            self._initialize()

    @contextmanager
    def serialized(self):
        # Keep database commits and the generated JSON projection in one writer
        # order. The lock is reentrant for snapshot/restore on this store.
        with self._thread_lock:
            if self._lock_active:
                yield
                return
            with self.path.with_suffix('.lock').open('a') as handle:
                fcntl.flock(handle, fcntl.LOCK_EX)
                self._lock_active = True
                try:
                    yield
                finally:
                    self._lock_active = False
                    fcntl.flock(handle, fcntl.LOCK_UN)

    def _initialize(self):
        export = self.export
        with closing(self.connect()) as db:
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0, 1):
                raise ValueError('This WorkItem database needs a newer app version')
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS registry_meta (
                    id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL, initialized INTEGER NOT NULL);
                INSERT OR IGNORE INTO registry_meta VALUES (1,0,0);
                CREATE TABLE IF NOT EXISTS work_items (
                    id TEXT PRIMARY KEY, kind TEXT NOT NULL, revision INTEGER NOT NULL, document TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS item_revisions (id TEXT PRIMARY KEY, revision INTEGER NOT NULL);
                INSERT OR IGNORE INTO item_revisions SELECT id, revision FROM work_items;
                PRAGMA user_version=1;
            ''')
            initialized = db.execute('SELECT initialized FROM registry_meta WHERE id=1').fetchone()[0]
        if not initialized:
            data = dict(version=2, items={})
            if export.exists():
                try:
                    data = json.loads(export.read_text())
                    if not isinstance(data, dict) or not isinstance(data.get('items'), dict):
                        raise ValueError()
                    for item_id, item in data['items'].items():
                        if not isinstance(item, dict) or item.get('id') != item_id:
                            raise ValueError()
                        normalize(item)
                except (OSError, ValueError, TypeError, KeyError) as exc:
                    raise ValueError('Cannot migrate items.json. Restore a valid copy; the original file was kept.') from exc
                legacy = export.with_name('items.before-sqlite.json')
                if not legacy.exists():
                    shutil.copy2(export, legacy)
            self._save(data, 0)

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def load(self, repair_export=True):
        with self.serialized():
            return self._load(repair_export)

    def _load(self, repair_export):
        with closing(self.connect()) as db:
            db.execute('BEGIN')
            revision = db.execute('SELECT revision FROM registry_meta WHERE id=1').fetchone()[0]
            records = db.execute('SELECT id, document FROM work_items ORDER BY rowid').fetchall()
        data = dict(version=2, registry_revision=revision, items={key: json.loads(value) for key, value in records})
        if not repair_export:
            return data, revision
        # A stale export can result from a crash after the database commit.
        # Edits to the current export are rejected instead of silently discarded.
        exported = None
        if self.export.exists():
            try:
                exported = json.loads(self.export.read_text())
            except ValueError:
                exported = None
            if isinstance(exported, dict) and type(exported.get('registry_revision')) is int and exported['registry_revision'] > revision:
                raise ValueError('items.json is newer than this database. Keep both files and restore a matching library.')
            if (isinstance(exported, dict) and exported.get('registry_revision') == revision
                    and exported.get('items') != data['items']):
                raise ValueError('items.json was edited outside the app. Keep that copy and reload from work-items.sqlite3.')
        if not self.export.exists() or exported != data:
            atomic_json(self.export, data)
        return data, revision

    def save(self, data, expected_revision):
        with self.serialized():
            return self._save(data, expected_revision)

    def _save(self, data, expected_revision):
        # Mutate callers' documents only after commit; a failed transaction must
        # not publish revisions or partially normalized records in memory.
        prepared = {}
        for key, item in data['items'].items():
            if key != item.get('id'):
                raise ValueError('WorkItem ID does not match its registry key')
            prepared[key] = normalize(copy.deepcopy(item))
        with closing(self.connect()) as db:
            try:
                db.execute('BEGIN IMMEDIATE')
                current, initialized = db.execute('SELECT revision,initialized FROM registry_meta WHERE id=1').fetchone()
                if current != expected_revision:
                    raise WorkItemConflict('Work items changed. Reload the list and try again.')
                old = {key: (revision, json.loads(document)) for key, revision, document in
                       db.execute('SELECT id, revision, document FROM work_items')}
                if initialized and self.export.exists():
                    try:
                        exported = json.loads(self.export.read_text())
                    except ValueError:
                        exported = None
                    if (isinstance(exported, dict) and exported.get('registry_revision') == current
                            and exported.get('items') != {key: document for key, (_, document) in old.items()}):
                        raise WorkItemConflict('items.json was edited outside the app. Keep that copy and restore the generated export before editing.')
                counters = dict(db.execute('SELECT id, revision FROM item_revisions'))
                changed = not initialized or set(old) != set(prepared)
                for key, item in prepared.items():
                    previous_revision, previous = old.get(key, (0, {}))
                    comparable = dict(item)
                    comparable.pop('revision', None)
                    previous.pop('revision', None)
                    different = comparable != previous
                    item['revision'] = previous_revision + 1 if different else previous_revision
                    if key not in old:
                        imported_revision = data['items'][key].get('revision', 1)
                        if type(imported_revision) is not int or imported_revision < 1:
                            imported_revision = 1
                        item['revision'] = max(counters.get(key, 0) + 1, imported_revision)
                    if different:
                        changed = True
                        db.execute('INSERT OR REPLACE INTO work_items VALUES (?,?,?,?)',
                                   (key, item['kind'], item['revision'], canonical(item)))
                        db.execute('INSERT OR REPLACE INTO item_revisions VALUES (?,?)', (key, item['revision']))
                for key in old.keys() - prepared.keys():
                    db.execute('DELETE FROM work_items WHERE id=?', (key,))
                revision = current + int(changed)
                db.execute('UPDATE registry_meta SET revision=?, initialized=1 WHERE id=1', (revision,))
                db.commit()
            except BaseException:
                db.rollback()
                raise
        for key, item in prepared.items():
            data['items'][key].clear()
            data['items'][key].update(item)
        data.update(version=2, registry_revision=revision)
        if changed or not self.export.exists():
            atomic_json(self.export, data)
        return revision
