"""Notes precision: part size, one section per statement, plain names, few observations, vocabulary spelling."""
import inspect
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import meeting_assistant
from app import notes_consolidation as nc, processing
from app.service import DEFAULTS
from meeting_assistant import TranscriptSegment
from tests.test_notes_consolidation import minutes, task


def audit_ids(audit):
    return [f['id'] for f in audit['candidates'] if f['field'] == 'summary']


class PromptRulesTests(unittest.TestCase):
    def setUp(self):
        self.prompt = meeting_assistant.llm_prompt('[00:00:01] Иван: Да започнем.', speakers=['Veselin Uzunov'])

    def test_each_statement_goes_to_one_section_in_a_fixed_order(self):
        self.assertIn('Всяко нещо записвай само в една секция', self.prompt)
        self.assertIn('decisions, tasks, секциите на типа\nсрещата, needs_decision, open_questions, next_steps, observations, summary', self.prompt)
        self.assertIn('Един въпрос е или в needs_decision, или в open_questions, не и в двете.', self.prompt)
        self.assertIn('не преразказва\nзадачите, решенията и въпросите', self.prompt)

    def test_known_names_are_used_in_every_statement(self):
        self.assertIn('навсякъде: в отговорника и в текста на всяко твърдение', self.prompt)
        self.assertIn('При съмнение кой е човекът запази името от текста.', self.prompt)
        self.assertIn('всяко име е или точно от списъка, или точно както е в текста', self.prompt)

    def test_observations_are_few_and_never_judge_a_person(self):
        self.assertIn('observations: до 3 поверителни наблюдения', self.prompt)
        self.assertIn('не описвай навици, характер, отношение или представяне на конкретен човек', self.prompt)


class PartSizeTests(unittest.TestCase):
    def test_parts_hold_about_ten_thousand_characters(self):
        # 4,000 characters split a 22-minute meeting into five partial summaries.
        self.assertEqual(processing.NOTES_PART_CHARS, 10000)
        self.assertIn('NOTES_PART_CHARS, overhead=15', inspect.getsource(processing.summarize))


class VocabularySpellingTests(unittest.TestCase):
    VOCABULARY = 'PacketFence | PacketFancy, Packet Fence\nAnthropic | Antropiq\nKubernetes'

    def test_variants_become_the_preferred_spelling_in_statements_and_tasks(self):
        notes = minutes(summary=[dict(text='Тест в PacketFancy и packet fence.', evidence_timestamp=None)],
                        tasks=[dict(task('Одобрение от Antropiq'), owner='Antropiq')])
        processing.canonical_notes(notes, self.VOCABULARY)
        self.assertEqual(notes['summary'][0]['text'], 'Тест в PacketFence и PacketFence.')
        self.assertEqual(notes['tasks'][0]['task'], 'Одобрение от Anthropic')
        # An owner is a person, not a vocabulary term.
        self.assertEqual(notes['tasks'][0]['owner'], 'Antropiq')

    def test_whole_words_only_and_no_change_without_variants(self):
        notes = minutes(summary=[dict(text='PacketFancyBox остава.', evidence_timestamp=None)])
        processing.canonical_notes(notes, self.VOCABULARY)
        self.assertEqual(notes['summary'][0]['text'], 'PacketFancyBox остава.')
        plain = minutes(summary=[dict(text='PacketFancy', evidence_timestamp=None)])
        processing.canonical_notes(plain, 'PacketFence, Kubernetes')
        self.assertEqual(plain['summary'][0]['text'], 'PacketFancy')

    def test_summarize_applies_the_vocabulary_before_saving(self):
        self.assertIn('result = canonical_notes(result, args.whisper_vocabulary)', inspect.getsource(processing.summarize))


