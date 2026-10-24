import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
import wave

from app import processing
from app.whisper import apply_prompted_text, build_prompt, collapse_repeats, remove_hallucinations, repeats_prompt
from meeting_assistant import TranscriptSegment, clean_text


class HallucinationTests(unittest.TestCase):
    def test_subtitle_credits_and_video_endings_are_removed(self):
        for text in ['Субтитри от Ани Петрова', 'Абонирайте се!', 'Благодаря за гледането.',
                     'Редактор на субтитрите Петя Петрова', 'Не забравяйте да се абонирате за канала.',
                     'Субтитры сделал DimaTorzok', 'Thank you for watching!', 'Продължава...']:
            self.assertEqual(clean_text(text), '', text)

    def test_real_speech_stays(self):
        for text in ['Благодаря.', 'Благодаря за вниманието.', 'Клиентите се абонират за услугата.',
                     'Това е краят на спринта.', 'Да, да, разбира се.']:
            self.assertEqual(clean_text(text), text)

    def test_credit_is_removed_from_real_speech(self):
        self.assertEqual(remove_hallucinations('Добре, приключваме. Субтитри от Ани Петрова'), 'Добре, приключваме.')

    def test_loops_keep_one_copy(self):
        self.assertEqual(collapse_repeats('Да, да, да, да, да, да, добре.'), 'Да, добре.')
        self.assertEqual(collapse_repeats('Ще го направим. Ще го направим. Ще го направим. Ще го направим.'),
                         'Ще го направим.')
        self.assertEqual(collapse_repeats('не, не, не'), 'не, не, не')


class PromptTests(unittest.TestCase):
    def test_vocabulary_then_speakers_without_duplicates(self):
        self.assertEqual(build_prompt('Kubernetes, terraform;\nSAP', ['Иван Петров', 'sap']),
                         'Kubernetes, terraform, SAP, Иван Петров.')

    def test_copied_prompt_is_detected(self):
        prompt = 'Kubernetes, Иван Петров.'
        self.assertTrue(repeats_prompt('Иван.', prompt))
        self.assertTrue(repeats_prompt('Kubernetes, Иван Петров.', prompt))
        self.assertFalse(repeats_prompt('Иван ще обнови Kubernetes.', prompt))
        self.assertFalse(repeats_prompt('Иван.', ''))

    def test_empty_and_long_prompts(self):
        self.assertEqual(build_prompt('', []), '')
        prompt = build_prompt(', '.join(f'термин{i}' for i in range(200)))
        self.assertLess(len(prompt), 401)
        self.assertTrue(prompt.endswith('.'))


class AlignmentTests(unittest.TestCase):
    timed = [TranscriptSegment(2, 5, 'Първо, докъде стигна с Кубернет и с Кластера?'),
             TranscriptSegment(12, 16, 'Миграцията към Тераформ е готова.')]

    def test_prompted_words_keep_plain_timestamps(self):
        result = apply_prompted_text(self.timed, 'Първо, докъде стигна с Kubernetes Cluster? Миграцията към Terraform е готова.')
        self.assertEqual([(s.start, s.end) for s in result], [(2, 5), (12, 16)])
        self.assertEqual(result[0].text, 'Първо, докъде стигна с Kubernetes Cluster?')
        self.assertEqual(result[1].text, 'Миграцията към Terraform е готова.')

    def test_unrelated_prompted_text_is_ignored(self):
        self.assertEqual(apply_prompted_text(self.timed, 'Kubernetes, Terraform, SAP, OIDC.'), self.timed)
        self.assertEqual(apply_prompted_text(self.timed, ''), self.timed)

    def test_segment_without_prompted_words_keeps_plain_text(self):
        result = apply_prompted_text(self.timed, 'Първо, докъде стигна с Kubernetes Cluster?')
        self.assertEqual(result[1].text, self.timed[1].text)


class FakeModel:
    calls = []

    def __init__(self, path, **options):
        self.options = options

    def transcribe(self, audio, **params):
        FakeModel.calls.append(params.get('initial_prompt'))
        if params.get('initial_prompt'):
            return [SimpleNamespace(t0=0, t1=300, text='Говорим за Kubernetes. Абонирайте се!')]
        return [SimpleNamespace(t0=100, t1=150, text='Говорим за'), SimpleNamespace(t0=500, t1=560, text='Кубернетис.')]


class LocalTranscriptionTests(unittest.TestCase):
    def run_transcribe(self, settings, vad=lambda *_: '/models/vad.bin'):
        FakeModel.calls = []
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            with wave.open(str(directory / 'recording.wav'), 'wb') as out:
                out.setnchannels(1); out.setsampwidth(2); out.setframerate(16000); out.writeframes(b'\0\0' * 16000 * 5)
            with patch('pywhispercpp.model.Model', FakeModel), patch('app.processing.ensure_model', return_value='/models/m.bin'), \
                    patch('app.processing.ensure_vad_model', side_effect=vad):
                processing.transcribe(directory, dict(transcription='local', local_model='large-v3-turbo', models_dir=root, **settings),
                                      lambda _: None, '', ['Иван'])
            return (json.loads((directory / 'transcript.json').read_text()),
                    json.loads((directory / 'transcript.metadata.json').read_text()))

    def test_prompted_pass_fills_plain_segments(self):
        transcript, metadata = self.run_transcribe(dict(whisper_vocabulary='Kubernetes'))
        self.assertEqual(FakeModel.calls, ['', 'Kubernetes, Иван.'])
        self.assertEqual([(s['start'], s['end'], s['text']) for s in transcript],
                         [(1, 1.5, 'Говорим за'), (5, 5.6, 'Kubernetes.')])
        self.assertEqual(metadata['prompt'], 'Kubernetes, Иван.')
        self.assertTrue(metadata['vad'])

    def test_vad_failure_does_not_stop_transcription(self):
        def offline(*_):
            raise OSError('offline')
        transcript, metadata = self.run_transcribe(dict(whisper_vad=True), vad=offline)
        self.assertEqual(len(transcript), 2)
        self.assertFalse(metadata['vad'])
        self.assertIn('offline', metadata['vad_error'])
