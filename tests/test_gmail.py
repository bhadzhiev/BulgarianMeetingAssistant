import base64
import copy
from pathlib import Path
import tempfile
import threading
import time
import unittest
from urllib.parse import parse_qs,urlsplit

from app.gmail import GmailSync, message_text, thread_record
from app.google_calendar import GoogleCalendar, CalendarError, SCOPES, GMAIL_SCOPE, TOKEN_URL, GMAIL_URL
from tests import test_calendar, test_http


def encoded(value): return base64.urlsafe_b64encode(value.encode()).decode().rstrip('=')
def thread(key='t1', sent=False, content='Please review synthetic backups.'):
    return dict(id=key, messages=[dict(id='m'+key, internalDate=str(int(time.time()*1000)),labelIds=['SENT'] if sent else ['INBOX'],
        payload=dict(mimeType='text/plain',headers=[dict(name='From',value='synthetic@example.invalid'),dict(name='Subject',value='Synthetic backup review')],body=dict(data=encoded(content))))])


class FakeMailGoogle:
    def __init__(self):
        self.account='synthetic@example.invalid';self.connected=True;self.calls=[];self.responses={};self.handler=None
    def status(self):
        return dict(account=self.account,connected=self.connected,capabilities=dict(gmail=self.connected))
    def gmail_get(self,path,query=None,expected_account=None):
        self.calls.append((path,copy.deepcopy(query),expected_account))
        if expected_account!=self.account:raise CalendarError('Account changed')
        if self.handler:return self.handler(path,query)
        if path=='/profile':return dict(emailAddress=self.account,historyId='100')
        if path=='/threads':return dict(threads=[dict(id='t1')])
        if path=='/history':return dict(historyId='110',history=[])
        return copy.deepcopy(self.responses.get(path,thread(path.rsplit('/',1)[-1])))


class GmailOAuthTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=test_calendar.MemoryStore();self.calls=[];self.granted={GMAIL_SCOPE}
        self.google=GoogleCalendar(Path(self.tmp.name),self.store,self.request)
        self.google.configure(test_calendar.CLIENT)
    def request(self,url,method='GET',payload=None,token=None,form=False):
        self.calls.append((url,method,payload))
        if url==TOKEN_URL:return dict(access_token='synthetic-access',refresh_token='synthetic-refresh',scope=' '.join(self.granted),expires_in=3600)
        if url==GMAIL_URL+'/profile':return dict(emailAddress='synthetic@example.invalid',historyId='100')
        return dict(items=[dict(id='synthetic@example.invalid',primary=True,accessRole='owner')])
    def connect(self):
        url=self.google.begin('http://127.0.0.1:8799','gmail')
        state=parse_qs(urlsplit(url).query)['state'][0]
        return url,self.google.complete(dict(state=state,code='synthetic-code'))
    def test_gmail_only_consent_does_not_request_calendar_or_call_calendar_api(self):
        url,status=self.connect()
        self.assertEqual(parse_qs(urlsplit(url).query)['scope'],[GMAIL_SCOPE])
        self.assertEqual(status['capabilities'],dict(calendar=False,gmail=True))
        self.assertFalse(any('/calendar/' in call[0] for call in self.calls))
        self.assertNotIn('synthetic-access',str(status));self.assertNotIn('synthetic-refresh',str(status))
        self.assertEqual(self.store.value['scopes'],[GMAIL_SCOPE])
    def test_existing_calendar_scopes_are_explicitly_requested_and_preserved(self):
        self.google.bundle.update(account_id='synthetic@example.invalid',refresh_token='old-refresh')
        self.granted=set(SCOPES)|{GMAIL_SCOPE}
        url,status=self.connect()
        self.assertEqual(set(parse_qs(urlsplit(url).query)['scope'][0].split()),self.granted)
        self.assertEqual(status['capabilities'],dict(calendar=True,gmail=True))
    def test_partial_consent_keeps_previous_credentials(self):
        self.google.bundle.update(account_id='synthetic@example.invalid',refresh_token='old-refresh')
        before=copy.deepcopy(self.google.bundle)
        with self.assertRaises(CalendarError):self.connect()
        self.assertEqual(self.google.bundle,before)
    def test_readonly_adapter_rejects_unsupported_path_or_account(self):
        self.connect()
        with self.assertRaises(ValueError):self.google.gmail_get('/messages/send')
        with self.assertRaises(CalendarError):self.google.gmail_get('/threads',expected_account='other@example.invalid')
        before=len(self.calls)
        with self.assertRaises(CalendarError):self.google.list_calendars()
        self.assertEqual(len(self.calls),before)


class GmailSyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.google=FakeMailGoogle();self.changed=[];self.active=False
        self.sync=GmailSync(Path(self.tmp.name),self.google,lambda:self.active,lambda *args:self.changed.append(args))
        self.addCleanup(self.sync.close)
    def run_sync(self):
        self.sync.start();self.sync.thread.join(5)
        self.assertFalse(self.sync.thread.is_alive())
        return self.sync.status()
    def test_initial_window_anchor_and_direction_views(self):
        state=self.run_sync()
        self.assertEqual(state['sync']['history_id'],'100')
        self.assertEqual(self.google.calls[1][1]['maxResults'],20)
        self.assertIn('{in:inbox in:sent}',self.google.calls[1][1]['q'])
        self.assertEqual(len(self.sync.listing()),1)
        self.assertNotIn('body',str(self.sync.listing()))
        self.assertEqual(self.sync.detail('t1')['messages'][0]['body'],'Please review synthetic backups.')
        self.assertEqual(self.sync.listing('waiting'),[])
    def test_full_pagination_continues_after_restart(self):
        def handler(path,query):
            if path=='/profile':return dict(emailAddress=self.google.account,historyId='100')
            if path=='/threads':return dict(threads=[dict(id='t2' if query.get('pageToken') else 't1')],**({} if query.get('pageToken') else dict(nextPageToken='page2')))
            return thread(path.rsplit('/',1)[-1],sent=True)
        self.google.handler=handler
        self.assertEqual(self.run_sync()['job']['status'],'continue')
        reopened=GmailSync(Path(self.tmp.name),self.google)
        reopened.start();reopened.thread.join(5);reopened.close()
        self.assertEqual(len(reopened.listing('waiting')),2)
        self.assertEqual(reopened.status()['sync']['history_id'],'100')
    def test_history_specific_events_are_fetched_before_cursor_advances(self):
        self.run_sync()
        self.google.handler=lambda path,query:dict(historyId='200',history=[dict(labelsAdded=[dict(message=dict(threadId='t1'))])]) if path=='/history' else thread('t1',sent=True)
        self.run_sync()
        self.assertEqual(self.sync.status()['sync']['history_id'],'200')
        self.assertEqual(len(self.sync.listing('waiting')),1)
    def test_failure_retries_pending_thread_without_advancing_cursor(self):
        self.run_sync()
        def fail(path,query):
            if path=='/history':return dict(historyId='200',history=[dict(messages=[dict(threadId='t2')])])
            raise CalendarError('Synthetic network failure')
        self.google.handler=fail
        self.assertEqual(self.run_sync()['job']['status'],'error')
        self.assertEqual(self.sync.status()['sync']['history_id'],'100')
        self.assertEqual(self.sync.status()['sync']['pending'],['t2'])
        self.google.handler=lambda path,query:thread('t2')
        self.run_sync()
        self.assertEqual(self.sync.status()['sync']['history_id'],'200')
    def test_expired_history_requires_bounded_rebuild(self):
        self.run_sync()
        def expired(path,query):
            error=CalendarError('History expired');error.status=404;raise error
        self.google.handler=expired
        self.assertIn('expired',self.run_sync()['job']['status'])
        self.assertNotIn('mode',self.sync.status()['sync'])
        self.google.handler=None
        self.run_sync()
        self.assertEqual(self.sync.status()['sync']['history_id'],'100')
    def test_recording_or_cancel_after_network_read_does_not_commit_page(self):
        for cancel in (False,True):
            self.sync.clear(self.google.account)
            def blocked(path,query):
                if path=='/profile':return dict(emailAddress=self.google.account,historyId='100')
                if cancel:self.sync.cancel.set()
                else:self.active=True
                return dict(threads=[dict(id='t1')])
            self.google.handler=blocked
            self.run_sync()
            self.assertEqual(self.sync.status()['count'],0)
            self.assertNotIn('history_id',self.sync.status()['sync'])
            self.active=False
    def test_account_partition_and_clear_when_disconnected(self):
        self.run_sync()
        old=self.google.account
        self.google.account='other@example.invalid'
        self.assertEqual(self.sync.listing(),[])
        self.google.connected=False
        self.sync.clear(old)
        self.assertNotIn(old,self.sync.status()['cached_accounts'])
    def test_thread_404_removes_cache_without_advancing_on_other_failures(self):
        self.run_sync()
        def missing(path,query):
            if path=='/history':return dict(historyId='200',history=[dict(messages=[dict(threadId='t1')])])
            error=CalendarError('Gone');error.status=404;raise error
        self.google.handler=missing
        self.run_sync()
        self.assertEqual(self.sync.listing(),[])
        self.assertIsNone(self.changed[-1][2])
    def test_initial_sync_stops_at_200_and_reports_a_partial_window(self):
        def paged(path,query):
            if path=='/profile':return dict(emailAddress=self.google.account,historyId='100')
            if path=='/threads':
                page=int(query.get('pageToken',0))
                return dict(threads=[dict(id='t'+str(page*20+i)) for i in range(20)],nextPageToken=str(page+1))
            return thread(path.rsplit('/',1)[-1])
        self.google.handler=paged
        for _ in range(10):self.run_sync()
        state=self.sync.status()
        self.assertEqual((state['count'],state['sync']['mode'],state['sync']['limited']),(200,'history',True))
        self.assertEqual(len([c for c in self.google.calls if c[0]=='/threads']),10)

    def test_large_history_page_retains_every_pending_id_before_advancing(self):
        self.run_sync()
        def many(path,query):
            if path=='/history':return dict(historyId='200',history=[dict(messages=[dict(threadId='n'+str(i)) for i in range(25)])])
            return thread(path.rsplit('/',1)[-1])
        self.google.handler=many
        self.run_sync()
        self.assertEqual(self.sync.status()['sync']['history_id'],'100')
        self.assertEqual(len(self.sync.status()['sync']['pending']),5)
        history_calls=len([c for c in self.google.calls if c[0]=='/history'])
        self.run_sync()
        self.assertEqual(self.sync.status()['sync']['history_id'],'200')
        self.assertEqual(len([c for c in self.google.calls if c[0]=='/history']),history_calls)
        self.assertEqual(self.sync.status()['count'],26)

    def test_mime_html_is_text_only_and_attachments_are_skipped(self):
        payload=dict(mimeType='multipart/alternative',parts=[dict(mimeType='text/html',body=dict(data=encoded('<p>Hello</p><script>bad()</script><img src="https://invalid">'))),dict(mimeType='text/plain',body=dict(data=encoded('Plain text')))])
        self.assertEqual(message_text(payload),'Plain text')
        html=message_text(payload['parts'][0]);self.assertIn('Hello',html);self.assertNotIn('bad()',html);self.assertNotIn('https://',html)
        self.assertEqual(message_text(dict(payload['parts'][1],filename='attachment.txt')),'')
    def test_bulgarian_windows_1251_body_is_decoded_without_replacement(self):
        content='Моля, прегледайте архивите.'
        payload=dict(mimeType='text/plain',headers=[dict(name='Content-Type',value='text/plain; charset=windows-1251')],
                     body=dict(data=base64.urlsafe_b64encode(content.encode('cp1251')).decode()))
        self.assertEqual(message_text(payload),content)

    def test_drafts_and_old_non_inbox_sent_threads_are_excluded(self):
        value=thread();value['messages'][0]['labelIds']=['DRAFT']
        self.assertIsNone(thread_record(value,int(time.time())-30*86400))


