"""Saving a correction refreshes derived notes without silently undoing reviewed work."""
import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from app import processing
from app.service import MeetingService
from app.storage import atomic_json
from app.work_items import WorkItemConflict
from meeting_assistant import save_minutes
from tests.test_calendar import FakeGoogle
from tests.test_notes import minutes, task, item

PROJECT=Path(__file__).resolve().parents[1]


class TranscriptRefreshTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.service=MeetingService(Path(self.tmp.name),PROJECT,google=FakeGoogle())
        self.service.settings.update(summarizer='local',auto_process=False,auto_title=False)
        self.service._run_analytics=lambda *args,**kwargs:None
        d=self.service.import_transcript('[00:00:00] Иван: Провери VPN.','test.txt')
        self.id=d['id'];self.directory=self.service.library.directory(self.id)
        save_minutes(self.directory,minutes(tasks=[task('Провери VPN failover',owner='Иван')],summary=[item('Старо резюме')]))
        self.service._sync_items(self.id)

    def tearDown(self):
        self.service.close();self.tmp.cleanup()

    def body(self,refresh=False):
        d=self.service.detail(self.id)
        segments=copy.deepcopy(d['transcript']);segments[0]['text']='Провери VPN failover до петък.'
        return dict(transcript=segments,transcript_revision=d['transcript_revision'],refresh_notes=refresh)

    def test_a_stale_transcript_edit_cannot_overwrite_newer_corrections(self):
        stale=self.body();self.service.edit(self.id,self.body())
        with self.assertRaises(WorkItemConflict):self.service.edit(self.id,stale)

    def test_edit_keeps_saved_notes_but_archives_and_invalidates_old_draft(self):
        atomic_json(self.directory/'minutes.proposed.json',minutes(summary=[item('Остаряла AI чернова')]))
        proposal=self.service.detail(self.id)['minutes_proposal']
        before=(self.directory/'minutes.json').read_bytes()
        d=self.service.edit(self.id,self.body())
        self.assertTrue(d['notes_need_refresh']);self.assertIsNone(d['minutes_proposal'])
        self.assertEqual((self.directory/'minutes.json').read_bytes(),before)
        self.assertTrue(list((self.directory/'versions').glob('*/minutes.proposed.json')))
        with self.assertRaisesRegex(ValueError,'changed'):self.service.review_notes(self.id,'apply',[],proposal['revision'])

    def test_save_and_refresh_uses_corrected_text_then_review_preserves_done_status(self):
        [tracked]=self.service.tasks();self.service.update_item(tracked['id'],tracked['text'],{'status':'done'})
        observed=[]
        def execute(action,directory,settings,progress,*args):
            self.assertEqual(action,'summarize')
            observed.append(json.loads((directory/'transcript.json').read_text())[0]['text'])
            output=minutes(tasks=[task('Провери VPN failover до петък',owner='Иван')],summary=[item('Актуално резюме')])
            with patch('meeting_assistant.generate_minutes',return_value=output):processing.summarize(directory,settings,progress)
        with patch.object(self.service,'_execute',side_effect=execute):
            self.service.edit(self.id,self.body(True))
            for _ in range(100):
                if self.id not in self.service.busy:break
                time.sleep(.02)
            self.assertNotIn(self.id,self.service.busy)
        d=self.service.detail(self.id)
        self.assertEqual(observed,['Провери VPN failover до петък.'])
        self.assertEqual(d['status'],'ready');self.assertIsNotNone(d['minutes_proposal'])
        self.assertEqual(d['minutes']['summary'][0]['text'],'Старо резюме')
        proposal=d['minutes_proposal'];accepted=[c['id'] for c in proposal['changes']]
        d=self.service.review_notes(self.id,'apply',accepted,proposal['revision'])
        self.assertFalse(d['notes_need_refresh'])
        [tracked]=self.service.tasks();self.assertEqual(tracked['status'],'done')
        self.assertEqual(tracked['text'],'Провери VPN failover до петък')

    def test_queue_failure_still_returns_saved_text_and_recoverable_warning(self):
        self.service.settings['summarizer']='none'
        d=self.service.edit(self.id,self.body(True))
        self.assertEqual(d['transcript'][0]['text'],'Провери VPN failover до петък.')
        self.assertTrue(d['notes_need_refresh']);self.assertIn('Settings',d['notes_refresh_error'])

    def test_no_change_does_not_invalidate_a_valid_draft(self):
        atomic_json(self.directory/'minutes.proposed.json',minutes(summary=[item('Чернова')]))
        d=self.service.detail(self.id)
        result=self.service.edit(self.id,dict(transcript=d['transcript'],transcript_revision=d['transcript_revision']))
        self.assertEqual(result['minutes_proposal'],d['minutes_proposal'])
