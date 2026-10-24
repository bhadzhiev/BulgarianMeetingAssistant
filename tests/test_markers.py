import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.service import MeetingService
from meeting_assistant import TranscriptSegment, llm_prompt, save_transcript
from tests.test_app import FakeRecorder, wait_for

PROJECT = Path(__file__).resolve().parents[1]


class MarkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.service = MeetingService(Path(self.tmp.name), PROJECT)
        self.service.save_settings({'auto_process': False, 'live_transcription': False, 'transcript_correction': 'none'})

    def tearDown(self):
        self.service.close()
        self.tmp.cleanup()

    def test_markers_during_recording_are_saved_shown_and_removable(self):
        with self.assertRaisesRegex(ValueError, 'only during a recording'):
            self.service.add_marker('decision')
        with patch('app.service.devices', return_value=[{'id': 2}]), patch('app.service.Recorder', FakeRecorder):
            meeting_id = self.service.start('Маркери', 'in_person', 2)['id']
            wait_for(lambda: self.service.library.get(meeting_id)['status'] == 'recording')
            self.service.add_marker('decision', '  LTE  за резерв \n')
            self.service.pause(True)
            paused = self.service.add_marker('check')['markers']
            self.assertEqual(self.service.snapshot()['active']['markers'], paused)
            with self.assertRaisesRegex(ValueError, 'important, decision or check'):
                self.service.add_marker('other')
            self.service.pause(False)
            self.service.stop()
            wait_for(lambda: self.service.library.get(meeting_id)['status'] == 'recorded')
        detail = self.service.detail(meeting_id)
        self.assertEqual([(m['kind'], m['note']) for m in detail['markers']], [('decision', 'LTE за резерв'), ('check', '')])
        self.assertLessEqual(detail['markers'][0]['time'], detail['markers'][1]['time'])
        self.assertIn('markers.json', detail['files'])
        detail = self.service.delete_marker(meeting_id, detail['markers'][0]['id'])
        self.assertEqual([m['kind'] for m in detail['markers']], ['check'])

    def test_notes_prompt_gets_markers_of_its_part_as_hints(self):
        prompt = llm_prompt('[00:00:01] Да.', markers=[dict(time=75, kind='decision', note='LTE')])
        self.assertIn('[00:01:15] Решение — LTE', prompt)
        self.assertIn('не факти', prompt)
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            save_transcript(directory, [TranscriptSegment(0, 10, 'Решаваме LTE.')])
            (directory / 'markers.json').write_text(json.dumps([dict(id='a', time=3, kind='decision', note=''),
                                                               dict(id='b', time=900, kind='check', note='')]))
            from app import processing
            from app.service import DEFAULTS
            with patch('app.local_ai.complete_json', return_value=dict(summary=[], decisions=[], tasks=[], open_questions=[])) as complete:
                processing.summarize(directory, dict(DEFAULTS, summarizer='local'), lambda _: None)
            prompt = complete.call_args.args[1][0]['content']
        self.assertIn('[00:00:03] Решение', prompt)
        self.assertNotIn('00:15:00', prompt)