class ConsolidationRepairTests(unittest.TestCase):
    """A small model may skip, repeat or invent one ID. The answer is repaired instead of failing all notes."""

    def setUp(self):
        segments = [TranscriptSegment(i * 10, i * 10 + 9, 'Обсъждаме базата данни.', 'Иван') for i in range(30)]
        self.facts = nc.candidates([minutes(tasks=[task(), task(stamp='00:00:10'), task(stamp='00:00:20')])], segments)
        self.ids = [f['id'] for f in self.facts]

    def test_missing_ids_become_singletons_and_repeats_count_once(self):
        a, b, c = self.ids
        value, fixed = nc.repair_plan(dict(groups=[dict(members=[a, b, a], representative=a), dict(members=[b, 'fake'], representative='fake')]), self.facts)
        groups = nc.validate_plan(value, self.facts)
        self.assertEqual(sorted(m for g in groups for m in g['members']), sorted(self.ids))
        self.assertIn(dict(members=[c], representative=c), groups)
        self.assertEqual(fixed, 4)

    def test_an_exact_answer_needs_no_repair(self):
        value, fixed = nc.repair_plan(dict(groups=[dict(members=self.ids, representative=self.ids[0])]), self.facts)
        self.assertEqual(fixed, 0)
        nc.validate_plan(value, self.facts)

    def summary_facts(self):
        segments = [TranscriptSegment(i * 10, i * 10 + 9, 'Обсъждаме базата данни.', 'Иван') for i in range(30)]
        return nc.candidates([minutes(summary=[dict(text=f'Тема {i}', evidence_timestamp=None) for i in range(3)])], segments)

    def test_summary_keeps_a_missing_source_as_its_own_point_when_there_is_room(self):
        facts = self.summary_facts()
        a, b, c = [f['id'] for f in facts]
        value, fixed = nc.repair_plan(dict(groups=[dict(members=[a, b], text='Обсъдена е базата данни.')]), facts, summary=True)
        groups = nc.validate_plan(value, facts, summary=True)
        self.assertEqual(len(groups), 2)
        self.assertEqual(groups[1]['members'], [c])
        self.assertEqual(fixed, 1)

    def test_summary_without_room_keeps_the_source_for_the_next_level(self):
        facts = self.summary_facts()
        a, b, c = [f['id'] for f in facts]
        value, fixed = nc.repair_plan(dict(groups=[dict(members=[a, b], text='Обсъдена е базата данни.')]), facts, summary=True, maximum=1)
        self.assertEqual(fixed, 1)
        # Over the final maximum for this level; the summary loop reduces it again.
        with self.assertRaises(ValueError):
            nc.validate_plan(value, facts, summary=True, maximum=1)
        self.assertEqual(len(nc.validate_plan(value, facts, summary=True, maximum=len(facts))), 2)

    def test_a_full_summary_that_skips_a_source_still_completes(self):
        def full_but_skips(settings, messages, schema, stage):
            import json
            ids = [f['id'] for f in json.loads(messages[1]['content'])['untrusted_candidates']]
            if 'text' in schema['properties']['groups']['items']['properties']:
                # Six points that leave the last source out when there are more than six.
                keep = ids[:-1] if len(ids) > 6 else ids
                return dict(groups=[dict(members=keep[i::6], text=f'Точка {i}') for i in range(min(6, len(keep)))])
            return dict(groups=[dict(members=[i], representative=i) for i in ids])
        segments = [TranscriptSegment(i * 10, i * 10 + 9, 'Обсъждаме базата данни.', 'Иван') for i in range(30)]
        parts = [minutes(summary=[dict(text=f'Тема {p}-{i}', evidence_timestamp=None) for i in range(6)]) for p in range(2)]
        with tempfile.TemporaryDirectory() as tmp, patch('app.local_ai.complete_json', side_effect=full_but_skips):
            result, audit = nc.consolidate(parts, segments, dict(DEFAULTS, summarizer='local'), Path(tmp), lambda _: None, '')
        self.assertEqual(audit['status'], 'completed')
        # This model skips a source on every level, so one point stays beyond six instead of a failure.
        self.assertEqual(len(result['summary']), 7)
        self.assertEqual(audit['summary_over_limit'], 7)
        self.assertGreater(audit['repaired'], 0)
        self.assertEqual(sorted(o for sources in audit['summary_sources'] for o in sources), sorted(audit_ids(audit)))

    def test_consolidation_repairs_a_fresh_answer_and_records_it(self):
        def skips_one(settings, messages, schema, stage):
            import json
            ids = [f['id'] for f in json.loads(messages[1]['content'])['untrusted_candidates']]
            if 'text' in schema['properties']['groups']['items']['properties']:
                return dict(groups=[dict(members=ids, text='Обсъдена е базата данни.')])
            return dict(groups=[dict(members=ids[:-1], representative=ids[0])])
        segments = [TranscriptSegment(i * 10, i * 10 + 9, 'Обсъждаме базата данни.', 'Иван') for i in range(30)]
        parts = [minutes(tasks=[task()]), minutes(tasks=[task(stamp='00:00:10')])]
        with tempfile.TemporaryDirectory() as tmp, patch('app.local_ai.complete_json', side_effect=skips_one):
            result, audit = nc.consolidate(parts, segments, dict(DEFAULTS, summarizer='local'), Path(tmp), lambda _: None, '')
        self.assertEqual(audit['status'], 'completed')
        self.assertEqual(audit['repaired'], 1)
        self.assertEqual(len(result['tasks']), 2)



class SchemaHintTests(unittest.TestCase):
    """The prompt text describes long value lists; the server still enforces them."""

    def test_long_timestamp_lists_are_described_not_repeated(self):
        from app import local_ai
        stamps = [f'00:{m:02d}:{s:02d}' for m in range(5) for s in range(0, 60, 5)]
        schema = meeting_assistant.minutes_schema(('today',))
        for field in ('summary', 'today'):
            schema['properties'][field]['items']['properties']['evidence_timestamp']['enum'] = stamps + [None]
        schema['properties']['tasks']['items']['properties']['evidence_timestamp']['enum'] = stamps
        hint = local_ai.schema_hint(schema)
        text = __import__('json').dumps(hint, ensure_ascii=False)
        self.assertNotIn('00:04:55', text)
        self.assertEqual(hint['properties']['summary']['items']['properties']['evidence_timestamp']['description'], 'One value that appears in the input or null.')
        self.assertEqual(hint['properties']['tasks']['items']['properties']['evidence_timestamp']['description'], 'One value that appears in the input.')
        # The original schema keeps every value for response_format.
        self.assertEqual(len(schema['properties']['tasks']['items']['properties']['evidence_timestamp']['enum']), 60)

    def test_short_lists_stay_listed(self):
        from app import local_ai
        self.assertEqual(local_ai.schema_hint(dict(type='string', enum=['a', 'b'])), dict(type='string', enum=['a', 'b']))

    def test_the_reminder_uses_the_hint_and_response_format_the_full_schema(self):
        from app import local_ai
        sent = {}
        def post(url, payload, headers=None, timeout=600):
            sent.update(payload)
            return dict(choices=[dict(message=dict(content='{}'), finish_reason='stop')])
        schema = dict(type='object', properties=dict(at=dict(type='string', enum=[str(i) for i in range(40)])))
        with patch('meeting_assistant.post_json', side_effect=post):
            local_ai.complete_json(dict(DEFAULTS, summarizer='local'), [dict(role='user', content='x')], schema, 'meeting_minutes')
        self.assertNotIn('"39"', sent['messages'][-1]['content'])
        self.assertEqual(len(sent['response_format']['json_schema']['schema']['properties']['at']['enum']), 40)

if __name__ == '__main__':
    unittest.main()
