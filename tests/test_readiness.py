from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.service import MeetingService
from tests.test_calendar import FakeGoogle

PROJECT = Path(__file__).resolve().parents[1]


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.service = MeetingService(Path(self.tmp.name), PROJECT, google=FakeGoogle())
        self.addCleanup(self.service.close)
        self.service.models_dir = Path(self.tmp.name) / 'models'

    def test_the_next_recording_shows_model_disk_and_system_audio_without_downloading(self):
        ready = self.service.readiness()
        self.assertEqual(ready['model'], dict(ready=False, label='Whisper large-v3-turbo downloads on first use'))
        self.service.models_dir.mkdir()
        (self.service.models_dir / 'ggml-large-v3-turbo.bin').write_bytes(b'model')
        self.assertTrue(self.service.readiness()['model']['ready'])
        self.assertGreater(ready['disk_free'], 0)
        self.assertEqual(ready['disk_hours'], round(ready['disk_free'] / 500_000_000, 1))
        self.assertIsInstance(ready['system_audio'], bool)
        self.assertIn('readiness', self.service.snapshot())

    def test_cloud_and_parakeet_report_what_they_need(self):
        self.service.settings = dict(self.service.settings, transcription='openai')
        self.assertEqual(self.service.readiness()['model'], dict(ready=False, label='Add an OpenAI key in Settings'))
        self.service.settings = dict(self.service.settings, transcription='parakeet')
        with patch('app.parakeet.availability', return_value=dict(available=True)):
            self.assertEqual(self.service.readiness()['model'], dict(ready=False, label='parakeet-tdt-0.6b-v3 downloads on first use'))
