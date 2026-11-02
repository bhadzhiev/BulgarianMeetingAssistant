import tempfile
import unittest
from pathlib import Path
from app.capture_setup import CaptureSetup


class CaptureSetupTests(unittest.TestCase):
    def test_round_trip_keeps_only_capture_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'capture-setup.json'
            setup = CaptureSetup(path)
            setup.remember({'title': 'Private meeting', 'mode': 'online', 'project_id': 'project', 'series_id': None,
                            'meeting_type': 'daily', 'settings': {'_capture_microphone': 'Mic',
                            'fallback_microphone': 'Backup', 'live_transcription': False, 'api_key': 'secret'}})
            restored = CaptureSetup(path).public()['data']
            self.assertEqual(restored['microphone_name'], 'Mic')
            self.assertEqual(restored['transcription_timing'], 'after')
            self.assertNotIn('Private meeting', path.read_text())
            self.assertNotIn('secret', path.read_text())

    def test_corrupt_setup_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'capture-setup.json'
            path.write_bytes(b'{broken')
            setup = CaptureSetup(path)
            self.assertTrue(setup.public()['error'])
            with self.assertRaises(ValueError):
                setup.remember({'mode': 'in_person', 'meeting_type': 'general',
                                'settings': {'_capture_microphone': 'Mic'}})
            self.assertEqual(path.read_bytes(), b'{broken')
