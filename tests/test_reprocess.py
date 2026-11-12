import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from app import reprocess
from app.service import MeetingService
from app.storage import atomic_json
from app.work_items import WorkItemConflict
from tests.test_calendar import FakeGoogle
from tests.test_app import wait_for
from tests.ai_meeting_tasks import setUpModule, tearDownModule  # noqa: F401  AI meeting tasks are on in these tests

PROJECT=Path(__file__).resolve().parents[1]

class ReprocessTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.s=MeetingService(Path(self.tmp.name),PROJECT,google=FakeGoogle());self.addCleanup(self.s.close)
        self.s.settings.update(auto_process=False,auto_title=False,summarizer='local',transcript_correction='local',diarization_enabled=False)
        self.s._run_analytics=lambda *a,**k:None
        self.m=self.s.import_transcript('[00:00:00] Иван: Проверяваме deployment.','test.txt');self.mid=self.m['id'];self.directory=self.s.library.directory(self.mid)
    def preview(self,action='notes'):return reprocess.preview(self.s,dict(meetings=[self.mid],action=action))
    def test_candidates_and_preview_never_start_ai(self):
        with patch.object(self.s,'process') as process:
            self.assertEqual(reprocess.candidates(self.s,dict(scope='meeting:'+self.mid))['meetings'][0]['id'],self.mid)
            preview=self.preview();self.assertFalse(preview['uses_audio']);process.assert_not_called()
    def test_approval_is_single_use_and_bound_to_operation(self):
        preview=self.preview()
        with patch.object(self.s,'process') as process:
            result=reprocess.start(self.s,dict(token=preview['token'],approved=True));self.assertEqual(result['queued'],[self.mid]);process.assert_called_once_with(self.mid,'summarize')
            with self.assertRaises(WorkItemConflict):reprocess.start(self.s,dict(token=preview['token'],approved=True))
    def test_changed_source_prompt_or_settings_requires_new_preview(self):
        for change in ('source','prompt','settings'):
            with self.subTest(change=change):
                preview=self.preview()
                if change=='source':atomic_json(self.directory/'transcript.json',[dict(start=0,end=1,text='Edited',speaker='Иван')])
                elif change=='prompt':self.s.prompts.save('meeting_minutes','global','New style',self.s.prompts.catalog()['revision'])
                else:self.s.settings['local_ai_model']='new-model'
                with patch.object(self.s,'process') as process,self.assertRaises(WorkItemConflict):reprocess.start(self.s,dict(token=preview['token'],approved=True))
                process.assert_not_called()
    def test_no_approval_and_unavailable_audio_cannot_start(self):
        preview=self.preview()
        with self.assertRaises(ValueError):reprocess.start(self.s,dict(token=preview['token']))
        with self.assertRaises(ValueError):self.preview('audio')
        self.s.busy.add(self.mid)
        try:
            with self.assertRaises(ValueError):self.preview()
        finally:self.s.busy.discard(self.mid)
    def test_combined_correction_then_notes_never_recognizes_or_recovers_audio(self):
        # A saved transcript is sufficient even for a meeting whose audio is unavailable.
        self.s.library.update(self.mid,mode='in_person')
        calls=[]
        def execute(action,*args,**kwargs):calls.append(action);return {}
        with patch.object(self.s,'_execute',side_effect=execute):
            preview=self.preview('correction_notes');reprocess.start(self.s,dict(token=preview['token'],approved=True));wait_for(lambda:self.mid not in self.s.busy)
        self.assertEqual(calls,['correct','summarize'])
    def test_bounded_unique_selection(self):
        for keys in ([],[self.mid,self.mid],[self.mid]*21):
            with self.assertRaises(ValueError):reprocess.preview(self.s,dict(meetings=keys,action='notes'))
    def test_audio_rerun_explicitly_preserves_saved_notes_for_review(self):
        self.s.library.update(self.mid,mode='audio')
        (self.directory/'recording.wav').write_bytes(b'synthetic-placeholder')
        preview=self.preview('audio');self.assertTrue(preview['uses_audio'])
        with patch.object(self.s,'process') as process:
            reprocess.start(self.s,dict(token=preview['token'],approved=True))
            process.assert_called_once_with(self.mid,'all',preserve_notes=True)
    def test_combined_failure_does_not_continue_to_notes(self):
        calls=[]
        def execute(action,*args,**kwargs):
            calls.append(action)
            if action=='correct':raise ValueError('Correction failed')
        with patch.object(self.s,'_execute',side_effect=execute):
            preview=self.preview('correction_notes');reprocess.start(self.s,dict(token=preview['token'],approved=True));wait_for(lambda:self.mid not in self.s.busy)
        self.assertEqual(calls,['correct']);self.assertEqual(self.s.detail(self.mid)['status'],'error')
    def test_updated_notes_wait_for_review_and_keep_completed_task_identity(self):
        from app import processing
        from meeting_assistant import save_minutes
        from tests.test_notes import minutes,task,item
        old='Проверяваме deployment.';new='Проверяваме deployment след тест.'
        save_minutes(self.directory,minutes(tasks=[task(old,owner='Иван')],summary=[item('Старо резюме')]))
        self.s._sync_items(self.mid);tracked=self.s.tasks()[0];self.s.update_item(tracked['id'],tracked['text'],{'status':'done'})
        def execute(action,directory,settings,progress,*args,**kwargs):
            if action=='correct':
                transcript=self.s.detail(self.mid)['transcript'];transcript[0]['text']=new;atomic_json(directory/'transcript.json',transcript)
            elif action=='summarize':
                with patch('meeting_assistant.generate_minutes',return_value=minutes(tasks=[task(new,owner='Иван')],summary=[item('Ново резюме')])):processing.summarize(directory,settings,progress)
        with patch.object(self.s,'_execute',side_effect=execute):
            preview=self.preview('correction_notes');reprocess.start(self.s,dict(token=preview['token'],approved=True));wait_for(lambda:self.mid not in self.s.busy)
        detail=self.s.detail(self.mid);self.assertIsNotNone(detail['minutes_proposal']);self.assertEqual(detail['minutes']['summary'][0]['text'],'Старо резюме')
        proposal=detail['minutes_proposal'];self.s.review_notes(self.mid,'apply',[c['id'] for c in proposal['changes']],proposal['revision'])
        tasks=self.s.tasks();self.assertEqual(len(tasks),1);self.assertEqual(tasks[0]['id'],tracked['id']);self.assertEqual(tasks[0]['status'],'done')
    def test_deferred_transcript_and_speaker_saves_do_not_start_ai(self):
        detail=self.s.detail(self.mid);transcript=copy.deepcopy(detail['transcript']);transcript[0]['text']='Saved correction'
        with patch.object(self.s,'_run_analytics') as analyze,patch.object(self.s,'process') as process:
            saved=self.s.edit(self.mid,dict(transcript=transcript,transcript_revision=detail['transcript_revision'],defer_analysis=True,refresh_notes=False))
            self.s.edit(self.mid,dict(speaker_assignment=dict(indices=[0],name='Maria',revision=saved['transcript_revision'],defer_analysis=True)))
        analyze.assert_not_called();process.assert_not_called();self.assertTrue(self.s.detail(self.mid)['analytics_need_refresh'])
    def test_analytics_preview_does_not_claim_cloud_notes_provider(self):
        self.s.settings['summarizer']='openai'
        preview=self.preview('analytics')
        self.assertEqual(preview['providers'],[dict(operation='Analytics',provider='on_device',destination='On this Mac')])
