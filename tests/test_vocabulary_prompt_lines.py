import unittest

from app import correction, vocabulary
from meeting_assistant import llm_prompt


class VocabularyPromptLinesTests(unittest.TestCase):
    def test_one_line_per_term_and_names_left_out(self):
        text = 'Kubernetes | кубернетис\nexample.org | Ex Am Pull, ex.am\nМария Петрова\nМими\nИван | Иванчо'
        lines = vocabulary.prompt_lines(text, ['Мария Петрова', 'Мими', 'Иван'])
        self.assertEqual(lines.split('\n'), ['Kubernetes ← кубернетис', 'example.org ← Ex Am Pull, ex.am', 'Иван ← Иванчо'])
        self.assertEqual(vocabulary.prompt_lines('', ['Мария']), '')

    def test_the_notes_prompt_takes_names_from_the_name_list(self):
        prompt = llm_prompt('[00:00:01] текст', [dict(name='Мария Петрова', aliases=['Мими'])], vocabulary='Мария Петрова\nМими\nLIFT')
        vocab = prompt.split('чути варианти (след ←)')[1].split('ТРАНСКРИПТ:')[0]
        self.assertIn('LIFT', vocab);self.assertNotIn('Мими', vocab);self.assertNotIn('Мария Петрова', vocab)
        self.assertNotIn('"term"', prompt)

    def test_correction_sends_each_term_once(self):
        prompt = correction.system_prompt(dict(whisper_vocabulary='Kubernetes | кубернетис\nИван'), ['Иван', 'Мария'])
        self.assertEqual(prompt.count('Kubernetes'), 1)
        self.assertIn('Известни имена: Иван, Мария', prompt)
        self.assertEqual(prompt.count('Иван'), 1)
        self.assertNotIn('{', prompt.split('Речник и известни имена')[1])


if __name__ == '__main__':
    unittest.main()
