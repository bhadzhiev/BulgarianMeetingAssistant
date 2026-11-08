from pathlib import Path
import tempfile
import unittest

from app.service import MeetingService
from app.team_facts import collect
from app.team_github import section
from tests.test_calendar import FakeGoogle
from tests.test_team_facts import DAY

PROJECT = Path(__file__).resolve().parents[1]


class TeamCompareTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.s = MeetingService(Path(self.tmp.name) / 'library', PROJECT, google=FakeGoogle(), backup_dir=Path(self.tmp.name) / 'backups'); self.addCleanup(self.s.close)
        self.maria = self.s.save_person(dict(name='Maria'))['person']
        task = self.s.create_task(dict(text='Write the runbook', request_id='a' * 32))
        self.task = self.s.update_item(task['id'], task['text'], dict(owner_person_id=self.maria['id']), task['revision'])

    def finalized(self, start, end):
        review = self.s.team_review_action('create', dict(person_id=self.maria['id'], start=start, end=end))
        return self.s.team_review_action('finalize', dict(id=review['id'], revision=review['revision']))

    def test_first_review_has_nothing_to_compare(self):
        self.assertIn('This is the first review. There is nothing to compare yet.', collect(self.s, self.maria, DAY(1, 0), DAY(8, 0))['review_md'])

    def test_comparable_periods_show_the_change(self):
        # A later week: the task of setUp has no new fact in it.
        previous = dict(period=dict(start=DAY(13, 0), end=DAY(20, 0)), coverage=dict(sources=['meetings', 'tasks', 'decisions'], meetings=2, speaking=1, counts=dict(assigned=3)), evidence=[])
        text = collect(self.s, self.maria, DAY(20, 0), DAY(27, 0), previous)['review_md']
        self.assertIn('| Fact | Last review | This review | Change |', text)
        self.assertIn('| Assigned | 3 | 0 | -3 |', text)
        self.assertIn('A change in a count is not a measure of performance.', text)

    def test_different_periods_are_not_comparable(self):
        previous = dict(period=dict(start=DAY(1, 0), end=DAY(3, 0)), coverage=dict(sources=['meetings', 'tasks', 'decisions'], counts=dict(assigned=1)), evidence=[])
        text = collect(self.s, self.maria, DAY(3, 0), DAY(17, 0), previous)['review_md']
        self.assertIn('Not comparable: The periods differ in length (2 and 14 days).', text)
        self.assertNotIn('Change |', text)
        other = dict(previous, period=dict(start=DAY(1, 0), end=DAY(8, 0)), coverage=dict(sources=['meetings', 'gmail'], counts=dict(assigned=0)))
        self.assertIn('The two reviews have different sources.', collect(self.s, self.maria, DAY(8, 0), DAY(15, 0), other)['review_md'])

    def test_a_changed_source_marks_a_finalized_review(self):
        review = self.finalized('2026-11-01T00:00', '2026-11-09T00:00')
        self.assertEqual(review['source_changes'], [])
        task = self.s.items.items[self.task['id']]
        self.s.update_item(task['id'], task['text'], dict(due_date='2026-12-01'), task['revision'])
        changes = self.s.team_review(review['id'])['source_changes']
        self.assertEqual([(c['item_id'], c['removed']) for c in changes], [(self.task['id'], False)])

    def test_a_new_version_collects_again_against_the_review_before(self):
        first = self.finalized('2026-10-20T00:00', '2026-10-27T00:00')
        second = self.finalized('2026-10-27T00:00', '2026-11-09T00:00')
        version = self.s.team_review_action('version', dict(id=second['id']))
        again = self.s.team_review_action('collect', dict(id=version['id'], revision=version['revision']))
        self.assertIn('- Last review: 20.10.2026 – 27.10.2026', again['review_md'])
        self.assertEqual(again['supersedes'], second['id'])

    def test_rename_keeps_the_attribution(self):
        review = self.finalized('2026-11-01T00:00', '2026-11-09T00:00')
        person = self.s.people.get(self.maria['id'])
        self.s.save_person(dict(person, name='Maria Petrova'))
        read = self.s.team_review(review['id'])
        self.assertEqual((read['person_name'], read['person_current_name']), ('Maria', 'Maria Petrova'))
        self.assertFalse(self.s.team_review_prepare(self.maria['id'])['first'])

    def test_github_section_names_the_last_counts(self):
        result = dict(repositories=[], included=['acme/app'], authored=[], reviews=[], commits=[], merged_for_others=0, noise=0, limitations=[], calls=0)
        self.assertIn('Last review: 2 pull requests · 1 reviews · 0 commits without a pull request. This review: 0 · 0 · 0.', section(result, dict(authored=2, reviews=1, commits=0)))


if __name__ == '__main__':
    unittest.main()
