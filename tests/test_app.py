import io
import json
import queue
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import wave

import numpy as np

from app.capture import Clock, PCMWriter, Recorder, render_recording
from app.storage import Library, atomic_json
from app.service import MeetingService
from app import processing
from meeting_assistant import TranscriptSegment, merge_segments, save_transcript, save_minutes, validate_minutes

PROJECT = Path(__file__).resolve().parents[1]


def wait_for(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.01)
    raise AssertionError('Timed out waiting for background operation')


def pcm_fixture(path, duration=1, online=False):
    rate = 48000
    samples = (np.sin(np.arange(int(rate*duration))*2*np.pi*440/rate)*6000).astype(np.int16)
    (path/'microphone.pcm').write_bytes(samples.tobytes())
    if online:
        (path/'system.pcm').write_bytes(samples.tobytes())
    atomic_json(path/'capture.json',dict(mode='online' if online else 'in_person',microphone_rate=rate,system_rate=rate,duration=duration))
    return samples


class DurableAudioTests(unittest.TestCase):
    def test_writer_preserves_gaps_and_trims_overlap(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'track.pcm'
            writer=PCMWriter(path,16000)
            writer.append(2,np.array([10,20,30],dtype=np.int16).tobytes())
            writer.append(4,np.array([99,40],dtype=np.int16).tobytes())
            writer.close()
            self.assertIsNone(writer.error)
            np.testing.assert_array_equal(np.frombuffer(path.read_bytes(),dtype=np.int16),[0,0,10,20,30,40])

    def test_clock_pause_removes_pause_from_timeline(self):
        with patch('app.capture.time.monotonic', side_effect=[10,12,19,20]):
            clock=Clock()
            self.assertEqual(clock.pause(True),12)
            self.assertEqual(clock.elapsed(),2)
            self.assertEqual(clock.pause(False),19)
            self.assertEqual(clock.elapsed(),3)

    def test_raw_audio_recovers_without_wav_header(self):
        with tempfile.TemporaryDirectory() as root:
            directory=Path(root)
            pcm_fixture(directory)
            render_recording(directory)
            with wave.open(str(directory/'recording.wav'),'rb') as wav:
                self.assertEqual((wav.getframerate(),wav.getnchannels()),(16000,1))
                self.assertAlmostEqual(wav.getnframes()/16000,1,places=2)
            self.assertTrue((directory/'microphone.pcm').exists())

    def test_online_mix_contains_both_tracks(self):
        with tempfile.TemporaryDirectory() as root:
            directory=Path(root)
            pcm_fixture(directory,online=True)
            render_recording(directory)
            with wave.open(str(directory/'recording.wav'),'rb') as wav:
                mixed=np.frombuffer(wav.readframes(wav.getnframes()),dtype=np.int16)
            self.assertGreater(np.sqrt(np.mean(mixed.astype(float)**2)),7500)
            self.assertAlmostEqual(len(mixed)/16000,1,places=2)

    def test_checkpoint_does_not_truncate_more_recent_raw_audio(self):
        with tempfile.TemporaryDirectory() as root:
            directory=Path(root);pcm_fixture(directory)
            info=json.loads((directory/'capture.json').read_text());info['duration']=.1;atomic_json(directory/'capture.json',info)
            self.assertAlmostEqual(render_recording(directory),1)

    def test_queue_overflow_becomes_explicit_error(self):
        writer=PCMWriter.__new__(PCMWriter);writer.error=None;writer.queue=queue.Queue(maxsize=1)
        writer.append(0,b'aa');writer.append(1,b'bb')
        self.assertIn('fell behind',writer.error)

    def test_pause_discards_microphone_data(self):
        recorder=Recorder.__new__(Recorder)
        recorder.clock=Clock();recorder.clock.pause(True)
        recorder.writer=SimpleNamespace(append=lambda *args:self.fail('Paused audio must not be saved'))
        recorder._callback(b'\xff\x7f'*10,10,None,None)
        self.assertEqual(recorder.level,0)


class LibraryTests(unittest.TestCase):
    def test_interrupted_recordings_and_jobs_are_recoverable(self):
        with tempfile.TemporaryDirectory() as root:
            lib=Library(Path(root));m=lib.create('Тест','in_person',{})
            lib.update(m['id'],status='recording');lib.recover()
            self.assertEqual(lib.get(m['id'])['status'],'interrupted')

    def test_paths_cannot_escape_library(self):
        with tempfile.TemporaryDirectory() as root:
            lib=Library(Path(root))
            for name in ['../README.md','/etc/passwd','bad','A'*32]:
                with self.assertRaises(ValueError):lib.directory(name)

    def test_searches_bulgarian_transcript(self):
        with tempfile.TemporaryDirectory() as root:
            lib=Library(Path(root));m=lib.create('Weekly','online',{})
            (lib.directory(m['id'])/'transcript.md').write_text('Доставка на оборудване')
            self.assertEqual(len(lib.list('ОБОРУДВАНЕ')),1)


class OutputTests(unittest.TestCase):
    def test_segments_have_bounded_duration_and_repetitions_survive(self):
        raw=[SimpleNamespace(t0=i*100,t1=(i+1)*100,text='Да') for i in range(60)]
        result=merge_segments(raw)
        self.assertGreater(len(result),1)
        self.assertEqual(sum(s.text.split().count('Да') for s in result),60)
        self.assertTrue(all(s.end-s.start<=10 for s in result))

    def test_notes_validate_shape_and_evidence(self):
        segments=[TranscriptSegment(0,10,'Текст')]
        good=dict(summary=[],decisions=[],open_questions=[],tasks=[dict(task='Тест',owner=None,deadline=None,evidence_timestamp='00:00:00')])
        validate_minutes(good,segments)
        good['tasks'][0]['evidence_timestamp']='00:00:05'
        with self.assertRaisesRegex(ValueError,'does not reference'):validate_minutes(good,segments)
        with self.assertRaises(ValueError):validate_minutes([])

    def test_failed_notes_validation_keeps_previous_output(self):
        with tempfile.TemporaryDirectory() as root:
            directory=Path(root)
            minutes=dict(summary=['Original'],decisions=[],tasks=[],open_questions=[])
            save_minutes(directory,minutes)
            with self.assertRaises(ValueError):save_minutes(directory,{'tasks':[]})
            self.assertEqual(json.loads((directory/'minutes.json').read_text()),minutes)

    def test_cloud_chunks_and_preserves_previous_transcript(self):
        with tempfile.TemporaryDirectory() as root:
            directory=Path(root)
            with wave.open(str(directory/'recording.wav'),'wb') as out:
                out.setnchannels(1);out.setsampwidth(2);out.setframerate(16000);out.writeframes(b'\0\0'*16000*65)
            save_transcript(directory,[TranscriptSegment(0,1,'Original')])
            def upload(audio,key,model):
                with wave.open(io.BytesIO(audio),'rb') as source:
                    self.assertLessEqual(source.getnframes()/16000,60)
                self.assertEqual(model,'gpt-transcribe')
                return {'text':'Нов текст'}
            settings=dict(transcription='openai',cloud_model='gpt-transcribe')
            with patch('app.processing.upload_audio',side_effect=upload) as mock:
                processing.transcribe(directory,settings,lambda _:None,'test-key')
                self.assertEqual(mock.call_count,2)
            self.assertEqual(len(list((directory/'versions').glob('*/transcript.json'))),1)
            metadata=json.loads((directory/'transcript.metadata.json').read_text())
            self.assertIn('approximate',metadata['timestamps'])
            final=json.loads((directory/'transcript.json').read_text())
            self.assertEqual(final[-1]['end'],65)

    def test_provider_failure_preserves_final_transcript(self):
        with tempfile.TemporaryDirectory() as root:
            directory=Path(root);pcm_fixture(directory);render_recording(directory)
            save_transcript(directory,[TranscriptSegment(0,1,'Original')])
            with patch('app.processing.upload_audio',side_effect=RuntimeError('offline')):
                with self.assertRaises(RuntimeError):processing.transcribe(directory,dict(transcription='openai',cloud_model='gpt-transcribe'),lambda _:None,'key')
            self.assertEqual(json.loads((directory/'transcript.json').read_text())[0]['text'],'Original')


class FakeRecorder:
    def __init__(self,directory,device,mode,helper):
        self.directory=directory;self.clock=Clock();self.level=.2
    def start(self):pcm_fixture(self.directory,duration=.1)
    def pause(self,paused):self.clock.pause(paused)
    def stop(self):pass
    def checkpoint(self):pass
    def error(self):return None


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.service=MeetingService(Path(self.tmp.name),PROJECT)
        self.service.save_settings({'auto_process':False,'live_transcription':False,'transcript_correction':'none'})
    def tearDown(self):
        self.service.close();self.tmp.cleanup()

    def test_record_pause_stop_reopen_transcribe_and_edit(self):
        with patch('app.service.devices',return_value=[{'id':2}]),patch('app.service.Recorder',FakeRecorder):
            meeting=self.service.start('Тестова среща','in_person',2);mid=meeting['id']
            wait_for(lambda:self.service.library.get(mid)['status']=='recording')
            self.service.pause(True);self.assertEqual(self.service.library.get(mid)['status'],'paused')
            self.service.pause(False);self.service.stop()
            wait_for(lambda:self.service.library.get(mid)['status']=='recorded')
        self.assertIn('recording.wav',self.service.detail(mid)['files'])
        def transcribe(directory,*args):save_transcript(directory,[TranscriptSegment(0,.1,'Здравей')])
        with patch('app.processing.transcribe',side_effect=transcribe):
            self.service.process(mid,'transcribe');wait_for(lambda:mid not in self.service.busy)
        detail=self.service.detail(mid);detail['transcript'][0]['text']='Корекция'
        self.service.edit(mid,{'transcript':detail['transcript']})
        self.assertEqual(self.service.detail(mid)['transcript'][0]['text'],'Корекция')
        self.assertEqual(self.service.library.get(mid)['status'],'ready')

    def test_second_recording_is_rejected(self):
        with patch('app.service.devices',return_value=[{'id':2}]),patch('app.service.Recorder',FakeRecorder):
            meeting=self.service.start('One','online',2)
            wait_for(lambda:self.service.library.get(meeting['id'])['status']=='recording')
            with self.assertRaisesRegex(ValueError,'already recording'):self.service.start('Two','online',2)

    def test_api_key_is_not_persisted(self):
        self.service.save_settings({'api_key':'test-secret','transcription':'openai'})
        self.assertNotIn('test-secret',self.service.settings_path.read_text())
        self.assertEqual(self.service.api_key,'test-secret')

    def test_cloud_without_key_does_not_start_processing(self):
        self.service.api_key='';self.service.save_settings({'transcription':'openai'})
        m=self.service.library.create('Meeting','in_person',{})
        self.service.library.update(m['id'],status='recorded')
        with self.assertRaisesRegex(ValueError,'API key'):self.service.process(m['id'],'transcribe')
        self.assertEqual(self.service.library.get(m['id'])['status'],'recorded')

    def test_edits_reject_invalid_timestamps(self):
        m=self.service.library.create('Meeting','in_person',{})
        self.service.library.update(m['id'],duration=10)
        for value in [-1,float('nan'),float('inf'),20]:
            with self.assertRaises(ValueError):self.service.edit(m['id'],{'transcript':[dict(start=value,end=value,text='x')]})

class CrashAndCLITests(unittest.TestCase):
    def test_raw_track_survives_process_exit_without_close(self):
        import subprocess
        import sys
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'track.pcm'
            code='''
import os, sys, time
from pathlib import Path
from app.capture import PCMWriter
writer=PCMWriter(Path(sys.argv[1]),16000)
writer.append(0,b"\\x01\\x00"*16000)
while writer.samples < 16000:
    time.sleep(.01)
os._exit(17)
'''
            result=subprocess.run([sys.executable,'-c',code,str(path)],cwd=PROJECT)
            self.assertEqual(result.returncode,17)
            self.assertEqual(path.stat().st_size,32000)

    def test_cli_inference_error_still_finalizes_audio(self):
        import meeting_assistant as m
        class CLIRecorder(FakeRecorder):
            def __init__(self,*args):
                super().__init__(*args);self.rate=48000;self.on_frame=None
            def start(self):
                super().start()
                data=(np.sin(np.arange(24000)/20)*10000).astype(np.int16).tobytes()
                self.on_frame(data,0);self.on_frame(data,24000)
        with tempfile.TemporaryDirectory() as root:
            live=m.LiveMeeting.__new__(m.LiveMeeting)
            live.output_dir=Path(root);live.args=m.build_parser().parse_args([])
            live.audio_queue=queue.Queue(maxsize=200);live.stop_requested=False
            live.buffer=[];live.pre_roll=__import__('collections').deque(maxlen=15)
            live.total_samples=0;live.silence=0;live.last_partial=0
            live.model=SimpleNamespace(transcribe=lambda *args,**kwargs:(_ for _ in ()).throw(RuntimeError('Inference failed')))
            with patch('app.capture.Recorder',CLIRecorder):
                with self.assertRaisesRegex(RuntimeError,'Inference failed'):live.run(2)
            self.assertTrue((Path(root)/'recording.wav').exists())
            self.assertTrue((Path(root)/'microphone.pcm').exists())
