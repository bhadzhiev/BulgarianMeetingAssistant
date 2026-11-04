import copy
from contextlib import closing
from pathlib import Path
import tempfile
import threading
import unittest
from app.github_source import GitHubError, GitHubSync
from tests.test_github_source import FakeGitHub, REPO


def repo(n):return dict(id=1000+n,full_name=f'example/repository-{n:03}',private=True,has_issues=True)

class RepositoryCatalogTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.connection=FakeGitHub();self.connection.lock=threading.RLock();self.connection.generation=0
        self.sync=GitHubSync(Path(tmp.name),self.connection);self.addCleanup(self.sync.close)
        self.pages={1:[repo(n) for n in range(100)],2:[repo(n) for n in range(100,145)]}
        self.connection.handler=self.handle
    def handle(self,path,query):
        self.assertEqual(path,'/user/repos')
        page=query['page'];return dict(data=copy.deepcopy(self.pages[page]),has_next=page<max(self.pages))
    def refresh(self):
        self.sync.start_repositories();self.sync.thread.join(3);self.assertFalse(self.sync.thread.is_alive())
        return self.sync.repository_status()
    def test_all_pages_and_affiliations_with_no_issue_dependency(self):
        result=self.refresh();self.assertEqual(len(result['repositories']),145);self.assertTrue(result['complete']);self.assertTrue(result['current'])
        self.assertEqual([query['page'] for _,query,_ in self.connection.calls],[1,2])
        query=self.connection.calls[0][1];self.assertEqual(query['per_page'],100);self.assertEqual(query['visibility'],'all')
        self.assertEqual(query['affiliation'],'owner,collaborator,organization_member')
        self.assertTrue(all(account=='1' for _,_,account in self.connection.calls))
    def test_complete_access_snapshot_drops_revoked_and_never_merges_issue_cache_back(self):
        self.refresh();self.pages={1:[repo(9)]};self.refresh()
        with closing(self.sync.db()) as db,db:
            import json
            db.execute('INSERT INTO repos VALUES (?,?,?)',('1',REPO['id'],json.dumps(REPO)))
        self.assertEqual([r['id'] for r in self.sync.repos()],[repo(9)['id']])
        self.pages={1:[]};self.refresh();self.assertEqual(self.sync.repos(),[])
    def test_failed_page_keeps_previous_complete_snapshot(self):
        previous=self.refresh();self.pages={1:[repo(200)] ,2:[]}
        def fail(path,query):
            if query['page']==2:raise GitHubError('rate limited')
            return dict(data=[repo(200)],has_next=True)
        self.connection.handler=fail;result=self.refresh()
        self.assertEqual(result['repositories'],previous['repositories']);self.assertEqual(result['checked_at'],previous['checked_at'])
        self.assertIn('rate limited',result['job']['error'])
    def test_token_rotation_same_user_discards_incomplete_access_listing(self):
        previous=self.refresh()
        def rotate(path,query):
            self.connection.generation+=1;return dict(data=[repo(201)],has_next=True)
        self.connection.handler=rotate;result=self.refresh()
        self.assertEqual(result['repositories'],previous['repositories']);self.assertFalse(result['current'])
        self.assertIn('credentials changed',result['job']['error'])
    def test_account_change_cannot_publish_old_users_catalog_under_new_account(self):
        self.refresh()
        def change(path,query):
            self.connection.account='2';return dict(data=[repo(201)],has_next=False)
        self.connection.handler=change;result=self.refresh()
        self.assertEqual(result['repositories'],[]);self.assertFalse(result['complete']);self.assertTrue(result['job']['error'])
        self.connection.account='1';self.assertEqual(len(self.sync.repos()),145)
    def test_invalid_page_does_not_replace_previous_snapshot(self):
        previous=self.refresh();self.pages={1:[dict(id=True,full_name='example/not-valid')]}
        result=self.refresh();self.assertEqual(result['repositories'],previous['repositories']);self.assertTrue(result['job']['error'])
    def test_clear_removes_discovery_snapshot_and_cached_repository_choices(self):
        self.refresh();self.sync.clear('1');self.assertFalse(self.sync.repository_status()['complete']);self.assertEqual(self.sync.repos(),[])
    def test_recording_priority_prevents_start(self):
        self.sync.priority=lambda:True
        with self.assertRaisesRegex(ValueError,'Stop recording'):self.sync.start_repositories()

    def test_status_does_not_wait_for_a_slow_network_request_holding_credentials(self):
        completed=threading.Event();errors=[]
        def read():
            try:self.sync.repository_status()
            except Exception as exc:errors.append(exc)
            finally:completed.set()
        with self.connection.lock:
            worker=threading.Thread(target=read);worker.start();responsive=completed.wait(1)
        worker.join(3)
        self.assertTrue(responsive,'Status blocked behind GitHub network I/O');self.assertEqual(errors,[])
