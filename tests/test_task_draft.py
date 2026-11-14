import copy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app import task_draft
from app.work_items import WorkItemConflict
from tests import test_repo_reports as report_tests


class DraftTests(unittest.TestCase):
    finish=report_tests.ReportTests.finish
    collect=report_tests.ReportTests.collect
    analyze=report_tests.ReportTests.analyze
    def setUp(self):
        report_tests.ReportTests.setUp(self)
        self.collect();self.analyze()
        finding=next(iter(self.r.detail(self.key)['analysis']['parts'].values()))[0]
        self.body=dict(provider='report',id=self.key,finding_id=finding['id'])

    def approved(self):
        return dict(self.body,approved=True,preview_token=task_draft.preview(self.s,self.body)['preview_token'])

    def test_draft_is_not_persisted_and_edited_text_keeps_source_evidence(self):
        before=copy.deepcopy(self.s.items.data)
        runner=SimpleNamespace(run=lambda *args,**kwargs:dict(text='Review backup behavior and document the result.'))
        result=task_draft.draft(self.s,self.approved(),runner)
        self.assertEqual(self.s.items.data,before)
        self.assertEqual(self.s.tasks(),[])
        proposals=self.r.propose(self.key,self.body['finding_id'],'My edited task\nCheck backup recovery.')
        proposal=self.s.items.data['proposals'][proposals['proposals'][0]]
        self.assertEqual(proposal['text'],'My edited task\nCheck backup recovery.')
        self.assertEqual(self.s.tasks(),[])
        self.assertTrue(result['text'])

    def test_task_edit_preview_and_draft_use_the_polish_stage(self):
        body=dict(provider='task_edit',id='c'*32,text='Мигрирай базата',details='',completion_criteria='',context='')
        preview=task_draft.preview(self.s,body)
        self.assertEqual(set(preview['target']['_prompt_snapshot']['stages']),{'task_polish'})
        seen={}
        def run(action,directory,settings,progress,key,cancel=None):
            seen.update(action=action,source=settings['task_draft_source'],stages=set(settings['_prompt_snapshot']['stages']))
            return dict(text='Провери миграцията на базата',details='Предложение: staging първо.',completion_criteria='')
        before=copy.deepcopy(self.s.items.data)
        result=task_draft.draft(self.s,dict(body,approved=True,preview_token=preview['preview_token']),SimpleNamespace(run=run))
        self.assertEqual(seen['action'],'task_draft');self.assertIs(seen['source']['polish'],True);self.assertEqual(seen['stages'],{'task_polish'})
        self.assertEqual(result['text'],'Провери миграцията на базата');self.assertEqual(self.s.items.data,before)
        with self.assertRaises(WorkItemConflict):
            task_draft.draft(self.s,dict(body,text='Друга карта',approved=True,preview_token=preview['preview_token']),SimpleNamespace(run=run))

    def test_consent_settings_and_source_changes_invalidate_draft(self):
        with self.assertRaises(WorkItemConflict):task_draft.draft(self.s,self.body)
        approved=self.approved();self.s.settings['local_ai_max_tokens']+=1
        with self.assertRaises(WorkItemConflict):task_draft.draft(self.s,approved)
        approved=self.approved()
        def changed(*args,**kwargs):
            self.r.data['reports'][self.key]['analysis']['parts'].clear()
            self.r.data['reports'][self.key]['analysis'].pop('summary',None)
            return dict(text='Draft')
        with self.assertRaises(ValueError):task_draft.draft(self.s,approved,SimpleNamespace(run=changed))
        self.assertTrue(self.s.processing_slot.acquire(blocking=False));self.s.processing_slot.release()
        self.assertEqual(self.s.tasks(),[])

    def test_recording_blocks_generation(self):
        approved=self.approved();self.s.active='recording'
        try:
            with self.assertRaises(ValueError):task_draft.draft(self.s,approved)
        finally:self.s.active=None

    def test_bad_model_output_is_not_saved(self):
        for output in [dict(text=''),dict(text='x'*1001),dict(text='Task',unexpected=True)]:
            with patch('app.task_draft.complete_json',return_value=output):
                with self.assertRaises(ValueError):task_draft.generate(dict(body='Source'),{})

    def test_task_edit_snapshot_is_the_current_card_and_needs_text(self):
        body=dict(provider='task_edit',id='a'*32,text='  Мигрирай базата към v2  ',details='текущ контекст',completion_criteria='',context='Project goal: по-лесен sync')
        source=task_draft.snapshot(None,body)
        self.assertTrue(source['polish'])
        self.assertEqual(json.loads(source['body']),dict(text='Мигрирай базата към v2',details='текущ контекст',context='Project goal: по-лесен sync'))
        with self.assertRaisesRegex(ValueError,'title or a description'):task_draft.snapshot(None,dict(body,text='  ',details=''))
        with self.assertRaisesRegex(ValueError,'capture ID'):task_draft.snapshot(None,dict(body,id='short'))
        with self.assertRaises(ValueError):task_draft.snapshot(None,dict(body,context='дума ' * 500))

    def test_task_edit_uses_the_polish_prompt_and_stage(self):
        seen={}
        def fake(settings,messages,schema,name,timeout=0,api_key='',max_tokens=None):
            seen.update(name=name,system=messages[0]['content'],max_tokens=max_tokens);return dict(text='Провери sync грешките',details='',completion_criteria='')
        with patch('app.task_draft.complete_json',side_effect=fake):
            result=task_draft.generate(dict(body='{}',polish=True),{})
        self.assertEqual(seen['name'],'task_polish');self.assertEqual(seen['system'],task_draft.POLISH_SYSTEM)
        self.assertEqual(seen['max_tokens'],2048,'a short rewrite does not wait for the full output budget')
        self.assertEqual(result['text'],'Провери sync грешките')
        with patch('app.task_draft.complete_json',side_effect=fake):
            task_draft.generate(dict(body='{}'),{})
        self.assertEqual(seen['name'],'task_draft');self.assertEqual(seen['system'],task_draft.SYSTEM)
        self.assertIs(seen['max_tokens'],None,'a draft keeps the settings output budget')

    def test_task_edit_never_creates_a_task(self):
        with self.assertRaisesRegex(ValueError,'never creates'):task_draft.create(None,dict(provider='task_edit'))

    def test_github_snapshot_rejects_stale_revision_and_unavailable_source(self):
        record=dict(available=True,revision='current',title='Issue',body='Requested change')
        self.addCleanup(patch.stopall)
        patch.object(self.s.github,'_account',return_value='1').start()
        patch.object(self.s.github,'detail',side_effect=lambda *args,**kwargs:record).start()
        body=dict(provider='github',id=42,revision='old')
        with self.assertRaises(WorkItemConflict):task_draft.snapshot(self.s,body)
        body['revision']='current';self.assertEqual(task_draft.snapshot(self.s,body)['body'],'Requested change')
        record['available']=False
        with self.assertRaises(ValueError):task_draft.snapshot(self.s,body)

    def test_confirmed_creation_uses_edited_text_and_retry_does_not_duplicate(self):
        body=dict(self.approved(),title='Edited task: verify recovery and record results.')
        first=task_draft.create(self.s,body)
        self.assertEqual(len(self.s.tasks()),1)
        self.assertEqual(self.s.tasks()[0]['text'],body['title'])
        self.assertEqual(task_draft.create(self.s,body),first)
        self.assertEqual(len(self.s.tasks()),1)


