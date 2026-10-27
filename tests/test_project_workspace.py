import tempfile
from pathlib import Path
import unittest
from app.service import MeetingService
from app.work_graph import WorkGraph
from app.work_items import WorkItemConflict
from tests.test_calendar import FakeGoogle
PROJECT=Path(__file__).resolve().parents[1]

class ProjectWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.s=MeetingService(Path(self.tmp.name)/'library',PROJECT,google=FakeGoogle(),backup_dir=Path(self.tmp.name)/'archives')
        self.addCleanup(self.s.close)
        self.a=self.s.create_project('Client A')['id'];self.b=self.s.create_project('Client B')['id']
    def question(self):
        return self.s.work_graph_action('question',dict(text='Who owns the rollout?'))
    def assign(self,item,ids):
        return self.s.work_graph_action('project',dict(id=item['id'],revision=item['revision'],project_ids=ids))
    def row(self,key):
        return next(i for i in self.s.item_list()['items'] if i['id']==key)
    def test_external_work_in_multiple_projects_without_duplication_or_status_change(self):
        graph=WorkGraph(self.s.items)
        for provider,kind in [('gmail','task'),('google_chat','decision'),('github','question')]:
            graph.ingest(dict(provider=provider,account='synthetic',external_id=provider,revision='1',text='Review backup configuration'),[dict(kind=kind,text='Review backups',quote='Review backup configuration',locator={})])
        for proposal in graph.snapshot()['proposals']:
            graph.review(proposal['id'],proposal['revision'],'accept')
        for item in list(self.s.item_list()['items']):
            self.assign(item,[self.a,self.b]);self.assertEqual(self.row(item['id'])['status'],'proposed' if item['kind']=='decision' else 'open')
        self.assertEqual(len(self.s.project_workspace(self.a)['items']),3)
        self.assertEqual(len(self.s.project_workspace(self.b)['items']),3)
        self.assertEqual(len(self.s.item_list()['items']),3)
    def test_inheritance_manual_override_and_return_to_inheritance(self):
        q=self.question();meeting=self.s.library.create('Sync','in_person',self.s.settings)
        self.s.set_scope(meeting['id'],{'id':self.a})
        def link(data):data['items'][q['id']]['links'].append(dict(meeting_id=meeting['id'],seen={}))
        WorkGraph(self.s.items)._write(link)
        self.assertEqual(self.row(q['id'])['effective_project_ids'],[self.a])
        self.assign(self.row(q['id']),[self.b]);self.s.set_scope(meeting['id'],None)
        self.assertEqual(self.row(q['id'])['effective_project_ids'],[self.b])
        self.assign(self.row(q['id']),[])
        self.assertIn(q['id'],[i['id'] for i in self.s.project_workspace('__none__')['items']])
        self.s.set_scope(meeting['id'],{'id':self.a});self.assign(self.row(q['id']),None)
        self.assertEqual(self.row(q['id'])['effective_project_ids'],[self.a])
    def test_stale_revision_and_invalid_project_are_rejected(self):
        q=self.question();self.assign(q,[self.a])
        with self.assertRaises(WorkItemConflict):self.assign(q,[self.b])
        with self.assertRaises(ValueError):self.assign(self.row(q['id']),['0'*12])
        self.assertEqual(self.row(q['id'])['effective_project_ids'],[self.a])
    def test_saved_membership_survives_reopen_and_question_edits(self):
        q=self.question();self.assign(q,[self.a])
        q=self.row(q['id']);self.s.work_graph_action('question',dict(id=q['id'],revision=q['revision'],answer='Maria'))
        self.s.items.data,self.s.items.revision=self.s.items.store.load()
        q=self.row(q['id']);self.assertEqual(q['effective_project_ids'],[self.a]);self.assertEqual(q['answer'],'Maria')
    def test_deleted_project_does_not_leave_invisible_work(self):
        q=self.question();self.assign(q,[self.a]);self.s.change_scope('projects',self.a,'delete')
        self.assertEqual(self.s.project_workspace('__none__')['items'][0]['id'],q['id'])
    def test_restore_remaps_project_membership_by_name(self):
        q=self.question();self.assign(q,[self.a]);archive=self.s.create_backup()['created']['name']
        target=MeetingService(Path(self.tmp.name)/'target',PROJECT,google=FakeGoogle(),backup_dir=self.s.backup_dir);self.addCleanup(target.close)
        replacement=target.create_project('Client A')['id'];target.restore_backup(archive)
        row=next(i for i in target.item_list()['items'] if i['id']==q['id'])
        self.assertEqual(row['effective_project_ids'],[replacement])
