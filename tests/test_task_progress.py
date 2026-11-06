import copy
import tempfile
import unittest
from pathlib import Path
from threading import RLock
from unittest.mock import patch
from app import task_progress
from app.service import MeetingService
from app.github_source import GitHubError
from app.work_items import WorkItemConflict
from app.work_graph import WorkGraph
from app.commit_journal import CommitJournal
from tests.test_calendar import FakeGoogle

PROJECT=Path(__file__).resolve().parents[1]
REPO='example/repo'
class Connection:
 def __init__(self):
  self.account='1';self.lock=RLock();self.calls=[];self.hook=None;self.pages={1:dict(data=[dict(id=1,event='commented',created_at='2026-11-06T10:00:00Z',body='Restore verified',actor=dict(login='maria'))],has_next=False)}
  self.issue=dict(id=101,number=1,title='Recovery',state='closed',updated_at='2026-11-06T10:00:00Z')
 def status(self):return dict(account_id=self.account,login='fixture',connected=bool(self.account))
 def get(self,path,query=None,expected_account=None):
  self.calls.append((path,query,expected_account))
  if expected_account!=self.account:raise GitHubError('Account changed')
  if self.hook:self.hook(path)
  if path.endswith('/timeline'):return copy.deepcopy(self.pages[(query or {}).get('page',1)])
  if path.endswith('/pulls/1'):return dict(data=dict(id=909,number=1,merged_at='2026-11-06T10:00:00Z'))
  if path=='/repos/'+REPO:return dict(data=dict(id=10,full_name=REPO,has_issues=True,permissions=dict(push=True)))
  return dict(data=copy.deepcopy(self.issue))

class TaskProgressTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.s=MeetingService(Path(self.tmp.name)/'library',PROJECT,google=FakeGoogle(),backup_dir=Path(self.tmp.name)/'backups');self.addCleanup(self.s.close)
  self.project=self.s.create_project('Platform')['id'];self.s.set_project_repositories(self.project,[REPO])
  self.task=self.s.create_task(dict(request_id='a'*32,text='Review restore',project_id=self.project));self.conn=Connection();self.s.github.connection=self.conn
  self.link=self.s.github_links.link(dict(kind='item',id=self.task['id']),REPO,1,dict(kind='issue',title='Recovery',state='open',issue_id=101,verification='cached'))
 def check(self,**extra):return task_progress.check(self.s,self.task['id'],dict(link_id=self.link['id'],**extra))
 def test_local_timeline_is_read_only_and_has_real_update_time(self):
  self.task=self.s.update_item(self.task['id'],self.task['text'],dict(update_note='Waiting for access',follow_up_date='2026-11-10'),self.task['revision'])
  before=copy.deepcopy(self.s.items.data);result=task_progress.build(self.s,self.task['id'])
  update=next(e for e in result['events'] if e['kind']=='progress_update')
  self.assertEqual(update['text'],'Waiting for access');self.assertIsNotNone(update['at']);self.assertEqual(self.s.items.data,before);self.assertEqual(self.conn.calls,[])
 def test_explicit_check_records_activity_and_never_finishes_local_task(self):
  result=self.check();self.assertEqual(result['links'][0]['state'],'closed');self.assertEqual(result['local_state'],'todo')
  self.assertEqual([e['text'] for e in result['events'] if e['kind']=='github_commented'],['Restore verified'])
  self.check();again=task_progress.build(self.s,self.task['id']);self.assertEqual(len([e for e in again['events'] if e['kind']=='github_commented']),1)
  self.assertTrue(all(expected=='1' for _,_,expected in self.conn.calls))
 def test_distinct_pr_and_issue_database_ids_can_mark_pr_merged(self):
  self.conn.issue['pull_request']={};result=self.check();self.assertEqual(result['links'][0]['state'],'merged');self.assertEqual(result['local_state'],'todo')
 def test_partial_pagination_can_continue_without_duplicates(self):
  self.conn.pages={page:dict(data=[dict(id=(page-1)*100+i,event='commented',created_at='2026-11-06T10:00:00Z',body='Update') for i in range(100)],has_next=page<3) for page in range(1,4)}
  first=self.check();self.assertTrue(first['links'][0]['progress']['partial']);self.assertEqual(first['links'][0]['progress']['next_page'],3)
  second=self.check(more=True);progress=second['links'][0]['progress'];self.assertEqual(len(progress['events']),300);self.assertIsNone(progress['next_page']);self.assertFalse(progress['partial'])
 def test_offline_keeps_previous_snapshot_and_does_not_leak_error_text(self):
  self.check();saved=self.s.github_links.all()[0]['progress']['events']
  def fail(path):raise GitHubError('synthetic-secret-must-not-leak')
  self.conn.hook=fail;result=self.check();self.assertEqual(result['links'][0]['progress']['events'],saved);self.assertEqual(result['links'][0]['verification'],'offline');self.assertNotIn('synthetic-secret',str(result))
 def test_account_switch_and_late_unlink_do_not_save_a_stale_response(self):
  before=copy.deepcopy(self.s.github_links.all())
  self.conn.hook=lambda path:setattr(self.conn,'account','2')
  with self.assertRaises(WorkItemConflict):self.check()
  self.assertEqual(self.s.github_links.all(),before)
  self.conn.account='1';self.conn.hook=None
  def unlink(path):
   if path.endswith('/issues/1'):self.s.github_links.unlink(self.link['id'],self.link['revision'])
  self.conn.hook=unlink
  with self.assertRaises(WorkItemConflict):self.check()
  self.assertEqual(self.s.github_links.all(),[])
 def test_other_account_activity_is_not_projected_as_current(self):
  self.check();self.conn.account='2';result=task_progress.build(self.s,self.task['id'])
  self.assertFalse(any(e['kind']=='github_commented' for e in result['events']));self.assertIn('another GitHub account',result['links'][0]['progress']['error'])
 def test_readiness_does_not_claim_issue_write_permission_from_push(self):
  result=task_progress.readiness(self.s,self.task['id'],REPO);self.assertTrue(result['read_access']);self.assertEqual(result['write_permission'],'not_verified')
  count=len(self.conn.calls)
  with self.assertRaises(ValueError):task_progress.readiness(self.s,self.task['id'],'other/repo')
  self.assertEqual(len(self.conn.calls),count)
 def test_update_can_reference_only_evidence_linked_to_same_task(self):
  graph=WorkGraph(self.s.items);result=graph.ingest(dict(provider='gmail',account='fixture',external_id='thread',revision='1',text='Please verify restore.'),[dict(kind='task',text='Review restore',quote='Please verify restore.')]);p=self.s.items.data['proposals'][result['proposals'][0]]
  graph.review(p['id'],p['revision'],'link',target_id=self.task['id'],target_revision=self.task['revision']);current=self.s.items.items[self.task['id']]
  evidence=current['source_evidence'][0]
  self.s.update_item(current['id'],current['text'],dict(update_note='Restore in progress',update_evidence_id=evidence),current['revision'])
  event=next(e for e in task_progress.build(self.s,current['id'])['events'] if e['kind']=='progress_update');self.assertEqual(event['quote'],'Please verify restore.')
  current=self.s.items.items[current['id']]
  with self.assertRaises(ValueError):self.s.update_item(current['id'],current['text'],dict(update_note='No source',update_evidence_id='missing'),current['revision'])
 def test_cached_activity_and_publication_labels_survive_archive_restore(self):
  self.check();journal=CommitJournal(self.s.items.store.path)
  op=journal.approve(dict(resource=dict(kind='item',id=self.task['id']),resource_revision='r',source_revision='s',account_id='1',repository_id=10,action='issue',target=None,title='Draft',body='Draft text',labels=['created by ATLANTA'],assignees=['maria']))
  journal.transition(op['id'],'approved','sending');journal.recover()
  self.assertEqual(journal.get(op['id'])['history'][-1]['state'],'unknown')
  archive=self.s.create_backup()['created'];other=MeetingService(Path(self.tmp.name)/'restored',PROJECT,google=FakeGoogle(),backup_dir=self.s.backup_dir)
  try:
   other.restore_backup(archive['name']);self.assertIn(self.task['id'],other.items.items);self.assertEqual(other.github_links.all()[0]['progress']['events'][0]['text'],'Restore verified')
   self.assertEqual(CommitJournal(other.items.store.path).get(op['id'])['state'],'unknown')
  finally:other.close()
 def test_clear_cache_preserves_task_and_local_history(self):
  self.check();before=copy.deepcopy(self.s.items.data);result=self.check(clear=True)
  self.assertEqual(result['links'][0]['progress'],{});self.assertEqual(self.s.items.data,before)
 def test_unsafe_remote_urls_never_enter_the_task_timeline(self):
  self.conn.pages[1]['data'][0]['html_url']='javascript:alert(1)';result=self.check()
  self.assertTrue(all(not e.get('url') or e['url'].startswith('https://github.com/') for e in result['events']))

 def test_unknown_publication_is_discoverable_after_restart_without_payload_body(self):
  journal=CommitJournal(self.s.items.store.path)
  op=journal.approve(dict(resource=dict(kind='item',id=self.task['id']),resource_revision='r',source_revision='s',account_id='1',repository_id=10,action='issue',target=None,title='Draft',body='PRIVATE DRAFT TEXT'))
  journal.destination(op['id'],REPO,'fixture');journal.transition(op['id'],'approved','sending');journal.recover()
  result=task_progress.build(self.s,self.task['id']);operation=result['publications'][0]
  self.assertEqual(operation['state'],'unknown');self.assertEqual(operation['repository'],REPO);self.assertNotIn('PRIVATE DRAFT TEXT',str(result))
  self.assertTrue(any(e['kind']=='publication_unknown' for e in result['events']))

 def test_comment_edit_uses_its_update_time_and_lists_omit_heavy_activity(self):
  self.conn.pages[1]['data'][0]['created_at']='2026-11-01T10:00:00Z';self.conn.pages[1]['data'][0]['updated_at']='2026-11-06T10:00:00Z'
  result=self.check();event=next(e for e in result['events'] if e['kind']=='github_comment_edited');self.assertTrue(event['at'].startswith('2026-11-06'))
  self.assertNotIn('events',self.s.item_list()['github_links'][0]['progress'])

from tests import test_http
class TaskProgressHTTPTests(unittest.TestCase):
 setUp=test_http.HTTPTests.setUp
 tearDown=test_http.HTTPTests.tearDown
 request=test_http.HTTPTests.request
 def test_progress_endpoints_require_session_and_do_not_write_to_github(self):
  import json
  task=self.service.create_task(dict(request_id='a'*32,text='Synthetic task'))
  project=self.service.create_project('Platform')['id'];self.service.set_project_repositories(project,[REPO]);self.service.update_item(task['id'],task['text'],dict(project_ids=[project]),task['revision'])
  self.service.github.connection=Connection();link=self.service.github_links.link(dict(kind='item',id=task['id']),REPO,1,dict(kind='issue',state='open',issue_id=101))
  path='/api/items/'+task['id']
  self.assertEqual(self.request(path+'/progress',headers={})[0],403)
  self.assertEqual(self.request(path+'/progress')[0],200)
  status,raw,_=self.request(path+'/github-progress',dict(link_id=link['id']));self.assertEqual(status,200);self.assertEqual(json.loads(raw)['local_state'],'todo')
  self.assertEqual(self.request(path+'/readiness',dict(repository=REPO))[0],200)
  self.assertEqual(self.request('/task-progress.js')[0],200)
