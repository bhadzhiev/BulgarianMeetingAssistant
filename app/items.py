"""Tasks and decisions that live longer than one meeting.

The SQLite registry (with an items.json export) holds each task and decision once: its current state, its history and links
to every meeting that discussed it. Meeting notes hold mentions; a mention points to its item by
item_id. A new mention that looks like an existing item waits for a person to choose: the same item,
a duplicate, a replacement (decisions) or a new item. The AI never changes a task status and never
overwrites a field that a person edited.
"""
from __future__ import annotations

import datetime as dt
import difflib
from pathlib import Path
import re
import threading
import uuid

from .work_items import WorkItemStore, WorkItemConflict

FIELD = {'task': 'tasks', 'decision': 'decisions'}
# Item field -> mention field. The mention fields are what one meeting said.
MENTION = {'task': {'text': 'task', 'owner': 'owner', 'deadline': 'deadline', 'due_date': 'due_date', 'status': 'status'},
           'decision': {'text': 'text'}}
TASK_STATES = ('open', 'done')
DECISION_STATES = ('proposed', 'accepted', 'superseded')
AI_UPDATES = ('owner', 'deadline', 'due_date')
MATCH = 0.55
# A decision's state shows in its mentions as the review state: accepted means checked.
REVIEW_OF = {'accepted': 'verified', 'proposed': 'ai'}
# Common words say nothing about which task a sentence means.
STOP_WORDS = {'чрез', 'дали', 'като', 'това', 'тази', 'този', 'тези', 'които', 'който', 'която', 'което', 'към', 'във', 'със',
              'при', 'след', 'преди', 'между', 'трябва', 'може', 'или', 'още', 'вече', 'все', 'нещо', 'неща', 'the', 'and', 'for', 'with'}


def now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec='seconds')


def _stems(text: str) -> set[str]:
    # Bulgarian words change their endings; the first five letters stand for the word.
    return {word[:5] for word in re.findall(r'\w+', text.casefold()) if len(word) >= 3 and word not in STOP_WORDS}


def similarity(a: str, b: str) -> float:
    """Shared word stems carry most of the weight; letter sequences alone are about 0.5 for unrelated long sentences."""
    plain_a, plain_b = ' '.join(re.findall(r'\w+', a.casefold())), ' '.join(re.findall(r'\w+', b.casefold()))
    sequence = difflib.SequenceMatcher(None, plain_a, plain_b).ratio()
    stems_a, stems_b = _stems(a), _stems(b)
    # Against the shorter text, so that a short restatement of a long task still matches.
    overlap = len(stems_a & stems_b) / min(len(stems_a), len(stems_b)) if stems_a and stems_b else 0.0
    return 0.6 * overlap + 0.4 * sequence


def seen(kind: str, mention: dict) -> dict:
    """What a meeting's notes said last time; a later difference is an edit by a person."""
    values = {name: mention.get(name) for name in MENTION[kind].values()}
    if kind == 'decision':
        values['review'] = mention.get('review', 'ai')
    return values


