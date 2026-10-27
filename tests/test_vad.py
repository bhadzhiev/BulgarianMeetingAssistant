import unittest
from unittest.mock import patch
import tempfile

import numpy as np

from app import vad


class SpanTests(unittest.TestCase):
    def windows(self, *values):
        return np.array([value for value, count in values for _ in range(count)], dtype=np.float32)

    def test_speech_starts_above_the_threshold_and_ends_after_a_pause(self):
        spans = vad.speech_spans(self.windows((0, 10), (.9, 20), (.4, 2), (.9, 10), (0, 10)))
        # A short dip above the release level does not split the speech.
        self.assertEqual(spans, [(10 * 512, 42 * 512)])

    def test_short_noise_bursts_are_not_speech(self):
        self.assertEqual(vad.speech_spans(self.windows((0, 5), (.9, 3), (0, 10))), [])

    def test_two_utterances_separated_by_silence_stay_apart(self):
        spans = vad.speech_spans(self.windows((.9, 12), (0, 20), (.9, 12)))
        self.assertEqual(spans, [(0, 12 * 512), (32 * 512, 44 * 512)])

    def test_speech_until_the_end_is_kept(self):
        self.assertEqual(vad.speech_spans(self.windows((0, 4), (.9, 10))), [(4 * 512, 14 * 512)])


class LoadTests(unittest.TestCase):
    def test_a_failed_download_or_runtime_returns_a_reason_instead_of_stopping(self):
        with tempfile.TemporaryDirectory() as folder, patch('app.model_cache.download', side_effect=OSError('offline')):
            detector, reason = vad.load(folder)
        self.assertIsNone(detector)
        self.assertEqual(reason, 'unavailable: offline')
