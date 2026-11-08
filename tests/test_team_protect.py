import json
from pathlib import Path
import shutil
import tempfile
import unittest

from app import backup
from app.service import MeetingService
from app.work_items import WorkItemConflict
from tests.test_calendar import FakeGoogle

PROJECT = Path(__file__).resolve().parents[1]


class TeamProtectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.s = MeetingService(self.root / 'library', PROJECT, google=FakeGoogle(), backup_dir=self.root / 'backups'); self.addCleanup(self.s.close)
        self.maria = self.s.save_person(dict(name='Maria'))['person']

    def review(self, start='2026-10-20T00:00', end='2026-10-27T00:00', final=True):
        r = self.s.team_review_action('create', dict(person_id=self.maria['id'], start=start, end=end))
        return self.s.team_review_action('finalize', dict(id=r['id'], revision=r['revision'])) if final else r

    def agree(self, review, rows):
        return self.s.team_review_action('agreements', dict(id=review['id'], revision=review['revision'], agreements=rows))

    def test_agreements_stay_editable_after_finalize_and_keep_their_ids(self):
        review = self.review()
        saved = self.agree(review, [dict(kind='action', text='Write  the runbook', owner='person', due_date='2026-11-10', status='open'),
                                    dict(kind='goal', text='Own the backups', owner='both', status='open')])
        self.assertEqual([(a['kind'], a['text'], a['status']) for a in saved['agreements']], [('action', 'Write the runbook', 'open'), ('goal', 'Own the backups', 'open')])
        first = saved['agreements'][0]
        again = self.agree(saved, [dict(first, status='done'), saved['agreements'][1]])
        self.assertEqual((again['agreements'][0]['id'], again['agreements'][0]['created'], again['agreements'][0]['status']), (first['id'], first['created'], 'done'))
        self.assertEqual(again['review_md'], review['review_md'])  # the fixed review text does not change
        for bad in ([dict(kind='wish', text='x', owner='person', status='open')], [dict(kind='action', text='', owner='person', status='open')],
                    [dict(kind='action', text='x', owner='person', status='open', due_date='soon')]):
            with self.assertRaises(ValueError): self.agree(again, bad)
        with self.assertRaises(WorkItemConflict): self.agree(review, [])

    def test_the_next_review_tracks_the_agreements_of_the_last_one(self):
        review = self.review()
        review = self.agree(review, [dict(kind='goal', text='Own the backups', owner='person', status='open'),
                                     dict(kind='action', text='Send the plan', owner='manager', status='done')])
        draft = self.review('2026-10-27T00:00', '2026-11-03T00:00', final=False)
        self.assertIn('- Goal (the person): Own the backups · open', draft['review_md'])
        self.assertIn('- Action (the manager): Send the plan · done', draft['review_md'])
        self.assertEqual([e['kind'] for e in draft['evidence']].count('agreement'), 2)
        self.assertEqual(draft['previous_agreements']['review_id'], review['id'])

    def test_delete_removes_everything_and_restores_the_version_before(self):
        old = self.review()
        version = self.s.team_review_action('version', dict(id=old['id']))
        version = self.s.team_review_action('finalize', dict(id=version['id'], revision=version['revision']))
        self.assertEqual(self.s.team_reviews.get(old['id'])['status'], 'superseded')
        folder = self.s.team_reviews.directory(version['id'])
        self.s.team_review_action('delete', dict(id=version['id'], revision=version['revision']))
        self.assertFalse(folder.exists())
        self.assertEqual((self.s.team_reviews.get(old['id'])['status'], self.s.team_reviews.get(old['id'])['superseded_by']), ('finalized', None))

    def test_a_person_with_reviews_is_not_deleted(self):
        review = self.review()
        person = self.s.people.get(self.maria['id'])
        with self.assertRaises(ValueError): self.s.delete_person(person['id'], person['revision'])
        self.s.team_review_action('delete', dict(id=review['id'], revision=review['revision']))
        self.s.delete_person(person['id'], person['revision'])

    def test_backup_keeps_reviews_and_restore_adds_only_missing_ones(self):
        review = self.agree(self.review(), [dict(kind='goal', text='Own the backups', owner='person', status='open')])
        folder = self.s.team_reviews.directory(review['id'])
        (folder / '.ai-checkpoint.json').write_text('{}')
        archive = self.s.create_backup()['created']
        with __import__('tarfile').open(self.root / 'backups' / archive['name']) as tar:
            names = tar.getnames()
        self.assertTrue(archive['verified'])
        self.assertEqual(sorted(n.rsplit('/', 1)[1] for n in names if n.startswith('team-reviews/')),
                         ['agreements.json', 'conversation-notes.md', 'evidence.json', 'metadata.json', 'review.md'])
        manifest = json.loads(__import__('tarfile').open(self.root / 'backups' / archive['name']).extractfile('manifest.json').read())
        self.assertFalse(any(m.startswith('team') for m in manifest['meetings']))
        # A deleted review comes back; an existing one is never changed.
        shutil.rmtree(folder)
        other = self.review('2026-10-27T00:00', '2026-11-03T00:00')
        (self.s.team_reviews.directory(other['id']) / 'review.md').write_text('kept')
        result = backup.restore(self.root / 'backups' / archive['name'], self.s.library)
        self.assertEqual(result['reviews_restored'], 1)
        self.assertEqual(self.s.team_reviews.get(review['id'])['agreements'][0]['text'], 'Own the backups')
        self.assertEqual((self.s.team_reviews.directory(other['id']) / 'review.md').read_text(), 'kept')


if __name__ == '__main__':
    unittest.main()
