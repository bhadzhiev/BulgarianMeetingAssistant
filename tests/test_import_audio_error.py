import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import capture


class UnreadableAudioTest(unittest.TestCase):
    def test_error_has_a_next_step_and_no_ffmpeg_output(self):
        stderr = '[in#0 @ 0x1234] Error opening input /private/var/folders/x/user-secret/upload.wav: Invalid data'
        with tempfile.TemporaryDirectory() as folder:
            done = mock.Mock(returncode=1, stderr=stderr)
            with mock.patch.object(capture.subprocess, 'run', return_value=done), \
                    self.assertLogs('app.capture', 'WARNING') as logs:
                with self.assertRaises(ValueError) as caught:
                    capture.convert_audio(Path(folder) / 'in.wav', Path(folder) / 'out.wav')
        message = str(caught.exception)
        self.assertEqual(message, capture.UNREADABLE_AUDIO)
        self.assertIn('convert it to WAV or MP3', message)
        for leak in ('ffmpeg', '0x1234', '/private/var', 'user-secret'):
            self.assertNotIn(leak, message)
        # The technical reason stays in the local log for diagnostics.
        self.assertIn('Invalid data', logs.output[0])


if __name__ == '__main__':
    unittest.main()
