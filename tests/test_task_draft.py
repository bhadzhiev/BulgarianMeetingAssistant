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

    def test_consent_settings_and_source_changes_invalidate_draft(self):
        with self.assertRaises(WorkItemConflict):task_draft.draft(self.s,self.body)
        approved=self.approved();self.s.settings['local_ai_max_tokens']+=1
        with self.assertRaises(WorkItemConflict):task_draft.draft(self.s,approved)
        approved=self.approved()
        def changed(*args,**kwargs):
            self.r.data['reports'][self.key]['analysis']['parts'].clear()
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
