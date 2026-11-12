import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app.service import MeetingService
from app.meeting_review import snapshot, act
from app.review_queue import build as queue
from app.storage import atomic_json
from app.work_items import WorkItemConflict
from tests.test_calendar import FakeGoogle
from tests.ai_meeting_tasks import setUpModule, tearDownModule  # noqa: F401  AI meeting tasks are on in these tests

PROJECT=Path(__file__).resolve().parents[1]

class ReviewConsistencyTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.s=MeetingService(Path(self.tmp.name)/'library',PROJECT,google=FakeGoogle(),backup_dir=Path(self.tmp.name)/'backups');self.addCleanup(self.s.close)
  self.project=self.s.create_project('Platform')['id']
  self.mid=self.s.library.create('Deployment planning','in_person',self.s.settings)['id'];self.s.library.update(self.mid,status='ready',duration=20,project_id=self.project)
  atomic_json(self.s.library.directory(self.mid)/'transcript.json',[dict(start=0,end=8,speaker='Maria',text='Verify backup recovery.'),dict(start=8,end=16,speaker='Maria',text='Check it again before deployment.')])
  self.s.edit(self.mid,dict(minutes=dict(summary=[dict(text='Deployment planning',evidence_timestamp='00:00:00')],tasks=[dict(task='Verify backup recovery',owner='Maria',deadline=None,evidence_timestamp='00:00:00')],decisions=[dict(text='Use staged rollout',review='ai',evidence_timestamp='00:00:08')],open_questions=[])))
  rows=self.s.detail(self.mid)['items'].values();self.task=next(i for i in rows if i['kind']=='task');self.decision=next(i for i in rows if i['kind']=='decision')
 def row(self,key):return next(i for i in snapshot(self.s,self.mid)['items'] if i['id']==key)
 def confirm(self,key):
  view=snapshot(self.s,self.mid);row=next(i for i in view['items'] if i['id']==key)
  return act(self.s,dict(meeting_id=self.mid,item_id=key,action='confirm',source=view['source'],content=row['content']))
 def change_notes(self,field,change):
  d=self.s.detail(self.mid);before=copy.deepcopy(d['minutes'][field]);after=copy.deepcopy(before);change(after)
  self.s.edit(self.mid,dict(minutes_fields={field:after},minutes_base={field:before},minutes_revision=d['minutes_revision']))
 def test_accept_in_my_work_confirms_task_and_named_owner_once(self):
  self.s.update_item(self.task['id'],self.task['text'],dict(acceptance_state='accepted'),self.task['revision'])
  task=self.s.items.items[self.task['id']]
  self.assertEqual(self.row(task['id'])['state'],'confirmed');self.assertIn('owner',task['manual'])
  self.assertEqual(self.s.detail(self.mid)['items'][task['id']]['review_state'],'confirmed')
  self.assertEqual(next(i for i in self.s.item_list()['items'] if i['id']==task['id'])['review_state'],'confirmed')
  history=copy.deepcopy(task['history']);self.confirm(task['id']);self.assertEqual(self.s.items.items[task['id']]['history'],history)
 def test_review_confirmation_accepts_decision_in_prepare_and_notes(self):
  self.confirm(self.decision['id']);self.assertEqual(self.s.items.items[self.decision['id']]['status'],'accepted')
  self.assertEqual(self.s.detail(self.mid)['minutes']['decisions'][0]['review'],'verified')
  prepared=self.s.prepare(project_id=self.project)
  self.assertIn(self.decision['id'],[i['item_id'] for i in prepared['decisions']])
  history=copy.deepcopy(self.s.items.items[self.decision['id']]['history']);self.confirm(self.decision['id']);self.assertEqual(self.s.items.items[self.decision['id']]['history'],history)
 def test_checked_marker_does_not_invalidate_confirmations_or_reopen_queue(self):
  self.confirm(self.task['id']);self.confirm(self.decision['id'])
  self.change_notes('summary',lambda rows:rows[0].update(review='verified'))
  self.assertEqual(self.row(self.task['id'])['state'],'confirmed');self.assertEqual(self.row(self.decision['id'])['state'],'confirmed')
  self.assertEqual(queue(self.s)['totals']['items'],0)
 def test_meaningful_notes_and_transcript_changes_still_require_review(self):
  self.confirm(self.task['id']);self.change_notes('summary',lambda rows:rows[0].update(text='Different meeting context'))
  self.assertEqual(self.row(self.task['id'])['state'],'needs_review')
  self.confirm(self.task['id'])
  atomic_json(self.s.library.directory(self.mid)/'transcript.json',[dict(start=0,end=8,speaker='Maria',text='Corrected source')])
  self.assertEqual(self.row(self.task['id'])['state'],'needs_review')
 def test_owner_or_date_of_one_task_keeps_every_review_in_the_meeting(self):
  # The registry writes a person's owner, date and status back into the notes; that is not new evidence.
  self.confirm(self.task['id']);self.confirm(self.decision['id'])
  item=self.s.items.items[self.task['id']]
  self.s.update_item(item['id'],item['text'],dict(due_date='2026-11-20'),item['revision'])
  self.assertEqual(self.s.detail(self.mid)['minutes']['tasks'][0]['due_date'],'2026-11-20')
  self.assertEqual(self.row(self.decision['id'])['state'],'confirmed')
  self.assertEqual(self.row(self.task['id'])['state'],'confirmed')
  item=self.s.items.items[self.task['id']]
  self.s.update_item(item['id'],item['text'],dict(owner='Ivan'),item['revision'])
  item=self.s.items.items[self.task['id']]
  self.s.update_item(item['id'],item['text'],dict(status='done'),item['revision'])
  self.assertEqual(self.row(self.task['id'])['state'],'confirmed');self.assertEqual(self.row(self.decision['id'])['state'],'confirmed')
  self.assertEqual(queue(self.s)['totals']['items'],0)
 def test_a_new_task_in_the_meeting_keeps_the_other_reviews(self):
  self.confirm(self.task['id']);self.confirm(self.decision['id'])
  self.s.create_task(dict(request_id='c'*32,text='Write the runbook',meeting_id=self.mid))
  self.assertEqual(self.row(self.task['id'])['state'],'confirmed');self.assertEqual(self.row(self.decision['id'])['state'],'confirmed')
 def test_bulk_owner_keeps_the_confirmation(self):
  self.confirm(self.task['id']);item=self.s.items.items[self.task['id']]
  self.s.bulk_update_tasks(dict(items=[dict(id=item['id'],revision=item['revision'])],changes=dict(due_date='2026-11-21'),request_id='d'*32))
  self.assertEqual(self.row(self.task['id'])['state'],'confirmed')
 def test_unconfirmed_task_still_needs_review_after_an_owner(self):
  item=self.s.items.items[self.task['id']]
  self.s.update_item(item['id'],item['text'],dict(owner='Ivan'),item['revision'])
  self.assertEqual(self.row(self.task['id'])['state'],'needs_review')
 def test_receipts_made_before_the_new_evidence_stay_valid(self):
  from app.meeting_review import legacy_minutes_evidence, source_digest
  self.confirm(self.task['id']);item=self.s.items.items[self.task['id']];receipt=item['meeting_reviews'][self.mid]
  d=self.s.detail(self.mid);receipt['evidence']=source_digest(d['transcript_revision'],legacy_minutes_evidence(d['minutes']));self.s.items.save()
  self.assertEqual(self.row(self.task['id'])['state'],'confirmed')
 def test_repeated_mentions_keep_one_review_row_and_both_citations(self):
  self.change_notes('tasks',lambda rows:rows.append(dict(rows[0],task='Check recovery before deployment',evidence_timestamp='00:00:08')))
  rows=snapshot(self.s,self.mid)['items'];task=next(i for i in rows if i['id']==self.task['id'])
  self.assertEqual(len([i for i in rows if i['kind']=='task']),1)
  self.assertEqual([e['timestamp'] for e in task['evidence']],['00:00:00','00:00:08'])
  self.assertEqual(len(self.s.detail(self.mid)['minutes']['tasks']),2)
 def test_changed_card_details_require_review_and_explicit_save_can_confirm(self):
  self.confirm(self.task['id']);item=self.s.items.items[self.task['id']]
  item=self.s.update_item(item['id'],item['text'],dict(details='Use staging'),item['revision'])
  self.assertEqual(self.row(item['id'])['state'],'needs_review')
  self.s.update_item(item['id'],item['text'],dict(acceptance_state='accepted'),item['revision'])
  self.assertEqual(self.row(item['id'])['state'],'confirmed')
 def test_stale_notes_are_not_confirmed_by_global_accept(self):
  self.s.library.update(self.mid,notes_need_refresh=True)
  self.s.update_item(self.task['id'],self.task['text'],dict(acceptance_state='accepted'),self.task['revision'])
  self.assertEqual(self.row(self.task['id'])['state'],'needs_review')
 def test_failed_accept_or_confirm_restores_registry_without_partial_receipt(self):
  before=copy.deepcopy(self.s.items.data)
  with patch.object(self.s.items,'save',side_effect=OSError('disk full')):
   with self.assertRaises(OSError):self.confirm(self.task['id'])
  self.assertEqual(self.s.items.data,before)
  with patch.object(self.s.items,'save',side_effect=OSError('disk full')):
   with self.assertRaises(OSError):self.s.update_item(self.task['id'],self.task['text'],dict(acceptance_state='accepted'),self.task['revision'])
  self.assertEqual(self.s.items.data,before)
 def test_placeholder_owner_is_not_confirmed_as_a_person(self):
  item=self.s.items.items[self.task['id']];item['owner']='SPEAKER_00';self.s.items.save()
  self.confirm(item['id']);self.assertNotIn('owner',self.s.items.items[item['id']]['manual'])

 def test_legacy_exact_source_confirmation_survives_marker_only_edit(self):
  self.confirm(self.task['id']);item=self.s.items.items[self.task['id']]
  item['meeting_reviews'][self.mid].pop('evidence');self.s.items.save()
  self.change_notes('summary',lambda rows:rows[0].update(review='verified'))
  self.assertEqual(self.row(item['id'])['state'],'confirmed')
  self.assertIn('evidence',self.s.items.items[item['id']]['meeting_reviews'][self.mid])
 def test_edited_decision_stays_in_review_queue_until_confirmed(self):
  view=snapshot(self.s,self.mid);row=next(i for i in view['items'] if i['id']==self.decision['id'])
  act(self.s,dict(meeting_id=self.mid,item_id=row['id'],source=view['source'],content=row['content'],action='edit',changes={'text':'Use a staged rollout with a rollback window'}))
  self.assertEqual(self.row(row['id'])['state'],'edited')
  self.assertEqual(queue(self.s)['totals']['items'],2)

 def test_exact_decision_confirmation_retry_survives_its_own_note_sync(self):
  view=snapshot(self.s,self.mid);row=next(i for i in view['items'] if i['id']==self.decision['id'])
  body=dict(meeting_id=self.mid,item_id=row['id'],source=view['source'],content=row['content'],action='confirm')
  act(self.s,body);history=copy.deepcopy(self.s.items.items[row['id']]['history'])
  result=act(self.s,body);self.assertEqual(next(i for i in result['items'] if i['id']==row['id'])['state'],'confirmed')
  self.assertEqual(self.s.items.items[row['id']]['history'],history)
  self.change_notes('summary',lambda rows:rows[0].update(text='Changed evidence'))
  with self.assertRaises(WorkItemConflict):act(self.s,body)

 def test_progress_note_alone_does_not_confirm_owner_or_review(self):
  item=self.s.items.items[self.task['id']];item['acceptance_state']='accepted';self.s.items.save()
  self.s.update_item(item['id'],item['text'],dict(update_note='Started the restore test'),item['revision'])
  item=self.s.items.items[item['id']]
  self.assertNotIn('owner',item['manual']);self.assertEqual(self.row(item['id'])['state'],'needs_review')
