import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import sounddevice as sd

from app import correction, processing
from app.capture import Clock, Recorder
from app.local_ai import OutputTruncatedError, complete_json
from app.service import DEFAULTS
from app.storage import atomic_json


def notes(group):
    return dict(summary=[dict(text='Test note', evidence_timestamp=None)],
                decisions=[], tasks=[], open_questions=[])


class ProcessingReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.settings = dict(DEFAULTS, summarizer='local')
        self.segments = [dict(start=i * 10, end=i * 10 + 9, text=('Test ' * 260).strip(), speaker=None) for i in range(4)]
        atomic_json(self.root / 'transcript.json', self.segments)

    def run_notes(self, fake, settings=None):
        with patch('meeting_assistant.generate_minutes', side_effect=fake) as model:
            processing.summarize(self.root, settings or self.settings, lambda _: None, 'secret-key')
        return model

    def test_failed_notes_resume_only_completed_parts(self):
        calls = []
        def fail_later(args, group):
            calls.append(group[0].start)
            if len(calls) == 2:
                raise RuntimeError('offline')
            return notes(group)
        with self.assertRaisesRegex(RuntimeError, 'offline'):
            self.run_notes(fail_later)
        self.assertFalse((self.root / 'minutes.json').exists())
        self.assertNotIn('secret-key', (self.root / '.notes-progress.json').read_text())
        resumed = self.run_notes(lambda args, group: notes(group))
        self.assertEqual(resumed.call_count, 1)
        self.assertEqual(resumed.call_args.args[1][0].start, 30)
        self.assertFalse((self.root / '.notes-progress.json').exists())
        self.assertEqual(len(json.loads((self.root / 'minutes.json').read_text())['summary']), 2)

    def test_changed_configuration_invalidates_cached_notes(self):
        with self.assertRaises(RuntimeError):
            self.run_notes(lambda args, group: notes(group) if group[0].start == 0 else (_ for _ in ()).throw(RuntimeError()))
        model = self.run_notes(lambda args, group: notes(group), dict(self.settings, local_ai_model='different'))
        self.assertEqual(model.call_count, 2)

    def test_truncated_notes_split_and_keep_original_source_timestamps(self):
        self.segments = self.segments[:2]
        atomic_json(self.root / 'transcript.json', self.segments)
        def generate(args, group):
            if len(group) > 1:
                raise OutputTruncatedError('length')
            return notes(group)
        model = self.run_notes(generate)
        self.assertEqual([len(call.args[1]) for call in model.call_args_list], [2, 1, 1])
        self.assertEqual(len(json.loads((self.root / 'minutes.json').read_text())['summary']), 2)

    def test_failed_split_resume_skips_failed_parent_and_completed_child(self):
        atomic_json(self.root / 'transcript.json', self.segments[:2])
        def generate(args, group):
            if len(group) > 1:
                raise OutputTruncatedError('length')
            if group[0].start > 0:
                raise RuntimeError('offline')
            return notes(group)
        with self.assertRaises(RuntimeError):
            self.run_notes(generate)
        model = self.run_notes(lambda args, group: notes(group))
        self.assertEqual(model.call_count, 1)
        self.assertEqual(model.call_args.args[1][0].start, 10)

    def test_reasoning_only_truncation_does_not_start_split_retries(self):
        response = {'choices': [{'finish_reason': 'length', 'message': {'content': None, 'reasoning_content': 'thinking'}}]}
        with patch('meeting_assistant.post_json', return_value=response):
            with self.assertRaises(OutputTruncatedError) as caught:
                complete_json(self.settings, [], {}, 'test')
        self.assertFalse(caught.exception.can_split)
        with patch('meeting_assistant.generate_minutes', side_effect=caught.exception) as model:
            with self.assertRaises(OutputTruncatedError):
                processing.summarize(self.root, self.settings, lambda _: None)
        self.assertEqual(model.call_count, 1)

    def test_repeated_truncation_has_a_bounded_retry_budget(self):
        self.segments = [dict(start=i, end=i + 1, text='Test', speaker=None) for i in range(16)]
        atomic_json(self.root / 'transcript.json', self.segments)
        with patch('meeting_assistant.generate_minutes', side_effect=OutputTruncatedError('length')) as model:
            with self.assertRaises(OutputTruncatedError):
                processing.summarize(self.root, self.settings, lambda _: None)
        self.assertEqual(model.call_count, 3)
        self.assertFalse((self.root / 'minutes.json').exists())

    def test_correction_splits_truncated_output_without_changing_timing(self):
        atomic_json(self.root / 'transcript.json', self.segments[:2])
        def ask(settings, messages, schema, key):
            items = json.loads(messages[1]['content'])
            if len(items) > 1:
                raise OutputTruncatedError('length')
            return {'segments': items}
        with patch('app.correction.ask', side_effect=ask) as model:
            # Put both segments in one group to exercise the split path.
            with patch('app.correction.CHUNK_CHARS', 4000):
                correction.correct(self.root, self.settings, lambda _: None)
        self.assertEqual(model.call_count, 3)
        self.assertEqual(json.loads((self.root / 'transcript.json').read_text()), self.segments[:2])


class CaptureReliabilityTests(unittest.TestCase):
    def recorder(self, root):
        recorder = Recorder.__new__(Recorder)
        recorder.clock = Clock()
        recorder.rate = 48000
        recorder.directory = root
        recorder.info = {}
        recorder.input_overflows = 0
        recorder.warnings = []
        recorder.fatal = None
        recorder.system = None
        recorder.stream = SimpleNamespace(active=True)
        recorder.writer = SimpleNamespace(error=None, append=lambda *args: None)
        recorder.on_frame = None
        return recorder

    def test_transient_overflow_keeps_recording_and_persists_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            recorder = self.recorder(root)
            status = sd.CallbackFlags()
            status.input_overflow = True
            recorder._callback(b'\0\0' * 100, 100, SimpleNamespace(currentTime=1, inputBufferAdcTime=1), status)
            self.assertIsNone(recorder.error())
            recorder.checkpoint()
            self.assertEqual(json.loads((root / 'capture.json').read_text())['input_overflows'], 1)
            self.assertIn('gaps', recorder.warnings[0])
            recorder.stream.active = False
            self.assertIn('disconnected', recorder.error())

    def test_non_overflow_error_still_stops_capture(self):
        with tempfile.TemporaryDirectory() as tmp:
            recorder = self.recorder(Path(tmp))
            status = sd.CallbackFlags()
            status.input_underflow = True
            recorder._callback(b'\0\0' * 100, 100, SimpleNamespace(currentTime=1, inputBufferAdcTime=1), status)
            self.assertIn('lost audio', recorder.error())