from tests import test_http, test_github_source


class DraftHTTPTests(unittest.TestCase):
    setUp=test_http.HTTPTests.setUp
    tearDown=test_http.HTTPTests.tearDown
    request=test_http.HTTPTests.request

    def test_editor_confirmation_creates_only_the_edited_local_task(self):
        self.service.github.connection=test_github_source.FakeGitHub()
        self.service.settings.update(summarizer='local',local_ai_model='synthetic')
        self.request('/api/github/sync',dict(repository=test_github_source.REPO['full_name']))
        self.service.github.thread.join(5)
        record=self.service.github.detail(101)
        body=dict(provider='github',id=101,revision=record['revision'])
        self.assertEqual(self.request('/api/task-draft/preview',body,headers={})[0],403)
        status,raw,_=self.request('/api/task-draft/preview',body)
        self.assertEqual(status,200);preview=json.loads(raw)
        self.assertEqual(self.service.tasks(),[])
        status,_,_=self.request('/api/task-draft/generate',body)
        self.assertEqual(status,409)
        status,_,_=self.request('/api/task-draft/create',dict(body,preview_token=preview['preview_token'],title='Edited task from source'))
        self.assertEqual(status,200)
        self.assertEqual(self.service.tasks()[0]['text'],'Edited task from source')
