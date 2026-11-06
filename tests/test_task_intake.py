import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from app import task_draft
from app.service import MeetingService
from app.storage import atomic_json
from app.work_items import WorkItemConflict
from tests.test_calendar import FakeGoogle

PROJECT=Path(__file__).resolve().parents[1]
class IntakeTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.s=MeetingService(Path(self.tmp.name)/'library',PROJECT,google=FakeGoogle(),backup_dir=Path(self.tmp.name)/'backups');self.addCleanup(self.s.close)
  self.s.settings.update(summarizer='local',local_ai_model='synthetic')
  self.mid=self.s.library.create('Daily','in_person',self.s.settings)['id']
  self.rows=[dict(start=0,end=8,speaker='Maria',text='Please test backup recovery.'),dict(start=8,end=15,speaker='Ivan',text='Document the result.')]
  atomic_json(self.s.library.directory(self.mid)/'transcript.json',self.rows)
 def body(self,provider='meeting',**extra):
  body=dict(provider=provider,id=self.mid,revision=self.s.detail(self.mid)['transcript_revision'],first=0,last=1)
  if provider=='manual':body=dict(provider='manual',id='a'*32,source_text='Check the deployment logs.')
  body.update(extra);body['preview_token']=task_draft.preview(self.s,body)['preview_token']
  return body
 def create(self,body,**extra):return task_draft.create(self.s,dict(body,title='Verify recovery',operation_id='b'*32,**extra))
 def test_meeting_capture_keeps_exact_evidence_and_survives_notes_regeneration(self):
  body=self.body();result=self.create(body,details='Use staging',completion_criteria='Restore succeeds')
  task=self.s.items.items[result['item_id']]
  self.assertEqual(task['details'],'Use staging');self.assertEqual(task['completion_criteria'],'Restore succeeds')
  self.assertEqual(task['owner'],None);self.assertEqual(task['links'][0]['meeting_id'],self.mid)
  ev=self.s.items.data['source_evidence'][task['source_evidence'][0]];self.assertEqual(ev['quote'],'Please test backup recovery.\nDocument the result.')
  self.assertEqual(self.create(body,details='Use staging',completion_criteria='Restore succeeds'),result)
  atomic_json(self.s.library.directory(self.mid)/'minutes.json',dict(summary=[],tasks=[],decisions=[],open_questions=[]));self.s._sync_items(self.mid)
  self.assertIn(task['id'],self.s.detail(self.mid)['items']);self.assertEqual(len(self.s.tasks()),1)
 def test_manual_capture_without_ai_and_generation_stays_blocked(self):
  self.s.settings['summarizer']='none'
  body=self.body('manual');preview=task_draft.preview(self.s,body)
  self.assertFalse(preview['ai_available'])
  result=self.create(body);self.assertEqual(self.s.items.items[result['item_id']]['text'],'Verify recovery')
  runner=SimpleNamespace(run=lambda *a,**k:self.fail('AI must not run'))
  approved=dict(body,approved=True)
  with self.assertRaises(ValueError):task_draft.draft(self.s,approved,runner)
  jobs=task_draft.DraftJobs(self.s,runner)
  with self.assertRaises(ValueError):jobs.start(approved)
  self.assertIsNone(jobs.thread)
 def test_link_evidence_without_ai_preserves_existing_task(self):
  self.s.settings['summarizer']='none'
  task=self.s.create_task(dict(request_id='c'*32,text='Existing task',owner='Ivan'))
  self.create(self.body(),target_id=task['id'],target_revision=task['revision'])
  current=self.s.items.items[task['id']]
  self.assertEqual(current['text'],'Existing task');self.assertEqual(current['owner'],'Ivan')
  self.assertEqual(len(current['source_evidence']),1);self.assertEqual(len(self.s.tasks()),1)
 def test_failure_rolls_back_source_task_projects_and_retry_receipt(self):
  body=self.body();before=copy.deepcopy(self.s.items.data)
  with patch.object(self.s.items.store,'save',side_effect=OSError('disk full')):
   with self.assertRaises(OSError):self.create(body)
  self.assertEqual(self.s.items.data,before)
  first=self.create(body);self.assertEqual(self.create(body),first);self.assertEqual(len(self.s.tasks()),1)
  with self.assertRaises(WorkItemConflict):self.create(body,details='Different after uncertain result')
 def test_transcript_change_invalidates_preview_before_creation(self):
  body=self.body();self.rows[0]['text']='Changed text';atomic_json(self.s.library.directory(self.mid)/'transcript.json',self.rows)
  with self.assertRaises(WorkItemConflict):self.create(body)
  self.assertEqual(self.s.tasks(),[])
 def test_link_adds_evidence_and_preserves_existing_human_fields(self):
  task=self.s.create_task(dict(request_id='c'*32,text='Existing task',owner='Ivan'))
  task=self.s.update_item(task['id'],task['text'],dict(workflow_state='waiting',details='Human context'),task['revision'])
  result=self.create(self.body(),target_id=task['id'],target_revision=task['revision'],details='Must not overwrite')
  current=self.s.items.items[result['item_id']]
  self.assertEqual((current['text'],current['owner'],current['details'],current['workflow_state']),('Existing task','Ivan','Human context','waiting'))
  self.assertEqual(len(self.s.tasks()),1);self.assertEqual(len(current['source_evidence']),1);self.assertEqual(current['links'][0]['meeting_id'],self.mid)
 def test_stale_target_cannot_create_an_extra_task_or_evidence(self):
  task=self.s.create_task(dict(request_id='c'*32,text='Existing task'));before=copy.deepcopy(self.s.items.data)
  with self.assertRaises(WorkItemConflict):self.create(self.body(),target_id=task['id'],target_revision=0)
  self.assertEqual(self.s.items.data,before)
 def test_manual_capture_and_structured_ai_remain_optional(self):
  body=self.body('manual');result=self.create(body)
  self.assertEqual(self.s.items.items[result['item_id']]['created_by'],'user')
  with patch('app.task_draft.complete_json',return_value=dict(text='Review logs',details='Check failed deployments',completion_criteria='Write findings')):
   result=task_draft.generate(dict(body='Check logs'),{})
  self.assertEqual(result['completion_criteria'],'Write findings')
  for bad in [dict(text='Task',details=3),dict(text='Task',completion_criteria='x'*5001)]:
   with self.assertRaises(ValueError):task_draft.draft_fields(bad)
 def test_invalid_selection_does_not_create_task(self):
  for first,last in [(-1,0),(1,0),(0,9),(False,1)]:
   with self.subTest(first=first,last=last),self.assertRaises(ValueError):self.body(first=first,last=last)
  self.assertEqual(self.s.tasks(),[])

 def test_confirmed_owner_and_requester_are_human_fields_not_ai_guesses(self):
  person=self.s.save_person(dict(name='Ivan'))['person']
  result=self.create(self.body('manual'),owner='Ivan',due_date='2026-11-10',requester_person_id=person['id'])
  item=self.s.items.items[result['item_id']]
  self.assertEqual((item['owner'],item['due_date'],item['requester_person_id']),('Ivan','2026-11-10',person['id']))
  self.assertIn('owner',item['manual'])
 def test_linking_meeting_proposal_keeps_one_active_task_with_same_target_id(self):
  atomic_json(self.s.library.directory(self.mid)/'minutes.json',dict(summary=[],tasks=[dict(task='Verify backup',owner=None,deadline=None,evidence_timestamp='00:00:00')],decisions=[],open_questions=[]));self.s._sync_items(self.mid)
  proposal=next(i for i in self.s.tasks() if i['acceptance_state']=='proposed')
  target=self.s.create_task(dict(request_id='c'*32,text='Existing task'))
  result=self.create(self.body(),target_id=target['id'],target_revision=target['revision'],proposal_item_id=proposal['id'],proposal_item_revision=proposal['revision'])
  self.assertEqual(result['item_id'],target['id']);self.assertTrue(self.s.items.items[proposal['id']]['dismissed'])
  active=[i for i in self.s.tasks() if i['acceptance_state']=='accepted' and not i['dismissed']]
  self.assertEqual([i['id'] for i in active],[target['id']])
  self.assertIn(target['id'],self.s.detail(self.mid)['items'])

 def test_manual_ai_capture_preserves_explicit_meeting_link_without_fake_timestamp(self):
  body=self.body('manual',capture_meeting_id=self.mid)
  result=self.create(body,owner='Maria')
  item=self.s.items.items[result['item_id']]
  self.assertEqual(item['links'][0]['meeting_id'],self.mid);self.assertIsNone(item['links'][0]['evidence_timestamp'])
  self.assertIn(item['id'],self.s.detail(self.mid)['items'])

 def test_prompt_lab_and_production_share_the_structured_card_contract(self):
  from app import prompt_lab
  output=dict(text='Провери Kubernetes backup',details='Използвай staging.',completion_criteria='Запиши резултата от restore.')
  messages,schema=prompt_lab.messages_for('task_draft','Провери backup в staging.','general')
  self.assertEqual(set(schema['required']),{'text','details','completion_criteria'})
  settings=dict(prompt_test=dict(stage='task_draft',snippet='Провери backup в staging.',messages=messages,schema=schema))
  with patch('app.prompt_lab.complete_json',return_value=output):self.assertEqual(prompt_lab.generate(settings)['result'],output)
  with patch('app.task_draft.complete_json',return_value=output):self.assertEqual(task_draft.generate({'body':'Провери backup в staging.'},{}),output)
  for invalid in [dict(output,owner='Maria'),dict(output,completion_criteria=['Unsupported shape'])]:
   with patch('app.prompt_lab.complete_json',return_value=invalid),self.assertRaises(ValueError):prompt_lab.generate(settings)
   with patch('app.task_draft.complete_json',return_value=invalid),self.assertRaises(ValueError):task_draft.generate({}, {})
