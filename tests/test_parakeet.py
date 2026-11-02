import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import wave

from app import parakeet, processing
from app.service import DEFAULTS, MeetingService
from app.storage import atomic_json
from app.speaker_alignment import align
from tests.test_calendar import FakeGoogle

PROJECT=Path(__file__).resolve().parents[1]


def token(text,start,end):return SimpleNamespace(text=text,start=start,end=end)


class TokenTests(unittest.TestCase):
    def test_subwords_keep_english_terms_and_original_word_times(self):
        result=SimpleNamespace(text='Обнови Kubernetes cluster.',tokens=[token('Об',0,.1),token('нови',.1,.3),token(' Ku',.4,.5),token('bernet',.5,.7),token('es',.7,.9),token(' cluster',1,1.3),token('.',1.3,1.4)])
        units=parakeet.word_units(result,60,2)
        self.assertEqual([u['text'] for u in units],['Обнови','Kubernetes','cluster.'])
        self.assertEqual([(u['start'],u['end']) for u in units],[(60,60.3),(60.4,60.9),(61,61.4)])

    def test_invalid_timing_and_unmatched_text_are_rejected(self):
        for result in [SimpleNamespace(text='a',tokens=[token('a',float('nan'),1)]),SimpleNamespace(text='a',tokens=[token('a',2,1)]),SimpleNamespace(text='a',tokens=[token('a',0,9)]),SimpleNamespace(text='different',tokens=[token('a',0,1)])]:
            with self.subTest(result=result),self.assertRaises(ValueError):parakeet.word_units(result,0,2)
        self.assertEqual(parakeet.word_units(SimpleNamespace(text='',tokens=[]),0,2),[])

    def test_capability_check_does_not_load_mlx_or_allow_intel(self):
        with patch('app.parakeet.platform.machine',return_value='x86_64'),patch('app.parakeet.util.find_spec') as find:
            self.assertFalse(parakeet.availability()['available']);find.assert_not_called()
        with patch('app.parakeet.sys.platform','darwin'),patch('app.parakeet.platform.machine',return_value='arm64'),patch('app.parakeet.util.find_spec',return_value=None):
            self.assertFalse(parakeet.availability()['available'])
            with self.assertRaisesRegex(RuntimeError,'not included'):parakeet.Decoder('/unused',lambda _:None)


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        with wave.open(str(self.root/'recording.wav'),'wb') as out:
            out.setnchannels(1);out.setsampwidth(2);out.setframerate(16000);out.writeframes(b'\0\0'*16000*70)
        self.original=(self.root/'recording.wav').read_bytes()
        self.settings=dict(DEFAULTS,transcription='parakeet',models_dir=str(self.root/'models'),diarization_enabled=True,whisper_vad=False)
        self.calls=[];self.fail_at=None;self.empty=False
        case=self
        class Decoder:
            def __init__(self,*args):pass
            def transcribe(self,samples,offset,rate):
                case.calls.append(offset)
                if case.fail_at==len(case.calls):raise RuntimeError('synthetic interruption')
                return [] if case.empty else [dict(start=offset,end=offset+1,text='Обнови',speaker=None),dict(start=offset+1,end=offset+2,text='Kubernetes.',speaker=None)]
        self.stub=patch('app.parakeet.Decoder',Decoder);self.stub.start();self.addCleanup(self.stub.stop)

    def run_transcribe(self):processing.transcribe(self.root,self.settings,lambda _:None)

    def test_publishes_native_word_alignment_usable_for_speaker_assignment(self):
        with patch('app.processing.ensure_model',side_effect=AssertionError('Must not load Whisper')):self.run_transcribe()
        data=json.loads((self.root/'transcript.json').read_text());metadata=json.loads((self.root/'transcript.metadata.json').read_text())
        saved=json.loads((self.root/'transcript.alignment.json').read_text())
        self.assertEqual(metadata['provider'],'parakeet');self.assertEqual(metadata['model'],parakeet.MODEL_NAME)
        self.assertEqual(metadata['model_revision'],parakeet.MODEL_REVISION);self.assertFalse(metadata['vocabulary_applied'])
        self.assertEqual(saved['method'],parakeet.ALIGNMENT_METHOD)
        assigned=align(data,saved,[dict(start=0,end=70,speaker='SPEAKER_00')])
        self.assertTrue(all(s['speaker']=='SPEAKER_00' for s in assigned))
        self.assertEqual((self.root/'recording.wav').read_bytes(),self.original)
        self.assertFalse((self.root/'.transcription-progress.json').exists())

    def test_resume_keeps_previous_transcript_and_notes_until_success(self):
        atomic_json(self.root/'transcript.json',[dict(start=0,end=1,text='Старо',speaker=None)])
        atomic_json(self.root/'minutes.json',{'saved':'human corrections'})
        self.fail_at=2
        with self.assertRaisesRegex(RuntimeError,'interruption'):self.run_transcribe()
        checkpoint=json.loads((self.root/'.transcription-progress.json').read_text())
        self.assertEqual(json.loads((self.root/'minutes.json').read_text()),{'saved':'human corrections'})
        self.assertEqual(json.loads((self.root/'transcript.json').read_text())[0]['text'],'Старо')
        self.fail_at=None;self.calls.clear();self.run_transcribe()
        self.assertEqual(self.calls,[checkpoint['cursor']/16000])
        self.assertTrue(list((self.root/'versions').glob('*/minutes.json')))
        self.assertFalse((self.root/'minutes.json').exists())

    def test_voice_detection_skips_silent_chunks_and_trims_each_chunk_to_speech(self):
        offsets=[];lengths=[]
        class Detector:
            def probabilities(self,samples):
                # Speech only from 10 s to 20 s of the first minute.
                windows=-(-len(samples)//512);start=len(offsets)==0
                return __import__('numpy').array([.9 if start and 10*16000<=i*512<20*16000 else 0 for i in range(windows)])
        case=self
        class Decoder:
            def __init__(self,*args):pass
            def transcribe(self,samples,offset,rate):
                offsets.append(offset);lengths.append(len(samples)/rate);return [dict(start=offset,end=offset+1,text='Обнови',speaker=None)]
        with patch('app.parakeet.Decoder',Decoder),patch('app.vad.load',return_value=(Detector(),None)):
            processing.transcribe(self.root,dict(self.settings,whisper_vad=True),lambda _:None)
        self.assertEqual(len(offsets),1)
        # Speech starts at the first 32 ms window after 10 s; each side keeps 0.3 s of context.
        self.assertAlmostEqual(offsets[0],9.716,places=3);self.assertAlmostEqual(lengths[0],10.584,places=3)
        metadata=json.loads((self.root/'transcript.metadata.json').read_text());self.assertTrue(metadata['vad'])

    def test_missing_voice_detection_keeps_whole_chunks(self):
        with patch('app.vad.load',return_value=(None,'unavailable: synthetic')):
            processing.transcribe(self.root,dict(self.settings,whisper_vad=True),lambda _:None)
        self.assertEqual(self.calls,[0,self.calls[1]])
        metadata=json.loads((self.root/'transcript.metadata.json').read_text())
        self.assertEqual((metadata['vad'],metadata['vad_error']),(False,'unavailable: synthetic'))

    def test_new_model_revision_does_not_reuse_old_checkpoint(self):
        self.fail_at=2
        with self.assertRaises(RuntimeError):self.run_transcribe()
        self.fail_at=None;self.calls.clear()
        with patch('app.parakeet.MODEL_REVISION','another-model-revision'):self.run_transcribe()
        self.assertEqual(self.calls[0],0)

    def test_empty_result_does_not_replace_existing_transcript(self):
        atomic_json(self.root/'transcript.json',[dict(start=0,end=1,text='Старо',speaker=None)])
        self.empty=True
        with self.assertRaisesRegex(ValueError,'No speech'):self.run_transcribe()
        self.assertEqual(json.loads((self.root/'transcript.json').read_text())[0]['text'],'Старо')

    def test_settings_choose_parakeet_without_changing_live_whisper_model(self):
        service=MeetingService(self.root/'library',PROJECT,google=FakeGoogle());self.addCleanup(service.close)
        with patch('app.parakeet.availability',return_value=dict(available=False,message='Parakeet requires Apple Silicon.')):
            with self.assertRaisesRegex(ValueError,'Apple Silicon'):service.save_settings({'transcription':'parakeet'})
        self.assertEqual(service.settings['transcription'],'local')
        previous=service.settings['local_model']
        with patch('app.parakeet.availability',return_value=dict(available=True,message='')):result=service.save_settings({'transcription':'parakeet'})
        self.assertEqual(service.settings['transcription'],'parakeet');self.assertEqual(service.settings['local_model'],previous)
