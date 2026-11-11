"""A context budget that fits the request, and a refused automatic run after an import that a person can see."""
from pathlib import Path
import tempfile
import unittest

from app.service import MeetingService
from tests.test_calendar import FakeGoogle

PROJECT = Path(__file__).resolve().parents[1]


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.s = MeetingService(root / 'library', PROJECT, google=FakeGoogle(), backup_dir=root / 'backups')
        self.addCleanup(self.s.close)

    def test_settings_refuse_an_output_limit_that_fills_the_context(self):
        with self.assertRaisesRegex(ValueError, 'leaves no room for the transcript'):
            self.s.validate_settings(dict(self.s.settings, local_ai_context=4096, local_ai_max_tokens=4096))
        self.s.validate_settings(dict(self.s.settings, local_ai_context=16384, local_ai_max_tokens=4096))

    def test_a_refused_automatic_run_after_a_transcript_import_is_visible(self):
        self.s.settings.update(auto_process=True, summarizer='openai', transcript_correction='none', auto_title=False)
        self.s.api_key = ''
        detail = self.s.import_transcript('[00:00] Иван: Проверяваме системата.', 'qa.txt')
        # The import itself worked: the transcript is ready and is not an error.
        self.assertEqual((detail['status'], detail['error'], detail['minutes']), ('ready', None, None))
        self.assertTrue(detail['transcript'])
        self.assertIn('Notes were not made automatically', detail['notes_refresh_error'])
        self.assertIn('OpenAI API key', detail['notes_refresh_error'])


if __name__ == '__main__':
    unittest.main()
