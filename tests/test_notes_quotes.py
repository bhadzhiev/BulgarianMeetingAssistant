import json
import tempfile
import unittest
from pathlib import Path

from meeting_assistant import TranscriptSegment, llm_prompt, save_minutes, validate_minutes, verify_quotes, QUOTE_LIMIT


def segments():
    return [TranscriptSegment(0.0, 4.0, 'Миграцията на базата е готова наполовина, чакаме достъп от клиента.', 'Иван'),
            TranscriptSegment(5.0, 9.0, 'Мария ще подготви офертата до петък.', 'Мария')]


def notes(**extra):
    base = dict(summary=[], decisions=[], tasks=[], open_questions=[])
    base.update(extra)
    return base


class QuoteTests(unittest.TestCase):
    def test_a_quote_stays_only_when_its_words_are_in_the_transcript(self):
        minutes = notes(
            tasks=[dict(task='Подготви офертата', owner='Мария', deadline='петък', due_date=None, evidence_timestamp='00:00:05',
                        quote='Мария ще подготви  офертата до петък')],
            updates=[dict(text='Миграцията е наполовина', evidence_timestamp='00:00:00', quote='готова наполовина, чакаме ДОСТЪП'),
                     dict(text='Клиентът е съгласен', evidence_timestamp='00:00:00', quote='клиентът се съгласи')])
        self.assertEqual(verify_quotes(minutes, segments()), 1)
        # Case, spaces and punctuation do not matter; the words do.
        self.assertEqual(minutes['tasks'][0]['quote'], 'Мария ще подготви офертата до петък')
        self.assertEqual(minutes['updates'][0]['quote'], 'готова наполовина, чакаме ДОСТЪП')
        # A rewritten quote is no evidence: it goes, the statement stays.
        self.assertIsNone(minutes['updates'][1]['quote'])
        self.assertEqual(minutes['updates'][1]['text'], 'Клиентът е съгласен')
        validate_minutes(minutes, segments())

    def test_a_long_quote_is_cut_at_a_word(self):
        long = ' '.join(['дума'] * 200)
        minutes = notes(decisions=[dict(text='Решение', evidence_timestamp=None, quote=long)])
        verify_quotes(minutes, [TranscriptSegment(0.0, 1.0, long, None)])
        self.assertLessEqual(len(minutes['decisions'][0]['quote']), QUOTE_LIMIT)
        self.assertTrue(minutes['decisions'][0]['quote'].endswith('дума'))

    def test_old_notes_without_quotes_or_updates_stay_valid_and_unchanged(self):
        old = notes(decisions=[dict(text='Решение', evidence_timestamp='00:00:00')])
        validate_minutes(old, segments())
        self.assertNotIn('updates', old)  # an empty list is not added to saved notes
        self.assertNotIn('quote', old['decisions'][0])
        with self.assertRaisesRegex(ValueError, 'quote must be text'):
            validate_minutes(notes(decisions=[dict(text='Решение', evidence_timestamp=None, quote=7)]))

    def test_updates_show_in_the_markdown_and_the_prompt_asks_for_them(self):
        minutes = notes(updates=[dict(text='Миграцията е наполовина', evidence_timestamp='00:00:00', quote=None)])
        validate_minutes(minutes, segments())
        with tempfile.TemporaryDirectory() as folder:
            save_minutes(Path(folder), minutes)
            text = (Path(folder) / 'minutes.md').read_text()
            self.assertIn('## Актуализации по започната работа', text)
            self.assertEqual(json.loads((Path(folder) / 'minutes.json').read_text())['updates'][0]['text'], 'Миграцията е наполовина')
        prompt = llm_prompt('[00:00:00] Иван: текст')
        self.assertIn('quote: за всяка задача, решение и актуализация копирай дословно', prompt)
        self.assertIn('updates: напредък, пречка или уточнение', prompt)


class ConsolidationQuoteTests(unittest.TestCase):
    def test_the_quote_rides_with_the_fact_and_does_not_go_to_the_ai(self):
        from app.notes_consolidation import candidates, messages
        part = dict(decisions=[dict(text='Решение', evidence_timestamp='00:00:00', quote='Миграцията на базата')])
        facts = candidates([part], segments())
        self.assertEqual(facts[0]['quote'], 'Миграцията на базата')
        payload = messages(facts)[1]['content']
        self.assertNotIn('"quote":"Миграцията на базата"', payload.replace(' ', ''))


if __name__ == '__main__':
    unittest.main()
