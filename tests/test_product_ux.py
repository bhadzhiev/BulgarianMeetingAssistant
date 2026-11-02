from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import subprocess,json
from app.service import MeetingService
from app import identity_channels,meeting_types
from app.storage import atomic_json
from app.work_items import WorkItemConflict
from tests.test_calendar import FakeGoogle
PROJECT=Path(__file__).resolve().parents[1]

class ProductUXTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.s=MeetingService(Path(self.tmp.name)/'library',PROJECT,google=FakeGoogle(),backup_dir=Path(self.tmp.name)/'archives');self.addCleanup(self.s.close)
  self.p=self.s.create_project('Atlas')['id']
 def person(self,**fields):return self.s.people.save(dict(name='Ivan',**fields))
 def test_rename_keeps_historical_name_and_confirmed_channel_ids(self):
  person=self.person(emails=['ivan@example.invalid']);person=self.s.people.confirm_channel(person['id'],person['revision'],'google_chat','workspace-one','users/123')
  updated=self.s.people.save(dict(person,name='Ivan Petrov',aliases=[]))
  self.assertIn('Ivan',updated['aliases']);self.assertEqual(self.s.people.match('Ivan')['id'],person['id'])
  self.assertEqual(self.s.people.match_channel('gmail','any','Ivan <ivan@example.invalid>')['id'],person['id'])
  self.assertEqual(self.s.people.match_channel('google_chat','workspace-one','users/123')['id'],person['id'])
  self.assertIsNone(self.s.people.match_channel('google_chat','workspace-two','users/123'))
 def test_confirmed_email_and_identity_cannot_be_claimed_by_another_person(self):
  a=self.person(emails=['ivan@example.invalid']);b=self.s.people.save(dict(name='Other'))
  with self.assertRaises(ValueError):self.s.people.confirm_channel(b['id'],b['revision'],'gmail','account','Ivan <ivan@example.invalid>')
  self.assertIsNone(self.s.people.match_channel('google_chat','account','Ivan'))
 def test_sender_identity_comes_from_cache_not_request_payload(self):
  person=self.person();thread=dict(revision='v1',messages=[dict(id='message',sender='Ivan <ivan@example.invalid>')])
  with patch.object(self.s.gmail,'detail',return_value=thread):
   result=identity_channels.confirm(self.s,dict(provider='gmail',account='me',thread_id='thread',message_id='message',source_revision='v1',person_id=person['id'],revision=person['revision'],sender='attacker@example.invalid'))
  self.assertIn('ivan@example.invalid',result['person']['emails']);self.assertNotIn('attacker@example.invalid',result['person']['emails'])
 def test_mixed_project_requires_purpose_and_uses_last_matching_type(self):
  for title,kind,blocker in [('Daily','daily','Waiting for VPN access'),('Client','client','')]:
   m=self.s.library.create(title,'in_person',self.s.settings);self.s.library.update(m['id'],status='ready',project_id=self.p,meeting_type=kind)
   atomic_json(self.s.library.directory(m['id'])/'minutes.json',dict(summary=[],decisions=[],tasks=[],open_questions=[],**({'blockers':[dict(text=blocker,evidence_timestamp=None)]} if blocker else {})))
  self.assertTrue(self.s.prepare(self.p)['requires_type'])
  result=self.s.prepare(self.p,meeting_type='daily');self.assertFalse(result['requires_type']);self.assertEqual(result['meeting_type'],'daily')
  self.assertTrue(any('Waiting for VPN access' in entry['title'] for entry in result['agenda']))
  self.assertEqual(self.s.prepare(self.p,meeting_type='refinement')['meeting_type'],'refinement')
 def test_cached_github_link_is_distinct_from_live_check_and_offline_refresh(self):
  q=self.s.work_graph_action('question',dict(text='Review issue'));resource=dict(kind='item',id=q['id']);body=dict(resource=resource,reference='org/repo#7')
  with patch.object(self.s.github,'find',return_value=dict(kind='issue',title='Rollout',state='open',issue_id=7,fetched_at=100)):
   cached=self.s.github_link(body)['link'];self.assertEqual(cached['verification'],'cached');self.assertEqual(cached['cached_at'],100);self.assertIsNone(cached['checked_at'])
   with patch.object(self.s.github.connection,'get',return_value=dict(data=dict(id=7,title='Rollout',state='closed'))):
    live=self.s.github_link(dict(body,verify_live=True))['link'];self.assertEqual(live['verification'],'github');self.assertTrue(live['checked_at'])
   with patch.object(self.s.github.connection,'get',side_effect=ValueError('offline')):
    offline=self.s.github_link(dict(body,verify_live=True))['link'];self.assertEqual(offline['verification'],'offline');self.assertEqual(offline['state'],'closed');self.assertEqual(offline['checked_at'],live['checked_at'])
 def test_draft_buffer_preserves_edits_but_updates_untouched_fields(self):
  script="""const assert=require('assert'),Draft=require('./web/draft-buffer.js');const d=new Draft();assert.deepStrictEqual(d.accept({title:'A',body:'first'}),{title:'A',body:'first'});d.capture('Manual title','first');assert.deepStrictEqual(d.accept({title:'Generated B',body:'second'}),{title:'Manual title',body:'second'});d.capture('Manual title','');assert.strictEqual(d.accept({title:'C',body:'third'}).body,'');assert(d.edited);assert.deepStrictEqual(d.reset(),{title:'C',body:'third'});assert(!d.edited);const pending=new Draft();pending.capture('Typed while loading','');assert.deepStrictEqual(pending.accept({title:'A',body:'Generated'}),{title:'Typed while loading',body:'Generated'});"""
  subprocess.run(['node','-e',script],cwd=PROJECT,check=True,capture_output=True)

 def test_profile_joins_confirmed_channels_without_display_name_matching(self):
  person=self.person(emails=['ivan@example.invalid']);person=self.s.people.confirm_channel(person['id'],person['revision'],'google_chat','chat-account','users/123')
  mail=dict(id='thread',subject='Rollout',messages=[dict(id='m',sender='Different display <ivan@example.invalid>',date=1793100000000,body='Review rollout')])
  with self.s.gmail.connect() as db:db.execute('INSERT INTO threads(account,id,document,view,date,summary) VALUES (?,?,?,?,?,?)',('mail-account','thread',json.dumps(mail),'needs_reply',1793100000000,'{}'))
  chat=dict(name='spaces/demo/messages/1',space='spaces/demo',sender_id='users/123',sender='Unrelated display',body='Ready to review',date=1793100000)
  with self.s.chat.connect() as db:db.execute('INSERT INTO messages VALUES (?,?,?,?,?,?)',('chat-account',chat['name'],chat['space'],chat['date'],'{}',json.dumps(chat)))
  profile=self.s.person_profile(person['id']);self.assertEqual(len(profile['channels']['email']),1);self.assertEqual(len(profile['channels']['chat']),1)
  with self.s.gmail.connect() as db:db.execute('INSERT INTO threads(account,id,document,view,date,summary) VALUES (?,?,?,?,?,?)',('mail-account','broken','not json','needs_reply',1793100000001,'{}'))
  self.assertEqual(len(self.s.person_profile(person['id'])['channels']['email']),1)
