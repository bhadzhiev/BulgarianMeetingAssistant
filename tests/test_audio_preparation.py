import io
import http.client
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import wave

import numpy as np

from app import audio_preparation, processing
from app.capture import render_recording
from app.service import DEFAULTS, MeetingService
from app.storage import atomic_json
from tests.test_calendar import FakeGoogle

RATE = 16000
PROJECT = Path(__file__).resolve().parents[1]


def write_wav(path, samples):
    with wave.open(str(path), 'wb') as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(RATE)
        output.writeframes(np.asarray(samples, dtype='<i2').tobytes())


def read_wav(path):
    with wave.open(str(path), 'rb') as source:
        return np.frombuffer(source.readframes(source.getnframes()), dtype='<i2').astype(float)


def amplitude(samples, frequency):
    # Measure the steady middle to exclude the filters' start/end transients.
    samples = samples[RATE:-RATE]
    phase = np.arange(len(samples)) * 2 * np.pi * frequency / RATE
    return abs(np.mean(samples * np.exp(-1j * phase))) * 2


class AudioPreparationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.directory = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def signal(self):
        time = np.arange(RATE * 6) / RATE
        samples = 2500 * np.sin(2 * np.pi * 30 * time) + 3000 * np.sin(2 * np.pi * 700 * time)
        write_wav(self.directory / 'recording.wav', samples)
        return read_wav(self.directory / 'recording.wav')

    def test_off_bypasses_ffmpeg_and_keeps_original_bytes(self):
        self.signal()
        original = (self.directory / 'recording.wav').read_bytes()
        with patch('app.audio_preparation.ffmpeg_path', side_effect=AssertionError('Off must bypass DSP')):
            path, info = audio_preparation.prepare(self.directory, 'off', lambda _: None)
        self.assertEqual(path, self.directory / 'recording.wav')
        self.assertEqual(info['profile'], 'off')
        self.assertEqual(path.read_bytes(), original)

    def test_light_reduces_rumble_and_preserves_samples_and_original(self):
        source = self.signal()
        original = (self.directory / 'recording.wav').read_bytes()
        path, info = audio_preparation.prepare(self.directory, 'light', lambda _: None)
        prepared = read_wav(path)
        self.assertEqual(len(prepared), len(source))
        self.assertEqual(info['frames'], len(source))
        self.assertLess(amplitude(prepared, 30) / amplitude(prepared, 700),
                        .35 * amplitude(source, 30) / amplitude(source, 700))
        self.assertGreater(amplitude(prepared, 700), 1000)
        self.assertLessEqual(np.max(np.abs(prepared)), 32768 * .951)
        self.assertEqual((self.directory / 'recording.wav').read_bytes(), original)

    def test_silence_stays_silent(self):
        write_wav(self.directory / 'recording.wav', np.zeros(RATE * 3))
        path, _ = audio_preparation.prepare(self.directory, 'light', lambda _: None)
        self.assertEqual(len(read_wav(path)), RATE * 3)
        self.assertEqual(np.max(np.abs(read_wav(path))), 0)

    def test_transients_do_not_shift_the_timeline(self):
        # Odd length and a final transient also exercise the denoiser's last partial hop.
        samples = np.zeros(RATE * 4 + 73)
        positions = (RATE, RATE * 3, len(samples) - 100)
        samples[list(positions)] = 16000
        write_wav(self.directory / 'recording.wav', samples)
        path, _ = audio_preparation.prepare(self.directory, 'light', lambda _: None)
        prepared = read_wav(path)
        for position in positions:
            start = position - RATE // 4
            actual = start + np.argmax(np.abs(prepared[start:position + RATE // 4]))
            self.assertGreater(np.max(np.abs(prepared[start:position + RATE // 4])), 1000)
            self.assertLessEqual(abs(actual - position), 1)
        self.assertEqual(len(prepared), len(samples))

    def test_online_keeps_system_audio_out_of_denoising(self):
        time = np.arange(RATE * 6) / RATE
        mic = (1500 * np.sin(2 * np.pi * 30 * time)).astype('<i2')
        system = (2500 * np.sin(2 * np.pi * 2100 * time)).astype('<i2')
        (self.directory / 'microphone.pcm').write_bytes(mic.tobytes())
        (self.directory / 'system.pcm').write_bytes(system.tobytes())
        atomic_json(self.directory / 'capture.json', dict(mode='online', microphone_rate=RATE, system_rate=RATE, duration=6))
        render_recording(self.directory)
        raw = [(self.directory / name).read_bytes() for name in ('microphone.pcm', 'system.pcm')]
        path, info = audio_preparation.prepare(self.directory, 'light', lambda _: None)
        prepared = read_wav(path)
        self.assertEqual(info['source'], 'separate microphone and system tracks')
        self.assertAlmostEqual(amplitude(prepared, 2100) / amplitude(system, 2100), 1, delta=.03)
        self.assertEqual(len(prepared), len(system))
        self.assertEqual(raw, [(self.directory / name).read_bytes() for name in ('microphone.pcm', 'system.pcm')])
        # A missing raw track must fall back to the complete mixed recording, not omit a voice.
        (self.directory / 'microphone.pcm').unlink()
        _, fallback = audio_preparation.prepare(self.directory, 'light', lambda _: None)
        self.assertEqual(fallback['source'], 'recording.wav')

    def test_cloud_receives_prepared_audio_and_off_retry_archives_it(self):
        self.signal()
        received = []
        def upload(audio, *_):
            with wave.open(io.BytesIO(audio), 'rb') as source:
                received.append(np.frombuffer(source.readframes(source.getnframes()), dtype='<i2').astype(float))
            return {'text': 'Тестов транскрипт.'}
        with patch('app.processing.upload_audio', side_effect=upload):
            processing.transcribe(self.directory, dict(DEFAULTS, transcription='openai', audio_preparation='light'), lambda _: None, 'fake')
            np.testing.assert_array_equal(received[0], read_wav(self.directory / 'transcription.wav'))
            self.assertEqual(json.loads((self.directory / 'transcript.metadata.json').read_text())['audio_preparation']['profile'], 'light')
            published = (self.directory / 'transcription.wav').read_bytes()
            processing.transcribe(self.directory, dict(DEFAULTS, transcription='openai', audio_preparation='off'), lambda _: None, 'fake')
        np.testing.assert_array_equal(received[1], read_wav(self.directory / 'recording.wav'))
        self.assertFalse((self.directory / 'transcription.wav').exists())
        self.assertTrue(published)
        # The derived audio is not copied into versions/; its profile is, through the archived metadata.
        self.assertEqual(list((self.directory / 'versions').glob('*/transcription.wav')), [])
        archived = json.loads(next((self.directory / 'versions').glob('*/transcript.metadata.json')).read_text())
        self.assertEqual(archived['audio_preparation']['profile'], 'light')

    def test_leftover_temporary_audio_is_removed_at_start_and_backups_skip_prepared_audio(self):
        from app import backup
        from app.storage import Library
        library = Library(self.directory / 'library')
        meeting = library.create('Среща', 'in_person', {})
        folder = library.directory(meeting['id'])
        write_wav(folder / 'recording.wav', np.zeros(RATE))
        write_wav(folder / 'transcription.wav', np.zeros(RATE))
        (folder / '.transcription-abc123.wav').write_bytes(b'interrupted preparation')
        Library(self.directory / 'library')
        self.assertEqual(list(folder.glob('.transcription-*')), [])
        self.assertTrue((folder / 'transcription.wav').exists())
        names = [name for name, _ in backup._library_files(self.directory / 'library', set())]
        self.assertIn(meeting['id'] + '/recording.wav', names)
        self.assertNotIn(meeting['id'] + '/transcription.wav', names)

    def test_local_whisper_receives_prepared_audio(self):
        self.signal()
        received = []
        class Model:
            def __init__(self, *_, **__): pass
            def transcribe(self, audio, **_):
                received.append(audio.copy())
                return [SimpleNamespace(t0=0, t1=100, text='Тестов транскрипт.')]
        with patch('pywhispercpp.model.Model', Model), patch('app.processing.ensure_model', return_value='unused'):
            processing.transcribe(self.directory, dict(DEFAULTS, models_dir=str(self.directory), whisper_vad=False,
                                                      audio_preparation='light'), lambda _: None)
        np.testing.assert_allclose(received[0], read_wav(self.directory / 'transcription.wav') / 32768, atol=1e-7)

    def test_failed_attempt_keeps_published_output_and_removes_temporary_audio(self):
        self.signal()
        (self.directory / 'transcript.json').write_text('previous transcript')
        (self.directory / 'transcription.wav').write_bytes(b'previous prepared audio')
        with patch('app.processing.upload_audio', side_effect=RuntimeError('API unavailable')):
            with self.assertRaisesRegex(RuntimeError, 'API unavailable'):
                processing.transcribe(self.directory, dict(DEFAULTS, transcription='openai', audio_preparation='light'), lambda _: None, 'fake')
        self.assertEqual((self.directory / 'transcript.json').read_text(), 'previous transcript')
        self.assertEqual((self.directory / 'transcription.wav').read_bytes(), b'previous prepared audio')
        self.assertEqual(list(self.directory.glob('.transcription-*')), [])
        with patch('app.audio_preparation.subprocess.run', return_value=subprocess.CompletedProcess([], 1, '', 'filter unavailable')):
            with self.assertRaisesRegex(RuntimeError, 'Audio preparation failed'):
                audio_preparation.prepare(self.directory, 'light', lambda _: None)
        self.assertEqual(list(self.directory.glob('.transcription-*')), [])

    def test_strong_stops_with_a_clear_reason_when_the_rnnoise_model_cannot_download(self):
        self.signal()
        with patch('app.model_cache.download', side_effect=OSError('offline')):
            with self.assertRaisesRegex(RuntimeError, 'RNNoise model .* unavailable \\(offline\\). Retry when online, or choose Light or Off'):
                audio_preparation.prepare(self.directory, 'strong', lambda _: None, self.directory / 'models')
        self.assertEqual(list(self.directory.glob('.transcription-*')), [])

    @unittest.skipUnless(os.environ.get('BMA_RNNOISE_MODEL'), 'set BMA_RNNOISE_MODEL to the downloaded RNNoise model to run')
    def test_strong_keeps_the_timeline_and_lowers_steady_noise(self):
        models = self.directory / 'models'
        models.mkdir()
        shutil.copy(os.environ['BMA_RNNOISE_MODEL'], models / audio_preparation.RNNOISE_MODEL)
        time = np.arange(RATE * 6) / RATE
        # A voice whose pitch glides from 120 to 220 Hz, so the timeline check has one clear match.
        phase = 2 * np.pi * np.cumsum(120 + 100 * time / 6) / RATE
        voice = sum(np.sin(k * phase) / k for k in range(1, 12)) * 2500 * ((time > 1) & (time < 2.5) | (time > 3.5) & (time < 5))
        noisy = voice + np.random.default_rng(3).normal(0, 800, len(time))
        write_wav(self.directory / 'recording.wav', noisy)
        path, info = audio_preparation.prepare(self.directory, 'strong', lambda _: None, models)
        prepared, source = read_wav(path), read_wav(self.directory / 'recording.wav')
        self.assertEqual((info['profile'], len(prepared)), ('strong', len(source)))
        shift = max(range(-200, 201), key=lambda k: np.dot(source[max(0, -k):len(source) - max(0, k)], prepared[max(0, k):len(source) - max(0, -k)]))
        self.assertLessEqual(abs(shift), 4)
        quiet = (time < .8) | (time > 5.2)
        self.assertLess(np.sqrt(np.mean(prepared[quiet] ** 2)), .7 * np.sqrt(np.mean(source[quiet] ** 2)))

    def test_setting_defaults_off_and_rejects_unknown_profile(self):
        service = MeetingService(self.directory, PROJECT, google=FakeGoogle())
        try:
            self.assertEqual(service.settings['audio_preparation'], 'off')
            service.save_settings({'audio_preparation': 'light'})
            self.assertEqual(json.loads(service.settings_path.read_text())['audio_preparation'], 'light')
            service.save_settings({'audio_preparation': 'strong'})
            self.assertEqual(service.settings['audio_preparation'], 'strong')
            with self.assertRaises(ValueError): service.save_settings({'audio_preparation': 'aggressive'})
        finally:
            service.close()

    def test_prepared_audio_is_listed_and_can_be_played_with_byte_ranges(self):
        from desktop_app import Server
        service = MeetingService(self.directory, PROJECT, google=FakeGoogle())
        server = Server(('127.0.0.1', 0), service)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
        try:
            meeting = service.library.create('Prepared playback', 'audio', dict(DEFAULTS))
            directory = service.library.directory(meeting['id'])
            write_wav(directory / 'transcription.wav', np.zeros(RATE))
            self.assertIn('transcription.wav', service.detail(meeting['id'])['files'])
            connection.request('GET', '/files/' + meeting['id'] + '/transcription.wav',
                               headers={'Cookie': 'meeting_session=' + server.token, 'Range': 'bytes=44-143'})
            response = connection.getresponse()
            self.assertEqual(response.status, 206)
            self.assertEqual(len(response.read()), 100)
            self.assertIsNone(response.getheader('Content-Disposition'))
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join(2)
            service.close()