class GmailServiceTests(unittest.TestCase):
    def setUp(self):
        from app.service import MeetingService
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.google=FakeMailGoogle()
        self.service=MeetingService(Path(self.tmp.name),Path(__file__).resolve().parents[1],google=self.google)
        self.addCleanup(self.service.close)
    def sync(self):
        self.service.gmail.start();self.service.gmail.thread.join(5)
        self.assertEqual(self.service.gmail.status()['job']['status'],'synced')
    def test_manual_proposal_and_changed_thread_invalidate_old_review(self):
        self.sync()
        original=self.service.gmail.detail('t1')
        result=self.service.gmail_proposal('t1',original['revision'],'mt1','Review the synthetic backup')
        proposal_id=result['proposals'][0]
        self.assertEqual(self.service.items.data['proposals'][proposal_id]['state'],'pending')
        self.assertEqual(self.service.items.items,{})
        def changed(path,query):
            if path=='/history':return dict(historyId='200',history=[dict(messages=[dict(threadId='t1')])])
            return thread('t1',content='Updated synthetic backup request.')
        self.google.handler=changed
        self.sync()
        self.assertEqual(self.service.items.data['proposals'][proposal_id]['state'],'stale')
        from app.work_items import WorkItemConflict
        with self.assertRaises(WorkItemConflict):
            self.service.gmail_proposal('t1',original['revision'],'mt1','Old content proposal')
    def test_clear_cache_keeps_workitem_quotes_and_no_credentials_in_archive(self):
        self.sync()
        record=self.service.gmail.detail('t1')
        result=self.service.gmail_proposal('t1',record['revision'],'mt1','Synthetic task')
        self.service.gmail.clear(self.google.account)
        self.assertEqual(self.service.gmail.listing(),[])
        self.assertIn(result['proposals'][0],self.service.items.data['proposals'])
        from app import backup
        with backup.snapshot(self.service.library.root,guard=self.service._snapshot_guard) as (frozen,_):
            self.assertFalse((frozen/'gmail-cache.sqlite3').exists())
            self.assertTrue((frozen/'items.json').exists())
    def test_changed_source_commit_failure_does_not_advance_gmail_cursor(self):
        self.sync()
        record=self.service.gmail.detail('t1')
        self.service.gmail_proposal('t1',record['revision'],'mt1','Synthetic task')
        def changed(path,query):
            if path=='/history':return dict(historyId='200',history=[dict(messages=[dict(threadId='t1')])])
            return thread('t1',content='New content')
        self.google.handler=changed
        from unittest.mock import patch
        with patch.object(self.service.items.store,'save',side_effect=OSError('Synthetic disk failure')):
            self.service.gmail.start();self.service.gmail.thread.join(5)
        self.assertEqual(self.service.gmail.status()['sync']['history_id'],'100')
        self.assertEqual(self.service.gmail.status()['sync']['pending'],['t1'])
        self.assertEqual(self.service.gmail.detail('t1')['revision'],record['revision'])


class GmailHTTPTests(unittest.TestCase):
    setUp=test_http.HTTPTests.setUp
    tearDown=test_http.HTTPTests.tearDown
    request=test_http.HTTPTests.request
    def test_mail_routes_require_session_and_same_origin(self):
        import json
        self.assertEqual(self.request('/api/gmail',headers={})[0],403)
        self.assertEqual(self.request('/api/gmail/sync',{},headers={})[0],403)
        self.assertEqual(self.request('/api/gmail/sync',{},headers=dict(self.headers,Origin='https://example.invalid'))[0],403)
        self.assertEqual(self.request('/api/gmail')[0],200)
        self.service.google=FakeMailGoogle()
        self.service.gmail.google=self.service.google
        self.assertEqual(self.request('/api/gmail/sync',{})[0],200)
        self.service.gmail.thread.join(5)
        status,body,_=self.request('/api/gmail/threads?view=needs_reply')
        self.assertEqual(status,200);self.assertEqual(len(json.loads(body)),1)
