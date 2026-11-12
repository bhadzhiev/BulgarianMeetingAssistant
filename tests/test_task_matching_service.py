import json
from pathlib import Path
import tempfile
import unittest

from app.service import MeetingService
from app.storage import atomic_json
from tests.test_calendar import FakeGoogle
from tests.test_items import notes, task
from tests.ai_meeting_tasks import setUpModule, tearDownModule  # noqa: F401  AI meeting tasks are on in these tests

PROJECT = Path(__file__).resolve().parents[1]
REMOTE = 'https://api.example.com/v1'


class MatchingStepTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.service = MeetingService(Path(self.tmp.name), PROJECT, google=FakeGoogle())
        self.calls = []
        real = self.service._execute

        def execute(action, directory, settings, progress, key='', *rest):
            if action != 'task_matching':
                return real(action, directory, settings, progress, key, *rest)
            self.calls.append(settings['task_matching_input'])
            mention = settings['task_matching_input']['mentions'][0]
            return dict(matches=[dict(mention_id=mention['id'], type='existing_mention', task_id=mention['candidate_ids'][0],
                                      reason='Same offer', update_text=None, changes=[])], rejected=[])
        self.service._execute = execute

    def tearDown(self):
        self.service.close()
        self.tmp.cleanup()

    def meeting(self, when, minutes):
        meeting = self.service.library.create('Среща', 'in_person', {})
        self.service.library.update(meeting['id'], status='ready', duration=60, started_at=when, created=when)
        atomic_json(self.service.library.directory(meeting['id']) / 'transcript.json', [dict(start=0, end=5, text='Да.', speaker=None)])
        self.service.edit(meeting['id'], {'minutes': minutes})
        return meeting['id']

    def accepted_task(self):
        first = self.meeting('2026-10-19T10:00:00+03:00', notes([task('Подготви офертата за клиента', 'Иван')]))
        [item] = self.service.tasks()
        self.service.update_item(item['id'], item['text'], {'acceptance_state': 'accepted'})
        return first, item

    def run_step(self, meeting_id, **settings):
        values = dict(self.service.settings, **{'summarizer': 'local', **settings})
        directory = self.service.library.directory(meeting_id)
        self.service._match_tasks(meeting_id, directory, values, lambda *a, **k: None, '')
        return json.loads((directory / 'task-matching.json').read_text())

    def test_a_remote_api_needs_the_permission_for_its_address(self):
        self.accepted_task()
        later = self.meeting('2026-10-23T10:00:00+03:00', notes([task('Подготви офертата за клиента до петък', 'Иван')]))
        record = self.run_step(later, local_ai_base_url=REMOTE, task_matching_target='')
        self.assertEqual(record['status'], 'needs_permission')
        self.assertEqual(self.calls, [])
        # The permission for another address is no permission.
        self.assertEqual(self.run_step(later, local_ai_base_url=REMOTE, task_matching_target='https://other.example.com/v1')['status'], 'needs_permission')
        record = self.run_step(later, local_ai_base_url=REMOTE, task_matching_target=REMOTE)
        self.assertEqual(record['status'], 'complete')
        self.assertEqual(record['matches'][0]['type'], 'existing_mention')
        self.assertEqual(record['target']['base_url'], REMOTE)

    def test_a_retry_with_the_same_input_uses_the_saved_answer(self):
        _, item = self.accepted_task()
        later = self.meeting('2026-10-23T10:00:00+03:00', notes([task('Подготви офертата за клиента до петък', 'Иван')]))
        first = self.run_step(later)
        again = self.run_step(later)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(first['signature'], again['signature'])
        self.assertEqual(again['candidates'], {item['id']: self.service.items.items[item['id']]['revision']})

    def test_no_candidate_no_request_and_other_providers_skip(self):
        later = self.meeting('2026-10-23T10:00:00+03:00', notes([task('Смени батериите на UPS')]))
        self.assertEqual(self.run_step(later)['status'], 'no_candidates')
        self.assertEqual(self.run_step(later, summarizer='openai')['status'], 'skipped')
        self.assertEqual(self.calls, [])

    def test_the_permission_goes_when_the_address_changes(self):
        self.service.save_settings(dict(local_ai_base_url=REMOTE, task_matching_target=REMOTE))
        self.assertEqual(self.service.settings['task_matching_target'], REMOTE)
        self.service.save_settings(dict(local_ai_base_url='https://api.other.example.com/v1'))
        self.assertEqual(self.service.settings['task_matching_target'], '')
        with self.assertRaisesRegex(ValueError, 'Invalid task matching permission'):
            self.service.save_settings(dict(task_matching_target=True))

    def test_allow_and_match_now_grants_the_permission_and_runs_matching(self):
        self.accepted_task()
        later = self.meeting('2026-10-23T10:00:00+03:00', notes([task('Подготви офертата за клиента до петък', 'Иван')]))
        self.service.save_settings(dict(local_ai_base_url=REMOTE, summarizer='local'))
        directory = self.service.library.directory(later)
        self.service._save_matching(directory, dict(status='needs_permission', notes='minutes.json', reason='Synthetic'))
        self.assertEqual(self.service.allow_task_matching(later)['status'], 'matching')
        self.assertEqual(self.service.settings['task_matching_target'], REMOTE)
        import time
        for _ in range(100):
            record = json.loads((directory / 'task-matching.json').read_text())
            if record.get('status') == 'complete':
                break
            time.sleep(0.05)
        self.assertEqual(record['status'], 'complete')
        self.assertEqual(record['target']['base_url'], REMOTE)

    def test_allow_and_match_now_refuses_without_notes_or_a_remote_api(self):
        meeting = self.service.library.create('Без бележки', 'in_person', {})
        self.service.save_settings(dict(local_ai_base_url=REMOTE, summarizer='local'))
        with self.assertRaisesRegex(ValueError, 'notes first'):
            self.service.allow_task_matching(meeting['id'])
        ready = self.meeting('2026-10-23T10:00:00+03:00', notes([task('Смени батериите на UPS')]))
        self.service.save_settings(dict(local_ai_base_url='http://localhost:1235/v1', summarizer='local'))
        with self.assertRaisesRegex(ValueError, 'needs no matching permission'):
            self.service.allow_task_matching(ready)

    def test_review_pending_reflects_what_waits(self):
        empty = self.service.library.create('Празна', 'in_person', {})
        self.assertFalse(self.service._review_pending(empty['id'], self.service.library.get(empty['id'])))
        ready = self.meeting('2026-10-19T10:00:00+03:00', notes([task('Подготви офертата за клиента', 'Иван')]))
        self.assertTrue(self.service._review_pending(ready, self.service.library.get(ready)))
        [item] = self.service.tasks()
        self.service.update_item(item['id'], item['text'], {'acceptance_state': 'accepted'})
        self.assertFalse(self.service._review_pending(ready, self.service.library.get(ready)))
        atomic_json(self.service.library.directory(ready) / 'transcript.json', [dict(start=0, end=5, text='Да.', speaker='SPEAKER_00')])
        self.assertTrue(self.service._review_pending(ready, self.service.library.get(ready)))


if __name__ == '__main__':
    unittest.main()
