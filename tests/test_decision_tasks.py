"""A task made from a meeting decision implements that exact decision without approving it."""
import copy
import unittest
from app.storage import atomic_json
from app.work_items import WorkItemConflict
from tests import test_manual_tasks


class DecisionTaskTests(unittest.TestCase):
    setUp = test_manual_tasks.ManualTaskTests.setUp
    create = test_manual_tasks.ManualTaskTests.create

    def seed(self, decisions=None):
        minutes = dict(summary=[], tasks=[], decisions=decisions if decisions is not None else [
            dict(text='Мигрираме базата към v2', evidence_timestamp='00:00:24', review='ai', rationale='Старата версия няма поддръжка')], open_questions=[])
        atomic_json(self.service.library.directory(self.meeting) / 'minutes.json', minutes)
        self.service._sync_items(self.meeting)
        return self.service.detail(self.meeting)

    def from_decision(self, request='a'*32, index=0):
        detail = self.service.detail(self.meeting)
        row = detail['minutes']['decisions'][index]
        body = dict(text='Планирай миграцията', request_id=request, meeting_id=self.meeting,
            minutes_revision=detail['minutes_revision'], decision_source=dict(index=index, text=row['text'], evidence_timestamp=row['evidence_timestamp']))
        return self.service.create_task(body), body

    def test_manual_mode_has_both_links_without_approving_decision(self):
        self.seed()
        task, body = self.from_decision()
        detail = self.service.detail(self.meeting)
        source_id = detail['decision_items']['0']
        self.assertEqual(detail['decision_tasks'], {source_id:[task['id']]})
        self.assertEqual(detail['minutes']['decisions'][0]['item_id'], source_id)
        self.assertEqual(detail['items'][source_id]['status'], 'proposed')
        self.assertEqual(detail['minutes']['decisions'][0]['text'], 'Мигрираме базата към v2')
        self.assertEqual(task['links'][0]['evidence_timestamp'], '00:00:24')
        self.assertEqual(self.service.effective_project_ids(task), [self.project])
        data = self.service.item_list()
        self.assertEqual([i['id'] for i in data['items']], [task['id']])
        self.assertEqual(data['derived_sources'][source_id]['text'], 'Мигрираме базата към v2')
        self.assertTrue(any(e['kind']=='implements' and e['from_id']==task['id'] and e['to_id']==source_id for e in data['graph']['relationships']))
        self.assertEqual(self.service.create_task(body)['id'], task['id'])
        self.assertEqual(len(self.service.items.data['relationships']), 1)

    def test_second_task_reuses_canonical_decision(self):
        self.seed()
        first, _ = self.from_decision()
        second, _ = self.from_decision('b'*32)
        detail = self.service.detail(self.meeting)
        self.assertEqual(len([i for i in self.service.items.items.values() if i['kind']=='decision']), 1)
        self.assertEqual(detail['decision_tasks'][detail['decision_items']['0']], [first['id'],second['id']])

    def test_existing_ai_decision_reused_and_not_accepted_by_task(self):
        self.service.save_settings(dict(meeting_task_ai=True))
        detail = self.seed()
        decision_id = detail['minutes']['decisions'][0]['item_id']
        self.from_decision()
        self.assertEqual(self.service.detail(self.meeting)['decision_items']['0'], decision_id)
        self.assertEqual(self.service.items.items[decision_id]['status'], 'proposed')

    def test_verified_decision_keeps_accepted_state(self):
        self.seed([dict(text='Мигрираме базата към v2', evidence_timestamp='00:00:24', review='verified')])
        self.from_decision()
        detail = self.service.detail(self.meeting)
        self.assertEqual(detail['items'][detail['decision_items']['0']]['status'], 'accepted')
        self.assertEqual(detail['minutes']['decisions'][0]['review'], 'verified')

    def test_stale_or_tampered_source_leaves_no_task_or_decision(self):
        detail = self.seed()
        source = dict(index=0, text='Мигрираме базата към v2', evidence_timestamp='00:00:24')
        body = dict(text='Мигрирай', request_id='a'*32, meeting_id=self.meeting, decision_source=source, minutes_revision=detail['minutes_revision'])
        tampered = copy.deepcopy(body);tampered['decision_source']['text']='Друго решение'
        with self.assertRaises(WorkItemConflict):self.service.create_task(tampered)
        self.seed([])
        with self.assertRaises(WorkItemConflict):self.service.create_task(body)
        self.assertEqual(self.service.items.items, {})

    def test_source_descriptor_requires_revision_and_cannot_mix_with_question(self):
        self.seed()
        body = dict(text='Мигрирай', request_id='a'*32, meeting_id=self.meeting,
            decision_source=dict(index=0,text='Мигрираме базата към v2',evidence_timestamp='00:00:24'))
        for changed in ({}, {'question_id':'anything'}, {'decision_source':{'index':True}}, {'mention_index':0}):
            with self.subTest(changed=changed),self.assertRaises(ValueError):self.service.create_task(body|changed)
        self.assertEqual(self.service.items.items, {})

    def test_regeneration_keeps_task_moment_and_decision_identity(self):
        self.seed()
        task, _ = self.from_decision()
        source_id = self.service.detail(self.meeting)['decision_items']['0']
        self.seed()
        detail = self.service.detail(self.meeting)
        self.assertEqual(detail['decision_items']['0'], source_id)
        self.assertEqual(detail['decision_tasks'][source_id], [task['id']])
        self.assertEqual(detail['items'][task['id']]['links'][0]['evidence_timestamp'], '00:00:24')

    def test_deleting_task_keeps_original_decision(self):
        self.seed()
        task, _ = self.from_decision()
        self.service.delete_item(task['id'], task['text'], task['revision'])
        detail = self.service.detail(self.meeting)
        self.assertEqual(detail['minutes']['decisions'][0]['text'], 'Мигрираме базата към v2')
        self.assertEqual(detail['decision_tasks'], {})
        self.assertEqual(self.service.item_list()['derived_sources'], {})