class Registry:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.RLock()
        self.store = WorkItemStore(path.with_name('work-items.sqlite3'), path)
        self.data, self.revision = self.store.load()
        self.status_changed = set()  # items whose status a sync changed; other meetings must follow

    @property
    def items(self) -> dict:
        return self.data['items']

    def save(self) -> None:
        try:
            self.revision = self.store.save(self.data, self.revision)
        except WorkItemConflict:
            self.data, self.revision = self.store.load(repair_export=False)
            raise

    def _event(self, item, event, meeting_id=None, changes=None, by='ai', **extra):
        item['history'].append(dict(at=now(), event=event, meeting_id=meeting_id, changes=changes or {}, by=by, **extra))

    def create(self, kind: str, mention: dict, meeting_id: str) -> str:
        item_id = uuid.uuid4().hex[:16]
        item = dict(id=item_id, kind=kind, created=now(), manual=[], links=[], history=[], superseded_by=None, supersedes=[])
        for name, source in MENTION[kind].items():
            item[name] = mention.get(source)
        if kind == 'decision':
            item['status'] = 'accepted' if mention.get('review') == 'verified' else 'proposed'
        self.items[item_id] = item
        item['links'].append(dict(meeting_id=meeting_id, evidence_timestamp=mention.get('evidence_timestamp'), seen=seen(kind, mention)))
        self._event(item, 'created', meeting_id)
        return item_id

    def candidates(self, kind: str, mention: dict, meeting_id=None) -> list[dict]:
        text = mention.get(MENTION[kind]['text']) or ''
        found = []
        for item in self.items.values():
            # An item from the earlier notes of this meeting waits for the new notes, whatever its status.
            detached = self._detached(item, meeting_id)
            if item['kind'] != kind or item['status'] in {'done', 'superseded'} and not detached:
                continue
            score = similarity(text, item['text'] or '')
            if kind == 'task' and mention.get('owner') and mention.get('owner') == item.get('owner'):
                score += 0.05
            if detached:
                score += 0.05
            if score >= MATCH:
                found.append(dict(item_id=item['id'], score=round(min(score, 1.0), 2)))
        return sorted(found, key=lambda entry: -entry['score'])[:3]

    def _apply_edit(self, item, kind, changes, meeting_id):
        """A person changed a linked mention in the meeting notes; the item follows."""
        applied = {}
        for name, source in MENTION[kind].items():
            if source in changes:
                old, new = item.get(name), changes[source][1]
                if old != new and (name != 'text' or new):
                    item[name] = new
                    applied[name] = [old, new]
                    if name not in item['manual']:
                        item['manual'].append(name)
        if kind == 'decision':
            review = changes.get('review', [None, None])[1]
            # Checking a decision accepts it; a changed AI statement needs a new check, so it is proposed again.
            new_status = 'accepted' if review == 'verified' and item['status'] == 'proposed' else \
                'proposed' if review == 'ai' and item['status'] == 'accepted' else None
            if new_status:
                applied['status'] = [item['status'], new_status]
                item['status'] = new_status
        if 'status' in applied:
            self.status_changed.add(item['id'])
        if applied:
            self._event(item, 'changed', meeting_id, applied, by='user')

    @staticmethod
    def _detached(item, meeting_id) -> bool:
        return bool(meeting_id) and any(link['meeting_id'] == meeting_id and link.get('detached') for link in item['links'])

    @staticmethod
    def _reconcile(kind: str, item: dict, mention: dict) -> bool:
        """The item holds the state; every meeting's notes show the same state."""
        if kind == 'task' and mention.get('status') != item['status']:
            mention['status'] = item['status']
            return True
        if kind == 'decision' and item['status'] in REVIEW_OF and mention.get('review') != REVIEW_OF[item['status']]:
            mention['review'] = REVIEW_OF[item['status']]
            return True
        return False

    def detach(self, meeting_id: str) -> None:
        """The notes of a meeting are gone because it was transcribed again. Its items keep their identity
        and history, and wait for the new notes of the meeting."""
        for item in self.items.values():
            for link in item['links']:
                if link['meeting_id'] == meeting_id and not link.get('detached'):
                    link['detached'] = True
                    self._event(item, 'detached', meeting_id)

    def link(self, item_id: str, kind: str, mention: dict, meeting_id: str, ai_updates: bool, duplicate=False) -> None:
        """Connect a mention to an existing item. With ai_updates, new details from the AI fill the item,
        except fields that a person edited."""
        item = self.items[item_id]
        applied = {}
        if ai_updates and kind == 'task':
            for name in AI_UPDATES:
                value = mention.get(MENTION[kind][name])
                if value is not None and value != item.get(name) and name not in item['manual']:
                    applied[name] = [item.get(name), value]
                    item[name] = value
        self._reconcile(kind, item, mention)
        existing = next((link for link in item['links'] if link['meeting_id'] == meeting_id), None)
        if existing:
            existing.pop('detached', None)
            existing.update(evidence_timestamp=mention.get('evidence_timestamp'), seen=seen(kind, mention))
        else:
            item['links'].append(dict(meeting_id=meeting_id, evidence_timestamp=mention.get('evidence_timestamp'),
                                      seen=seen(kind, mention), duplicate=duplicate))
        self._event(item, 'duplicate' if duplicate else 'discussed', meeting_id, applied)

    def replace(self, old_id: str, mention: dict, meeting_id: str) -> str:
        """A new decision replaces an older one."""
        if self.items[old_id]['status'] == 'superseded':
            raise ValueError('This decision was already replaced. Reload and choose the current decision.')
        new_id = self.create('decision', mention, meeting_id)
        old, new = self.items[old_id], self.items[new_id]
        old['superseded_previous_status'] = old['status']
        old['superseded_by'] = new_id
        new['supersedes'].append(old_id)
        self._event(old, 'superseded', meeting_id, {'status': [old['status'], 'superseded']}, by='user', by_item=new_id)
        old['status'] = 'superseded'
        return new_id

    def sync(self, meeting_id: str, minutes: dict | None) -> bool:
        """Bring the registry in line with one meeting's notes. Returns True when the notes changed."""
        changed, present, primary = False, set(), set()
        for kind, field in FIELD.items():
            for mention in (minutes or {}).get(field, []):
                item_id = mention.get('item_id')
                item = self.items.get(item_id) if item_id else None
                if item_id and not item:
                    mention.pop('item_id')
                    changed = True
                if item and item_id in primary:
                    # A second mention of the same item in this meeting shows its state; only the first one is edited.
                    changed |= self._reconcile(kind, item, mention)
                    continue
                if item:
                    present.add(item_id)
                    primary.add(item_id)
                    link = next((link for link in item['links'] if link['meeting_id'] == meeting_id), None)
                    now_seen = seen(kind, mention)
                    if link is None:
                        item['links'].append(dict(meeting_id=meeting_id, evidence_timestamp=mention.get('evidence_timestamp'), seen=now_seen))
                        self._event(item, 'discussed', meeting_id)
                    else:
                        edits = {name: [link['seen'].get(name), value] for name, value in now_seen.items() if link['seen'].get(name) != value}
                        if edits:
                            self._apply_edit(item, kind, edits, meeting_id)
                        link.pop('detached', None)
                    changed |= self._reconcile(kind, item, mention)
                    link = link or item['links'][-1]
                    link.update(seen=seen(kind, mention), evidence_timestamp=mention.get('evidence_timestamp'))
                    continue
                if mention.get('link'):
                    continue
                text = mention.get(MENTION[kind]['text']) or ''
                same = next((item for item in self.items.values() if item['kind'] == kind and self._detached(item, meeting_id)
                             and ' '.join(text.casefold().split()) == ' '.join((item['text'] or '').casefold().split())), None)
                if same:
                    # The new notes of the meeting say the same thing again: it is the same item.
                    self.link(same['id'], kind, mention, meeting_id, ai_updates=False)
                    mention['item_id'] = same['id']
                    present.add(same['id'])
                    changed = True
                    continue
                found = self.candidates(kind, mention, meeting_id)
                if found:
                    mention['link'] = dict(candidates=found)
                else:
                    mention['item_id'] = self.create(kind, mention, meeting_id)
                    present.add(mention['item_id'])
                changed = True
        for item in list(self.items.values()):
            # Detached links wait for a person to link the new notes; only a removed mention ends a link.
            if item['id'] in present or not any(link['meeting_id'] == meeting_id and (minutes is None or not link.get('detached'))
                                                for link in item['links']):
                continue
            item['links'] = [link for link in item['links'] if link['meeting_id'] != meeting_id or minutes is not None and link.get('detached')]
            if item['links'] or self.has_graph_links(item['id']):
                self._event(item, 'removed', meeting_id, by='user')
            else:
                self.remove(item['id'])
        return changed

    def has_graph_links(self, item_id):
        return bool(self.items[item_id].get('source_evidence') or any(item_id in (edge['from_id'], edge['to_id'])
            for edge in self.data.get('relationships', {}).values()))

    def remove(self, item_id: str) -> None:
        if self.has_graph_links(item_id):
            raise ValueError('This item has work graph links. Dismiss it to keep its source history.')
        item = self.items.pop(item_id)
        for old_id in item.get('supersedes', []):
            old = self.items.get(old_id)
            if old and old.get('superseded_by') == item_id:
                # Removing a replacement must not accept an unverified proposal.
                previous = old.pop('superseded_previous_status', None)
                if previous not in {'proposed', 'accepted'}:
                    previous = next((event.get('changes', {}).get('status', [None])[0]
                        for event in reversed(old['history']) if event.get('event') == 'superseded'), 'proposed')
                previous = previous if previous in {'proposed', 'accepted'} else 'proposed'
                old.update(superseded_by=None, status=previous)
                self._event(old, 'changed', None, {'status': ['superseded', previous]}, by='user')
        for other in self.items.values():
            if item_id in other.get('supersedes', []):
                other['supersedes'].remove(item_id)

    def update(self, item_id: str, changes: dict) -> dict:
        item = self.items[item_id]
        applied = {name: [item.get(name), value] for name, value in changes.items() if item.get(name) != value}
        for name, (_, value) in applied.items():
            item[name] = value
            if name not in item['manual']:
                item['manual'].append(name)
        if 'status' in applied and item['kind'] == 'decision' and applied['status'][0] == 'superseded':
            replacement = self.items.get(item.get('superseded_by'))
            if replacement and item_id in replacement.get('supersedes', []):
                replacement['supersedes'].remove(item_id)
            item['superseded_by'] = None
        if applied:
            self._event(item, 'changed', None, applied, by='user')
        return item

    def prune(self, meeting_ids: set[str]) -> None:
        """Drop links to meetings that the library does not have, and items that are left with none."""
        for item in list(self.items.values()):
            item['links'] = [link for link in item['links'] if link['meeting_id'] in meeting_ids]
            if not item['links'] and item.get('managed_by') != 'work_graph' and not self.has_graph_links(item['id']):
                self.remove(item['id'])

    def merge(self, item_id: str, into_id: str) -> None:
        """Two items are the same thing; keep one with all links and history."""
        item, into = self.items[item_id], self.items[into_id]
        if item.get('source_evidence') or into.get('source_evidence'):
            raise ValueError('Use proposal Link for items with work graph sources.')
        for link in item['links']:
            if not any(own['meeting_id'] == link['meeting_id'] for own in into['links']):
                into['links'].append(link)
        into['history'] = sorted(into['history'] + item['history'], key=lambda event: event['at'])
        into['manual'] = sorted(set(into['manual']) | set(item['manual']))
        into['evidence'] = list({entry['id']: entry for entry in
                                into.get('evidence', []) + item.get('evidence', [])}.values())
        self._event(into, 'merged', None, {'text': [item['text'], into['text']]}, by='user')
        for other in self.items.values():
            if other.get('superseded_by') == item_id:
                other['superseded_by'] = into_id
            if item_id in other.get('supersedes', []):
                other['supersedes'] = [into_id if entry == item_id else entry for entry in other['supersedes']]
        del self.items[item_id]
