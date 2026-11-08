import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app import team_reviews
from app.team_reviews import TeamReviews, TZ
from app.work_items import WorkItemConflict

NOW = dt.datetime(2026, 11, 8, 15, 30, tzinfo=TZ)
MARIA = dict(id='a1b2c3d4e5f6', name='Maria')


class TeamReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        clock = patch.object(team_reviews, '_now', return_value=NOW); clock.start(); self.addCleanup(clock.stop)
        self.r = TeamReviews(self.root)

    def draft(self, **period):
        p = self.r.next_period(MARIA['id'])
        return self.r.create(MARIA, period.get('start', p['start']), period.get('end', p['end']))

    def test_first_period_is_the_last_seven_days_in_sofia(self):
        p = self.r.next_period(MARIA['id'])
        self.assertEqual((p['start'], p['end'], p['timezone'], p['first']), ('2026-11-01T15:30:00+02:00', '2026-11-08T15:30:00+02:00', 'Europe/Sofia', True))

    def test_files_and_template(self):
        review = self.draft()
        folder = self.root / 'team-reviews' / MARIA['id'] / review['id']
        self.assertEqual(sorted(p.name for p in folder.iterdir()), ['conversation-notes.md', 'evidence.json', 'metadata.json', 'review.md'])
        self.assertIn('## Questions for the conversation', review['review_md'])
        self.assertEqual((review['status'], review['version'], review['notes_md']), ('draft', 1, ''))
        self.assertFalse(list((self.root / 'team-reviews' / MARIA['id']).glob('.*')))

    def test_draft_and_discard_do_not_move_the_period(self):
        first = self.r.next_period(MARIA['id'])
        review = self.draft()
        self.assertEqual(self.r.next_period(MARIA['id']), first)
        with self.assertRaises(ValueError): self.draft()
        self.r.discard(review['id'], review['revision'])
        self.assertEqual(self.r.next_period(MARIA['id']), first)
        with self.assertRaises(ValueError): self.r.get(review['id'])

    def test_next_period_starts_at_the_end_of_the_last_finalized_review(self):
        review = self.draft(start='2026-10-20T09:00', end='2026-10-27T09:00')
        self.r.finalize(review['id'], review['revision'])
        p = self.r.next_period(MARIA['id'])
        self.assertEqual((p['start'], p['end'], p['first']), ('2026-10-27T09:00:00+02:00', '2026-11-08T15:30:00+02:00', False))

    def test_finalized_review_is_fixed_and_notes_stay_editable(self):
        review = self.draft()
        review = self.r.save_review(review['id'], review['revision'], '# Edited')
        with self.assertRaises(WorkItemConflict): self.r.save_review(review['id'], review['revision'] - 1, '# Old')
        review = self.r.finalize(review['id'], review['revision'])
        self.assertEqual(review['status'], 'finalized'); self.assertTrue(review['finalized_at'])
        with self.assertRaises(ValueError): self.r.save_review(review['id'], review['revision'], '# Changed')
        with self.assertRaises(ValueError): self.r.discard(review['id'], review['revision'])
        review = self.r.save_notes(review['id'], review['revision'], 'Agreed: weekly check.')
        self.assertEqual((review['review_md'], review['notes_md']), ('# Edited', 'Agreed: weekly check.'))

    def test_correction_is_a_new_version_that_supersedes_the_old_one(self):
        old = self.draft(start='2026-10-20T09:00', end='2026-10-27T09:00')
        old = self.r.finalize(old['id'], old['revision'])
        new = self.r.create(MARIA, old['period']['start'], old['period']['end'], supersedes=old['id'])
        self.assertEqual((new['version'], new['supersedes'], new['period'], new['review_md']), (2, old['id'], old['period'], old['review_md']))
        self.assertEqual(self.r.get(old['id'])['status'], 'finalized')
        new = self.r.finalize(new['id'], new['revision'])
        old = self.r.get(old['id'])
        self.assertEqual((old['status'], old['superseded_by']), ('superseded', new['id']))
        with self.assertRaises(ValueError): self.r.create(MARIA, old['period']['start'], old['period']['end'], supersedes=old['id'])

    def test_period_is_validated(self):
        for start, end in [('2026-11-05T10:00', '2026-11-05T10:00'), ('2025-01-01T00:00', '2026-11-01T00:00'), ('2026-11-08T00:00', '2026-11-20T00:00'), ('x', '2026-11-01T00:00')]:
            with self.assertRaises(ValueError): self.r.create(MARIA, start, end)

    def test_list_and_summary(self):
        review = self.draft(start='2026-10-20T09:00', end='2026-10-27T09:00')
        self.r.finalize(review['id'], review['revision'])
        draft = self.draft()
        self.assertEqual([r['id'] for r in self.r.list()], [draft['id'], review['id']])
        summary = self.r.summary(MARIA['id'])
        self.assertEqual((summary['last_finalized']['id'], summary['draft']['id']), (review['id'], draft['id']))
        self.assertNotIn('review_md', self.r.list()[0])


if __name__ == '__main__':
    unittest.main()
