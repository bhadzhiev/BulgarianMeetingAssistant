import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.service import MeetingService
from tests.test_app import FakeRecorder
from tests import test_http

PROJECT = Path(__file__).resolve().parents[1]


class TranscriptionTimingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.service = MeetingService(Path(self.tmp.name), PROJECT)
        self.service.save_settings(dict(auto_process=False, auto_title=False, transcript_correction='local'))

    def tearDown(self):
        self.service.close()
        self.tmp.cleanup()

    def start(self, **kwargs):
        meeting = self.service.start('Synthetic timing test', 'in_person', 2, **kwargs)
        self.service.start_thread.join(timeout=5)
        self.assertEqual(self.service.library.get(meeting['id'])['status'], 'recording')
        return meeting

    def stop(self):
        self.service.stop()
        self.service.finish_thread.join(timeout=5)
        self.assertFalse(self.service.finish_thread.is_alive())

    def test_both_modes_control_worker_without_replacing_defaults_or_correction(self):
        with patch('app.service.devices', return_value=[dict(id=2)]), patch('app.service.Recorder', FakeRecorder), patch('app.service.LiveSession') as live:
            for timing in ['after', 'live']:
                self.service.save_settings(dict(live_transcription=timing == 'after'))
                before = self.service.settings_path.read_bytes()
                meeting = self.start(transcription_timing=timing)
                self.assertEqual(meeting['settings']['live_transcription'], timing == 'live')
                self.assertEqual(meeting['settings']['transcription'], 'local')
                self.assertEqual(meeting['settings']['transcript_correction'], 'local')
                self.assertEqual(live.call_count, int(timing == 'live'))
                self.assertEqual(self.service.settings_path.read_bytes(), before)
                saved = json.loads((self.service.library.directory(meeting['id'])/'meeting.json').read_text())
                self.assertEqual(saved['settings']['live_transcription'], timing == 'live')
                self.stop()
                self.assertTrue((self.service.library.directory(meeting['id'])/'recording.wav').exists())
                self.assertEqual(self.service.library.get(meeting['id'])['status'], 'recorded')

    def test_omitted_choice_preserves_legacy_default(self):
        with patch('app.service.devices', return_value=[dict(id=2)]), patch('app.service.Recorder', FakeRecorder), patch('app.service.LiveSession'):
            for enabled in [False, True]:
                self.service.save_settings(dict(live_transcription=enabled))
                meeting = self.start()
                self.assertEqual(meeting['settings']['live_transcription'], enabled)
                self.stop()

    def test_invalid_choice_is_rejected_before_capture_or_creating_a_meeting(self):
        with patch('app.service.ffmpeg_path') as audio:
            for value in ['', 'later', True, 0, [], {}]:
                with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'live captions'):
                    self.service.start('Invalid', 'in_person', 2, transcription_timing=value)
            audio.assert_not_called()
        self.assertIsNone(self.service.active)
        self.assertEqual(self.service.library.list(), [])

    def test_after_mode_still_schedules_final_processing_with_frozen_settings(self):
        self.service.save_settings(dict(auto_process=True, live_transcription=True))
        with patch('app.service.devices', return_value=[dict(id=2)]), patch('app.service.Recorder', FakeRecorder), patch('app.service.LiveSession') as live, patch.object(self.service, 'process') as process:
            meeting = self.start(transcription_timing='after')
            self.service.save_settings(dict(auto_process=False, live_transcription=True))
            self.stop()
            live.assert_not_called()
            process.assert_called_once_with(meeting['id'], 'all', use_saved=True)
            self.assertFalse(self.service.library.get(meeting['id'])['settings']['live_transcription'])
            self.assertTrue(self.service.library.get(meeting['id'])['settings']['auto_process'])


class TranscriptionTimingHTTPTests(unittest.TestCase):
    setUp, tearDown, request = test_http.HTTPTests.setUp, test_http.HTTPTests.tearDown, test_http.HTTPTests.request

    def test_start_accepts_per_meeting_choice_without_saving_global_settings(self):
        self.service.save_settings(dict(auto_process=False, auto_title=False, live_transcription=True))
        with patch('app.service.devices', return_value=[dict(id=2)]), patch('app.service.Recorder', FakeRecorder), patch('app.service.LiveSession') as live:
            status, body, _ = self.request('/api/start', dict(title='Synthetic HTTP meeting', mode='in_person', device=2, transcription_timing='after'))
            self.assertEqual(status, 200, body)
            meeting = json.loads(body)
            self.service.start_thread.join(timeout=5)
            self.assertFalse(meeting['settings']['live_transcription'])
            self.assertTrue(self.service.settings['live_transcription'])
            live.assert_not_called()
            self.assertEqual(self.request('/api/stop', {})[0], 200)
            self.service.finish_thread.join(timeout=5)
            self.assertEqual(self.service.library.get(meeting['id'])['status'], 'recorded')

    def test_invalid_http_choice_does_not_start_capture(self):
        status, body, _ = self.request('/api/start', dict(mode='in_person', device=2, transcription_timing='invalid'))
        self.assertEqual(status, 400, body)
        self.assertIsNone(self.service.active)
