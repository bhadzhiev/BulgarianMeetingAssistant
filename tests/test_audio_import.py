import io
from pathlib import Path
import subprocess
import tempfile
import unittest
import wave

from app.capture import ffmpeg_path
from app.service import MeetingService

PROJECT = Path(__file__).resolve().parents[1]


def phone_recording(path, seconds=3, created='2026-10-21T08:30:00Z'):
    subprocess.run([ffmpeg_path(), '-loglevel', 'error', '-y', '-f', 'lavfi', '-i', f'sine=frequency=440:duration={seconds}:sample_rate=44100',
                    '-ac', '2', '-c:a', 'aac', '-metadata', f'creation_time={created}', str(path)], check=True)
    return path.read_bytes()


class AudioImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.service = MeetingService(self.root / 'library', PROJECT)
        self.service.save_settings({'auto_process': False, 'auto_title': False})

    def tearDown(self):
        self.service.close()
        self.tmp.cleanup()

    def test_phone_audio_becomes_a_recorded_meeting_with_its_own_date(self):
        data = phone_recording(self.root / 'Voice memo 12.m4a')
        detail = self.service.import_audio(io.BytesIO(data), len(data), 'Voice memo 12.m4a', 1_700_000_000_000)
        self.assertEqual((detail['mode'], detail['status'], detail['title']), ('audio', 'recorded', 'Voice memo 12'))
        self.assertAlmostEqual(detail['duration'], 3, delta=0.1)
        self.assertTrue(detail['started_at'].startswith('2026-10-21'))
        with wave.open(str(self.service.library.directory(detail['id']) / 'recording.wav')) as audio:
            self.assertEqual((audio.getframerate(), audio.getnchannels(), audio.getsampwidth()), (16000, 1, 2))
        self.assertEqual(list(self.service.library.root.glob('.upload-*')), [])
        with self.assertRaisesRegex(ValueError, 'no raw tracks'):
            self.service.process(detail['id'], 'recover')

    def test_without_a_date_in_the_file_the_file_time_is_used(self):
        subprocess.run([ffmpeg_path(), '-loglevel', 'error', '-y', '-f', 'lavfi', '-i', 'sine=duration=1', str(self.root / 'a.wav')], check=True)
        data = (self.root / 'a.wav').read_bytes()
        detail = self.service.import_audio(io.BytesIO(data), len(data), 'a.wav', 1_761_000_000_000)
        self.assertTrue(detail['started_at'].startswith('2025-10-2'))

    def test_failed_uploads_leave_no_meeting_and_no_partial_files(self):
        data = phone_recording(self.root / 'x.m4a')
        for stream, size, name, message in [(io.BytesIO(data[:100]), len(data), 'x.m4a', 'stopped'),
                                            (io.BytesIO(b'not audio' * 100), 900, 'x.mp3', 'no audio'),
                                            (io.BytesIO(data), len(data), 'notes.pdf', 'Choose an audio file')]:
            with self.assertRaisesRegex(ValueError, message):
                self.service.import_audio(stream, size, name)
        self.assertEqual(self.service.library.list(), [])
        self.assertEqual(list(self.service.library.root.glob('.upload-*')), [])
