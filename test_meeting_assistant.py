import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from meeting_assistant import (
    LiveMeeting,
    TranscriptSegment,
    clean_text,
    extract_json,
    merge_segments,
    read_wav,
    save_minutes,
    save_transcript,
    timestamp,
    write_wav,
)


class MeetingAssistantTests(unittest.TestCase):
    def test_timestamp(self):
        self.assertEqual(timestamp(3661.25), "01:01:01")
        self.assertEqual(timestamp(1.25, srt=True), "00:00:01,250")

    def test_clean_text(self):
        self.assertEqual(clean_text("  Здравей   [BLANK_AUDIO] свят "), "Здравей свят")

    def test_merge_segments(self):
        raw = [
            SimpleNamespace(t0=0, t1=100, text="Здравей"),
            SimpleNamespace(t0=120, t1=220, text="свят"),
        ]
        result = merge_segments(raw, 5)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].text, "Здравей свят")
        self.assertAlmostEqual(result[0].start, 5)
        self.assertAlmostEqual(result[0].end, 7.2)

    def test_wav_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audio.wav"
            samples = (np.sin(np.arange(16000) / 20) * 10000).astype(np.int16)
            write_wav(path, samples)
            np.testing.assert_array_equal(read_wav(path), samples)

    def test_iphone_rate_conversion(self):
        live = LiveMeeting.__new__(LiveMeeting)
        live.capture_rate = 48000
        samples = np.arange(1440, dtype=np.int16)
        converted = live.resample_frame(samples.tobytes())
        self.assertEqual(len(converted), 480)
        self.assertEqual(converted.dtype, np.int16)

    def test_exports(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            segments = [TranscriptSegment(0, 1.5, "Тест", "Иван")]
            save_transcript(output, segments)
            self.assertIn("Иван", (output / "transcript.md").read_text())
            self.assertEqual(json.loads((output / "transcript.json").read_text())[0]["text"], "Тест")
            self.assertIn("00:00:00,000 --> 00:00:01,500", (output / "transcript.srt").read_text())
            save_minutes(output, {
                "summary": ["Резюме"], "decisions": ["Решение"],
                "tasks": [{"task": "Задача", "owner": None, "deadline": None, "evidence_timestamp": "00:00:01"}],
                "open_questions": []
            })
            minutes = (output / "minutes.md").read_text()
            self.assertIn("Не е посочен", minutes)
            self.assertNotIn("Няма извлечени решения", minutes)

    def test_extract_json(self):
        self.assertEqual(extract_json('prefix {"summary": []} suffix')["summary"], [])


if __name__ == "__main__":
    unittest.main()
