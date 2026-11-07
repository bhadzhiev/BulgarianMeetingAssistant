import copy
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.prompts import Prompts,STAGES,POLICY,apply,validate_store
from app import prompt_lab,meeting_types,backup
from app.work_items import WorkItemConflict
from app.service import MeetingService
from tests import test_http

PROJECT=Path(__file__).resolve().parents[1]

class PromptStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.path=Path(self.tmp.name)/'ai-prompts.json';self.p=Prompts(self.path)
    def test_inheritance_reset_and_frozen_history(self):
        self.p.save('meeting_minutes','global','Global',0)
        self.p.save('meeting_minutes','type:daily','Daily',1)
        mid='a'*32;self.p.save('meeting_minutes','meeting:'+mid,'Personal',2)
        frozen=self.p.snapshot('daily',mid);self.assertEqual([v['text'] for v in frozen['stages']['meeting_minutes']['layers']],['Global','Daily','Personal'])
        self.p.save('meeting_minutes','meeting:'+mid,None,3)
        current=self.p.snapshot('daily',mid);self.assertNotEqual(current['id'],frozen['id']);self.assertIn('Personal',frozen['stages']['meeting_minutes']['effective']);self.assertNotIn('Personal',current['stages']['meeting_minutes']['effective'])
        self.assertEqual(Prompts(self.path).snapshot('daily',mid),current)
        self.assertIsNone(self.p.catalog()['entries']['meeting_minutes|meeting:'+mid]['history'][-1]['text'])
    def test_conflicting_edit_does_not_overwrite(self):
        self.p.save('meeting_minutes','global','First',0)
        for revision in [0,True,None]:
            with self.assertRaises(WorkItemConflict):self.p.save('meeting_minutes','global','Other',revision)
        self.assertEqual(self.p.snapshot()['stages']['meeting_minutes']['layers'][0]['text'],'First')
    def test_bounded_history_and_reset_version(self):
        for n in range(23):self.p.save('task_draft','global',str(n),n)
        self.assertEqual(len(self.p.catalog()['entries']['task_draft|global']['history']),20)
    def test_corrupt_store_is_preserved_and_not_silently_ignored(self):
        self.path.write_text('{bad');p=Prompts(self.path);self.assertTrue(p.catalog()['error'])
        with self.assertRaises(ValueError):p.snapshot()
        with self.assertRaises(ValueError):p.save('task_draft','global','Text',0)
        self.assertEqual(self.path.read_text(),'{bad')
    def test_invalid_archive_rows_fail_validation(self):
        for row in [dict(text='x',history=[]),dict(text='x',history=[None]),dict(text='x',history=[dict(at='now',revision=1,text='y')])]:
            with self.assertRaises(ValueError):validate_store(dict(version=1,revision=1,entries={'task_draft|global':row}))
    def test_apply_preserves_contract_sources_and_literal_placeholders(self):
        self.p.save('task_draft','global','Style {meeting_type}; {language}; {unknown}; {obj.secret}',0)
        source=[dict(role='system',content='Required'),dict(role='user',content='Untrusted source')];original=copy.deepcopy(source)
        result=apply(dict(_prompt_snapshot=self.p.snapshot()),source,'task_draft')
        self.assertEqual(source,original);self.assertEqual(result[-1],source[-1]);self.assertIn(POLICY,[v['content'] for v in result]);self.assertIn('{obj.secret}',result[1]['content']);self.assertIn('general',result[1]['content'])
        self.assertEqual(apply({},source,'task_draft'),source)
    def test_restore_merge_preserves_current_overrides(self):
        other=Path(self.tmp.name)/'other.json';q=Prompts(other);q.save('task_draft','global','Archived',0);q.save('meeting_title','global','Short',1)
        self.p.save('task_draft','global','Current',0);self.p.merge(other)
        self.assertEqual(self.p.snapshot()['stages']['task_draft']['layers'][0]['text'],'Current');self.assertEqual(self.p.snapshot()['stages']['meeting_title']['layers'][0]['text'],'Short')
    def test_backup_shared_file_is_allowed(self):
        self.assertIn('ai-prompts.json',backup.SHARED);self.assertIsNotNone(backup.MEMBER.fullmatch('ai-prompts.json'))


class PromptIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.s=MeetingService(Path(self.tmp.name)/'library',PROJECT);self.addCleanup(self.s.close);self.s.settings['summarizer']='local'
    def body(self,stage='task_draft',**kwargs):return dict(stage=stage,scope='global',text='Keep it concise.',revision=self.s.prompts.data['revision'],snippet='Проверяваме deployment-а утре.',**kwargs)
    def test_every_stage_previews_real_schema_and_source_without_sending(self):
        before=copy.deepcopy(self.s.items.data)
        with patch('meeting_assistant.post_json') as post:
            for stage in STAGES:
                result=prompt_lab.preview(self.s,self.body(stage))
                self.assertIn('required',result['schema']);self.assertIn('deployment',json.dumps(result['messages'],ensure_ascii=False));self.assertIn('Keep it concise.',json.dumps(result['messages']));self.assertNotIn('api_key',result['target']);self.assertEqual(result['target']['provider'],'local')
            post.assert_not_called()
        self.assertEqual(self.s.items.data,before);self.assertEqual(self.s.library.list(),[])
    def test_scope_is_validated_and_deleted_meeting_cannot_be_edited(self):
        for scope in ['type:missing','meeting:'+'a'*32,'global|bad']:
            with self.assertRaises((ValueError,FileNotFoundError)):prompt_lab.resolve(self.s,dict(self.body(),scope=scope))
        with self.assertRaises(ValueError):prompt_lab.resolve(self.s,dict(self.body(),scope='type:daily'))
    def test_source_and_prompt_changes_invalidate_approval(self):
        body=self.body();token=prompt_lab.preview(self.s,body)['preview_token'];self.s.prompts.save('task_draft','global','New',0)
        with self.assertRaises(WorkItemConflict):self.s.prompt_lab.start(dict(body,preview_token=token,approved=True))
        fresh=self.body();token=prompt_lab.preview(self.s,fresh)['preview_token']
        with self.assertRaises(WorkItemConflict):self.s.prompt_lab.start(dict(fresh,snippet='Different',preview_token=token,approved=True))
        self.s.settings['local_ai_model']='Changed'
        with self.assertRaises(WorkItemConflict):self.s.prompt_lab.start(dict(fresh,preview_token=token,approved=True))
    def test_lab_is_isolated_and_does_not_apply_results(self):
        before=copy.deepcopy(self.s.items.data);seen={}
        def run(action,directory,settings,*args,**kwargs):
            seen.update(action=action,directory=directory,settings=settings);return dict(result={'text':'A proposed task'})
        self.s.prompt_lab.runner=SimpleNamespace(run=run);body=self.body();token=prompt_lab.preview(self.s,body)['preview_token']
        job=self.s.prompt_lab.start(dict(body,preview_token=token,approved=True));self.s.prompt_lab.thread.join(3);status=self.s.prompt_lab.status(job['id'])
        self.assertFalse(status['running']);self.assertIsNone(status['error']);self.assertEqual(status['result']['text'],'A proposed task');self.assertFalse(seen['directory'].exists());self.assertEqual(self.s.items.data,before);self.assertEqual(self.s.library.list(),[])
    def test_test_is_refused_during_recording(self):
        self.s.active='a'*32
        try:
            body=self.body();token=prompt_lab.preview(self.s,body)['preview_token'];job=self.s.prompt_lab.start(dict(body,preview_token=token,approved=True));self.s.prompt_lab.thread.join(2)
            self.assertIn('Wait until',self.s.prompt_lab.status(job['id'])['error'])
        finally:self.s.active=None
    def test_safety_validation_rejects_changed_numbers_and_fabricated_quote(self):
        for stage,output in [('transcript_correction',dict(segments=[dict(id=0,text='Срокът е 20 дни.')])),('email_commitments',dict(tasks=[dict(text='Do it',quote='Fabricated',owner=None,deadline=None,due_date=None)]))]:
            settings=prompt_lab.preview(self.s,dict(self.body(stage),snippet='Срокът е 10 дни.'))['target']
            with patch('app.prompt_lab.complete_json',return_value=output),self.assertRaises(ValueError):prompt_lab.generate(settings)
    def test_all_local_calls_receive_saved_stage_instructions(self):
        from app.local_ai import complete_json
        for stage in STAGES:
            self.s.prompts.save(stage,'global','Unique '+stage,self.s.prompts.data['revision'])
            with patch('meeting_assistant.post_json',return_value=dict(choices=[dict(message=dict(content='{}'),finish_reason='stop')])) as post:
                complete_json(dict(self.s.settings,_prompt_snapshot=self.s.prompts.snapshot()),[dict(role='user',content='source')],{},stage)
                payload=post.call_args.args[1];self.assertIn('Unique '+stage,json.dumps(payload['messages']));self.assertIn(POLICY,json.dumps(payload['messages']))
    def test_meeting_context_uses_saved_custom_type(self):
        meeting=self.s.library.create('Meeting','imported',dict(self.s.settings));self.s.library.update(meeting['id'],meeting_type='daily')
        self.s.prompts.save('meeting_minutes','type:daily','Daily instructions',0)
        result=prompt_lab.resolve(self.s,dict(stage='meeting_minutes',scope='meeting:'+meeting['id']))[0]
        self.assertIn('Daily instructions',result['stages']['meeting_minutes']['effective'])
    def test_saved_snapshot_does_not_change_mid_job(self):
        meeting=self.s.library.create('Meeting','imported',dict(self.s.settings));directory=self.s.library.directory(meeting['id']);settings=dict(self.s.settings,_prompt_snapshot=self.s.prompts.snapshot('general',meeting['id']))
        self.s.prompts.save('meeting_minutes','global','New instructions',0)
        self.s.step_runner=SimpleNamespace(run=lambda *args,**kwargs:args[2])
        result=self.s._execute('summarize',directory,settings,lambda _:None)
        self.assertEqual(result['_prompt_snapshot'],settings['_prompt_snapshot']);self.assertNotIn('New instructions',json.dumps(result['_prompt_snapshot']));self.assertTrue((directory/'prompt-summarize.json').exists())

    def test_cloud_paths_receive_the_same_frozen_instructions(self):
        from app import correction,search
        from app.meeting_automation import generate_title
        from meeting_assistant import generate_minutes,TranscriptSegment
        from tests.test_local_ai import NOTES,response
        for stage in ('meeting_minutes','transcript_correction','meeting_title','meeting_answer'):
            self.s.prompts.save(stage,'global','Cloud '+stage,self.s.prompts.data['revision'])
        settings=dict(self.s.settings,summarizer='openai',title_provider='openai',transcript_correction='openai',_prompt_snapshot=self.s.prompts.snapshot())
        directory=self.s.library.root/'cloud-test';directory.mkdir();(directory/'transcript.json').write_text(json.dumps([dict(start=0,end=10,text='Иван ще изпрати оферта до петък.')]))
        operations=[('meeting_minutes',NOTES,lambda:generate_minutes(SimpleNamespace(**dict(settings,api_key='synthetic')), [TranscriptSegment(0,10,'Иван ще изпрати оферта до петък.')])),
            ('transcript_correction',dict(segments=[]),lambda:correction.ask(settings,[dict(role='user',content='text')],correction.schema(0),'synthetic')),
            ('meeting_title',dict(title='Оферта за новия сайт'),lambda:generate_title(directory,settings,'synthetic')),
            ('meeting_answer',dict(found=True,answer='Answer',sources=[1]),lambda:search.ai_answer(settings,'synthetic','Question',[dict(kind='transcript',meeting_title='Title',meeting_date='',text='Source')]))]
        for stage,output,operation in operations:
            with patch('meeting_assistant.post_json',return_value=response(output)) as post:
                operation();self.assertIn('Cloud '+stage,json.dumps(post.call_args.args[1]['messages']));self.assertIn(POLICY,json.dumps(post.call_args.args[1]['messages']))
    def test_unrelated_prompt_change_keeps_source_cache_keys(self):
        from app.prompts import select_stages
        before=select_stages(self.s.prompts.snapshot(),('repository_changes','repository_summary'))
        self.s.prompts.save('meeting_title','global','Unrelated',0)
        self.assertEqual(select_stages(self.s.prompts.snapshot(),('repository_changes','repository_summary')),before)
        self.s.prompts.save('repository_changes','global','Relevant',1)
        self.assertNotEqual(select_stages(self.s.prompts.snapshot(),('repository_changes','repository_summary')),before)
    def test_corrupt_store_can_be_recovered_from_verified_archive(self):
        path=self.s.library.root/'ai-prompts.json';path.write_text('{bad');self.s.prompts=Prompts(path)
        other=self.s.library.root/'restore.json';restored=Prompts(other);restored.save('task_draft','global','Recovered',0)
        self.s.prompts.merge(other)
        self.assertIsNone(self.s.prompts.error);self.assertEqual(self.s.prompts.snapshot()['stages']['task_draft']['layers'][0]['text'],'Recovered')
        self.assertEqual(next(path.parent.glob('ai-prompts.corrupt-*')).read_text(),'{bad')
    def test_archive_round_trip_includes_prompt_library(self):
        self.s.backup_dir=Path(self.tmp.name)/'archives';self.s.prompts.save('task_draft','global','Archived',0)
        result=self.s.create_backup();archive=self.s.backup_dir/result['created']['name']
        import tarfile
        with tarfile.open(archive) as handle:self.assertIn('ai-prompts.json',handle.getnames())
    def test_actual_saved_version_is_not_labelled_draft(self):
        self.s.prompts.save('task_draft','global','Saved',0)
        result=prompt_lab.resolve(self.s,dict(stage='task_draft',scope='global',text='Saved',revision=1))[0]
        self.assertEqual(result['stages']['task_draft']['layers'][0]['revision'],1)


class PromptHTTPTests(unittest.TestCase):
    setUp=test_http.HTTPTests.setUp
    tearDown=test_http.HTTPTests.tearDown
    request=test_http.HTTPTests.request
    def test_prompt_routes_use_session_and_cas(self):
        self.assertEqual(self.request('/api/prompts',headers={})[0],403)
        code,raw,_=self.request('/api/prompts');self.assertEqual(code,200);catalog=json.loads(raw);self.assertEqual(len(catalog['stages']),11)
        body=dict(stage='task_draft',scope='global',text='My instructions',revision=catalog['revision'])
        self.assertEqual(self.request('/api/prompts/save',body)[0],200)
        self.assertEqual(self.request('/api/prompts/save',body)[0],409)
        self.assertEqual(self.request('/api/prompts/save',dict(body,revision=1),headers=dict(self.headers,Origin='https://evil.example'))[0],403)
        self.assertEqual(self.request('/prompt-editor.js')[0],200)
    def test_builtin_copy_includes_all_sections(self):
        catalog=json.loads(self.request('/api/prompts')[1])
        for key,value in meeting_types.TYPES.items():
            template=catalog['builtin_templates'][key];self.assertEqual(len(template['sections']),len(value['sections']))
