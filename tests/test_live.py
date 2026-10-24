import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import numpy as np

from app.live import CaptionEngine, LiveSession, read_window, run_worker
from app.service import MeetingService
from app.storage import atomic_json
from tests.test_app import FakeRecorder, wait_for

PROJECT = Path(__file__).resolve().parents[1]


def speech(seconds, rate=16000):
    return (np.sin(np.arange(round(seconds*rate))*2*np.pi*300/rate)*8000).astype(np.int16)


class CaptionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.directory=Path(self.tmp.name)
        self.info=dict(mode='in_person',microphone_rate=16000,system_rate=48000,duration=0)
    def tearDown(self):self.tmp.cleanup()
    def test_partial_revisions_commit_once_after_silence(self):
        (self.directory/'microphone.pcm').write_bytes(speech(5).tobytes()+b'\0\0'*16000)
        decoded=[]
        def decode(samples):
            decoded.append(len(samples));return ['Здравей','Здравей свят','Здравей свят.'][len(decoded)-1]
        engine=CaptionEngine(self.directory,decode)
        engine.step(self.info,2.5)
        self.assertEqual(engine.state['partial']['text'],'Здравей')
        self.assertEqual(engine.state['segments'],[])
        engine.step(self.info,5)
        self.assertEqual(engine.state['partial']['text'],'Здравей свят')
        engine.step(self.info,6,stopping=True)
        engine.finish()
        self.assertEqual([s['text'] for s in engine.state['segments']],['Здравей свят.'])
        self.assertIsNone(engine.state['partial'])
        self.assertEqual(json.loads((self.directory/'live-transcript.json').read_text())[0]['text'],'Здравей свят.')
        self.assertFalse((self.directory/'transcript.json').exists())
    def test_silence_never_decodes(self):
        (self.directory/'microphone.pcm').write_bytes(b'\0\0'*16000*3)
        engine=CaptionEngine(self.directory,lambda _:self.fail('Silence should not invoke Whisper'))
        engine.step(self.info,3)
        self.assertEqual(engine.cursor,3)
    def test_pausing_flushes_short_tail_without_duplicates(self):
        (self.directory/'microphone.pcm').write_bytes(speech(1).tobytes())
        engine=CaptionEngine(self.directory,lambda _:'Кратка фраза')
        engine.step(self.info,1,stopping=True)
        engine.step(self.info,1,stopping=True)
        self.assertEqual(len(engine.state['segments']),1)
    def test_long_speech_is_bounded_and_backlog_lives_on_disk(self):
        (self.directory/'microphone.pcm').write_bytes(speech(40).tobytes())
        def decode(samples):
            self.assertLessEqual(len(samples),12*16000);return 'Текст'
        engine=CaptionEngine(self.directory,decode)
        engine.step(self.info,40)
        self.assertEqual(engine.cursor,12)
        engine.step(self.info,40)
        self.assertEqual(engine.cursor,24)
    def test_window_boundary_commits_even_before_the_next_partial_interval(self):
        (self.directory/'microphone.pcm').write_bytes(speech(20).tobytes())
        engine=CaptionEngine(self.directory,lambda _:'Продължителна реч')
        engine.step(self.info,11.8)
        self.assertEqual(len(engine.state['segments']),0)
        engine.step(self.info,12.2)
        self.assertEqual(len(engine.state['segments']),1)
        self.assertEqual(engine.cursor,12)
    def test_online_remote_audio_is_included_when_microphone_is_silent(self):
        self.info['mode']='online'
        (self.directory/'microphone.pcm').write_bytes(b'\0\0'*16000*3)
        (self.directory/'system.pcm').write_bytes(speech(3,48000).tobytes())
        samples=read_window(self.directory,self.info,0,3)
        self.assertGreater(np.sqrt(np.mean(samples**2)),.1)
        engine=CaptionEngine(self.directory,lambda _:'Отдалечен участник')
        engine.step(self.info,3,stopping=True)
        self.assertEqual(engine.state['segments'][0]['text'],'Отдалечен участник')
    def test_out_of_band_energy_is_filtered_during_resampling(self):
        self.info['microphone_rate']=48000
        high=(np.sin(np.arange(48000)*2*np.pi*12000/48000)*16000).astype(np.int16)
        (self.directory/'microphone.pcm').write_bytes(high.tobytes())
        result=read_window(self.directory,self.info,0,1)
        self.assertLess(np.sqrt(np.mean(result**2)),.02)
    def test_stop_before_model_slot_is_free_does_not_launch_a_model(self):
        slot=threading.Semaphore(0)
        session=LiveSession(self.directory,PROJECT,{},slot)
        with patch('app.live.subprocess.Popen') as process:
            session.start();session.close()
        process.assert_not_called()
        self.assertEqual(session.snapshot()['status'],'stopped')
    def test_model_failure_preserves_raw_recording(self):
        (self.directory/'microphone.pcm').write_bytes(speech(1).tobytes())
        with patch('app.live.ensure_model',return_value='/tmp/fake.bin'), patch('pywhispercpp.model.Model',side_effect=RuntimeError('model unavailable')):
            with self.assertRaisesRegex(RuntimeError,'model unavailable'):
                run_worker(self.directory,self.directory/'models','tiny')
        self.assertTrue((self.directory/'microphone.pcm').exists())
        self.assertEqual(json.loads((self.directory/'live.json').read_text())['status'],'error')
    def test_worker_flushes_on_stop_and_saves_draft(self):
        from types import SimpleNamespace
        (self.directory/'microphone.pcm').write_bytes(speech(1).tobytes())
        atomic_json(self.directory/'capture.json',dict(self.info,duration=1))
        (self.directory/'.live-stop').touch()
        model=SimpleNamespace(transcribe=lambda *a,**kw:[SimpleNamespace(text='Тест на работния процес')])
        with patch('app.live.ensure_model',return_value='/tmp/fake.bin'), patch('pywhispercpp.model.Model',return_value=model):
            run_worker(self.directory,self.directory/'models','tiny')
        self.assertEqual(json.loads((self.directory/'live.json').read_text())['status'],'stopped')
        self.assertIn('Тест на работния процес',(self.directory/'live-transcript.md').read_text())


