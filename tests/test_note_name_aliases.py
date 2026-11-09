import tempfile
import unittest
from pathlib import Path

from app.service import MeetingService
from meeting_assistant import llm_prompt
from tests.test_calendar import FakeGoogle

PROJECT = Path(__file__).resolve().parents[1]


class NoteNameAliasesTests(unittest.TestCase):
    def test_the_prompt_lists_other_names_and_says_which_one_to_write(self):
        prompt = llm_prompt('[00:00:01] Мими: Ще проверя.', [dict(name='Мария Петрова', aliases=['Мими', 'Мария']), dict(name='Иван', aliases=[]), 'Петър'])
        self.assertIn('- Мария Петрова (наричан също: Мими, Мария)', prompt)
        self.assertIn('- Иван\n', prompt)
        self.assertIn('- Петър', prompt)
        self.assertIn('пиши името преди скобите', prompt)

    def test_plain_names_still_work(self):
        self.assertIn('- Мария Петрова', llm_prompt('[00:00:01] текст', ['Мария Петрова']))

    def test_the_notes_step_gets_people_with_their_aliases(self):
        tmp = tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        s = MeetingService(Path(tmp.name), PROJECT, google=FakeGoogle());self.addCleanup(s.close)
        s.save_person(dict(name='Мария Петрова', aliases=['Мими']));s.save_person(dict(name='Иван'))
        self.assertEqual(s.note_names(), [dict(name='Иван', aliases=[]), dict(name='Мария Петрова', aliases=['Мими'])])


if __name__ == '__main__':
    unittest.main()
