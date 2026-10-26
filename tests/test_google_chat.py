import copy
import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
from urllib.parse import parse_qs,urlsplit
from unittest.mock import patch

from app.google_calendar import GoogleCalendar,CalendarError,SCOPES,GMAIL_SCOPE,CHAT_SCOPES,USERINFO_URL,TOKEN_URL,GMAIL_URL
from app.google_chat import ChatSync,message_record
from app.service import MeetingService
from app.work_graph import WorkGraph
from app.work_items import WorkItemConflict
from tests import test_calendar,test_http

SPACE='spaces/synthetic'
NAME=SPACE+'/messages/m1'


def message(name=NAME,text='Review synthetic backups.',**values):
    stamp=dt.datetime.now(dt.timezone.utc).isoformat()
    return dict(name=name,text=text,createTime=stamp,sender=dict(name='users/synthetic-sender',displayName='Synthetic sender'),
                thread=dict(name=name.rsplit('/messages/',1)[0]+'/threads/thread1'),**values)


class FakeChatGoogle:
    def __init__(self):
        self.account='synthetic@example.invalid';self.uid='synthetic-user-1';self.connected=True;self.calls=[];self.handler=None
        self.value=message()
    def status(self):return dict(connected=self.connected,account=self.account,chat_account_id=self.uid,
                                capabilities=dict(chat=self.connected))
    def chat_get(self,resource,query=None,expected_account=None):
        self.calls.append((resource,copy.deepcopy(query),expected_account))
        if expected_account!=self.uid:raise CalendarError('Account changed')
        if self.handler:return self.handler(resource,query)
        if resource=='spaces':return dict(spaces=[dict(name=SPACE,displayName='Synthetic space',spaceType='SPACE')])
        if resource==SPACE+'/messages':return dict(messages=[copy.deepcopy(self.value)])
        return copy.deepcopy(self.value)


class ChatOAuthTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=test_calendar.MemoryStore();self.calls=[];self.granted=set(CHAT_SCOPES);self.address='synthetic@example.invalid'
        self.google=GoogleCalendar(Path(self.tmp.name),self.store,self.request)
        self.google.configure(test_calendar.CLIENT)
    def request(self,url,method='GET',payload=None,token=None,form=False):
        self.calls.append((url,method,payload))
        if url==TOKEN_URL:return dict(access_token='synthetic-access',refresh_token='synthetic-refresh',scope=' '.join(self.granted),expires_in=3600)
        if url==USERINFO_URL:return dict(email=self.address,email_verified=True,sub='synthetic-user-1')
        if url==GMAIL_URL+'/profile':return dict(emailAddress='synthetic@example.invalid')
        return dict(items=[dict(id='synthetic@example.invalid',primary=True,accessRole='owner')])
    def connect(self):
        url=self.google.begin('http://127.0.0.1:8799','chat')
        return url,self.google.complete(dict(state=parse_qs(urlsplit(url).query)['state'][0],code='synthetic-code'))
    def test_chat_only_scopes_verified_identity_and_no_calendar_or_gmail_call(self):
        url,status=self.connect()
        self.assertEqual(set(parse_qs(urlsplit(url).query)['scope'][0].split()),set(CHAT_SCOPES))
        self.assertEqual(status['capabilities'],dict(chat=True,calendar=False,gmail=False))
        self.assertEqual(status['chat_account_id'],'synthetic-user-1')
        self.assertFalse(any('/calendar/' in call[0] or '/gmail/' in call[0] for call in self.calls))
        self.assertNotIn('synthetic-refresh',str(status));self.assertNotIn('synthetic-access',str(status))
    def test_existing_google_capabilities_are_preserved_in_explicit_consent(self):
        self.google.bundle.update(account_id='synthetic@example.invalid',scopes=list(SCOPES)+[GMAIL_SCOPE],refresh_token='old-token')
        self.granted|=set(SCOPES)|{GMAIL_SCOPE}
        _,status=self.connect()
        self.assertEqual(status['capabilities'],dict(chat=True,calendar=True,gmail=True))
    def test_denied_chat_or_mismatched_identity_preserves_credentials(self):
        for mismatch in (False,True):
            self.google.bundle.update(account_id='synthetic@example.invalid',scopes=list(SCOPES),refresh_token='old-token')
            self.granted=set(CHAT_SCOPES)|set(SCOPES)
            if mismatch:self.address='other@example.invalid'
            else:self.granted.discard(CHAT_SCOPES[-1])
            before=copy.deepcopy(self.google.bundle)
            with self.assertRaises(CalendarError):self.connect()
            self.assertEqual(self.google.bundle,before)
    def test_chat_adapter_only_allows_read_endpoints_and_bound_user_id(self):
        self.connect()
        for resource in ('spaces/synthetic/messages/..','spaces/../messages/m1','spaces/synthetic/members','https://example.invalid'):
            with self.assertRaises(ValueError):self.google.chat_get(resource)
        with self.assertRaises(CalendarError):self.google.chat_get('spaces',expected_account='different-user')
        self.google.chat_get(NAME,expected_account='synthetic-user-1')
        self.assertEqual(self.calls[-1][1],'GET')
    def test_keychain_failure_status_is_safe_and_disconnected(self):
        self.google.loaded=False
        with patch.object(self.store,'get',side_effect=CalendarError('Keychain unavailable')):
            status=self.google.status()
        self.assertFalse(status['connected']);self.assertFalse(status['capabilities']['chat'])


class ChatSyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.google=FakeChatGoogle();self.changed=[];self.unavailable=[];self.active=False
        self.chat=ChatSync(Path(self.tmp.name),self.google,lambda:self.active,lambda *v:self.changed.append(v),lambda *v:self.unavailable.append(v))
        self.addCleanup(self.chat.close)
    def run_sync(self,kind='messages',resource=SPACE,restart=False):
        self.chat.start(kind,resource,restart);self.chat.thread.join(5)
        self.assertFalse(self.chat.thread.is_alive())
        return self.chat.status()
    def test_discovery_fetches_metadata_only_and_explicit_space_sync_fetches_text(self):
        self.run_sync('spaces','')
        self.assertEqual([c[0] for c in self.google.calls],['spaces'])
        self.assertEqual(self.chat.spaces()[0]['name'],SPACE)
        self.run_sync()
        self.assertEqual(self.chat.detail(NAME)['body'],'Review synthetic backups.')
        query=next(c[1] for c in self.google.calls if c[0]==SPACE+'/messages')
        self.assertEqual((query['pageSize'],query['orderBy'],query['showDeleted']),(20,'createTime desc','true'))
        self.assertIn('AND',query['filter'])
        self.assertNotIn('body',self.chat.messages(SPACE)[0])
    def test_pagination_keeps_same_window_and_resumes_after_restart(self):
        def paged(resource,query):
            if query.get('pageToken'):return dict(messages=[message(SPACE+'/messages/m2')])
            return dict(messages=[message()],nextPageToken='next-page')
        self.google.handler=paged
        self.assertEqual(self.run_sync()['job']['status'],'continue')
        second=ChatSync(Path(self.tmp.name),self.google)
        second.start('messages',SPACE);second.thread.join(5);second.close()
        queries=[c[1] for c in self.google.calls]
        self.assertEqual(queries[0]['filter'],queries[1]['filter'])
        self.assertEqual(len(second.messages(SPACE)),2)
    def test_recent_window_stops_at_200_and_marks_limit(self):
        def paged(resource,query):
            page=int(query.get('pageToken','0'))
            return dict(messages=[message(SPACE+'/messages/m'+str(page*20+i)) for i in range(20)],nextPageToken=str(page+1))
        self.google.handler=paged
        for _ in range(10):self.run_sync()
        state=self.chat.status()['states'][SPACE]
        self.assertTrue(state['complete']);self.assertTrue(state['limited']);self.assertEqual(state['count'],200)
    def test_partial_pages_cannot_push_message_or_space_cycles_past_200(self):
        def paged(resource,query):
            page=int(query.get('pageToken','0'))
            if resource=='spaces':
                return dict(spaces=[dict(name='spaces/s'+str(page*49+i)) for i in range(49)],nextPageToken=str(page+1))
            return dict(messages=[message(SPACE+'/messages/m'+str(page*19+i)) for i in range(19)],nextPageToken=str(page+1))
        self.google.handler=paged
        for _ in range(5):self.run_sync('spaces','')
        self.assertEqual(len(self.chat.spaces()),200)
        self.assertTrue(self.chat.status()['states']['']['limited'])
        for _ in range(11):self.run_sync()
        self.assertEqual(self.chat.status()['states'][SPACE]['count'],200)
        self.assertEqual(len(self.chat.messages(SPACE)),200)
        self.assertTrue(self.chat.status()['states'][SPACE]['limited'])
        self.assertEqual({call[1]['pageSize'] for call in self.google.calls if call[0]==SPACE+'/messages'},{20})

    def test_bad_cross_space_record_rejects_page_before_callbacks(self):
        self.google.handler=lambda *_:dict(messages=[message(),message('spaces/other/messages/m2')])
        self.assertEqual(self.run_sync()['job']['status'],'error')
        self.assertEqual(self.changed,[]);self.assertEqual(self.chat.messages(SPACE),[])
    def test_failed_source_update_keeps_pending_records_for_retry(self):
        def fail(*args):raise OSError('Synthetic source store failure')
        self.chat.on_message=fail
        self.assertEqual(self.run_sync()['job']['status'],'error')
        self.assertEqual(self.chat.messages(SPACE),[])
        self.assertNotIn('pending',self.chat.status()['states'][SPACE])
        before=len(self.google.calls);self.chat.on_message=lambda *args:None
        self.run_sync()
        self.assertEqual(len(self.google.calls),before)
        self.assertEqual(len(self.chat.messages(SPACE)),1)
    def test_cancel_or_recording_after_request_does_not_commit_messages(self):
        for active in (False,True):
            self.chat.clear(self.google.uid)
            def handler(*args):
                if active:self.active=True
                else:self.chat.cancel.set()
                return dict(messages=[message()])
            self.google.handler=handler
            self.run_sync()
            self.assertEqual(self.chat.messages(SPACE),[])
            self.active=False
    def test_deleted_message_is_a_tombstone_and_keeps_identity(self):
        self.run_sync()
        self.google.value=dict(name=NAME,deleteTime=dt.datetime.now(dt.timezone.utc).isoformat(),deletionMetadata=dict(deletionType='CREATOR'))
        self.run_sync('refresh',NAME)
        record=self.chat.detail(NAME)
        self.assertFalse(record['available']);self.assertEqual(record['body'],'')
        self.assertEqual(record['name'],NAME)
    def test_permission_loss_marks_all_space_cache_entries_unavailable(self):
        self.run_sync()
        def denied(*args):
            error=CalendarError('Chat access denied');error.status=403;raise error
        self.google.handler=denied
        self.run_sync()
        self.assertFalse(self.chat.detail(NAME)['available']);self.assertEqual(self.chat.detail(NAME)['body'],'')
        self.assertEqual(self.unavailable[-1],(self.google.uid,SPACE+'/'))
    def test_direct_space_sync_is_clearable_without_prior_discovery(self):
        self.run_sync()
        self.assertEqual(self.chat.status()['cached_accounts'],[dict(id=self.google.uid,label=self.google.account)])

    def test_email_rename_keeps_the_same_verified_user_cache_partition(self):
        self.run_sync()
        self.google.account='renamed@example.invalid'
        self.assertEqual(self.chat.detail(NAME)['body'],'Review synthetic backups.')
        self.run_sync()
        self.assertEqual(self.chat.status()['cached_accounts'][0]['label'],'renamed@example.invalid')

    def test_stable_user_id_partitions_cache_and_clear_works_offline(self):
        self.run_sync();old=self.google.uid
        self.google.uid='another-user'
        self.assertEqual(self.chat.messages(SPACE),[])
        self.google.connected=False;self.chat.clear(old)
        self.assertEqual(self.chat.status()['cached_accounts'],[])


class ChatServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.google=FakeChatGoogle();self.service=MeetingService(Path(self.tmp.name),Path(__file__).resolve().parents[1],google=self.google)
        self.addCleanup(self.service.close)
        self.sync()
    def sync(self):self.service.chat.start('messages',SPACE);self.service.chat.thread.join(5)
    def propose(self):
        record=self.service.chat.detail(NAME)
        return self.service.chat_proposal(NAME,record['revision'],'Review synthetic backups')
    def test_proposal_has_stable_message_thread_evidence_and_no_ai_permission(self):
        result=self.propose();again=self.propose()
        self.assertEqual(result,again);self.assertEqual(self.service.items.items,{})
        source=next(iter(self.service.items.data['sources'].values()))
        self.assertEqual((source['provider'],source['account'],source['external_id']),('google_chat',self.google.uid,NAME))
        self.assertFalse(source['ai_export_allowed'])
        ev=next(iter(self.service.items.data['source_evidence'].values()))
        self.assertEqual(ev['locator']['thread'],SPACE+'/threads/thread1')
    def test_edit_stales_pending_proposals_and_does_not_change_accepted_task_status(self):
        result=self.propose();p=self.service.items.data['proposals'][result['proposals'][0]]
        graph=WorkGraph(self.service.items)
        accepted=graph.review(p['id'],p['revision'],'accept')
        item=accepted['result_id']
        self.google.value=dict(self.google.value,text='Changed synthetic backup request.',lastUpdateTime=dt.datetime.now(dt.timezone.utc).isoformat())
        self.sync()
        self.assertEqual(self.service.items.items[item]['status'],'open')
        record=self.service.chat.detail(NAME)
        newer=self.service.chat_proposal(NAME,record['revision'],'Updated backup review')
        self.google.value=dict(self.google.value,text='Changed once more.',lastUpdateTime=dt.datetime.now(dt.timezone.utc).isoformat())
        self.sync()
        self.assertEqual(self.service.items.data['proposals'][newer['proposals'][0]]['state'],'stale')
    def test_deleted_source_blocks_accept_and_retains_history(self):
        result=self.propose();p=self.service.items.data['proposals'][result['proposals'][0]]
        self.google.value=dict(name=NAME,deleteTime=dt.datetime.now(dt.timezone.utc).isoformat())
        self.service.chat.start('refresh',NAME);self.service.chat.thread.join(5)
        with self.assertRaises(WorkItemConflict):WorkGraph(self.service.items).review(p['id'],p['revision'],'accept')
        with self.assertRaises(ValueError):self.propose()
        self.assertEqual(len(self.service.items.data['source_revisions']),1)
    def test_cache_clear_keeps_portable_graph_source(self):
        self.propose();self.service.chat.clear(self.google.uid)
        self.assertEqual(self.service.chat.messages(SPACE),[])
        self.assertEqual(len(self.service.items.data['proposals']),1)
        from app import backup
        with backup.snapshot(self.service.library.root,guard=self.service._snapshot_guard) as (frozen,_):
            self.assertFalse((frozen/'chat-cache.sqlite3').exists())
            portable=json.loads((frozen/'items.json').read_text())
            self.assertTrue(portable['sources'])


class ChatHTTPTests(unittest.TestCase):
    setUp=test_http.HTTPTests.setUp;tearDown=test_http.HTTPTests.tearDown;request=test_http.HTTPTests.request
    def test_routes_require_session_origin_and_make_manual_proposals(self):
        self.assertEqual(self.request('/api/chat',headers={})[0],403)
        self.assertEqual(self.request('/api/chat/sync',dict(space=SPACE),headers=dict(self.headers,Origin='https://example.invalid'))[0],403)
        self.assertEqual(self.request('/api/chat')[0],200)
        fake=FakeChatGoogle();self.service.google=fake;self.service.chat.google=fake
        self.assertEqual(self.request('/api/chat/discover',{})[0],200);self.service.chat.thread.join(5)
        self.assertEqual(self.request('/api/chat/sync',dict(space=SPACE))[0],200);self.service.chat.thread.join(5)
        _,raw,_=self.request('/api/chat/message?name='+NAME);record=json.loads(raw)
        body=dict(name=NAME,revision=record['revision'],title='Synthetic task')
        self.assertEqual(self.request('/api/chat/propose',body)[0],200)
        self.assertEqual(self.request('/api/chat/propose',dict(body,revision='stale'))[0],409)
