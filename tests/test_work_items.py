import copy
import datetime as dt
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

from app import backup, items
from app.service import MeetingService
from app.storage import atomic_json
from app.work_items import WorkItemConflict
from tests.test_calendar import FakeGoogle
from tests.test_items import task, decision, notes
from tests import test_http

PROJECT = Path(__file__).resolve().parents[1]


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / 'items.json'

    def seed(self):
        registry = items.Registry(self.path)
        key = registry.create('task', dict(task('Synthetic task'), status='open'), 'a' * 32)
        registry.save()
        return registry, key

    def test_migration_retains_identity_history_manual_fields_and_original(self):
        registry, key = self.seed()
        registry.update(key, dict(owner='Synthetic person', status='done'))
        registry.save()
        original = copy.deepcopy(registry.data)
        for file in self.root.glob('work-items.sqlite3*'):
            file.unlink()
        self.path.write_text(json.dumps(original))
        raw = self.path.read_bytes()
        migrated = items.Registry(self.path)
        self.assertEqual((self.root / 'items.before-sqlite.json').read_bytes(), raw)
        self.assertEqual(migrated.items[key], original['items'][key])
        revision = migrated.items[key]['revision']
        migrated.save()
        self.assertEqual(items.Registry(self.path).items[key]['revision'], revision)

    def test_invalid_legacy_input_is_not_replaced_by_empty_registry(self):
        self.path.write_text('{invalid')
        with self.assertRaisesRegex(ValueError, 'Cannot migrate'):
            items.Registry(self.path)
        self.assertEqual(self.path.read_text(), '{invalid')

    def test_stale_writer_reloads_without_overwriting_newer_data(self):
        first, key = self.seed()
        second = items.Registry(self.path)
        first.update(key, dict(owner='First person'))
        first.save()
        second.update(key, dict(owner='Second person'))
        with self.assertRaises(WorkItemConflict):
            second.save()
        self.assertEqual(second.items[key]['owner'], 'First person')
        self.assertEqual(items.Registry(self.path).items[key]['owner'], 'First person')

    def test_export_failure_after_commit_recovers_from_database(self):
        registry, key = self.seed()
        registry.update(key, dict(status='done'))
        with patch('app.work_items.atomic_json', side_effect=OSError('synthetic disk failure')):
            with self.assertRaises(OSError):
                registry.save()
        recovered = items.Registry(self.path)
        self.assertEqual(recovered.items[key]['status'], 'done')
        self.assertEqual(json.loads(self.path.read_text())['items'][key]['status'], 'done')

    def test_invalid_batch_does_not_partially_commit(self):
        registry, key = self.seed()
        old = items.Registry(self.path).items[key]['status']
        registry.update(key, dict(status='done'))
        registry.items['bad'] = dict(id='bad', kind='unsupported', text='Invalid')
        with self.assertRaises(ValueError):
            registry.save()
        self.assertEqual(items.Registry(self.path).items[key]['status'], old)

    def test_current_export_edits_are_reported(self):
        _, key = self.seed()
        exported = json.loads(self.path.read_text())
        exported['items'][key]['owner'] = 'Out-of-band edit'
        atomic_json(self.path, exported)
        with self.assertRaisesRegex(ValueError, 'edited outside'):
            items.Registry(self.path)
        self.assertEqual(json.loads(self.path.read_text())['items'][key]['owner'], 'Out-of-band edit')

    def test_runtime_export_edit_blocks_save_without_overwriting_either_copy(self):
        registry, key = self.seed()
        exported = json.loads(self.path.read_text())
        exported['items'][key]['owner'] = 'External edit'
        atomic_json(self.path, exported)
        registry.update(key, dict(status='done'))
        with self.assertRaisesRegex(WorkItemConflict, 'edited outside'):
            registry.save()
        self.assertEqual(registry.items[key]['status'], 'open')
        self.assertEqual(json.loads(self.path.read_text())['items'][key]['owner'], 'External edit')
        with registry.store.connect() as db:
            document = json.loads(db.execute('SELECT document FROM work_items WHERE id=?', (key,)).fetchone()[0])
        self.assertEqual(document['status'], 'open')

    def test_projection_writer_serializes_other_store_readers(self):
        first, key = self.seed()
        second = items.Registry(self.path)
        entered, release, loaded = threading.Event(), threading.Event(), threading.Event()
        real_atomic = atomic_json
        def slow_export(path, data):
            entered.set()
            if not release.wait(5):
                raise RuntimeError('test release timeout')
            real_atomic(path, data)
        first.update(key, dict(status='done'))
        failures = []
        def writer():
            try:
                first.save()
            except BaseException as exc:
                failures.append(exc)
        def reader():
            try:
                second.data, second.revision = second.store.load()
                loaded.set()
            except BaseException as exc:
                failures.append(exc)
        with patch('app.work_items.atomic_json', side_effect=slow_export):
            writing = threading.Thread(target=writer)
            writing.start()
            self.assertTrue(entered.wait(5))
            reading = threading.Thread(target=reader)
            reading.start()
            try:
                self.assertFalse(loaded.wait(.1))
            finally:
                release.set()
                writing.join(5)
                reading.join(5)
        self.assertFalse(writing.is_alive() or reading.is_alive())
        self.assertEqual(failures, [])
        self.assertTrue(loaded.is_set())
        self.assertEqual(json.loads(self.path.read_text())['items'][key]['status'], 'done')

    def test_restored_item_does_not_reuse_deleted_revision(self):
        registry, key = self.seed()
        saved = copy.deepcopy(registry.items[key])
        registry.remove(key)
        registry.save()
        registry.items[key] = copy.deepcopy(saved)
        registry.save()
        self.assertGreater(registry.items[key]['revision'], saved['revision'])

    def test_newer_schema_is_not_opened_as_empty_registry(self):
        self.seed()
        with sqlite3.connect(self.root / 'work-items.sqlite3') as db:
            db.execute('PRAGMA user_version=99')
        with self.assertRaisesRegex(ValueError, 'newer app'):
            items.Registry(self.path)


class FoundationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.service = MeetingService(self.root / 'library', PROJECT, google=FakeGoogle(), backup_dir=self.root / 'backups')

    def tearDown(self):
        self.service.close()
        self.tmp.cleanup()

    def meeting(self, content):
        meeting = self.service.library.create('Synthetic meeting', 'in_person', {})
        self.service.library.update(meeting['id'], status='ready', duration=5)
        atomic_json(self.service.library.directory(meeting['id']) / 'transcript.json',
                    [dict(start=0, end=5, text='Synthetic speech.', speaker=None)])
        self.service.edit(meeting['id'], dict(minutes=content))
        return meeting['id']

    def test_deleting_replacement_does_not_accept_original_proposal(self):
        self.meeting(notes(decisions=[decision('Synthetic original proposal')]))
        old = self.service.item_list()['items'][0]
        registry = self.service.items
        with registry.lock:
            new = registry.replace(old['id'], decision('Synthetic replacement'), old['links'][0]['meeting_id'])
            registry.save()
            registry.remove(new)
            registry.save()
        self.assertEqual(registry.items[old['id']]['status'], 'proposed')

    def test_stale_revision_cannot_overwrite_unchanged_text(self):
        self.meeting(notes([task('Synthetic task')]))
        old = self.service.tasks()[0]
        self.service.update_item(old['id'], old['text'], dict(owner='First person'), old['revision'])
        with self.assertRaises(WorkItemConflict):
            self.service.update_item(old['id'], old['text'], dict(owner='Second person'), old['revision'])
        with self.assertRaises(WorkItemConflict):
            self.service.delete_item(old['id'], old['text'], old['revision'])
        self.assertEqual(self.service.tasks()[0]['owner'], 'First person')

    def test_personal_disposition_keeps_status_and_evidence(self):
        self.meeting(notes([task('Synthetic task')]))
        old = self.service.tasks()[0]
        tomorrow = (dt.date.today() + dt.timedelta(days=1)).isoformat()
        fresh = self.service.update_item(old['id'], old['text'], dict(snoozed_until=tomorrow), old['revision'])
        self.assertEqual(self.service.task_summary()['open'], 0)
        self.assertEqual((fresh['status'], fresh['evidence']), ('open', old['evidence']))
        fresh = self.service.update_item(fresh['id'], fresh['text'], dict(snoozed_until=None, dismissed=True), fresh['revision'])
        self.assertEqual(self.service.task_summary()['open'], 0)
        self.service.update_item(fresh['id'], fresh['text'], dict(dismissed=False), fresh['revision'])
        self.assertEqual(self.service.task_summary()['open'], 1)

    def test_evidence_preserves_earlier_note_wording(self):
        meeting_id = self.meeting(notes([task('Original note wording')]))
        old = self.service.tasks()[0]
        self.service.update_item(old['id'], old['text'], dict(text='Internal item title'), old['revision'])
        self.assertEqual({e['quote'] for e in self.service.tasks()[0]['evidence']}, {'Original note wording'})
        detail = self.service.detail(meeting_id)
        detail['minutes']['tasks'][0]['task'] = 'Changed note wording'
        self.service.edit(meeting_id, dict(minutes=detail['minutes'], minutes_revision=detail['minutes_revision']))
        fresh = self.service.tasks()[0]
        self.assertEqual({e['quote'] for e in fresh['evidence']}, {'Original note wording', 'Changed note wording'})
        self.assertTrue(all(e['quote_kind'] == 'meeting_note' for e in fresh['evidence']))
        before = copy.deepcopy(fresh)
        self.service._sync_items(meeting_id)
        self.assertEqual(self.service.tasks()[0], before)

    def test_snapshot_recovers_export_interrupted_after_database_commit(self):
        self.meeting(notes([task('Synthetic task')]))
        old = self.service.tasks()[0]
        registry = self.service.items
        registry.update(old['id'], dict(status='done'))
        with patch('app.work_items.atomic_json', side_effect=OSError('synthetic disk failure')):
            with self.assertRaises(OSError):
                registry.save()
        with backup.snapshot(self.service.library.root, guard=self.service._snapshot_guard) as (frozen, _):
            exported = json.loads((frozen / 'items.json').read_text())
            self.assertEqual(exported['items'][old['id']]['status'], 'done')
        self.assertEqual(registry.items[old['id']]['status'], 'done')

    def test_snapshot_pins_registry_and_notes_while_live_state_changes(self):
        meeting_id = self.meeting(notes([task('Synthetic task')]))
        item = self.service.tasks()[0]
        with backup.snapshot(self.service.library.root, guard=self.service._snapshot_guard) as (frozen, _):
            self.service.update_item(item['id'], item['text'], dict(status='done'), item['revision'])
            self.assertEqual(json.loads((frozen / 'items.json').read_text())['items'][item['id']]['status'], 'open')
            self.assertEqual(json.loads((frozen / meeting_id / 'minutes.json').read_text())['tasks'][0]['status'], 'open')
        self.assertEqual(self.service.tasks()[0]['status'], 'done')

    def test_compression_releases_recording_controls_lock(self):
        self.meeting(notes([task('Synthetic task')]))
        entered, release, updated = threading.Event(), threading.Event(), threading.Event()
        read = backup._Hashing.read
        def blocked(handle, size=-1):
            if not entered.is_set():
                entered.set()
                release.wait(5)
            return read(handle, size)
        errors = []
        def archive():
            try:
                self.service.create_backup()
            except Exception as exc:
                errors.append(exc)
        with patch.object(backup._Hashing, 'read', blocked):
            thread = threading.Thread(target=archive)
            thread.start()
            try:
                self.assertTrue(entered.wait(5))
                change = threading.Thread(target=lambda: (self.service.save_settings({'auto_process': False}), updated.set()))
                change.start()
                self.assertTrue(updated.wait(1), 'Compression blocked the service lock')
                change.join()
            finally:
                release.set()
                thread.join(5)
        self.assertEqual(errors, [])

    def test_unique_archives_restore_disposition_and_evidence(self):
        self.meeting(notes([task('Synthetic task')]))
        item = self.service.tasks()[0]
        self.service.update_item(item['id'], item['text'], dict(dismissed=True), item['revision'])
        fixed = dt.datetime.now().astimezone()
        with patch('app.backup.dt.datetime', wraps=dt.datetime) as clock:
            clock.now.return_value = fixed
            first = self.service.create_backup()['created']
            second = self.service.create_backup()['created']
        self.assertNotEqual(first['name'], second['name'])
        other = MeetingService(self.root / 'other', PROJECT, google=FakeGoogle(), backup_dir=self.root / 'backups')
        try:
            other.restore_backup(first['name'])
            restored = other.tasks()[0]
            self.assertEqual((restored['id'], restored['dismissed'], restored['evidence']),
                             (item['id'], True, self.service.tasks()[0]['evidence']))
        finally:
            other.close()


class ItemHTTPTests(unittest.TestCase):
    setUp, tearDown, request = test_http.HTTPTests.setUp, test_http.HTTPTests.tearDown, test_http.HTTPTests.request

    def test_http_requires_revision_and_reports_conflicts(self):
        meeting = self.service.library.create('Synthetic meeting', 'in_person', {})
        self.service.library.update(meeting['id'], status='ready', duration=5)
        atomic_json(self.service.library.directory(meeting['id']) / 'transcript.json',
                    [dict(start=0, end=5, text='Synthetic speech.', speaker=None)])
        self.service.edit(meeting['id'], dict(minutes=notes([task('Synthetic task')])))
        item = self.service.tasks()[0]
        path = '/api/items/' + item['id']
        self.assertEqual(self.request(path, dict(text=item['text'], changes=dict(status='done')))[0], 400)
        body = dict(text=item['text'], revision=item['revision'], changes=dict(status='done'))
        self.assertEqual(self.request(path, body)[0], 200)
        self.assertEqual(self.request(path, body)[0], 409)
        self.assertEqual(self.request(path, body, headers={})[0], 403)
