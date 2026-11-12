"""The AI stops at the meeting notes (default since 2026-11-12); the person makes tasks from the notes by hand."""
import json
from pathlib import Path
import tempfile
import unittest

from app import items
from app.service import MeetingService
from app.storage import atomic_json
from tests.test_calendar import FakeGoogle

PROJECT = Path(__file__).resolve().parents[1]


def minutes(*texts):
    return dict(summary=['Резюме'], decisions=[], open_questions=[],
                tasks=[dict(task=text, details='Описание: ' + text, owner='Иван', deadline='петък', due_date=None,
                            status='open', evidence_timestamp='00:00:00') for text in texts])


class ManualMeetingTaskTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.service = MeetingService(Path(self.tmp.name), PROJECT, google=FakeGoogle())

    def tearDown(self):
        self.service.close()
        self.tmp.cleanup()

    def meeting(self, notes):
        m = self.service.library.create('Среща', 'in_person', {})
        directory = self.service.library.directory(m['id'])
        atomic_json(directory / 'transcript.json', [dict(start=0, end=5, text='Иван ще изпрати оферта до петък.', speaker=None)])
        atomic_json(directory / 'minutes.json', notes)
        return m['id']

    def notes(self, meeting_id):
        return json.loads((self.service.library.directory(meeting_id) / 'minutes.json').read_text())

    def create(self, meeting_id, index, text='Изпрати оферта', request='a' * 32, **extra):
        return self.service.create_task(dict(text=text, owner='Иван', due_date=None, meeting_id=meeting_id,
                                             project_id=None, request_id=request, mention_index=index, **extra))

    def test_the_setting_is_off_by_default(self):
        self.assertFalse(self.service.settings['meeting_task_ai'])
        self.assertFalse(self.service.meeting_task_ai())

    def test_notes_make_no_tasks_and_no_proposals(self):
        meeting_id = self.meeting(minutes('Изпрати оферта', 'Резервирай зала'))
        listed = self.service.item_list()
        self.assertEqual([i for i in listed['items'] if i['kind'] == 'task'], [])
        self.assertEqual(listed['graph']['proposals'], [])
        self.assertTrue(all('item_id' not in t and 'link' not in t for t in self.notes(meeting_id)['tasks']))
        self.assertEqual(self.service.task_summary()['review'], 0)

    def test_matching_permission_is_refused(self):
        meeting_id = self.meeting(minutes('Изпрати оферта'))
        with self.assertRaisesRegex(ValueError, 'AI tasks from meetings are off'):
            self.service.allow_task_matching(meeting_id)

    def test_create_task_from_a_line_links_the_line(self):
        meeting_id = self.meeting(minutes('Изпрати оферта', 'Резервирай зала'))
        self.service.item_list()
        task = self.create(meeting_id, 1, text='Зала за среща', details='Голямата зала')
        self.assertEqual((task['text'], task['details'], task['created_by']), ('Зала за среща', 'Голямата зала', 'user'))
        self.assertEqual(task['links'][0]['evidence_timestamp'], '00:00:00')
        lines = self.notes(meeting_id)['tasks']
        self.assertEqual(lines[1]['item_id'], task['id'])
        self.assertNotIn('item_id', lines[0])
        # What the notes said stays as said; only one task exists and the next sync changes nothing.
        self.assertEqual(lines[1]['task'], 'Резервирай зала')
        self.service.item_list()
        self.assertEqual([i['id'] for i in self.service.tasks()], [task['id']])
        self.assertEqual(self.service.tasks()[0]['text'], 'Зала за среща')
        # The same request again returns the same task; another request for the line is refused.
        self.assertEqual(self.create(meeting_id, 1, text='Зала за среща', details='Голямата зала')['id'], task['id'])
        with self.assertRaises(items.WorkItemConflict):
            self.create(meeting_id, 1, request='b' * 32)
        with self.assertRaises(items.WorkItemConflict):
            self.create(meeting_id, 5, request='c' * 32)

    def test_a_task_from_the_notes_survives_new_notes(self):
        meeting_id = self.meeting(minutes('Изпрати оферта'))
        task = self.create(meeting_id, 0)
        atomic_json(self.service.library.directory(meeting_id) / 'minutes.json', minutes('Друга задача'))
        self.service.item_list()
        self.assertEqual([i['id'] for i in self.service.tasks()], [task['id']])
        self.assertIn(task['id'], [t.get('item_id') for t in self.notes(meeting_id)['tasks']])

    def test_old_ai_proposals_are_hidden_not_deleted(self):
        self.service.save_settings(dict(meeting_task_ai=True))
        meeting_id = self.meeting(minutes('Изпрати оферта'))
        proposed = [i for i in self.service.item_list()['items'] if i['kind'] == 'task']
        self.assertEqual([i['acceptance_state'] for i in proposed], ['proposed'])
        self.service.save_settings(dict(meeting_task_ai=False))
        self.assertEqual([i for i in self.service.item_list()['items'] if i['kind'] == 'task'], [])
        self.assertIn(proposed[0]['id'], self.service.items.items)
        self.service.save_settings(dict(meeting_task_ai=True))
        self.assertEqual([i['id'] for i in self.service.item_list()['items'] if i['kind'] == 'task'], [proposed[0]['id']])
        # Back to manual: a task from the line replaces the hidden proposal of that line.
        self.service.save_settings(dict(meeting_task_ai=False))
        task = self.create(meeting_id, 0)
        self.assertNotIn(proposed[0]['id'], self.service.items.items)
        self.assertEqual(self.notes(meeting_id)['tasks'][0]['item_id'], task['id'])

    def test_decisions_stay_text_and_search_reads_the_check(self):
        notes = minutes('Изпрати оферта')
        notes['decisions'] = [dict(text='Резервният интернет ще е LTE рутер', evidence_timestamp='00:00:00', review='verified'),
                              dict(text='Офертата е до петък', evidence_timestamp='00:00:00', review='ai')]
        meeting_id = self.meeting(notes)
        listed = self.service.item_list()
        self.assertEqual([i for i in listed['items'] if i['kind'] == 'decision'], [])
        self.assertEqual(listed['pending'], [])
        self.assertTrue(all('item_id' not in d for d in self.notes(meeting_id)['decisions']))
        answer = self.service.ask('LTE рутер', ai=False)
        self.assertEqual([r['text'] for r in answer['confirmed']], ['Резервният интернет ще е LTE рутер'])

    def test_old_ai_decisions_are_hidden_not_deleted(self):
        self.service.save_settings(dict(meeting_task_ai=True))
        notes = minutes('Изпрати оферта')
        notes['decisions'] = [dict(text='Офертата е до петък', evidence_timestamp='00:00:00', review='ai')]
        self.meeting(notes)
        decisions = [i['id'] for i in self.service.item_list()['items'] if i['kind'] == 'decision']
        self.assertEqual(len(decisions), 1)
        self.service.save_settings(dict(meeting_task_ai=False))
        self.assertEqual([i for i in self.service.item_list()['items'] if i['kind'] == 'decision'], [])
        self.assertIn(decisions[0], self.service.items.items)

    def test_a_task_that_a_person_wrote_needs_no_review(self):
        meeting_id = self.meeting(minutes('Изпрати оферта'))
        task = self.create(meeting_id, 0)
        row = next(i for i in self.service.item_list()['items'] if i['id'] == task['id'])
        self.assertIsNone(row['review_state'])


if __name__ == '__main__':
    unittest.main()
