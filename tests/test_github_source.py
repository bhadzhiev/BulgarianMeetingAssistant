import copy
import datetime as dt
import io
import json
from pathlib import Path
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

from app.github_source import GitHubConnection,GitHubSync,GitHubError,http_get,_NoRedirect,item_record
from app.service import MeetingService
from app.work_graph import WorkGraph
from app.work_items import WorkItemConflict
from tests import test_calendar,test_http

REPO=dict(id=11,full_name='synthetic/repository')


def issue(number=1,issue_id=101,pr=False,state='open',body='Review synthetic backups.'):
    row=dict(id=issue_id,number=number,title='Synthetic backup review',body=body,state=state,user=dict(id=1),assignees=[dict(id=1)],
             url=f'https://api.github.com/repos/{REPO["full_name"]}/issues/{number}',updated_at='2026-10-26T00:00:00Z')
    if pr:row['pull_request']=dict(url=f'https://api.github.com/repos/{REPO["full_name"]}/pulls/{number}')
    return row


def pull(number=2,state='closed',merged=True):
    return dict(id=900,number=number,state=state,merged=merged,merged_at='2026-10-26T00:00:00Z' if merged else None,
                draft=False,base=dict(repo=REPO),head=dict(sha='a'*40),merge_commit_sha='b'*40)


class FakeGitHub:
    def __init__(self):
        self.account='1';self.login='synthetic-user';self.connected=True;self.calls=[];self.handler=None
        self.rows={1:issue(),2:issue(2,202,True,'closed')};self.pr=pull()
    def status(self):return dict(connected=self.connected,account_id=self.account,login=self.login)
    def get(self,path,query=None,expected_account=None):
        self.calls.append((path,copy.deepcopy(query),expected_account))
        if expected_account!=self.account:raise GitHubError('Account changed')
        if self.handler:return self.handler(path,query)
        if path=='/user':data=dict(id=int(self.account),login=self.login)
        elif path=='/repos/'+REPO['full_name']:data=REPO
        elif path=='/search/issues':data=dict(items=list(self.rows.values()),incomplete_results=False)
        elif '/issues/' in path:data=self.rows[int(path.rsplit('/',1)[1])]
        elif '/pulls/' in path:data=self.pr
        else:raise AssertionError(path)
        return dict(data=copy.deepcopy(data),has_next=False)


class CredentialTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=test_calendar.MemoryStore();self.calls=[]
        self.connection=GitHubConnection(Path(self.tmp.name),self.store,self.request)
        self.token='github_pat_'+'x'*32
    def request(self,path,query,token):
        self.calls.append((path,query,token));return dict(data=dict(id=1,login='synthetic-user'),has_next=False)
    def test_verified_token_is_only_in_keychain_not_status_or_metadata(self):
        status=self.connection.connect(self.token)
        self.assertTrue(status['connected']);self.assertEqual(status['account_id'],'1')
        public=json.dumps(status)+self.connection.path.read_text()
        self.assertNotIn(self.token,public);self.assertEqual(self.store.value['token'],self.token)
        self.connection.disconnect();self.assertFalse(self.connection.status()['connected']);self.assertIsNone(self.store.value)
    def test_invalid_token_or_failed_identity_keeps_previous_connection(self):
        self.connection.connect(self.token);old=copy.deepcopy(self.store.value)
        with self.assertRaises(ValueError):self.connection.connect('classic-token')
        self.connection.request=lambda *args:dict(data=dict(id='invalid',login='synthetic-user'))
        with self.assertRaises(GitHubError):self.connection.connect('github_pat_'+'y'*32)
        self.assertEqual(self.store.value,old)
    def test_get_adapter_rejects_unsupported_paths_and_wrong_account(self):
        self.connection.connect(self.token)
        for path in ('/repos/synthetic/repository/issues','/user/repos','https://example.invalid','/repos/a/../issues/1'):
            with self.assertRaises(ValueError):self.connection.get(path)
        with self.assertRaises(GitHubError):self.connection.get('/user',expected_account='2')
        self.connection.get('/repos/synthetic/repository/issues/1',expected_account='1')
        self.assertEqual(self.calls[-1][0],'/repos/synthetic/repository/issues/1')
    def test_redirects_are_not_followed_and_http_errors_hide_response_and_token(self):
        self.assertIsNone(_NoRedirect().redirect_request(None,None,None,None,None,None,None))
        error=urllib.error.HTTPError('https://api.github.com/user',403,'Denied',{'X-RateLimit-Remaining':'0'},io.BytesIO(self.token.encode()))
        with patch('urllib.request.build_opener') as opener:
            opener.return_value.open.side_effect=error
            with self.assertRaises(GitHubError) as raised:http_get('/user',None,self.token)
        self.assertNotIn(self.token,str(raised.exception));self.assertTrue(raised.exception.rate_limited)


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.connection=FakeGitHub();self.changed=[];self.unavailable=[];self.active=False
        self.sync=GitHubSync(Path(self.tmp.name),self.connection,lambda:self.active,lambda *args:self.changed.append(args),lambda *args:self.unavailable.append(args))
        self.addCleanup(self.sync.close)
    def run_sync(self,role='all',restart=False,key=None):
        self.sync.start(REPO['full_name'],role,restart,key);self.sync.thread.join(5)
        self.assertFalse(self.sync.thread.is_alive());return self.sync.status()
    def test_issue_and_pr_use_issue_database_id_and_explicit_merged_state(self):
        self.run_sync()
        records=self.sync.listing(11)
        self.assertEqual({r['issue_id'] for r in records},{101,202})
        record=self.sync.detail(202)
        self.assertEqual((record['kind'],record['state'],record['pull_id']),('pull_request','merged',900))
        self.assertEqual(record['head_sha'],'a'*40)
    def test_closed_unmerged_pr_is_distinct_from_merged(self):
        self.connection.pr=pull(merged=False)
        self.run_sync()
        self.assertEqual(self.sync.detail(202)['state'],'closed')

    def test_personal_filters_use_server_assignee_author_and_mentions_queries(self):
        for role,qualifier in (('assigned','assignee'),('created','author'),('mentioned','mentions')):
            self.run_sync(role)
            query=next(c[1]['q'] for c in reversed(self.connection.calls) if c[0]=='/search/issues')
            self.assertIn(qualifier+':synthetic-user',query);self.assertIn('repo:synthetic/repository',query)
            self.assertEqual(len(self.sync.listing(11,role)),2)
    def test_overview_lists_open_items_from_every_repository_without_a_selection(self):
        other=dict(id=12,full_name='synthetic/other')
        def rows(path,query):
            if path=='/user':return dict(data=dict(id=1,login='synthetic-user'))
            if path=='/issues':
                self.assertEqual((query['filter'],query['state'],query['per_page']),('assigned','open',100))
                second=issue(7,707);second['url']='https://api.github.com/repos/synthetic/other/issues/7';second['updated_at']='2026-10-27T00:00:00Z'
                return dict(data=[dict(issue(),repository=REPO),dict(second,repository=other),dict(issue(3,303,True),repository=REPO)],has_next=False)
            if '/pulls/' in path:return dict(data=pull(3,'open',False))
            raise AssertionError(path)
        self.connection.handler=rows
        self.sync.start_overview('assigned');self.sync.thread.join(5)
        view=self.sync.overview('assigned')
        self.assertEqual([r['repository'] for r in view['items']],['synthetic/other','synthetic/repository','synthetic/repository'])
        self.assertTrue(view['state']['complete']);self.assertEqual(view['state']['count'],3)
        self.assertEqual([r['number'] for r in self.sync.overview('assigned','pull_request')['items']],[3])
        self.assertEqual({r['full_name'] for r in self.sync.repos()},{'synthetic/other','synthetic/repository'})
        self.assertEqual(self.sync.overview('all')['items'],[])
        with self.assertRaises(ValueError):self.sync.overview('everything')
    def test_partial_page_cap_and_fixed_query_limit(self):
        def many(path,query):
            if path=='/user':return dict(data=dict(id=1,login='synthetic-user'))
            if path=='/repos/'+REPO['full_name']:return dict(data=REPO)
            if path=='/search/issues':
                page=query['page'];rows=[issue(number=(page-1)*19+i+1,issue_id=(page-1)*19+i+1) for i in range(19)]
                return dict(data=dict(items=rows,incomplete_results=False),has_next=True)
            n=int(path.rsplit('/',1)[1]);return dict(data=issue(number=n,issue_id=n))
        self.connection.handler=many
        for _ in range(11):self.run_sync()
        state=self.sync.status()['states']['11:all']
        self.assertTrue(state['complete']);self.assertTrue(state['limited']);self.assertEqual(state['count'],200)
        self.assertEqual(len(self.sync.listing(11)),200)
        searches=[c[1] for c in self.connection.calls if c[0]=='/search/issues']
        self.assertEqual({q['per_page'] for q in searches},{20});self.assertEqual(len({q['q'] for q in searches}),1)
    def test_source_failure_preserves_pending_before_advancing_page(self):
        self.sync.on_item=lambda *args:(_ for _ in ()).throw(OSError('Synthetic disk failure'))
        self.assertEqual(self.run_sync()['job']['status'],'error')
        self.assertEqual(self.sync.listing(11),[])
        self.assertNotIn('pending',self.sync.status()['states']['11:all'])
        self.sync.on_item=lambda *args:None
        searches=len([c for c in self.connection.calls if c[0]=='/search/issues'])
        self.run_sync()
        self.assertEqual(len([c for c in self.connection.calls if c[0]=='/search/issues']),searches)
        self.assertEqual(len(self.sync.listing(11)),2)
    def test_cross_repository_search_page_is_rejected_before_item_fetch(self):
        def bad(path,query):
            if path=='/user':return dict(data=dict(id=1,login='synthetic-user'))
            if path=='/repos/'+REPO['full_name']:return dict(data=REPO)
            return dict(data=dict(items=[dict(issue(),url='https://api.github.com/repos/other/repository/issues/1')]))
        self.connection.handler=bad
        self.assertEqual(self.run_sync()['job']['status'],'error');self.assertEqual(self.changed,[])
    def test_cancel_and_recording_stop_before_body_commit(self):
        original=self.connection.get
        def handler(path,query):
            if path=='/search/issues':self.active=True
            self.connection.handler=None
            try:return original(path,query,expected_account='1')
            finally:self.connection.handler=handler
        self.connection.handler=handler
        status=self.run_sync();self.assertIn('paused',status['job']['status']);self.assertEqual(self.sync.listing(11),[])
    def test_account_partition_and_cache_clear_after_disconnect(self):
        self.run_sync();old=self.connection.account;self.connection.account='2'
        self.assertEqual(self.sync.listing(11),[])
        self.connection.connected=False;self.sync.clear(old)
        self.assertEqual(self.sync.status()['cached_accounts'],[])
    def test_incomplete_search_is_reported_and_absence_does_not_delete_cached_object(self):
        self.run_sync();original=self.connection.get
        def empty(path,query):
            if path=='/search/issues':return dict(data=dict(items=[],incomplete_results=True),has_next=False)
            self.connection.handler=None
            try:return original(path,query,expected_account='1')
            finally:self.connection.handler=empty
        self.connection.handler=empty;self.run_sync()
        self.assertTrue(self.sync.status()['states']['11:all']['incomplete'])
        self.assertEqual(self.sync.listing(11),[]);self.assertTrue(self.sync.detail(101)['available'])
    def test_rate_limit_does_not_mark_repository_deleted_or_clear_cached_text(self):
        self.run_sync();original=self.connection.get
        def limited(path,query):
            if path=='/search/issues':
                error=GitHubError('Rate limited');error.status=403;error.rate_limited=True;raise error
            self.connection.handler=None
            try:return original(path,query,expected_account='1')
            finally:self.connection.handler=limited
        self.connection.handler=limited;self.run_sync()
        self.assertTrue(self.sync.detail(101)['available']);self.assertEqual(self.unavailable,[])


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.service=MeetingService(Path(self.tmp.name),Path(__file__).resolve().parents[1])
        self.addCleanup(self.service.close);self.connection=FakeGitHub();self.service.github.connection=self.connection
        self.run_sync()
    def run_sync(self,key=None):self.service.github.start(REPO['full_name'],key=key);self.service.github.thread.join(5)
    def propose(self,key=101):
        record=self.service.github.detail(key)
        return self.service.github_proposal(key,record['revision'],'Review the synthetic GitHub work')
    def test_manual_proposal_keeps_canonical_and_remote_status_separate(self):
        result=self.propose(202);p=self.service.items.data['proposals'][result['proposals'][0]]
        self.assertEqual(self.service.items.items,{})
        source=next(iter(self.service.items.data['sources'].values()))
        self.assertEqual((source['external_id'],source['remote']['state']),('issue:202','merged'))
        accepted=WorkGraph(self.service.items).review(p['id'],p['revision'],'accept')
        self.assertEqual(self.service.items.items[accepted['result_id']]['status'],'open')
        self.assertFalse(source['ai_export_allowed'])
    def test_remote_close_stales_pending_but_does_not_complete_linked_task(self):
        result=self.propose();p=self.service.items.data['proposals'][result['proposals'][0]]
        accepted=WorkGraph(self.service.items).review(p['id'],p['revision'],'accept')
        item=accepted['result_id']
        self.connection.rows[1]=dict(self.connection.rows[1],state='closed')
        self.run_sync(key=101)
        self.assertEqual(self.service.items.items[item]['status'],'open')
        self.assertEqual(next(iter(self.service.items.data['sources'].values()))['remote']['state'],'closed')
    def test_changed_quote_invalidates_pending_and_old_revision_proposal(self):
        result=self.propose();p=self.service.items.data['proposals'][result['proposals'][0]]
        old=self.service.github.detail(101)
        self.connection.rows[1]=dict(self.connection.rows[1],body='Changed backup request')
        self.run_sync(key=101)
        self.assertEqual(self.service.items.data['proposals'][p['id']]['state'],'stale')
        with self.assertRaises(WorkItemConflict):self.service.github_proposal(101,old['revision'],'Stale task')
    def test_unchanged_github_refresh_does_not_rewrite_work_graph(self):
        self.propose();revision=self.service.items.revision
        self.run_sync(key=101)
        self.assertEqual(self.service.items.revision,revision)

    def test_repository_rename_keeps_source_identity_and_creates_a_new_content_revision(self):
        self.propose();source=copy.deepcopy(next(iter(self.service.items.data['sources'].values())))
        renamed=dict(REPO,full_name='synthetic/renamed')
        row=dict(self.connection.rows[1],url='https://api.github.com/repos/synthetic/renamed/issues/1')
        record=item_record(row,renamed,'1')
        self.service._refresh_github_source('1',record)
        current=next(iter(self.service.items.data['sources'].values()))
        self.assertEqual(current['id'],source['id'])
        self.assertNotEqual(current['current_revision'],source['current_revision'])
        self.assertEqual(current['remote']['repository'],'synthetic/renamed')

    def test_permission_loss_blocks_accept_and_keeps_source_history(self):
        result=self.propose();p=self.service.items.data['proposals'][result['proposals'][0]]
        def denied(*args):
            error=GitHubError('Repository access denied');error.status=404;raise error
        self.connection.handler=denied;self.run_sync(key=101)
        with self.assertRaises(WorkItemConflict):WorkGraph(self.service.items).review(p['id'],p['revision'],'accept')
        self.assertEqual(self.service.github.detail(101)['body'],'')
        self.assertEqual(len(self.service.items.data['source_revisions']),1)
    def test_cache_is_rebuildable_and_credentials_are_excluded_from_archive(self):
        self.propose();self.service.github.clear('1')
        self.assertEqual(len(self.service.items.data['proposals']),1)
        from app import backup
        with backup.snapshot(self.service.library.root,guard=self.service._snapshot_guard) as (frozen,_):
            self.assertFalse((frozen/'github-cache.sqlite3').exists());self.assertFalse((frozen/'.github-account.json').exists())
            self.assertTrue((frozen/'items.json').exists())


class HTTPTests(unittest.TestCase):
    setUp=test_http.HTTPTests.setUp;tearDown=test_http.HTTPTests.tearDown;request=test_http.HTTPTests.request
    def test_routes_require_session_origin_and_current_revision(self):
        self.assertEqual(self.request('/api/github',headers={})[0],403)
        self.assertEqual(self.request('/api/github/sync',dict(repository=REPO['full_name']),headers=dict(self.headers,Origin='https://example.invalid'))[0],403)
        self.service.github.connection=FakeGitHub()
        self.assertEqual(self.request('/api/github/sync',dict(repository=REPO['full_name']))[0],200)
        self.service.github.thread.join(5)
        _,raw,_=self.request('/api/github/item?id=101');record=json.loads(raw)
        body=dict(id=101,revision=record['revision'],title='Synthetic task')
        self.assertEqual(self.request('/api/github/propose',body)[0],200)
        self.assertEqual(self.request('/api/github/propose',dict(body,revision='stale'))[0],409)
