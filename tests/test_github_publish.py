import socket
import tempfile
import unittest
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from threading import RLock
from app.github_publish import Publisher
from app.work_items import WorkItemConflict

class PublishTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.remote={};self.posts=0;self.links=[];self.text='Task'
        def get(path,query=None,expected_account=None):
            if path=='/user':data=dict(id=1,login='test')
            elif path=='/repos/test/repo':data=dict(id=2,full_name='test/repo')
            else:data=self.remote[path]
            return dict(data=data)
        conn=SimpleNamespace(lock=RLock(),get=get,_load=lambda:dict(token='test-only'))
        self.service=SimpleNamespace(github=SimpleNamespace(connection=conn),items=SimpleNamespace(store=SimpleNamespace(path=Path(self.tmp.name)/'work.sqlite3')),github_links=SimpleNamespace(link=lambda *a:self.links.append(a)))
        self.service._resource=lambda resource:dict(target=resource,text=self.text)
        self.publisher=Publisher(self.service,self.write)
    def write(self,path,payload,token):
        self.posts+=1
        result=dict(id=42,number=7,body=payload['body'])
        self.remote['/repos/test/repo/issues/7']=result
        return result
    def preview(self):
        return self.publisher.preview(dict(resource=dict(kind='item',id='a'),repository='test/repo',format='issue',title='Title',body='Text'))['operation']
    def test_create_verify_and_double_click_make_one_post(self):
        op=self.preview();result=self.publisher.publish(op['id'],'test/repo')
        self.assertEqual(result['state'],'verified');self.assertTrue(self.links)
        self.publisher.publish(op['id'],'test/repo');self.assertEqual(self.posts,1)
    def test_lost_response_blocks_retry_even_if_draft_changes(self):
        def timeout(*args):self.write(*args);raise TimeoutError()
        self.publisher.write=timeout
        op=self.preview();self.assertEqual(self.publisher.publish(op['id'],'test/repo')['state'],'unknown')
        self.publisher.publish(op['id'],'test/repo');self.assertEqual(self.posts,1)
        self.text='Edited task'
        with self.assertRaises(WorkItemConflict):self.preview()
    def test_changed_resource_prevents_post(self):
        op=self.preview();self.text='Edited'
        with self.assertRaises(WorkItemConflict):self.publisher.publish(op['id'],'test/repo')
        self.assertEqual(self.posts,0)

    def test_reconciliation_finds_remote_creation_without_second_post(self):
        def timeout(*args):self.write(*args);raise TimeoutError()
        self.publisher.write=timeout
        op=self.preview();self.publisher.publish(op['id'],'test/repo')
        created=self.remote['/repos/test/repo/issues/7'];created['user']={'id':1}
        original=self.publisher.connection.get
        def get(path,query=None,expected_account=None):
            if path=='/repos/test/repo/issues':return dict(data=[created],has_next=False)
            return original(path,query,expected_account)
        self.publisher.connection.get=get
        result=self.publisher.reconcile(op['id'],'test/repo')
        self.assertEqual(result['state'],'verified');self.assertEqual(self.posts,1)

    def test_edited_draft_after_an_unsent_preview_gets_a_new_preview(self):
        first=self.preview();self.text='Edited task'
        second=self.preview();self.assertNotEqual(first['id'],second['id'])
        self.assertEqual(self.publisher.publish(second['id'],'test/repo')['state'],'verified')
        self.assertEqual(self.publisher.publish(first['id'],'test/repo')['state'],'cancelled');self.assertEqual(self.posts,1)

    def test_refused_request_fails_and_allows_a_new_attempt(self):
        def refused(*args):raise urllib.error.HTTPError('https://api.github.com',403,'Forbidden',{},None)
        self.publisher.write=refused
        op=self.preview();result=self.publisher.publish(op['id'],'test/repo')
        self.assertEqual(result['state'],'failed');self.assertEqual(result['result']['status'],403)
        self.publisher.write=self.write
        again=self.preview();self.assertNotEqual(again['id'],op['id'])
        self.assertEqual(self.publisher.publish(again['id'],'test/repo')['state'],'verified');self.assertEqual(self.posts,1)

    def test_offline_fails_without_retry(self):
        def offline(*args):raise urllib.error.URLError(socket.gaierror(8,'nodename nor servname provided'))
        self.publisher.write=offline
        op=self.preview();result=self.publisher.publish(op['id'],'test/repo')
        self.assertEqual(result['state'],'failed');self.assertTrue(result['result']['offline'])
        self.assertEqual(self.publisher.publish(op['id'],'test/repo')['state'],'failed');self.assertEqual(self.posts,0)

    def test_server_error_stays_unknown(self):
        def broken(*args):raise urllib.error.HTTPError('https://api.github.com',502,'Bad Gateway',{},None)
        self.publisher.write=broken
        self.assertEqual(self.publisher.publish(self.preview()['id'],'test/repo')['state'],'unknown')

    def test_person_can_abandon_only_after_a_complete_empty_check(self):
        def timeout(*args):raise TimeoutError()
        self.publisher.write=timeout
        op=self.preview();self.publisher.publish(op['id'],'test/repo')
        with self.assertRaises(ValueError):self.publisher.abandon(op['id'])
        original=self.publisher.connection.get
        def get(path,query=None,expected_account=None):
            if path=='/repos/test/repo/issues':return dict(data=[],has_next=False)
            return original(path,query,expected_account)
        self.publisher.connection.get=get
        checked=self.publisher.reconcile(op['id'],'test/repo')
        self.assertEqual(checked['state'],'unknown');self.assertEqual(checked['result']['last_check']['matches'],0)
        self.assertEqual(self.publisher.abandon(op['id'])['state'],'abandoned')
        self.publisher.write=self.write
        self.assertEqual(self.publisher.publish(self.preview()['id'],'test/repo')['state'],'verified');self.assertEqual(self.posts,1)
