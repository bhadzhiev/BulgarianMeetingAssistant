import datetime as dt
from pathlib import Path
import tempfile
import unittest

from app.service import MeetingService
from app.storage import atomic_json
from app.team_facts import collect, TZ
from tests.test_calendar import FakeGoogle

PROJECT = Path(__file__).resolve().parents[1]
DAY = lambda d, h=12: dt.datetime(2026, 11, d, h, tzinfo=TZ).isoformat()


class TeamFactTests(unittest.TestCase):
    """A synthetic week, 2–9 November 2026. Each history time is set by hand."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.s = MeetingService(Path(self.tmp.name) / 'library', PROJECT, google=FakeGoogle(), backup_dir=Path(self.tmp.name) / 'backups'); self.addCleanup(self.s.close)
        self.maria = self.s.save_person(dict(name='Maria'))['person']
        self.ivan = self.s.save_person(dict(name='Ivan'))['person']
        meeting = self.s.library.create('Planning', 'in_person', self.s.settings)
        self.s.library.update(meeting['id'], status='ready', started_at=DAY(3, 10))
        self.meeting = meeting['id']
        atomic_json(self.s.library.directory(self.meeting) / 'transcript.json', [
            dict(start=10, end=14, speaker='Maria', text='I will finish the VPN rollout by Friday.'),
            dict(start=20, end=24, speaker='SPEAKER_01', text='Somebody checks the backups.')])

    def task(self, text, request, **changes):
        task = self.s.create_task(dict(text=text, request_id=request * 32))
        if changes:
            task = self.s.update_item(task['id'], task['text'], changes, task['revision'])
        return task

    def times(self, task, *moments, created=None):
        """Give the history events of a task these times, in order."""
        item = self.s.items.items[task['id']]
        if created: item['created'] = created
        for event, moment in zip(item['history'], moments):
            event['at'] = moment
        self.s.items.save()

    def link(self, task, stamp):
        item = self.s.items.items[task['id']]
        item['links'] = [dict(meeting_id=self.meeting, evidence_timestamp=stamp, seen=dict(task=item['text'], owner=item.get('owner'), deadline=None, due_date=None, status='open'))]
        self.s.items.save()

    def run_week(self, person=None, previous=None):
        return collect(self.s, person or self.maria, DAY(2, 0), DAY(9, 0), previous)

    def facts(self, result, kind):
        return [e for e in result['evidence'] if e['kind'] == kind]

    def test_assigned_taken_on_completed_and_confirmed_are_different_facts(self):
        a = self.task('Roll out the VPN', 'a', owner_person_id=self.maria['id'])
        a = self.s.update_item(a['id'], a['text'], dict(workflow_state='done'), a['revision'])
        a = self.s.update_item(a['id'], a['text'], dict(update_note='Checked with the client', update_evidence_id=None), a['revision'])
        self.times(a, DAY(3), DAY(3, 13), DAY(5), DAY(5, 14), created=DAY(3))
        self.link(a, '00:00:11')
        result = self.run_week()
        counts = result['coverage']['counts']
        self.assertEqual((counts['assigned'], counts['taken on'], counts['completed']), (1, 1, 1))
        self.assertEqual(self.facts(result, 'task_taken_on')[0]['quote'], 'I will finish the VPN rollout by Friday.')
        self.assertEqual(self.facts(result, 'task_taken_on')[0]['confirmation_basis'], 'The person said it in a meeting (confirmed name)')
        self.assertEqual(counts['result confirmed'], 0)  # an update without evidence does not confirm the result
        self.assertIn('[e1]', result['review_md'])
        self.assertTrue(all(len(e['quote']) <= 500 for e in result['evidence']))

    def test_overdue_belongs_to_the_owner_on_the_due_date(self):
        t = self.task('Fix the backup job', 'b', owner_person_id=self.ivan['id'], due_date='2026-11-04')
        t = self.s.update_item(t['id'], t['text'], dict(owner_person_id=self.maria['id']), t['revision'])
        self.times(t, DAY(1), DAY(1), DAY(6), created=DAY(1))
        self.assertEqual(self.run_week(self.maria)['coverage']['counts']['overdue'], 0)
        self.assertEqual(self.run_week(self.ivan)['coverage']['counts']['overdue'], 1)
        self.assertEqual(self.run_week(self.ivan)['coverage']['counts']['transferred'], 1)

    def test_shared_task_counts_the_others_apart_and_until_a_date(self):
        t = self.task('Migrate the printers', 'c', assignee_person_ids=[self.maria['id'], self.ivan['id']])
        t = self.s.update_item(t['id'], t['text'], dict(assignee_person_ids=[self.maria['id']]), t['revision'])
        self.times(t, DAY(2, 9), DAY(2, 9), DAY(6), created=DAY(2, 9))
        ivan = self.run_week(self.ivan)
        self.assertEqual((ivan['coverage']['counts']['joined'], ivan['coverage']['counts']['left'], ivan['coverage']['counts']['assigned']), (1, 1, 0))
        self.assertIn('until 06.11.2026', ivan['review_md'])
        maria = self.run_week(self.maria)
        self.assertEqual(maria['coverage']['counts']['assigned'], 1)
        self.assertIn('shared', maria['review_md'])

    def test_cancelled_is_visible(self):
        t = self.task('Order new laptops', 'd', owner_person_id=self.maria['id'])
        t = self.s.update_item(t['id'], t['text'], dict(workflow_state='cancelled'), t['revision'])
        self.times(t, DAY(3), DAY(3), DAY(4), created=DAY(3))
        self.assertEqual(self.run_week()['coverage']['counts']['cancelled'], 1)

    def test_name_only_owner_is_excluded_and_counts_nothing(self):
        t = self.task('Check the firewall', 'e', owner='Maria')
        # Both events (created, owner set) are in the week; the second had the real time before.
        self.times(t, DAY(3), DAY(3), created=DAY(3))
        result = self.run_week()
        self.assertEqual(sum(result['coverage']['counts'].values()), 0)
        self.assertEqual([row['item_id'] for row in result['excluded']], [t['id']])
        self.assertIn('Excluded from the analysis', result['review_md'])

    def test_open_commitments_of_the_last_review_carry_over(self):
        t = self.task('Write the runbook', 'f', owner_person_id=self.maria['id'])
        self.times(t, DAY(1), DAY(1), created=DAY(1))
        first = collect(self.s, self.maria, DAY(1, 0), DAY(2, 0))
        self.assertTrue(any(e['facts'].get('open_at_end') for e in first['evidence']))
        later = self.run_week(previous=dict(evidence=first['evidence']))
        self.assertIn('Write the runbook · now to do', later['review_md'])
        self.assertIn('This is the first review', first['review_md'])

    def test_same_input_gives_the_same_review(self):
        t = self.task('Roll out the VPN', '1', owner_person_id=self.maria['id'])
        self.times(t, DAY(3), DAY(3), created=DAY(3))
        self.assertEqual(self.run_week(), self.run_week())
        self.assertIn('Work that nobody recorded in Atlanta is not missing work.', self.run_week()['coverage']['limitations'])


if __name__ == '__main__':
    unittest.main()
