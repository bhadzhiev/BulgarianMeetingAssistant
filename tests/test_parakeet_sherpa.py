import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import wave

from app import parakeet_sherpa as backend, processing
from app.service import DEFAULTS, MeetingService
from app.storage import atomic_json
from app.speaker_alignment import align
from tests.test_calendar import FakeGoogle

PROJECT = Path(__file__).resolve().parents[1]


class BackendTests(unittest.TestCase):
    def test_phrases_keep_names_and_reject_decoder_control_syntax(self):
        self.assertEqual(backend.vocabulary_terms('Kubernetes, Иван Петров; PostgreSQL\nKubernetes', ['Мария']),
                         ['Kubernetes', 'Иван Петров', 'PostgreSQL', 'Мария'])
        for value in ['CI/CD', 'name :99']:
            with self.assertRaisesRegex(ValueError, 'cannot contain'):
                backend.vocabulary_terms(value)

    def test_unknown_characters_fail_before_inference(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); tokens = root / 'tokens.txt'
            tokens.write_text('<unk> 0\n▁ 1\nИ 2\nв 3\nа 4\nн 5\n')
            backend.prepare_vocabulary(tokens, root / 'nested/bpe.vocab', ['Иван'])
            self.assertIn('И\t-1.0', (root / 'nested/bpe.vocab').read_text())
            with self.assertRaisesRegex(ValueError, 'unsupported'):
                backend.prepare_vocabulary(tokens, root / 'nested/bpe.vocab', ['Иван🦊'])

    def test_native_token_durations_preserve_word_anchors(self):
        result = SimpleNamespace(text='Обнови Kubernetes.', tokens=['▁Об', 'нови', '▁Kuber', 'netes', '.'],
                                 timestamps=[0, .1, .5, .7, .9], durations=[.1, .2, .2, .2, .1])
        units = backend.result_units(result, 60, 2)
        self.assertEqual([x['text'] for x in units], ['Обнови', 'Kubernetes.'])
        self.assertEqual(units[1]['start'], 60.5)
        self.assertEqual(units[1]['end'], 61)
        for mutation in [dict(durations=[]), dict(durations=[-1]*5), dict(timestamps=[float('nan')]*5), dict(text='different')]:
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                backend.result_units(SimpleNamespace(**(vars(result) | mutation)), 0, 2)

    def test_missing_or_unfixed_runtime_is_unavailable_without_importing_native_module(self):
        for installed in ['1.12.25', 'unknown']:
            with patch.object(backend.util, 'find_spec', return_value=object()), patch.object(backend, 'version', return_value=installed):
                self.assertFalse(backend.availability()['available'])
        with patch.object(backend, 'availability', return_value=dict(available=False, message='not installed')):
            with self.assertRaisesRegex(RuntimeError, 'not installed'):
                backend.Decoder('/unused', lambda _: None)

    def test_stream_receives_hotwords_and_length_reward_not_a_post_text_replacement(self):
        import numpy as np
        model = backend.Decoder.__new__(backend.Decoder)
        from unittest.mock import Mock
        stream = Mock(); stream.result = SimpleNamespace(text='Иван', tokens=['▁Иван'], timestamps=[.1], durations=[.2])
        model.model = Mock(); model.model.create_stream.return_value = stream
        model.hotwords = 'Иван/Kubernetes'
        self.assertEqual(model.transcribe(np.zeros(16000, dtype=np.int16), 5)[0]['text'], 'Иван')
        model.model.create_stream.assert_called_once_with('Иван/Kubernetes')
        stream.set_option.assert_called_once_with('length_reward', '0.5')
        model.model.decode_stream.assert_called_once_with(stream)
        with self.assertRaisesRegex(ValueError, '16 kHz'):
            model.transcribe(np.zeros(5), 0, 44100)


class PipelineTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup); self.root = Path(tmp.name)
        with wave.open(str(self.root / 'recording.wav'), 'wb') as out:
            out.setnchannels(1); out.setsampwidth(2); out.setframerate(16000); out.writeframes(b'\0\0' * 16000 * 70)
        self.original = (self.root / 'recording.wav').read_bytes()
        self.settings = dict(DEFAULTS, transcription='parakeet_sherpa', models_dir=str(self.root / 'models'),
                             whisper_vocabulary='Kubernetes', whisper_vad=False)
        self.calls = []; self.fail = False; case = self
        class Decoder:
            def __init__(self, models, progress, vocabulary, speakers):
                self.terms = backend.vocabulary_terms(vocabulary, speakers)
            def transcribe(self, samples, offset, rate):
                case.calls.append(offset)
                if case.fail and len(case.calls) == 2:
                    raise RuntimeError('interrupted')
                return [dict(start=offset, end=offset+1, text='Kubernetes', speaker=None)]
        stub = patch.object(backend, 'Decoder', Decoder); stub.start(); self.addCleanup(stub.stop)

    def run_transcribe(self):
        processing.transcribe(self.root, self.settings, lambda _: None, speakers=['Иван'])

    def test_alignment_metadata_and_raw_audio_survive(self):
        self.run_transcribe()
        data = json.loads((self.root/'transcript.json').read_text())
        saved = json.loads((self.root/'transcript.alignment.json').read_text())
        metadata = json.loads((self.root/'transcript.metadata.json').read_text())
        self.assertEqual(saved['method'], backend.ALIGNMENT_METHOD)
        self.assertTrue(all(x['speaker']=='SPEAKER_00' for x in align(data, saved, [dict(start=0,end=70,speaker='SPEAKER_00')])))
        self.assertTrue(metadata['vocabulary_applied'])
        self.assertEqual(metadata['vocabulary_terms'], ['Kubernetes', 'Иван'])
        self.assertEqual(metadata['model_revision'], backend.MODEL_REVISION)
        self.assertEqual((self.root/'recording.wav').read_bytes(), self.original)

    def test_dictionary_and_decoder_changes_invalidate_checkpoint_without_losing_saved_work(self):
        for change in ['vocabulary', 'score']:
            self.calls.clear(); self.fail = True
            atomic_json(self.root/'transcript.json', [dict(start=0,end=1,text='Старо',speaker=None)])
            with self.assertRaisesRegex(RuntimeError, 'interrupted'): self.run_transcribe()
            self.assertEqual(json.loads((self.root/'transcript.json').read_text())[0]['text'], 'Старо')
            self.calls.clear(); self.fail = False
            if change == 'vocabulary':
                self.settings['whisper_vocabulary'] = 'PostgreSQL'; self.run_transcribe()
            else:
                with patch.object(backend, 'HOTWORDS_SCORE', 2): self.run_transcribe()
            self.assertEqual(self.calls[0], 0)

    def test_settings_readiness_and_missing_dependency(self):
        service = MeetingService(self.root/'library', PROJECT, google=FakeGoogle()); self.addCleanup(service.close)
        with patch.object(backend, 'availability', return_value=dict(available=False,message='not installed')):
            with self.assertRaisesRegex(ValueError, 'not installed'):
                service.save_settings(dict(transcription='parakeet_sherpa'))
        with patch.object(backend, 'availability', return_value=dict(available=True,message='')), patch.object(backend, 'cached', return_value=False):
            service.save_settings(dict(transcription='parakeet_sherpa',whisper_vocabulary='Иван'))
            self.assertFalse(service.readiness()['model']['ready'])
            self.assertIn('670 MB', service.readiness()['model']['label'])
        with patch.object(backend, 'availability', return_value=dict(available=True,message='')), patch.object(backend, 'cached', return_value=True):
            self.assertTrue(service.readiness()['model']['ready'])
