import copy
import tempfile
import unittest
from pathlib import Path
from app.service import MeetingService
from app.items import Registry
from app.storage import atomic_json
from app.work_items import WorkItemConflict
from tests.test_calendar import FakeGoogle

PROJECT=Path(__file__).resolve().parents[1]

class ManualTaskTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.service=MeetingService(Path(self.tmp.name)/'library',PROJECT,google=FakeGoogle(),backup_dir=Path(self.tmp.name)/'backups')
        self.addCleanup(self.service.close)
        self.project=self.service.create_project('Platform')['id']
        self.meeting=self.service.library.create('Daily','in_person',self.service.settings)['id']
        self.service.library.update(self.meeting,status='ready',project_id=self.project)
    def create(self,**changes):
        body=dict(text='Провери Kubernetes backup',owner='Иван',due_date='2026-11-10',request_id='a'*32)
        body.update(changes);return self.service.create_task(body)
    def test_standalone_survives_refresh_prune_and_reload_and_uses_normal_updates(self):
        task=self.create(project_id=self.project)
        listed=next(t for t in self.service.item_list()['items'] if t['id']==task['id'])
        self.assertEqual(listed['effective_project_ids'],[self.project]);self.assertEqual(listed['links'],[])
        self.service.items.prune(set());self.service.items.save()
        self.assertIn(task['id'],Registry(self.service.items.path).items)
        updated=self.service.update_item(task['id'],task['text'],dict(status='done',text='Провери restore'),task['revision'])
        self.assertEqual(updated['status'],'done');self.assertIn('text',updated['manual'])
        with self.assertRaises(WorkItemConflict):self.service.update_item(task['id'],task['text'],dict(status='open'),task['revision'])
    def test_meeting_task_without_notes_is_visible_editable_and_reviewable(self):
        task=self.create(meeting_id=self.meeting)
        self.assertIn(task['id'],self.service.detail(self.meeting)['items'])
        self.assertEqual(self.service.effective_project_ids(task),[self.project])
        updated=self.service.update_item(task['id'],task['text'],dict(text='Провери Kubernetes restore'),task['revision'])
        from app.meeting_review import snapshot
        review=snapshot(self.service,self.meeting)
        self.assertEqual(review['items'][0]['text'],updated['text']);self.assertEqual(review['items'][0]['evidence'],[])
        self.assertFalse(task['links'][0].get('detached'))
    def test_regenerated_minutes_keep_manual_task_identity_and_fields(self):
        task=self.create(meeting_id=self.meeting)
        directory=self.service.library.directory(self.meeting)
        minutes=dict(summary=[],tasks=[],decisions=[],open_questions=[])
        atomic_json(directory/'minutes.json',minutes);self.service._sync_items(self.meeting)
        first=self.service.detail(self.meeting)['minutes']['tasks'][0]
        self.assertEqual(first['item_id'],task['id']);self.assertIsNone(first['evidence_timestamp'])
        self.service.items.detach(self.meeting)
        self.assertFalse(self.service.items.items[task['id']]['links'][0].get('detached'))
        atomic_json(directory/'minutes.json',minutes);self.service._sync_items(self.meeting)
        second=self.service.detail(self.meeting)['minutes']['tasks'][0]
        self.assertEqual(first,second)
        self.assertEqual(len(self.service.item_list()['items']),1)
    def test_idempotent_retry_and_payload_conflict(self):
        first=self.create();self.assertEqual(first['id'],self.create()['id'])
        with self.assertRaises(WorkItemConflict):self.create(text='A different task')
        self.assertEqual(len(self.service.item_list()['items']),1)
    def test_expected_result_from_the_new_task_dialog_is_saved_as_a_person_edit(self):
        task=self.create(completion_criteria='  Restore работи на staging  ')
        self.assertEqual(task['completion_criteria'],'Restore работи на staging');self.assertIn('completion_criteria',task['manual'])
        self.assertNotIn('completion_criteria',self.create(request_id='b'*32,completion_criteria='  ')['manual'])
    def test_invalid_inputs_and_busy_meeting_never_create(self):
        for change in [dict(text=' '),dict(text='x'*1001),dict(owner=42),dict(completion_criteria=7),dict(completion_criteria='x'*5001),dict(due_date='2026-02-30'),dict(due_date='20261110'),dict(project_id='missing'),dict(meeting_id='missing'),dict(request_id='bad')]:
            with self.subTest(change=change),self.assertRaises((ValueError,FileNotFoundError)):self.create(**change)
        self.service.busy.add(self.meeting)
        with self.assertRaisesRegex(ValueError,'processing'):self.create(meeting_id=self.meeting)
        self.service.busy.clear();self.assertEqual(self.service.item_list()['items'],[])
    def test_delete_meeting_keeps_user_task_without_dangling_source(self):
        task=self.create(meeting_id=self.meeting)
        self.service.delete(self.meeting)
        current=next(t for t in self.service.item_list()['items'] if t['id']==task['id'])
        self.assertEqual(current['links'],[])
    def test_task_uses_github_preview_without_invented_evidence(self):
        self.service.set_project_repositories(self.project,['example/project'])
        task=self.create(project_id=self.project)
        resource=self.service._resource(dict(kind='item',id=task['id']))
        self.assertIsNone(resource['moment']);self.assertIsNone(resource['quote'])
        self.assertEqual(resource['source_label'],'Manually added task')
        draft=self.service.github_draft(dict(resource=dict(kind='item',id=task['id']),format='issue'))
        self.assertTrue(draft)
    def test_delete_task_without_minutes_uses_existing_endpoint(self):
        task=self.create(meeting_id=self.meeting)
        self.service.delete_item(task['id'],task['text'],task['revision'])
        self.assertEqual(self.service.item_list()['items'],[])
    def test_task_from_a_question_keeps_the_link_and_retries_safely(self):
        from app.work_graph import WorkGraph
        question=WorkGraph(self.service.items).question('Ще мигрираме ли базата към v2?')
        task=self.create(question_id=question['id'])
        edges=[e for e in self.service.items.data['relationships'].values() if e['kind']=='derives_from']
        self.assertEqual(len(edges),1);self.assertEqual((edges[0]['from_id'],edges[0]['to_id']),(task['id'],question['id']))
        # The question stays open; its history names the task that came from it.
        self.assertEqual(self.service.items.items[question['id']]['status'],'open')
        events=[e['event'] for e in self.service.items.items[question['id']]['history']]
        self.assertIn('task_created',events)
        # An idempotent retry returns the same task and never adds a second relationship.
        self.assertEqual(self.create(question_id=question['id'])['id'],task['id'])
        self.assertEqual(len(self.service.items.data['relationships']),1)
        with self.assertRaises(ValueError):self.create(request_id='b'*32,question_id='missing')
        with self.assertRaises(ValueError):self.create(request_id='b'*32,question_id=task['id'])
    def test_task_from_a_notes_question_keeps_the_source_moment(self):
        task=self.create(meeting_id=self.meeting,evidence_timestamp='00:12:30',request_id='c'*32)
        self.assertEqual(task['links'][0]['evidence_timestamp'],'00:12:30')
        with self.assertRaises(ValueError):self.create(request_id='d'*32,evidence_timestamp='12:30')
        with self.assertRaises(ValueError):self.create(request_id='d'*32,evidence_timestamp='00:12:30')
