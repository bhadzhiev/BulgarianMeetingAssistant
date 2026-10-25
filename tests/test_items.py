import json
from pathlib import Path
import tempfile
import unittest

from app import items
from app.service import MeetingService
from app.storage import atomic_json
from tests.test_calendar import FakeGoogle

PROJECT = Path(__file__).resolve().parents[1]


def task(text, owner=None, deadline=None, due_date=None):
    return dict(task=text, owner=owner, deadline=deadline, due_date=due_date, evidence_timestamp='00:00:00')


def decision(text, review='ai'):
    return dict(text=text, evidence_timestamp='00:00:00', review=review)


def notes(tasks=(), decisions=()):
    return dict(summary=[], decisions=list(decisions), tasks=list(tasks), open_questions=[])


class SimilarityTests(unittest.TestCase):
    def test_reworded_task_matches_and_unrelated_does_not(self):
        self.assertGreaterEqual(items.similarity('Иван да провери VPN failover', 'Провери VPN failover до петък'), items.MATCH)
        self.assertLess(items.similarity('Изпрати оферта на клиента', 'Провери VPN failover'), items.MATCH)


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.service = MeetingService(Path(self.tmp.name), PROJECT, google=FakeGoogle())

    def tearDown(self):
        self.service.close()
        self.tmp.cleanup()

    def meeting(self, when, minutes, title='Среща'):
        meeting = self.service.library.create(title, 'in_person', {})
        self.service.library.update(meeting['id'], status='ready', duration=60, started_at=when, created=when)
        atomic_json(self.service.library.directory(meeting['id']) / 'transcript.json', [dict(start=0, end=5, text='Да.', speaker=None)])
        self.service.edit(meeting['id'], {'minutes': minutes})
        return meeting['id']

    def minutes(self, meeting_id):
        return json.loads((self.service.library.directory(meeting_id) / 'minutes.json').read_text())

    def resolve(self, meeting_id, field, action, item_id=None, index=0):
        mention = self.minutes(meeting_id)[field][index]
        return self.service.resolve_link(meeting_id, field, index, mention['task' if field == 'tasks' else 'text'], action, item_id)

    def test_a_task_keeps_its_identity_history_and_status_across_meetings(self):
        first = self.meeting('2026-10-19T10:00:00+03:00', notes([task('Иван да провери VPN failover', 'Иван')]), 'DevOps')
        [item] = self.service.tasks()
        second = self.meeting('2026-10-23T10:00:00+03:00', notes([task('Провери VPN failover до петък', 'Иван', 'петък', '2026-10-30')]), 'Weekly')
        [pending] = self.service.item_list()['pending']
        self.assertEqual((pending['meeting_id'], pending['candidates'][0]['item_id']), (second, item['id']))
        self.resolve(second, 'tasks', 'same', item['id'])
        [item] = self.service.tasks()
        self.assertEqual({link['meeting_id'] for link in item['links']}, {first, second})
        self.assertEqual((item['text'], item['deadline'], item['due_date'], item['status']),
                         ('Иван да провери VPN failover', 'петък', '2026-10-30', 'open'))
        discussed = item['history'][-1]
        self.assertEqual((discussed['event'], discussed['meeting_id'], discussed['changes']['due_date']), ('discussed', second, [None, '2026-10-30']))
        self.service.update_item(item['id'], item['text'], {'status': 'done'})
        self.assertEqual([self.minutes(m)['tasks'][0]['status'] for m in (first, second)], ['done', 'done'])
        self.assertIn('Изпълнена', (self.service.library.directory(first) / 'minutes.md').read_text())
        self.assertEqual(self.service.task_summary()['open'], 0)

    def test_ai_never_overwrites_manual_edits_or_status(self):
        self.meeting('2026-10-19T10:00:00+03:00', notes([task('Обнови сертификатите на принтерите', 'Иван')]))
        [item] = self.service.tasks()
        self.service.update_item(item['id'], item['text'], {'owner': 'Мария', 'status': 'done'})
        self.service.update_item(item['id'], item['text'], {'status': 'open'})
        later = self.meeting('2026-10-23T10:00:00+03:00', notes([task('Обнови сертификатите на принтерите', 'Иван', None, '2026-11-01')]))
        self.resolve(later, 'tasks', 'same', item['id'])
        [item] = self.service.tasks()
        self.assertEqual((item['owner'], item['due_date'], item['status']), ('Мария', '2026-11-01', 'open'))

    def test_duplicate_and_new_choices(self):
        self.meeting('2026-10-19T10:00:00+03:00', notes([task('Подготви оферта за Клиент X')]))
        [item] = self.service.tasks()
        later = self.meeting('2026-10-23T10:00:00+03:00', notes([task('Подготви оферта за Клиент X', 'Иван'), task('Подготви оферта за Клиент Y')]))
        self.assertEqual(len(self.service.item_list()['pending']), 2)
        self.resolve(later, 'tasks', 'duplicate', item['id'], index=0)
        self.resolve(later, 'tasks', 'new', index=1)
        tasks = {t['text']: t for t in self.service.tasks()}
        self.assertEqual(set(tasks), {'Подготви оферта за Клиент X', 'Подготви оферта за Клиент Y'})
        self.assertIsNone(tasks['Подготви оферта за Клиент X']['owner'])
        self.assertEqual(tasks['Подготви оферта за Клиент X']['history'][-1]['event'], 'duplicate')
        self.assertEqual(self.service.item_list()['pending'], [])

    def test_decisions_are_proposed_accepted_and_superseded(self):
        first = self.meeting('2026-10-19T10:00:00+03:00', notes(decisions=[decision('Резервният интернет е LTE рутер')]))
        old = next(i for i in self.service.item_list()['items'] if i['kind'] == 'decision')
        self.assertEqual(old['status'], 'proposed')
        minutes = self.minutes(first)
        minutes['decisions'][0]['review'] = 'verified'
        self.service.edit(first, {'minutes': minutes})
        self.assertEqual(self.service.item_list()['items'][0]['status'], 'accepted')
        second = self.meeting('2026-10-23T10:00:00+03:00', notes(decisions=[decision('Резервният интернет е оптика, не LTE рутер')]))
        detail = self.resolve(second, 'decisions', 'replaces', old['id'])
        new_id = detail['minutes']['decisions'][0]['item_id']
        registry = {i['id']: i for i in self.service.item_list()['items']}
        self.assertEqual((registry[old['id']]['status'], registry[old['id']]['superseded_by']), ('superseded', new_id))
        self.assertEqual(registry[new_id]['supersedes'], [old['id']])
        self.service.delete_item(new_id, registry[new_id]['text'])
        self.assertEqual(self.service.item_list()['items'][0]['status'], 'accepted')
        self.assertEqual(self.minutes(second)['decisions'], [])

    def test_merge_delete_and_removed_meetings(self):
        a = self.meeting('2026-10-19T10:00:00+03:00', notes([task('Купи UPS за сървърното')]))
        b = self.meeting('2026-10-20T10:00:00+03:00', notes([task('Обнови документацията на API')]))
        first, second = sorted(self.service.tasks(), key=lambda t: t['created'])
        merged = self.service.merge_items(second['id'], first['id'])
        self.assertEqual({link['meeting_id'] for link in merged['links']}, {a, b})
        self.assertEqual(self.minutes(b)['tasks'][0]['item_id'], first['id'])
        self.service.delete(a)
        [item] = self.service.tasks()
        self.assertEqual([link['meeting_id'] for link in item['links']], [b])
        self.service.delete(b)
        self.assertEqual(self.service.tasks(), [])

    def test_sync_is_idempotent_and_stale_choices_are_rejected(self):
        meeting_id = self.meeting('2026-10-19T10:00:00+03:00', notes([task('Провери бекъпа')]))
        history = json.dumps(self.service.tasks())
        self.service._sync_items(meeting_id)
        self.service._sync_items(meeting_id)
        self.assertEqual(json.dumps(self.service.tasks()), history)
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.service.resolve_link(meeting_id, 'tasks', 0, 'Провери бекъпа', 'new')
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.service.update_item(self.service.tasks()[0]['id'], 'old text', {'status': 'done'})

    def test_accepted_ai_changes_keep_the_task_identity(self):
        from unittest.mock import patch
        from app import processing
        from app.service import DEFAULTS
        meeting_id = self.meeting('2026-10-19T10:00:00+03:00', notes([task('Провери VPN failover', 'Иван')]))
        [item] = self.service.tasks()
        self.service.update_item(item['id'], item['text'], {'status': 'done'})
        directory = self.service.library.directory(meeting_id)
        with patch('meeting_assistant.generate_minutes', return_value=notes([task('Провери VPN failover на офиса', 'Иван')])):
            processing.summarize(directory, dict(DEFAULTS, summarizer='local'), lambda _: None)
        proposal = self.service.detail(meeting_id)['minutes_proposal']
        self.service.review_notes(meeting_id, 'apply', [c['id'] for c in proposal['changes']], proposal['revision'])
        [item] = self.service.tasks()
        mention = self.minutes(meeting_id)['tasks'][0]
        self.assertEqual((mention['item_id'], mention['status'], mention['task']), (item['id'], 'done', 'Провери VPN failover на офиса'))
        self.assertEqual((item['status'], item['text']), ('done', 'Провери VPN failover на офиса'))
