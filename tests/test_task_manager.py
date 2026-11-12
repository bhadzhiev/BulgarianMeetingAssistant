from pathlib import Path
import copy,tempfile,unittest
from unittest.mock import patch
from app.service import MeetingService
from app.storage import atomic_json
from app.work_items import WorkItemConflict
from app.meeting_review import snapshot,act
from tests.test_calendar import FakeGoogle
from tests.ai_meeting_tasks import setUpModule, tearDownModule  # noqa: F401  AI meeting tasks are on in these tests

PROJECT=Path(__file__).resolve().parents[1]
class TaskManagerTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.s=MeetingService(Path(self.tmp.name)/'library',PROJECT,google=FakeGoogle(),backup_dir=Path(self.tmp.name)/'backups');self.addCleanup(self.s.close)
  self.project=self.s.create_project('Platform')['id'];self.other=self.s.create_project('Infra')['id']
  self.task=self.s.create_task(dict(request_id='a'*32,text='Check backup',project_id=self.project))
 def change(self,**changes):
  self.task=self.s.update_item(self.task['id'],self.task['text'],changes,self.task['revision']);return self.task
 def test_workflow_legacy_notes_projection_and_reopening(self):
  self.assertEqual(self.task['workflow_state'],'todo')
  for value in ['in_progress','waiting','cancelled','todo']:
   self.assertEqual(self.change(workflow_state=value)['status'],'open')
  self.assertEqual(self.change(workflow_state='done')['status'],'done')
  self.assertEqual(self.change(status='open')['workflow_state'],'todo')
 def test_atomic_project_and_content_failure_and_retry(self):
  old=copy.deepcopy(self.s.items.data)
  with patch.object(self.s.items,'save',side_effect=OSError('disk full')):
   with self.assertRaises(OSError):self.change(text='Edited',project_ids=[self.other])
  self.assertEqual(self.s.items.data,old)
  current=self.change(text='Edited',project_ids=[self.other],owner='Maria')
  self.assertEqual(current['project_ids'],[self.other]);self.assertEqual(current['text'],'Edited')
  with self.assertRaises(WorkItemConflict):self.s.update_item(current['id'],'Check backup',{'text':'Stale'},1)
 def test_invalid_project_does_not_save_other_fields(self):
  with self.assertRaises(ValueError):self.change(text='Must not save',project_ids=['missing'])
  self.assertEqual(self.s.items.items[self.task['id']]['text'],'Check backup')
 def test_task_update_is_one_revision_checked_history_event(self):
  original=copy.deepcopy(self.task)
  self.change(update_note='Maria is testing restore.',follow_up_date='2026-11-10',details='Kubernetes backup',completion_criteria='Restore test succeeds')
  events=[e for e in self.task['history'] if e['event']=='progress_update'];self.assertEqual(len(events),1);self.assertIn('Maria',events[0]['text'])
  with self.assertRaises(WorkItemConflict):self.s.update_item(original['id'],original['text'],{'update_note':'Maria is testing restore.'},original['revision'])
  self.assertEqual(len([e for e in self.s.items.items[original['id']]['history'] if e['event']=='progress_update']),1)
 def test_people_fields_need_existing_confirmed_profiles(self):
  person=self.s.save_person(dict(name='Maria'))['person']
  self.change(requester_person_id=person['id'],assigned_by_person_id=person['id'])
  with self.assertRaises(ValueError):self.change(requester_person_id='missing')
 def test_new_meeting_proposal_does_not_count_as_active_before_acceptance(self):
  mid=self.s.library.create('Daily','in_person',self.s.settings)['id']
  atomic_json(self.s.library.directory(mid)/'minutes.json',dict(summary=[],decisions=[],open_questions=[],tasks=[dict(task='Prepare runbook',owner=None,deadline=None,evidence_timestamp='00:00:00')]))
  self.s._sync_items(mid)
  proposal=next(t for t in self.s.tasks() if t['text']=='Prepare runbook')
  self.assertEqual(proposal['acceptance_state'],'proposed');self.assertEqual(self.s.task_summary()['open'],1)
  self.s.update_item(proposal['id'],proposal['text'],{'acceptance_state':'accepted'},proposal['revision'])
  self.assertEqual(self.s.task_summary()['open'],2)
 def test_meeting_and_global_review_invalidate_on_same_source_change(self):
  mid=self.s.library.create('Daily','in_person',self.s.settings)['id'];directory=self.s.library.directory(mid)
  rows=[dict(start=0,end=5,text='Check backup',speaker='Maria')];atomic_json(directory/'transcript.json',rows)
  task=self.s.create_task(dict(request_id='b'*32,text='Meeting task',meeting_id=mid))
  view=snapshot(self.s,mid);row=view['items'][0]
  act(self.s,dict(meeting_id=mid,item_id=task['id'],action='confirm',source=view['source'],content=row['content']))
  rows[0]['text']='Corrected backup';atomic_json(directory/'transcript.json',rows)
  self.assertEqual(snapshot(self.s,mid)['items'][0]['state'],'needs_review')
  self.assertEqual(next(i for i in self.s.item_list()['items'] if i['id']==task['id'])['review_state'],'needs_review')
 def test_details_reach_github_draft_and_invalidate_approval_fingerprint(self):
  from app.github_publish import Publisher
  self.s.set_project_repositories(self.project,['example/repo']);resource=dict(kind='item',id=self.task['id']);before=Publisher(self.s).resource_revision(resource)
  self.change(details='Restore a backup',completion_criteria='Test passes')
  draft=self.s.github_draft(dict(resource=resource,format='issue'))
  self.assertIn('Restore a backup',draft['body']);self.assertIn('Test passes',draft['body']);self.assertNotEqual(before,Publisher(self.s).resource_revision(resource))

 def test_archive_restore_retains_manager_fields_identity_and_history(self):
  person=self.s.save_person(dict(name='Manager'))['person']
  self.change(details='Restore test',completion_criteria='Report passes',follower_person_id=person['id'],assigned_by_person_id=person['id'],workflow_state='waiting',follow_up_date='2026-11-10',update_note='Waiting for a maintenance window')
  original=copy.deepcopy(self.s.items.items[self.task['id']])
  archive=self.s.create_backup()['created']
  other=MeetingService(Path(self.tmp.name)/'restored',PROJECT,google=FakeGoogle(),backup_dir=self.s.backup_dir)
  try:
   other.restore_backup(archive['name'])
   restored=other.items.items[self.task['id']]
   for field in ['id','task_model_version','text','details','completion_criteria','follower_person_id','assigned_by_person_id','workflow_state','follow_up_date','history','links']:
    self.assertEqual(restored[field],original[field],field)
   other.restore_backup(archive['name'])
   self.assertEqual(list(other.items.items),[self.task['id']])
  finally:other.close()
 def test_legacy_task_migration_has_explicit_version_and_preserves_done(self):
  from app.work_items import normalize
  old=copy.deepcopy(self.task);old.pop('task_model_version');old.pop('workflow_state');old.pop('acceptance_state');old['status']='done'
  result=normalize(old)
  self.assertEqual(result['id'],self.task['id']);self.assertEqual(result['status'],'done');self.assertEqual(result['workflow_state'],'done');self.assertEqual(result['task_model_version'],1)

 def batch(self,rows=None,changes=None,request='d'*32):
  return self.s.bulk_update_tasks(dict(items=rows or [dict(id=self.task['id'],revision=self.task['revision'])],changes=changes or dict(workflow_state='waiting'),request_id=request))
 def test_bulk_stale_selection_saves_nothing(self):
  other=self.s.create_task(dict(request_id='b'*32,text='Second task'))
  before=copy.deepcopy(self.s.items.data)
  with self.assertRaises(WorkItemConflict):self.batch([dict(id=self.task['id'],revision=self.task['revision']),dict(id=other['id'],revision=0)])
  self.assertEqual(self.s.items.data,before)
 def test_bulk_commit_failure_and_exact_retry_are_atomic(self):
  original=copy.deepcopy(self.s.items.data)
  with patch.object(self.s.items,'save',side_effect=OSError('disk full')):
   with self.assertRaises(OSError):self.batch()
  self.assertEqual(self.s.items.data,original)
  first=self.batch();self.assertEqual(first,self.batch())
  self.assertEqual(self.s.items.items[self.task['id']]['workflow_state'],'waiting')
  with self.assertRaises(WorkItemConflict):self.batch(changes=dict(workflow_state='done'))
 def test_bulk_confirmed_people_dates_and_non_task_rejection(self):
  person=self.s.save_person(dict(name='Maria'))['person']
  self.batch(changes=dict(owner_person_id=person['id'],follow_up_date='2026-11-12',workflow_state='in_progress'))
  current=self.s.items.items[self.task['id']]
  self.assertEqual(current['owner'],'Maria');self.assertIn('owner',current['manual']);self.assertEqual(current['follow_up_date'],'2026-11-12')
  with self.assertRaises(ValueError):self.batch(changes=dict(project_ids=[]),request='e'*32)
 def test_bulk_proposed_or_dismissed_items_cannot_be_changed(self):
  self.change(dismissed=True)
  with self.assertRaises(ValueError):self.batch()
  self.change(dismissed=False);self.s.items.items[self.task['id']]['acceptance_state']='proposed';self.s.items.save();self.task=self.s.items.items[self.task['id']]
  with self.assertRaises(ValueError):self.batch()

 def test_bulk_multiple_tasks_use_one_save_and_no_external_writes(self):
  other=self.s.create_task(dict(request_id='b'*32,text='Second task'))
  rows=[dict(id=t['id'],revision=t['revision']) for t in [self.task,other]]
  with patch.object(self.s.items,'save',wraps=self.s.items.save) as save:
   result=self.batch(rows,dict(workflow_state='in_progress',due_date='2026-11-15'))
  self.assertEqual(save.call_count,1);self.assertEqual(result['count'],2)
  for row in rows:self.assertEqual(self.s.items.items[row['id']]['workflow_state'],'in_progress')
  self.assertEqual(self.s.github_links.all(),[])


from tests import test_http
class TaskBulkHTTPTests(unittest.TestCase):
 setUp=test_http.HTTPTests.setUp
 tearDown=test_http.HTTPTests.tearDown
 request=test_http.HTTPTests.request
 def test_bulk_requires_session_and_preserves_revision_contract(self):
  import json
  task=self.service.create_task(dict(request_id='a'*32,text='Synthetic task'))
  body=dict(items=[dict(id=task['id'],revision=task['revision'])],changes=dict(workflow_state='waiting'),request_id='b'*32)
  self.assertEqual(self.request('/api/items/bulk',body,headers={})[0],403)
  status,raw,_=self.request('/api/items/bulk',body)
  self.assertEqual(status,200);self.assertEqual(json.loads(raw)['count'],1)
  self.assertEqual(self.request('/api/items/bulk',body)[0],200)
  body['request_id']='c'*32
  self.assertEqual(self.request('/api/items/bulk',body)[0],409)
