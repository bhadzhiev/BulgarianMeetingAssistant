"""Decisions keep why they were taken; open questions keep what is known about them (2026-11-13)."""
from pathlib import Path
import tempfile
import unittest

from app import notes
from app.notes_consolidation import candidates, consolidate, messages
from app.processing import canonical_notes
from meeting_assistant import TranscriptSegment, llm_prompt, minutes_schema, save_minutes, validate_minutes


def segments():
    return [TranscriptSegment(0, 4, 'Избираме LTE рутер, защото е по-евтин.', 'Ана'),
            TranscriptSegment(5, 9, 'Кой ще плати рутера?', 'Борис')]


def notes_with(decision_reason='Ана: по-евтин е. Борис се съгласи.', question_context='Борис попита; бюджетът не е ясен.'):
    return dict(summary=[], tasks=[], open_questions=[dict(text='Кой плаща рутера?', evidence_timestamp='00:00:05', context=question_context)],
                decisions=[dict(text='Резервният интернет е LTE рутер', evidence_timestamp='00:00:00', quote=None, rationale=decision_reason)])


class ExplanationTests(unittest.TestCase):
    def test_the_schema_and_the_prompt_ask_for_them(self):
        schema = minutes_schema()['properties']
        self.assertEqual(schema['decisions']['items']['properties']['rationale'], {'type': ['string', 'null']})
        self.assertIn('rationale', schema['decisions']['items']['required'])
        self.assertIn('context', schema['open_questions']['items']['required'])
        self.assertNotIn('rationale', schema['updates']['items']['properties'])
        self.assertNotIn('context', schema['summary']['items']['properties'])
        prompt = llm_prompt('[00:00:00] Да.')
        self.assertIn('rationale: за всяко решение 1–3 кратки изречения', prompt)
        self.assertIn('Ако никой не каза причина, върни null.', prompt)
        self.assertIn('context: за всеки отворен въпрос', prompt)
        self.assertIn('в записа не се чува ясно', prompt)

    def test_validation_takes_them_only_where_they_belong(self):
        validate_minutes(notes_with(), segments())
        validate_minutes(notes_with(None, None), segments())
        bad = notes_with()
        bad['decisions'][0]['rationale'] = 5
        with self.assertRaisesRegex(ValueError, 'rationale must be text'):
            validate_minutes(bad)
        bad = notes_with()
        bad['decisions'][0]['rationale'] = 'x' * 2001
        with self.assertRaisesRegex(ValueError, 'rationale must be text'):
            validate_minutes(bad)
        bad = notes_with()
        bad['summary'] = [dict(text='Резюме', evidence_timestamp=None, rationale='Защо')]
        with self.assertRaisesRegex(ValueError, 'summary items'):
            validate_minutes(bad)

    def test_a_new_reason_is_a_change_and_a_missing_one_clears_nothing(self):
        saved = notes_with()
        validate_minutes(saved)
        same = notes_with(None, None)
        self.assertEqual(notes.changes(saved, same), [])
        newer = notes_with('Ана: по-евтин и по-бърз е.')
        found = notes.changes(saved, newer)
        self.assertEqual([(c['field'], c['kind']) for c in found], [('decisions', 'changed')])
        applied = notes.apply(saved, newer, [found[0]['id']])
        self.assertEqual(applied['decisions'][0]['rationale'], 'Ана: по-евтин и по-бърз е.')
        self.assertEqual(applied['open_questions'][0]['context'], 'Борис попита; бюджетът не е ясен.')

    def test_markdown_shows_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            save_minutes(Path(tmp), notes_with())
            text = (Path(tmp) / 'minutes.md').read_text()
        self.assertIn('- Резервният интернет е LTE рутер (00:00:00)\n  Причина: Ана: по-евтин е. Борис се съгласи.', text)
        self.assertIn('  Контекст: Борис попита; бюджетът не е ясен.', text)

    def test_they_ride_with_the_fact_through_consolidation(self):
        part = notes_with()
        part['tasks'] = [dict(task='Ана да купи рутер', details='Ана: до петък.', owner='Ана', deadline=None, due_date=None, evidence_timestamp='00:00:00')]
        facts = candidates([part], segments())
        payload = messages(facts)[1]['content']
        self.assertNotIn('по-евтин е', payload)
        result, _ = consolidate([part], segments(), dict(summarizer='local'), tempfile.mkdtemp(), lambda *_: None)
        self.assertEqual(result['decisions'][0]['rationale'], 'Ана: по-евтин е. Борис се съгласи.')
        self.assertEqual(result['open_questions'][0]['context'], 'Борис попита; бюджетът не е ясен.')
        self.assertEqual(result['tasks'][0]['details'], 'Ана: до петък.')

    def test_spelling_and_speaker_names_reach_them(self):
        minutes = notes_with('SPEAKER_00 предложи PacketFancy.', None)
        named = notes.name_speakers(minutes, {'SPEAKER_00': 'Ана'})
        self.assertEqual(named['decisions'][0]['rationale'], 'Ана предложи PacketFancy.')
        fixed = canonical_notes(named, 'PacketFence | PacketFancy')
        self.assertEqual(fixed['decisions'][0]['rationale'], 'Ана предложи PacketFence.')


if __name__ == '__main__':
    unittest.main()
