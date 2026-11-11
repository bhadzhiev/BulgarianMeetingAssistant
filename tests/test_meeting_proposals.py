import json
from pathlib import Path
import tempfile
import unittest

from app import meeting_proposals
from app.service import MeetingService
from app.storage import atomic_json
from app.work_items import WorkItemConflict
from tests.test_calendar import FakeGoogle

PROJECT = Path(__file__).resolve().parents[1]
ROWS = [dict(start=0, end=5, text='Офертата за клиента е почти готова, остава цената.', speaker='Иван'),
        dict(start=6, end=9, text='Нека срокът стане двадесети ноември.', speaker='Мария')]


def task(text, owner=None, stamp='00:00:00'):
    return dict(task=text, owner=owner, deadline=None, due_date=None, evidence_timestamp=stamp)


class MeetingProposalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.service = MeetingService(Path(self.tmp.name), PROJECT, google=FakeGoogle())

    def tearDown(self):
        self.service.close()
        self.tmp.cleanup()

    def meeting(self, when, minutes, matching=None):
        meeting = self.service.library.create('Среща', 'in_person', {})
        self.service.library.update(meeting['id'], status='ready', duration=60, started_at=when, created=when)
        directory = self.service.library.directory(meeting['id'])
        atomic_json(directory / 'transcript.json', ROWS)
        if matching:
            atomic_json(directory / 'task-matching.json', matching)
        self.service.edit(meeting['id'], {'minutes': dict(dict(summary=[], decisions=[], open_questions=[], tasks=[]), **minutes)})
        return meeting['id']

    def accepted(self, text='Подготви офертата за клиента'):
        self.meeting('2026-10-19T10:00:00+03:00', dict(tasks=[task(text, 'Иван')]))
        [item] = [i for i in self.service.tasks() if i['text'] == text]
        self.service.update_item(item['id'], item['text'], {'acceptance_state': 'accepted'})
        return self.service.items.items[item['id']]

    def proposals(self):
        return [p for p in self.service.items.data['proposals'].values() if p.get('origin') == meeting_proposals.ORIGIN]

    def review(self, proposal, action, **extra):
        target = self.service.items.items.get(extra.get('task_id') or proposal['match']['task_id'] or '')
        body = dict(id=proposal['id'], revision=proposal['revision'], action=action, task_id=target and target['id'],
                    task_revision=target and target.get('revision'))
        body.update(extra)
        return meeting_proposals.review(self.service, body)

    def ai(self, item, mention_type, key='u0', text='Офертата е почти готова', **extra):
        match = dict(mention_id=key, type=mention_type, task_id=item['id'], reason='Same offer', update_text=None, changes=[])
        match.update(extra)
        return dict(version=1, status='complete', notes='minutes.json', mentions=[dict(id=key, text=text, candidate_ids=[item['id']])],
                    matches=[match], rejected=[])

    def test_text_similarity_makes_a_proposal_and_link_adds_evidence_only(self):
        item = self.accepted()
        second = self.meeting('2026-10-23T10:00:00+03:00', dict(tasks=[task('Подготви офертата за клиента до петък', 'Мария')]))
        [proposal] = self.proposals()
        self.assertEqual((proposal['match']['type'], proposal['match']['basis']), ('uncertain', 'similarity'))
        self.assertEqual(proposal['match']['task_id'], item['id'])
        self.review(proposal, 'link')
        item = self.service.items.items[item['id']]
        self.assertEqual({l['meeting_id'] for l in item['links']} >= {second}, True)
        self.assertEqual(item['owner'], 'Иван')  # link is evidence only
        minutes = json.loads((self.service.library.directory(second) / 'minutes.json').read_text())
        self.assertEqual(minutes['tasks'][0]['item_id'], item['id'])
        self.assertNotIn('link', minutes['tasks'][0])
        self.assertEqual(self.proposals()[0]['state'], 'linked')
        # A second click finds no pending proposal; nothing repeats.
        with self.assertRaises(WorkItemConflict):
            self.review(proposal, 'link')
        # Running the build again creates nothing new.
        self.service._sync_items(second)
        self.assertEqual(len(self.proposals()), 1)

    def test_an_ai_update_adds_the_accepted_text_to_the_history(self):
        item = self.accepted()
        meeting = self.meeting('2026-10-23T10:00:00+03:00', dict(updates=[dict(text='Офертата е почти готова', evidence_timestamp='00:00:00', quote=None)]),
                               self.ai(item, 'existing_update', update_text='Офертата е почти готова, остава цената'))
        [proposal] = self.proposals()
        self.assertEqual(proposal['match']['basis'], 'ai')
        self.review(proposal, 'update', update_text='Остава само цената')
        item = self.service.items.items[item['id']]
        update = [e for e in item['history'] if e['event'] == 'progress_update'][-1]
        self.assertEqual((update['text'], update['meeting_id'], update['proposal_id'], update['by']), ('Остава само цената', meeting, proposal['id'], 'user'))
        self.assertIn('Офертата за клиента е почти готова', update['quote'])
        self.assertIn(meeting, {l['meeting_id'] for l in item['links']})

    def test_only_the_chosen_changes_apply_and_a_changed_task_is_a_conflict(self):
        item = self.accepted()
        self.meeting('2026-10-23T10:00:00+03:00', dict(updates=[dict(text='Офертата е почти готова', evidence_timestamp='00:00:06', quote=None)]),
                     self.ai(item, 'proposed_change', changes=[dict(field='due_date', value='2026-11-20'), dict(field='workflow_state', value='waiting')]))
        [proposal] = self.proposals()
        stale = dict(proposal)
        self.service.update_item(item['id'], item['text'], {'details': 'Нови условия'})
        with self.assertRaisesRegex(WorkItemConflict, 'changed after the proposal opened'):
            meeting_proposals.review(self.service, dict(id=stale['id'], revision=stale['revision'], action='change', task_id=item['id'],
                                                        task_revision=item['revision'], fields=['due_date']))
        for wrong in ([], ['owner']):
            with self.assertRaisesRegex(ValueError, 'proposed changes'):
                self.review(self.proposals()[0], 'change', fields=wrong)
        self.assertEqual(self.proposals()[0]['state'], 'pending')  # a refused choice changes nothing
        self.review(self.proposals()[0], 'change', fields=['due_date'])
        item = self.service.items.items[item['id']]
        self.assertEqual((item['due_date'], item['workflow_state']), ('2026-11-20', 'todo'))

    def test_new_and_reject_keep_the_mention_as_its_own_task(self):
        self.accepted()
        second = self.meeting('2026-10-23T10:00:00+03:00', dict(tasks=[task('Подготви офертата за клиента до петък', 'Мария')]))
        [proposal] = self.proposals()
        self.review(proposal, 'new')
        minutes = json.loads((self.service.library.directory(second) / 'minutes.json').read_text())
        own = self.service.items.items[minutes['tasks'][0]['item_id']]
        self.assertEqual((own['text'], own['acceptance_state']), ('Подготви офертата за клиента до петък', 'proposed'))
        self.assertEqual(self.proposals()[0]['state'], 'accepted')

    def test_the_generic_review_refuses_a_meeting_match_and_old_links_migrate(self):
        self.accepted()
        self.meeting('2026-10-23T10:00:00+03:00', dict(tasks=[task('Подготви офертата за клиента до петък')]))
        [proposal] = self.proposals()
        with self.assertRaisesRegex(ValueError, 'own buttons'):
            self.service.work_graph_action('review', dict(id=proposal['id'], revision=proposal['revision'], action='accept'))
        # The old link review is gone from the list; For review counts the proposal.
        self.assertEqual(self.service.item_list()['pending'], [])
        self.assertEqual(self.service.task_summary()['review'], 1)

    def test_an_unknown_task_or_changed_notes_are_refused(self):
        item = self.accepted()
        second = self.meeting('2026-10-23T10:00:00+03:00', dict(tasks=[task('Подготви офертата за клиента до петък')]))
        [proposal] = self.proposals()
        with self.assertRaisesRegex(ValueError, 'suggested tasks'):
            self.review(proposal, 'link', task_id='0' * 16)
        directory = self.service.library.directory(second)
        minutes = json.loads((directory / 'minutes.json').read_text())
        minutes['tasks'][0]['task'] = 'Друг текст'
        atomic_json(directory / 'minutes.json', minutes)
        with self.assertRaisesRegex(WorkItemConflict, 'notes changed'):
            self.review(proposal, 'link')
        self.assertEqual(self.service.items.items[item['id']]['links'][0]['meeting_id'] != second, True)

    def test_a_stale_match_proposal_can_be_dismissed_without_touching_the_notes(self):
        item = self.accepted()
        second = self.meeting('2026-10-23T10:00:00+03:00', dict(tasks=[task('Подготви офертата за клиента до петък', 'Мария')]))
        [proposal] = self.proposals()
        directory = self.service.library.directory(second)
        atomic_json(directory / 'transcript.json', ROWS + [dict(start=10, end=14, text='Да я финализираме до петък.', speaker='Мария')])
        self.service._sync_items(second)
        stale = self.service.items.data['proposals'][proposal['id']]
        self.assertEqual(stale['state'], 'stale')
        result = self.review(stale, 'reject')
        self.assertEqual(result['state'], 'dismissed')
        minutes = json.loads((directory / 'minutes.json').read_text())
        self.assertNotIn('item_id', minutes['tasks'][0])
        self.assertNotIn(second, {link['meeting_id'] for link in self.service.items.items[item['id']]['links']})
        self.assertEqual(sorted(p['state'] for p in self.proposals()), ['dismissed', 'pending'])

    def test_task_summary_counts_source_proposals_that_need_a_decision(self):
        from app.work_graph import WorkGraph
        self.accepted()
        graph = WorkGraph(self.service.items)
        first = graph.ingest(dict(provider='fixture', account='synthetic', external_id='mail', revision='1', text='Renew the certificate'),
                             [dict(kind='task', text='Renew the certificate', quote='Renew the certificate')])
        self.assertEqual(self.service.task_summary()['suggested'], 1)
        graph.review(first['proposals'][0], 1, 'snooze', snoozed_until='2099-12-01')
        self.assertEqual(self.service.task_summary()['suggested'], 0)
        graph.ingest(dict(provider='fixture', account='synthetic', external_id='mail', revision='2', text='Renew the certificate soon'),
                     [dict(kind='task', text='Renew the certificate soon', quote='Renew the certificate soon')])
        # The source change staled the snoozed one and added a new pending proposal; each needs a decision.
        self.assertEqual(self.service.task_summary()['suggested'], 2)


if __name__ == '__main__':
    unittest.main()
