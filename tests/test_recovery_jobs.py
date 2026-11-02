import io
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
import signal
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import wave

import numpy as np

from app import capture, processing
from app.jobs import JobCancelled
from app.power import RecordingPower
from app.service import DEFAULTS, MeetingService
from app.storage import atomic_json
from app.worker import ProcessingWorker
from tests.test_app import FakeRecorder, pcm_fixture, wait_for
from tests.test_calendar import FakeGoogle

PROJECT = Path(__file__).resolve().parents[1]


class ResumeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.settings = dict(DEFAULTS, transcription='openai')
        with wave.open(str(self.root / 'recording.wav'), 'wb') as out:
            out.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
            out.writeframes(np.zeros(16000 * 80, dtype='<i2').tobytes())

    def transcribe(self, upload, progress=lambda _: None, settings=None):
        with patch('app.processing.upload_audio', side_effect=upload) as request:
            processing.transcribe(self.root, settings or self.settings, progress, 'not-saved-key')
        return request

    def interrupt(self):
        calls = []
        def upload(*args):
            calls.append(True)
            if len(calls) == 2:
                raise RuntimeError('offline')
            return {'text': 'Synthetic speech.'}
        with self.assertRaisesRegex(RuntimeError, 'offline'):
            self.transcribe(upload)

    def test_retry_resumes_exact_chunk_boundary(self):
        self.interrupt()
        checkpoint = json.loads((self.root / '.transcription-progress.json').read_text())
        self.assertNotIn('not-saved-key', json.dumps(checkpoint))
        self.assertFalse((self.root / 'transcript.json').exists())
        uploaded = []
        def upload(audio, *args):
            with wave.open(io.BytesIO(audio)) as source:
                uploaded.append(source.getnframes())
            return {'text': 'Remaining synthetic speech.'}
        self.transcribe(upload)
        self.assertEqual(uploaded, [16000 * 80 - checkpoint['cursor']])
        segments = json.loads((self.root / 'transcript.json').read_text())
        self.assertEqual(segments[1]['start'], checkpoint['cursor'] / 16000)
        self.assertEqual(segments[0]['end'], segments[1]['start'])
        self.assertFalse((self.root / '.transcription-progress.json').exists())

    def test_audio_content_change_invalidates_checkpoint_even_at_same_size(self):
        self.interrupt()
        path = self.root / 'recording.wav'
        data = bytearray(path.read_bytes())
        data[100] = 1
        path.write_bytes(data)
        model = self.transcribe(lambda *args: {'text': 'New speech.'})
        self.assertEqual(model.call_count, 2)
        self.assertEqual(json.loads((self.root / 'transcript.metadata.json').read_text())['resumed_from_seconds'], 0)

    def test_model_change_invalidates_checkpoint(self):
        self.interrupt()
        model = self.transcribe(lambda *args: {'text': 'Speech.'}, settings=dict(self.settings, cloud_model='different'))
        self.assertEqual(model.call_count, 2)

    def test_completed_checkpoint_publishes_without_repeating_inference(self):
        def stop_before_publish(message):
            if message == 'Publishing transcript':
                raise JobCancelled()
        with self.assertRaises(JobCancelled):
            self.transcribe(lambda *args: {'text': 'Speech.'}, stop_before_publish)
        model = self.transcribe(lambda *args: self.fail('Completed chunks must not be repeated'))
        self.assertEqual(model.call_count, 0)
        self.assertTrue((self.root / 'transcript.json').exists())

    def test_malformed_checkpoint_is_ignored(self):
        (self.root / '.transcription-progress.json').write_text('{broken')
        self.assertEqual(self.transcribe(lambda *args: {'text': 'Speech.'}).call_count, 2)


class MicrophoneRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def recorder(self, fallback=''):
        with patch('app.capture.sd.query_devices', return_value=dict(name='iPhone', default_samplerate=48000)):
            recorder = capture.Recorder(self.root, 2, 'in_person', Path('unused'))
        recorder.fallback_name = fallback
        recorder.clock.origin -= 10
        recorder.writer = SimpleNamespace(error=None, append=Mock())
        recorder.fatal = None
        recorder.stream = Mock(active=False)
        recorder.recovering = Mock()
        recorder.recovering.wait.side_effect = [False, True]
        return recorder

    def test_only_explicit_fallback_is_opened_and_writer_rate_is_preserved(self):
        recorder = self.recorder('Mac mic')
        stream = Mock()
        def start():
            recorder._callback(b'\0\0' * 100, 100, SimpleNamespace(currentTime=10, inputBufferAdcTime=10), None)
        stream.start.side_effect = start
        with patch('app.capture.devices', return_value=[dict(id=9, name='Mac mic', rate=44100)]), \
             patch('app.capture.sd.RawInputStream', return_value=stream) as opened:
            recorder._watch_input()
        self.assertEqual(opened.call_args.kwargs['device'], 9)
        self.assertEqual(opened.call_args.kwargs['samplerate'], 48000)
        self.assertEqual(recorder.input_status, 'connected')
        self.assertEqual(recorder.info['input_gaps'][0]['resumed_with'], 'Mac mic')
        self.assertIsNotNone(recorder.info['input_gaps'][0]['end'])
        self.assertGreaterEqual(recorder.writer.append.call_args.args[0], 480000)

    def test_unselected_microphone_is_never_used(self):
        recorder = self.recorder()
        with patch('app.capture.devices', return_value=[dict(id=9, name='Mac mic', rate=48000)]), \
             patch('app.capture.sd.RawInputStream') as opened:
            recorder._watch_input()
        opened.assert_not_called()
        self.assertEqual(recorder.input_status, 'missing')
        recorder.checkpoint()
        self.assertTrue(any('Microphone unavailable' in warning for warning in recorder.warnings))
        self.assertIsNone(recorder.info['input_gaps'][0]['end'])

    def test_selected_device_can_reconnect_after_renumbering(self):
        recorder = self.recorder()
        with patch('app.capture.devices', return_value=[dict(id=12, name='iPhone', rate=48000)]), \
             patch('app.capture.sd.RawInputStream') as opened:
            recorder._watch_input()
        self.assertEqual(opened.call_args.kwargs['device'], 12)

    def test_disk_error_does_not_start_device_recovery(self):
        recorder = self.recorder()
        recorder.writer.error = 'Cannot save microphone audio'
        with patch('app.capture.devices') as scanned:
            recorder._watch_input()
        scanned.assert_not_called()
        self.assertIn('Cannot save', recorder.error())

    def test_duplicate_device_names_are_not_guessed(self):
        recorder = self.recorder()
        with patch('app.capture.devices', return_value=[dict(id=10, name='iPhone'), dict(id=11, name='iPhone')]), \
             patch('app.capture.sd.RawInputStream') as opened:
            recorder._watch_input()
        opened.assert_not_called()

    def test_bad_fallback_does_not_prevent_original_reconnection(self):
        recorder = self.recorder('Mac mic')
        with patch('app.capture.devices', return_value=[dict(id=9, name='Mac mic'), dict(id=12, name='iPhone')]), \
             patch('app.capture.sd.RawInputStream', side_effect=[RuntimeError('unsupported sample rate'), Mock()]) as opened:
            recorder._watch_input()
        self.assertEqual([call.kwargs['device'] for call in opened.call_args_list], [9, 12])

    def test_gap_begins_at_last_saved_audio_not_detection_time(self):
        recorder = self.recorder()
        recorder.last_audio_end = 4.0
        with patch('app.capture.devices', return_value=[]):
            recorder._watch_input()
        self.assertEqual(recorder.info['input_gaps'][0]['start'], 4.0)

    def test_power_assertion_is_scoped_to_recording(self):
        with patch('app.power.Path.is_file', return_value=True), patch('app.power.subprocess.Popen') as spawn:
            child = spawn.return_value
            child.poll.return_value = None
            power = RecordingPower()
            power.start()
            power.start()
            self.assertEqual(spawn.call_count, 1)
            power.close()
            child.terminate.assert_called_once()
            self.assertIsNone(power.child)


class JobsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.service = MeetingService(self.root, PROJECT, google=FakeGoogle())
        self.addCleanup(self.service.close)
        self.service.save_settings(dict(auto_process=False, live_transcription=False, auto_title=False))

    def test_queued_job_can_be_cancelled_without_waiting_for_slot(self):
        meeting = self.service.library.create('Synthetic meeting', 'audio', dict(DEFAULTS))
        self.service.processing_slot.acquire()
        try:
            self.service.process(meeting['id'], 'transcribe')
            self.service.cancel_processing(meeting['id'])
            wait_for(lambda: meeting['id'] not in self.service.busy)
        finally:
            self.service.processing_slot.release()
        result = self.service.detail(meeting['id'])
        self.assertEqual(result['processing_stage'], 'Cancelled')
        self.assertEqual(result['status'], 'recorded')
        self.assertIn('Queued', result['processing_timings'])

    def test_invalid_fallback_is_rejected_before_start(self):
        with patch('app.service.devices', return_value=[dict(id=2, name='iPhone')]):
            with self.assertRaisesRegex(ValueError, 'another available'):
                self.service.start('Test', 'in_person', 2, fallback_device_name='Unselected device')
        self.assertIsNone(self.service.active)

    def test_activity_events_cover_start_and_saved_stop(self):
        changed = []
        self.service.activity_changed = changed.append
        with patch('app.service.devices', return_value=[dict(id=2, name='Mic')]), patch('app.service.Recorder', FakeRecorder):
            meeting = self.service.start('Test', 'in_person', 2)
            wait_for(lambda: self.service.library.get(meeting['id'])['status'] == 'recording')
            self.service.stop()
            wait_for(lambda: self.service.active is None)
        self.assertEqual(changed, [True, False])


class WorkerTests(unittest.TestCase):
    def test_parent_death_leaves_no_worker_or_guardian(self):
        entered, release = threading.Event(), threading.Event()
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                entered.set()
                release.wait(10)
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        def running(pid):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return False
            status = subprocess.run(['/bin/ps', '-p', str(pid), '-o', 'stat='], capture_output=True, text=True)
            self.assertIn(status.returncode, (0, 1))
            return bool(status.stdout.strip()) and not status.stdout.strip().startswith('Z')
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                atomic_json(root / 'transcript.json', [dict(start=0, end=1, text='Synthetic speech.', speaker=None)])
                code = f'''from pathlib import Path
import json
import app.worker as worker
from app.service import DEFAULTS
original = worker.subprocess.Popen
ids = {{}}
def spawn(command, *args, **kwargs):
    child = original(command, *args, **kwargs)
    if '-m' in command: ids['worker'] = child.pid
    elif command[0] == '/bin/sh': ids['guardian'] = child.pid
    Path({str(root / 'pids.json')!r}).write_text(json.dumps(ids))
    return child
worker.subprocess.Popen = spawn
worker.ProcessingWorker(Path({str(PROJECT)!r})).run('summarize', Path({tmp!r}),
    dict(DEFAULTS, summarizer='local', local_ai_base_url='http://127.0.0.1:{server.server_port}/v1'), lambda _: None)
'''
                parent = subprocess.Popen([sys.executable, '-c', code], cwd=PROJECT,
                                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                ids = {}
                try:
                    self.assertTrue(entered.wait(10))
                    ids = json.loads((root / 'pids.json').read_text())
                    self.assertEqual(set(ids), {'worker', 'guardian'})
                    parent.kill()
                    parent.wait(timeout=5)
                    wait_for(lambda: not any(running(pid) for pid in ids.values()))
                finally:
                    if parent.poll() is None:
                        parent.kill()
                        parent.wait()
                    for pid in ids.values():
                        if running(pid):
                            os.killpg(pid, signal.SIGKILL)
        finally:
            release.set()
            server.shutdown()
            server.server_close()

    def test_real_worker_recovers_synthetic_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pcm_fixture(root, duration=.1)
            result = ProcessingWorker(PROJECT).run('recover', root, {}, lambda _: None)
            self.assertAlmostEqual(result, .1)
            self.assertTrue((root / 'recording.wav').exists())

    def test_cancellation_terminates_a_worker_waiting_for_http(self):
        entered, release = threading.Event(), threading.Event()
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                entered.set()
                release.wait(10)
                self.send_response(500)
                self.end_headers()
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            atomic_json(root / 'transcript.json', [dict(start=0, end=1, text='Synthetic speech.', speaker=None)])
            settings = dict(DEFAULTS, summarizer='local', local_ai_base_url=f'http://127.0.0.1:{server.server_port}/v1')
            cancel, result = threading.Event(), []
            def run():
                try:
                    ProcessingWorker(PROJECT).run('summarize', root, settings, lambda _: None, key='private-test-key', cancel=cancel)
                except JobCancelled:
                    result.append('cancelled')
            thread = threading.Thread(target=run)
            thread.start()
            try:
                self.assertTrue(entered.wait(10))
                cancel.set()
                thread.join(5)
                self.assertFalse(thread.is_alive())
                self.assertEqual(result, ['cancelled'])
                self.assertFalse((root / 'minutes.json').exists())
                self.assertNotIn('private-test-key', (root / 'processing.log').read_text())
            finally:
                cancel.set()
                release.set()
                thread.join(5)