class LiveLifecycleTests(unittest.TestCase):
    def test_library_search_includes_saved_live_drafts(self):
        from app.storage import Library
        with tempfile.TemporaryDirectory() as root:
            library=Library(Path(root))
            meeting=library.create('Test','in_person',{})
            (library.directory(meeting['id'])/'live-transcript.md').write_text('Текуща транскрипция')
            self.assertEqual(len(library.list('ТРАНСКРИПЦИЯ')),1)

    def test_recording_starts_live_session_exposes_draft_and_signals_stop(self):
        class FakeLive:
            def __init__(self,directory,project,settings,slot):self.started=False;self.stopped=False
            def start(self):self.started=True
            def snapshot(self):return dict(status='listening',segments=[],partial=dict(start=0,end=.1,text='Жив текст'),processed_until=.1)
            def request_stop(self):self.stopped=True
            def close(self):self.request_stop()
        with tempfile.TemporaryDirectory() as root:
            service=MeetingService(Path(root),PROJECT)
            service.save_settings({'auto_process':False})
            try:
                with patch('app.service.devices',return_value=[{'id':2}]),patch('app.service.Recorder',FakeRecorder),patch('app.service.LiveSession',FakeLive):
                    meeting=service.start('Live test','online',2);mid=meeting['id']
                    wait_for(lambda:mid in service.live_sessions)
                    live=service.live_sessions[mid]
                    self.assertTrue(live.started)
                    self.assertEqual(service.snapshot()['active']['live']['partial']['text'],'Жив текст')
                    service.stop();wait_for(lambda:service.library.get(mid)['status']=='recorded')
                    self.assertTrue(live.stopped)
            finally:service.close()


class ModelCacheTests(unittest.TestCase):
    def response(self, chunks, expected):
        from unittest.mock import MagicMock
        response=MagicMock()
        response.__enter__.return_value=response
        response.headers={'content-length':str(expected)}
        response.iter_content.return_value=iter(chunks)
        return response
    def test_incomplete_download_never_creates_final_model(self):
        from app.model_cache import ensure_model
        with tempfile.TemporaryDirectory() as root:
            directory=Path(root)
            with patch('requests.get',return_value=self.response([b'partial'],100)):
                with self.assertRaisesRegex(RuntimeError,'Incomplete'):ensure_model('tiny',directory)
            self.assertFalse((directory/'ggml-tiny.bin').exists())
    def test_successful_download_is_reused_without_network(self):
        from app.model_cache import ensure_model
        with tempfile.TemporaryDirectory() as root:
            directory=Path(root)
            with patch('requests.get',return_value=self.response([b'complete'],8)) as request:
                first=ensure_model('tiny',directory)
                second=ensure_model('tiny',directory)
            self.assertEqual(first,second)
            self.assertEqual(Path(first).read_bytes(),b'complete')
            self.assertEqual(request.call_count,1)
