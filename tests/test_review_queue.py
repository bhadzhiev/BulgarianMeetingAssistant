from pathlib import Path
import tempfile
import unittest

from app.meeting_review import act, snapshot
from app.review_queue import build
from app.service import MeetingService
from app.storage import atomic_json
from tests.test_calendar import FakeGoogle
from tests.test_people_github import PROJECT, ROWS
from tests.ai_meeting_tasks import setUpModule, tearDownModule  # noqa: F401  AI meeting tasks are on in these tests


class ReviewQueueTests(unittest.TestCase):
    """My Work lists every meeting that waits for a person, with the same states as its Review tab."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.s = MeetingService(root / 'library', PROJECT, google=FakeGoogle(), backup_dir=root / 'archives')
        self.addCleanup(self.s.close)
        self.mid = self.meeting('Platform sync', ROWS, tasks=[dict(task='Обнови Kubernetes клъстера', owner='Иван', deadline='петък', evidence_timestamp='00:00:12')])

    def meeting(self, title, rows, tasks=None):
        key = self.s.library.create(title, 'in_person', self.s.settings)['id']
        self.s.library.update(key, created='2026-10-27T08:00:00Z', started_at='2026-10-27T08:00:00Z', status='ready', duration=40)
        atomic_json(self.s.library.directory(key) / 'transcript.json', rows)
        if tasks is not None:
            self.s.edit(key, dict(minutes=dict(summary=[], open_questions=[], decisions=[], tasks=tasks)))
        return key

    def row(self, key=None):
        return next((r for r in build(self.s)['meetings'] if r['id'] == (key or self.mid)), None)

    def test_a_meeting_lists_unnamed_speakers_and_items_to_review(self):
        row = self.row()
        self.assertEqual((row['speakers'], row['items'], row['notes']), (1, 1, None))
        pending = [r for r in snapshot(self.s, self.mid)['items'] if r['state'] == 'needs_review']
        self.assertEqual(row['items'], len(pending))

    def test_names_then_updated_notes_then_confirm_empty_the_queue(self):
        revision = self.s.detail(self.mid)['transcript_revision']
        self.s.edit(self.mid, dict(speaker_name=dict(speaker='SPEAKER_00', name='Петър', revision=revision)))
        # A new name changes the transcript, so the notes wait for an update before a confirm.
        self.assertEqual((self.row()['speakers'], self.row()['notes']), (0, 'refresh'))
        self.s.library.update(self.mid, notes_need_refresh=False)
        view = snapshot(self.s, self.mid)
        item = view['items'][0]
        act(self.s, dict(meeting_id=self.mid, item_id=item['id'], action='confirm', source=view['source'], content=item['content']))
        self.assertIsNone(self.row())
        self.assertEqual(build(self.s)['totals'], dict(meetings=0, speakers=0, items=0, notes=0))

    def test_a_changed_transcript_asks_for_new_notes(self):
        self.s.library.update(self.mid, notes_need_refresh=True)
        self.assertEqual(self.row()['notes'], 'refresh')

    def test_items_review_is_blocked_while_the_notes_wait_for_an_update(self):
        self.s.library.update(self.mid, notes_need_refresh=True)
        row = self.row()
        self.assertEqual((row['items'], row['review_blocked']), (1, True))

    def test_items_review_is_actionable_when_the_notes_are_current(self):
        row = self.row()
        self.assertEqual((row['items'], row['review_blocked']), (1, False))

    def test_named_meeting_without_notes_is_not_listed(self):
        named = self.meeting('Retro', [dict(start=0, end=5, speaker='Мария', text='Готово.')])
        self.assertIsNone(self.row(named))
        self.assertEqual(build(self.s)['totals']['meetings'], 1)


if __name__ == '__main__':
    unittest.main()
