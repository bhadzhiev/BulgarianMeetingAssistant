import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from app.service import MeetingService
from app.storage import atomic_json,Library
from app.work_graph import WorkGraph
from app.work_items import WorkItemConflict
from app.conversations import scope_revision,transcript_revision
from tests.test_calendar import FakeGoogle
PROJECT=Path(__file__).resolve().parents[1]

class ConversationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.s=MeetingService(self.root/'library',PROJECT,google=FakeGoogle(),backup_dir=self.root/'archives');self.addCleanup(self.s.close)
        self.p=self.s.create_project('Atlas')['id'];self.other=self.s.create_project('Other')['id']
        self.m=self.s.library.create('Planning','in_person',self.s.settings)
        self.s.library.update(self.m['id'],created='2026-10-25T22:30:00Z',status='ready')
        self.rows=[dict(start=0,end=10,speaker='Maria',text='Review the VPN rollout.'),dict(start=12,end=20,speaker='Ivan',text='Use a staged rollout.'),dict(start=22,end=30,speaker='Maria',text='Check the backup.')]
        atomic_json(self.s.library.directory(self.m['id'])/'transcript.json',self.rows)
    def excerpt(self,**extra):
        return self.s.conversations.attach(dict(provider='excerpt',meeting_id=self.m['id'],transcript_revision=transcript_revision(self.rows),first=0,last=1,project_ids=[self.p],**extra))
    def test_search_filters_use_transcript_participants_and_sofia_dates(self):
        result=self.s.conversations.listing(dict(q='VPN',participant='Maria',**{'from':'2026-10-26','to':'2026-10-26'}))
        self.assertEqual(result['total'],1);self.assertNotIn('text',result['rows'][0])
        self.assertEqual(self.s.conversations.listing(dict(participant='Missing'))['total'],0)
        self.rows[0]['speaker']='Elena';atomic_json(self.s.library.directory(self.m['id'])/'transcript.json',self.rows)
        self.assertIn('Elena',self.s.conversations.listing({})['participants'])
    def test_bulk_is_prevalidated_and_protects_manual_item_projects(self):
        q=self.s.work_graph_action('question',dict(text='Who owns rollout?'))
        self.s.work_graph_action('project',dict(id=q['id'],revision=q['revision'],project_ids=[self.other]))
        m=self.s.library.get(self.m['id']);entry=dict(id=m['id'],revision=scope_revision(m))
        with self.assertRaises(WorkItemConflict):self.s.conversations.bulk(dict(meetings=[dict(entry,revision='stale')],project_id=self.p))
        self.assertIsNone(self.s.library.get(m['id']).get('project_id'))
        self.s.conversations.bulk(dict(meetings=[entry],project_id=self.p))
        self.assertEqual(self.s.library.get(m['id'])['project_id'],self.p)
        self.assertEqual(self.s.item_list()['items'][0]['effective_project_ids'],[self.other])
    def test_interrupted_batch_finishes_on_library_reopen(self):
        changes=[dict(id=self.m['id'],project_id=self.p,series_id=None)]
        atomic_json(self.s.library.root/'.scope-batch.json',changes)
        library=Library(self.s.library.root)
        self.assertEqual(library.get(self.m['id'])['project_id'],self.p)
        self.assertFalse((library.root/'.scope-batch.json').exists())
    def test_excerpt_pins_text_and_marks_stale_after_edit_without_copying_audio(self):
        saved=self.excerpt();self.assertIn('VPN',saved['text']);self.assertNotIn('backup',saved['text'])
        self.rows[0]['text']='Changed';atomic_json(self.s.library.directory(self.m['id'])/'transcript.json',self.rows)
        old=self.s.conversations.attachment(saved['id']);self.assertTrue(old['stale']);self.assertIn('VPN',old['text'])
        self.assertEqual(list(self.s.library.root.glob('*/recording.wav')),[])
    def test_excerpt_range_and_changed_transcript_are_checked(self):
        saved=self.s.conversations.attach(dict(provider='excerpt',meeting_id=self.m['id'],transcript_revision=transcript_revision(self.rows),range=[11,21],project_ids=[self.p]))
        self.assertNotIn('VPN',saved['text']);self.assertIn('staged',saved['text'])
        with self.assertRaises(WorkItemConflict):self.s.conversations.attach(dict(provider='excerpt',meeting_id=self.m['id'],transcript_revision='stale',first=0,last=0,project_ids=[self.p]))
    def test_whole_email_attachment_needs_no_task_or_ai_and_checks_revision(self):
        row=dict(provider='gmail',external_id='thread',account='synthetic',title='Release',date='2026-10-26T10:00:00Z',participants=['Maria'],revision='v1',text='Review rollout',partial=False)
        body=dict(provider='gmail',external_id='thread',account='synthetic',revision='v1',project_ids=[self.p])
        with patch.object(self.s.conversations,'_external',return_value=row):
            saved=self.s.conversations.attach(body)
            with self.assertRaises(WorkItemConflict):self.s.conversations.attach(dict(body,revision='old'))
        self.assertEqual(self.s.item_list()['items'],[]);self.assertEqual(WorkGraph(self.s.items).snapshot()['proposals'],[])
        self.assertEqual(self.s.project_workspace(self.p)['conversations'][0]['id'],saved['id'])
        with self.assertRaises(WorkItemConflict):self.s.conversations.assign(dict(id=saved['id'],revision=99,project_ids=[self.other]))
    def test_archive_remaps_excerpt_project_and_preserves_snapshot(self):
        saved=self.excerpt();name=self.s.create_backup()['created']['name']
        target=MeetingService(self.root/'target',PROJECT,google=FakeGoogle(),backup_dir=self.s.backup_dir);self.addCleanup(target.close)
        p=target.create_project('Atlas')['id'];target.restore_backup(name)
        restored=target.conversations.attachment(saved['id']);self.assertEqual(restored['project_ids'],[p]);self.assertEqual(restored['text'],saved['text'])
    def test_disconnected_sources_do_not_break_meeting_browser(self):
        result=self.s.conversations.listing(dict(source='all'));self.assertEqual(result['total'],1);self.assertTrue(result['notices'])
    def test_reader_gets_the_current_revision_and_existing_projects_without_text(self):
        row=dict(provider='gmail',external_id='thread',account='synthetic',title='Release',date='2026-10-26T10:00:00Z',participants=['Maria'],revision='v1',text='Review rollout',partial=False)
        with patch.object(self.s.conversations,'_external',return_value=row):
            fresh=self.s.conversations.external('gmail','thread')
            self.assertEqual((fresh['revision'],fresh['project_ids'],fresh['attachment_id']),('v1',[],None));self.assertNotIn('text',fresh)
            saved=self.s.conversations.attach(dict(provider='gmail',external_id='thread',account=fresh['account'],revision=fresh['revision'],project_ids=[self.p]))
            again=self.s.conversations.external('gmail','thread')
        self.assertEqual((again['attachment_id'],again['attachment_revision'],again['project_ids']),(saved['id'],1,[self.p]))
    def test_account_switch_is_rejected_before_attaching_email(self):
        with patch.object(self.s.gmail,'_account',return_value='other'):
            with self.assertRaises(WorkItemConflict):self.s.conversations.attach(dict(provider='gmail',external_id='thread',account='old',revision='v1',project_ids=[self.p]))
        self.assertEqual(self.s.conversations.attachments(),[])
    def test_chat_snapshot_checks_account_after_cache_read(self):
        messages=[dict(name='spaces/demo/messages/1',sender='Ivan',date=1793060000,available=True,body='Review the checklist')]
        with patch.object(self.s.chat,'_account',side_effect=['one','two']),patch.object(self.s.chat,'spaces',return_value=[dict(name='spaces/demo',label='Release')]),patch.object(self.s.chat,'conversation',return_value=messages):
            with self.assertRaises(WorkItemConflict):self.s.conversations.attach(dict(provider='google_chat',external_id='spaces/demo',account='one',revision='v1',project_ids=[self.p]))
        self.assertEqual(self.s.conversations.attachments(),[])
    def test_pagination_does_not_drop_or_repeat_meetings(self):
        for n in range(51):self.s.library.create('Meeting '+str(n),'in_person',self.s.settings)
        first=self.s.conversations.listing({});second=self.s.conversations.listing(dict(offset='50'))
        self.assertEqual(first['total'],52);self.assertEqual(len(first['rows']),50);self.assertEqual(len(second['rows']),2)
        self.assertFalse({r['id'] for r in first['rows']} & {r['id'] for r in second['rows']})
    def test_active_meeting_is_not_moved(self):
        self.s.active=self.m['id']
        try:
            with self.assertRaises(ValueError):self.s.conversations.bulk(dict(meetings=[dict(id=self.m['id'],revision=scope_revision(self.s.library.get(self.m['id'])))],project_id=self.p))
        finally:self.s.active=None
        self.assertIsNone(self.s.library.get(self.m['id']).get('project_id'))
    def test_partial_batch_write_is_recovered_as_one_intent(self):
        second=self.s.library.create('Second','in_person',self.s.settings)
        changes=[dict(id=key,project_id=self.p,series_id=None) for key in (self.m['id'],second['id'])]
        from app import storage
        original=storage.atomic_json
        def fail_second(path,value):
            if path.name=='meeting.json' and path.parent.name==second['id']:raise OSError('synthetic disk interruption')
            return original(path,value)
        with patch('app.storage.atomic_json',side_effect=fail_second):
            with self.assertRaises(OSError):self.s.library.assign_scopes(changes)
        recovered=Library(self.s.library.root)
        self.assertEqual([recovered.get(c['id'])['project_id'] for c in changes],[self.p,self.p])
    def test_regular_work_refresh_does_not_include_conversation_bodies(self):
        self.excerpt();graph=self.s.item_list()['graph']
        self.assertTrue(graph['conversation_links'])
        for revision in graph['source_revisions']:self.assertNotIn('text',revision)
        self.assertIn('VPN',self.s.conversations.attachment(graph['conversation_links'][0]['id'])['text'])

class TraceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.s=MeetingService(Path(self.tmp.name),PROJECT,google=FakeGoogle());self.addCleanup(self.s.close)
        self.p=self.s.create_project('Atlas')['id']
        m=self.s.library.create('Planning','in_person',self.s.settings)
        self.s.library.update(m['id'],created='2026-10-20T08:00:00Z',status='ready',duration=40,project_id=self.p)
        self.rows=[dict(start=0,end=10,speaker='Maria',text='Review the VPN rollout.'),dict(start=12,end=20,speaker='Ivan',text='We use a staged rollout.'),dict(start=22,end=30,speaker='Maria',text='Check the backup.')]
        atomic_json(self.s.library.directory(m['id'])/'transcript.json',self.rows);self.meeting=m['id']
        self.s.edit(m['id'],dict(minutes=dict(summary=[],tasks=[],open_questions=[],decisions=[dict(text='Staged VPN rollout',evidence_timestamp='00:00:12',review='verified')])))
        self.decision=next(i for i in self.s.item_list()['items'] if i['kind']=='decision')
        self.excerpt=self.s.conversations.attach(dict(provider='excerpt',meeting_id=m['id'],transcript_revision=transcript_revision(self.rows),range=[11,21],project_ids=[self.p]))
        graph=WorkGraph(self.s.items)
        def remote(data,result):data['sources'][result['source_id']]['remote']=dict(authority='github',kind='pull_request',repository='synthetic/infra',number=7,state='merged',fetched_at=1793000000)
        result=graph.ingest(dict(provider='github',account='github.com:1',external_id='issue:701',revision='r1',text='synthetic/infra #7: Roll out the VPN in stages'),[dict(kind='task',text='Roll out the VPN in stages',quote='Roll out the VPN in stages')],after=remote)
        proposal=self.s.items.data['proposals'][result['proposals'][0]]
        accepted=graph.review(proposal['id'],proposal['revision'],'accept')['result_id']
        self.task=next(i for i in self.s.item_list()['items'] if i['id']==accepted)
        self.s.work_graph_action('project',dict(id=self.task['id'],revision=self.task['revision'],project_ids=[self.p]))
    def relate(self):
        items={i['id']:i for i in self.s.item_list()['items']}
        self.s.work_graph_action('relate',dict(from_id=self.task['id'],to_id=self.decision['id'],kind='implements',from_revision=items[self.task['id']]['revision'],to_revision=items[self.decision['id']]['revision']))
    def report(self):
        self.s.repo_reports.data=dict(version=1,reports={'a'*32:dict(id='a'*32,account='1',repository='synthetic/infra',meeting_id=None,
            changes={'pr:7':dict(id='pr:7',label='PR #7: Staged VPN rollout',url='https://github.com/synthetic/infra/pull/7',sha='b'*40,kind='pull_request',date='2026-10-22T09:00:00Z'),
                     'pr:8':dict(id='pr:8',label='PR #8: Unrelated',url='https://github.com/synthetic/infra/pull/8',sha='c'*40,kind='pull_request',date='2026-10-23T09:00:00Z')})})
    def chain(self):
        timeline=self.s.project_workspace(self.p)['timeline']
        return timeline,next(c for c in timeline['chains'] if any(n['ref'].get('item_id')==self.task['id'] for n in c['stages']['task']))
    def test_saved_relationship_joins_conversation_decision_task_pr_and_code_change(self):
        self.relate();self.report()
        with patch.object(self.s.repo_reports,'account',return_value='1'):timeline,chain=self.chain()
        stages=chain['stages']
        self.assertEqual([n['ref'].get('meeting_id') for n in stages['conversation'] if n['kind']=='meeting'],[self.meeting])
        self.assertIn(self.excerpt['id'],[n['ref'].get('attachment_id') for n in stages['conversation']])
        excerpt=next(n for n in stages['conversation'] if n['ref'].get('attachment_id')==self.excerpt['id'])
        self.assertEqual((excerpt['ref']['meeting_id'],excerpt['ref']['start'],excerpt['ref']['end']),(self.meeting,12,20))
        moment=next(e for e in timeline['events'] if e.get('attachment_id')==self.excerpt['id'])
        self.assertEqual((moment['meeting_id'],moment['start'],moment['end']),(self.meeting,12,20))
        self.assertEqual([n['ref']['item_id'] for n in stages['decision']],[self.decision['id']])
        self.assertEqual([(n['kind'],n['ref']['number']) for n in stages['github']],[('pull_request',7)])
        self.assertEqual([n['ref']['url'] for n in stages['code']],['https://github.com/synthetic/infra/pull/7'])
        self.assertEqual(chain['complete'],5);self.assertEqual(chain['relationships'][0]['kind'],'implements')
        self.assertIn('https://github.com/synthetic/infra/pull/7',[e.get('url') for e in timeline['events'] if e['kind']=='code'])
        self.assertNotIn('https://github.com/synthetic/infra/pull/8',[e.get('url') for e in timeline['events']])
    def test_meetings_say_whether_a_recording_can_play(self):
        self.assertFalse(self.s.snapshot()['meetings'][0]['has_audio']);self.assertFalse(self.s.item_list()['meetings'][self.meeting]['has_audio'])
        (self.s.library.directory(self.meeting)/'recording.wav').write_bytes(b'RIFF'+bytes(40))
        self.assertTrue(self.s.snapshot()['meetings'][0]['has_audio']);self.assertTrue(self.s.item_list()['meetings'][self.meeting]['has_audio'])
        self.s.active=self.meeting
        try:self.assertFalse(self.s.item_list()['meetings'][self.meeting]['has_audio'])
        finally:self.s.active=None
    def test_without_a_saved_relationship_similar_items_stay_in_separate_chains(self):
        self.report()
        with patch.object(self.s.repo_reports,'account',return_value='1'):timeline,chain=self.chain()
        self.assertEqual(chain['stages']['decision'],[])
        self.assertEqual(chain['stages']['conversation'],[])
        decision=next(c for c in timeline['chains'] if c['stages']['decision'])
        self.assertEqual(decision['stages']['task'],[])
    def test_code_changes_of_another_github_account_are_not_shown(self):
        self.relate();self.report()
        with patch.object(self.s.repo_reports,'account',return_value='2'):_,chain=self.chain()
        self.assertEqual(chain['stages']['code'],[])
        _,chain=self.chain()
        self.assertEqual(chain['stages']['code'],[])
