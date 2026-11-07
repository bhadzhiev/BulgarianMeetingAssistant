"""Recording buffer depth and reasoning-model JSON extraction resilience."""
import json
import tempfile
import unittest
from pathlib import Path

from app.capture import PCMWriter
from meeting_assistant import extract_json


class RecordingBufferTests(unittest.TestCase):
    def test_queue_absorbs_long_disk_spikes(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer = PCMWriter(Path(tmp) / 'mic.pcm', 16000)
            try:
                # 30 ms per callback: 1500 entries cover about 45 seconds of disk stalls.
                self.assertGreaterEqual(writer.queue.maxsize, 1500)
            finally:
                writer.close()


class ThinkStripTests(unittest.TestCase):
    def test_json_after_thinking_block(self):
        self.assertEqual(extract_json('<think>reasoning with {braces} inside</think>{"a": 1}'), {'a': 1})

    def test_text_before_and_after_thinking(self):
        self.assertEqual(extract_json('<think>long chain</think>\n{"found": true, "sources": [1]}'), {'found': True, 'sources': [1]})

    def test_plain_json_unchanged(self):
        self.assertEqual(extract_json('{"a": 1}'), {'a': 1})

    def test_tags_inside_json_strings_are_kept(self):
        # Repository reports quote code exactly; such a quote can contain the tags.
        quote = "if tag == '<think>': skip()  # closes at </think> later"
        self.assertEqual(extract_json(json.dumps({'quote': quote}))['quote'], quote)
        self.assertEqual(extract_json('<think>plan</think>' + json.dumps({'quote': quote}))['quote'], quote)

    def test_thinking_without_json_still_fails(self):
        with self.assertRaises(ValueError):
            extract_json('<think>only reasoning, the budget ran out</think>')


if __name__ == '__main__':
    unittest.main()
