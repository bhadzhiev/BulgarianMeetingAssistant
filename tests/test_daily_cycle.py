import datetime as dt
import tempfile
import unittest
from pathlib import Path

from app import daily, manager_attention
from app.service import MeetingService
from app.storage import atomic_json
from app.work_items import WorkItemConflict
from tests.test_calendar import FakeGoogle

PROJECT = Path(__file__).resolve().parents[1]


class DailyCycleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.service = service = MeetingService(Path(temporary.name) / 'meetings', PROJECT, google=FakeGoogle())
        self.addCleanup(service.close)
        self.project = service.create_project('Infrastructure')['id']
        result = daily.create_series(service, dict(project_id=self.project, name='Team daily'))
        self.series = result['series_id']
        self.task = service.create_task(dict(text='Check access to Q01', project_id=self.project, request_id='a' * 32))
        self.before = service.prepare(series_id=self.series)['daily']

    def add_topic(self, text):
        return daily.change_agenda(self.service, dict(series_id=self.series, action='add', text=text,
                                  task_id=self.task['id'], revision=self.service.prepare(series_id=self.series)['daily']['agenda_revision']))

    def meeting(self, **fields):
        service = self.service
        meeting = service.library.create('Daily', 'in_person', {})
        service.set_scope(meeting['id'], dict(id=self.project), dict(id=self.series))
        service.library.update(meeting['id'], status='ready', duration=30,
                               started_at=(dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=1)).isoformat())
        directory = service.library.directory(meeting['id'])
        atomic_json(directory / 'transcript.json', [dict(start=0, end=10, speaker='Ana', text='Access is available; the check is due tomorrow.')])
        notes = dict(summary=[], decisions=[], tasks=[], updates=[], blockers=[], open_questions=[], needs_decision=[])
        notes.update(fields)
        service.edit(meeting['id'], dict(minutes=notes))
        return meeting['id']

    def test_topics_are_saved_between_dailies_and_explicitly_removed(self):
        updated = self.add_topic('Who can confirm the Q01 result?')
        with self.assertRaises(WorkItemConflict):
            daily.change_agenda(self.service, dict(series_id=self.series, action='add', text='Another topic',
                                                   revision=self.before['agenda_revision']))
        meeting = self.meeting()
        first = self.service.detail(meeting)['daily_review']
        self.assertEqual(first['topics'], updated['topics'])
        self.assertEqual(self.service.prepare(series_id=self.series)['daily']['topics'], updated['topics'])
        self.assertEqual(daily.create_series(self.service, dict(project_id=self.project, name='Team daily'))['series_id'], self.series)
        daily.change_agenda(self.service, dict(series_id=self.series, meeting_id=meeting, action='remove',
                            revision=first['agenda_revision'], id=first['topics'][0]['id']))
        self.assertEqual(self.service.prepare(series_id=self.series)['daily']['topics'], [])

    def test_updates_keep_evidence_and_are_idempotent(self):
        meeting = self.meeting(updates=[dict(text='Access granted; check is pending.', evidence_timestamp='00:00:00')])
        after = self.service.detail(meeting)['daily_review']
        row = after['rows'][0]
        request = dict(revision=after['revision'], key=row['key'], action='update', task_id=self.task['id'],
                       task_revision=self.task['revision'], changes=dict(workflow_state='waiting', follow_up_date='2026-11-25'))
        self.assertEqual(self.service.items.items[self.task['id']]['workflow_state'], 'todo')
        self.assertEqual(daily.review(self.service, meeting, request)['state'], 'applied')
        self.assertEqual(daily.review(self.service, meeting, request)['state'], 'applied')
        task = self.service.items.items[self.task['id']]
        updates = [event for event in task['history'] if event['event'] == 'progress_update']
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0]['quote'], 'Access is available; the check is due tomorrow.')
        self.assertEqual(task['follow_up_date'], '2026-11-25')
        self.assertEqual(self.service.prepare(series_id=self.series)['daily']['groups']['changed'][0]['item_id'], task['id'])
        self.assertEqual(self.service.detail(meeting)['daily_review']['rows'][0]['state'], 'applied')

    def test_a_promise_to_help_keeps_the_line_open_for_an_update(self):
        meeting = self.meeting(updates=[dict(text='Access granted; check is pending.', evidence_timestamp='00:00:00')])
        view = self.service.detail(meeting)['daily_review']
        key = view['rows'][0]['key']
        daily.review(self.service, meeting, dict(action='promise', key=key, revision=view['revision']))
        row = self.service.detail(meeting)['daily_review']['rows'][0]
        self.assertEqual((row['state'], row['help']['state']), ('pending', 'promise'))
        request = dict(revision=view['revision'], key=key, action='update', task_id=self.task['id'],
                       task_revision=self.task['revision'], changes=dict(workflow_state='waiting'))
        self.assertEqual(daily.review(self.service, meeting, request)['state'], 'applied')
        self.assertEqual(self.service.items.items[self.task['id']]['workflow_state'], 'waiting')
        row = self.service.detail(meeting)['daily_review']['rows'][0]
        self.assertEqual((row['state'], row['help']['state']), ('applied', 'promise'))
        daily.review(self.service, meeting, dict(action='helped', key=key, revision=view['revision']))
        row = self.service.detail(meeting)['daily_review']['rows'][0]
        self.assertEqual((row['state'], row['help']['state']), ('applied', 'helped'))
        self.assertEqual(manager_attention.build(self.service, '')['groups']['help'], [])

    def test_a_skipped_line_keeps_its_promise_and_old_receipts_still_read(self):
        meeting = self.meeting(blockers=[dict(text='Waiting for Q01 access', evidence_timestamp='00:00:00')])
        view = self.service.detail(meeting)['daily_review']
        key = view['rows'][0]['key']
        directory = self.service.library.directory(meeting)
        atomic_json(directory / daily.RECEIPTS, {key: dict(state='promise', text='Waiting for Q01 access', task_id=None)})
        row = self.service.detail(meeting)['daily_review']['rows'][0]
        self.assertEqual((row['state'], row['help']['state']), ('pending', 'promise'))
        daily.review(self.service, meeting, dict(action='skip', key=key, revision=view['revision']))
        daily.review(self.service, meeting, dict(action='reopen', key=key, revision=view['revision']))
        row = self.service.detail(meeting)['daily_review']['rows'][0]
        self.assertEqual((row['state'], row['help']['state']), ('pending', 'promise'))
        self.assertEqual(len(manager_attention.build(self.service, '')['groups']['help']), 1)

    def test_stale_source_and_stale_task_are_rejected(self):
        meeting = self.meeting(updates=[dict(text='Access granted', evidence_timestamp='00:00:00')])
        after = self.service.detail(meeting)['daily_review']
        common = dict(revision=after['revision'], key=after['rows'][0]['key'])
        with self.assertRaises(WorkItemConflict):
            daily.review(self.service, meeting, dict(common, action='skip', revision='old'))
        with self.assertRaises(WorkItemConflict):
            daily.review(self.service, meeting, dict(common, action='update', task_id=self.task['id'],
                                                    task_revision=self.task['revision'] + 1, changes={}))
        directory = self.service.library.directory(meeting)
        atomic_json(directory / 'minutes.proposed.json', dict(summary=[], decisions=[], tasks=[], open_questions=[]))
        self.assertEqual(self.service.detail(meeting)['daily_review']['status'], 'stale')
        with self.assertRaises(WorkItemConflict):
            daily.review(self.service, meeting, dict(common, action='skip'))

    def test_a_done_task_leaves_results_to_check(self):
        manager = self.service.save_person(dict(name='Manager'))['person']
        task = self.service.update_item(self.task['id'], self.task['text'], dict(owner_person_id=manager['id'],
                                       follow_up_date='2000-01-01'), self.task['revision'])
        self.assertEqual(len(manager_attention.build(self.service, manager['id'])['groups']['checks']), 1)
        self.service.update_item(task['id'], task['text'], dict(workflow_state='done'), task['revision'])
        self.assertEqual(manager_attention.build(self.service, manager['id'])['groups']['checks'], [])

    def test_a_shared_daily_without_a_project_updates_tasks_across_projects_and_reaches_needs_me(self):
        other = self.service.create_project('Applications')['id']
        second = self.service.create_task(dict(text='Renew the certificate', project_id=other, request_id='b' * 32))
        loose = self.service.create_task(dict(text='Order cables', request_id='c' * 32))
        archived = self.service.create_project('Old')['id']
        hidden = self.service.create_task(dict(text='Old work', project_id=archived, request_id='d' * 32))
        self.service.change_scope('projects', archived, 'archive')
        meeting = self.meeting(updates=[dict(text='The certificate is renewed.', evidence_timestamp='00:00:00')],
                               needs_decision=[dict(text='Do we buy a new UPS?', evidence_timestamp='00:00:00')])
        self.service.library.update(meeting, project_id=None, series_id=None)
        view = self.service.detail(meeting)['daily_review']
        offered = {task['id']: task['project'] for task in view['tasks']}
        self.assertEqual(offered, {self.task['id']: 'Infrastructure', second['id']: 'Applications', loose['id']: ''})
        self.assertNotIn(hidden['id'], offered)
        row = next(row for row in view['rows'] if row['field'] == 'updates')
        daily.review(self.service, meeting, dict(revision=view['revision'], key=row['key'], action='update', task_id=second['id'],
                                                 task_revision=second['revision'], changes=dict(workflow_state='done')))
        self.assertEqual(self.service.items.items[second['id']]['workflow_state'], 'done')
        decisions = manager_attention.build(self.service, '')['groups']['decisions']
        self.assertEqual([(row['text'], row['project']) for row in decisions], [('Do we buy a new UPS?', 'Daily')])

    def test_decision_is_checked_in_notes_and_handled_questions_leave_attention(self):
        meeting = self.meeting(decisions=[dict(text='Keep staging', evidence_timestamp='00:00:00')],
                               needs_decision=[dict(text='Approve another check?', evidence_timestamp='00:00:00')])
        self.assertEqual(len(manager_attention.build(self.service, '')['groups']['decisions']), 1)
        after = self.service.detail(meeting)['daily_review']
        daily.review(self.service, meeting, dict(revision=after['revision'], key=after['rows'][0]['key'], action='confirm'))
        meeting_data = self.service.detail(meeting)
        self.assertEqual(meeting_data['minutes']['decisions'][0]['review'], 'verified')
        after = meeting_data['daily_review']
        question = next(row for row in after['rows'] if row['field'] == 'needs_decision')
        daily.review(self.service, meeting, dict(revision=after['revision'], key=question['key'], action='skip'))
        self.assertEqual(manager_attention.build(self.service, '')['groups']['decisions'], [])

    def test_help_promise_survives_a_later_daily_and_revised_notes(self):
        meeting = self.meeting(blockers=[dict(text='Waiting for Q01 access', evidence_timestamp='00:00:00')])
        view = self.service.detail(meeting)['daily_review']
        key = view['rows'][0]['key']
        daily.review(self.service, meeting, dict(action='promise', key=key, revision=view['revision']))
        self.meeting()
        self.assertEqual(manager_attention.build(self.service, '')['groups']['help'][0]['text'], 'Waiting for Q01 access')
        current = self.service.detail(meeting)
        self.service.edit(meeting, dict(minutes_fields=dict(blockers=[]),
                                        minutes_base=dict(blockers=current['minutes']['blockers']),
                                        minutes_revision=current['minutes_revision']))
        view = self.service.detail(meeting)['daily_review']
        self.assertTrue(view['rows'][0]['source_changed'])
        daily.review(self.service, meeting, dict(action='helped', key=key, revision=view['revision']))
        self.assertEqual(manager_attention.build(self.service, '')['groups']['help'], [])

    def test_only_owned_or_followed_checks_are_shown_and_future_waiting_is_quiet(self):
        manager = self.service.save_person(dict(name='Manager'))['person']
        other = self.service.save_person(dict(name='Other'))['person']
        task = self.service.update_item(self.task['id'], self.task['text'], dict(owner_person_id=other['id'],
                                       follower_person_id=manager['id'], follow_up_date='2000-01-01'), self.task['revision'])
        self.assertEqual(manager_attention.build(self.service, manager['id'])['groups']['checks'][0]['task_id'], task['id'])
        self.assertEqual(manager_attention.build(self.service, '')['groups']['checks'], [])
        self.service.update_item(task['id'], task['text'], dict(workflow_state='waiting', follow_up_date='2099-01-01'), task['revision'])
        self.assertEqual(manager_attention.build(self.service, manager['id'])['groups']['checks'], [])
        self.assertEqual(manager_attention.build(self.service, other['id'])['groups']['help'], [])

    def test_a_shared_task_check_shows_to_the_co_assignee_and_names_the_owner(self):
        owner = self.service.save_person(dict(name='Owner'))['person']
        helper = self.service.save_person(dict(name='Helper'))['person']
        task = self.service.update_item(self.task['id'], self.task['text'], dict(assignee_person_ids=[owner['id'], helper['id']],
                                       follow_up_date='2000-01-01'), self.task['revision'])
        mine = manager_attention.build(self.service, owner['id'])['groups']['checks']
        self.assertEqual([(row['task_id'], row['reason']) for row in mine], [(task['id'], 'Next check is due')])
        shared = manager_attention.build(self.service, helper['id'])['groups']['checks']
        self.assertEqual([(row['task_id'], row['reason']) for row in shared], [(task['id'], 'Next check is due · Owner owns the check')])
