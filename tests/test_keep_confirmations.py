import json
from pathlib import Path
import tempfile
import unittest

from app.meeting_review import review_state, snapshot
from app.review_queue import build as review_queue
from app.service import MeetingService
from app.storage import atomic_json
from meeting_assistant import validate_minutes
from tests.test_calendar import FakeGoogle
from tests.ai_meeting_tasks import setUpModule, tearDownModule  # noqa: F401  AI meeting tasks are on in these tests

PROJECT = Path(__file__).resolve().parents[1]


class KeepConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.service = MeetingService(Path(self.tmp.name), PROJECT, google=FakeGoogle())
        meeting = self.service.library.create('Среща', 'in_person', {})
        self.meeting = meeting['id']
        self.service.library.update(self.meeting, status='ready', duration=60)
        self.directory = self.service.library.directory(self.meeting)
        atomic_json(self.directory / 'transcript.json', [dict(start=0, end=5, text='Иван ще смени батериите.', speaker='Иван')])
        self.service.edit(self.meeting, {'minutes': dict(summary=[dict(text='Батерии', evidence_timestamp='00:00:00')], decisions=[], open_questions=[],
                                                          tasks=[dict(task='Смени батериите на UPS', owner='Иван', deadline=None, due_date=None, evidence_timestamp='00:00:00')])})
        [self.task] = self.service.tasks()

    def tearDown(self):
        self.service.close()
        self.tmp.cleanup()

    def notes(self, change):
        path = self.directory / 'minutes.json'
        minutes = json.loads(path.read_text())
        change(minutes)
        atomic_json(path, minutes)

    def state(self):
        return review_state(self.service.items.items[self.task['id']], self.service.review_sources())

    def confirm(self):
        item = self.service.items.items[self.task['id']]
        self.service.update_item(item['id'], item['text'], {'acceptance_state': 'accepted'})

    def test_an_empty_updates_list_never_asks_for_the_confirmation_again(self):
        self.confirm()
        self.assertEqual(self.state(), 'confirmed')
        # Notes saved between #156 and this fix have "updates": [] — the same evidence.
        self.notes(lambda m: m.update(updates=[]))
        self.assertEqual(self.state(), 'confirmed')
        self.notes(lambda m: m.pop('updates'))
        self.assertEqual(self.state(), 'confirmed')

    def test_a_confirmation_made_with_the_empty_list_stays_valid_without_it(self):
        self.notes(lambda m: m.update(updates=[]))
        self.confirm()
        self.notes(lambda m: m.pop('updates'))
        self.assertEqual(self.state(), 'confirmed')

    def test_real_new_content_still_asks_again(self):
        self.confirm()
        self.notes(lambda m: m['summary'].append(dict(text='Нов факт', evidence_timestamp='00:00:00')))
        self.assertEqual(self.state(), 'needs_review')

    def test_old_notes_get_no_empty_updates_list(self):
        minutes = dict(summary=[], decisions=[], tasks=[], open_questions=[])
        validate_minutes(minutes)
        self.assertNotIn('updates', minutes)
        self.service._sync_items(self.meeting)
        self.assertNotIn('updates', json.loads((self.directory / 'minutes.json').read_text()))

    def test_a_closed_task_is_not_asked_again(self):
        self.confirm()
        item = self.service.items.items[self.task['id']]
        self.service.update_item(item['id'], item['text'], {'workflow_state': 'done'})
        self.notes(lambda m: m['summary'].append(dict(text='Нов факт', evidence_timestamp='00:00:00')))
        rows = [row for row in snapshot(self.service, self.meeting)['items'] if row['id'] == self.task['id']]
        self.assertTrue(rows[0]['closed'])
        rows = [row for row in review_queue(self.service)['meetings'] if row['id'] == self.meeting]
        self.assertEqual([row['items'] for row in rows], [0] if rows else [])
        # The same change on an open task does ask: the rule is for closed tasks only.
        self.service.update_item(item['id'], item['text'], {'workflow_state': 'todo'})
        self.assertEqual([row['items'] for row in review_queue(self.service)['meetings'] if row['id'] == self.meeting], [1])


if __name__ == '__main__':
    unittest.main()
