"""The review entry point counts pending receipts for this meeting, not all linked work."""
from pathlib import Path
import tempfile
import unittest

from app.service import MeetingService
from app.storage import atomic_json
from tests.test_calendar import FakeGoogle
from tests.test_manual_meeting_tasks import minutes

PROJECT = Path(__file__).resolve().parents[1]


class MeetingReviewVisibilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.service = MeetingService(Path(self.tmp.name), PROJECT, google=FakeGoogle())
        meeting = self.service.library.create('Review', 'in_person', {})
        self.mid = meeting['id']
        directory = self.service.library.directory(self.mid)
        atomic_json(directory / 'transcript.json', [dict(start=0, end=5, text='Иван ще изпрати оферта.', speaker='Иван')])
        atomic_json(directory / 'minutes.json', minutes('Изпрати оферта'))

    def tearDown(self):
        self.service.close()
        self.tmp.cleanup()

    def test_manual_mode_has_no_artificial_review_step(self):
        self.assertEqual(self.service.detail(self.mid)['meeting_review_count'], 0)
        self.service.create_task(dict(text='Изпрати оферта', owner='Иван', due_date=None,
                                     meeting_id=self.mid, project_id=None, request_id='a' * 32, mention_index=0))
        self.assertEqual(self.service.detail(self.mid)['meeting_review_count'], 0)

    def test_pending_proposal_is_counted_and_confirming_it_clears_the_count(self):
        from app import meeting_review
        self.service.save_settings(dict(meeting_task_ai=True))
        self.service.item_list()
        self.assertEqual(self.service.detail(self.mid)['meeting_review_count'], 1)
        snapshot = meeting_review.snapshot(self.service, self.mid)
        item = snapshot['items'][0]
        meeting_review.act(self.service, dict(meeting_id=self.mid, item_id=item['id'], source=snapshot['source'],
                                         content=item['content'], action='confirm'))
        self.assertEqual(self.service.detail(self.mid)['meeting_review_count'], 0)

    def test_closed_or_hidden_work_does_not_create_a_review_entry(self):
        self.service.save_settings(dict(meeting_task_ai=True))
        self.service.item_list()
        task = next(iter(self.service.items.items.values()))
        with self.service.items.lock:
            task['status'] = 'done'
        self.assertEqual(self.service.detail(self.mid)['meeting_review_count'], 0)
        with self.service.items.lock:
            task['status'] = 'open'
            task['dismissed'] = True
        self.assertEqual(self.service.detail(self.mid)['meeting_review_count'], 0)
        with self.service.items.lock:
            task['dismissed'] = False
            task['links'][0]['detached'] = True
        self.assertEqual(self.service.detail(self.mid)['meeting_review_count'], 0)
