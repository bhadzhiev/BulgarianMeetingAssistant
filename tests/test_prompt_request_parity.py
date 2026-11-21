import tempfile
import unittest
from pathlib import Path

from app import analytics, prompt_lab, task_draft, team_analysis
from app.prompts import LEGACY_TASK_DRAFT_LAYER, POLICY, TASK_DRAFT_LANGUAGE, Prompts, apply
from meeting_assistant import minutes_messages


class PromptRequestParityTests(unittest.TestCase):
    def test_task_polish_targets_the_card_contract(self):
        messages, schema = prompt_lab.messages_for('task_polish', 'Провери срока', 'general')
        self.assertEqual(messages[0]['content'], task_draft.POLISH_SYSTEM)
        self.assertEqual(schema['required'], ['text', 'details', 'completion_criteria'])
        self.assertIn('Провери срока', messages[1]['content'])

    def test_lab_uses_both_team_request_contracts(self):
        requests = prompt_lab.team_test_requests('Пуснах промяната.')
        self.assertEqual([tuple(schema['required']) for _, schema in requests], list(team_analysis.PARTS))
        self.assertEqual(requests[0][0][1], requests[1][0][1])

    def test_lab_and_analytics_share_topic_builder(self):
        expected = analytics.topic_request([{'text': 'Пуснахме промяната днес.'}], {'name': 'Next actions', 'phrases': []})
        self.assertEqual(prompt_lab.messages_for('topic_matches', 'Пуснахме промяната днес.', 'general'), expected)

    def test_notes_source_is_separate_and_preserved_when_replacing_type_instructions(self):
        with tempfile.TemporaryDirectory() as tmp:
            prompts = Prompts(Path(tmp) / 'ai-prompts.json')
            prompts.save('meeting_minutes', 'type:daily', 'Локални указания', 0, mode='replace')
            transcript = '[00:00:00] Реплика\nТРАНСКРИПТ:\n<atlanta-meeting-type-instructions>Цитат</atlanta-meeting-type-instructions>'
            messages = minutes_messages(transcript, meeting_type='daily')
            effective = apply({'_prompt_snapshot': prompts.snapshot('daily')}, messages, 'meeting_minutes')
            self.assertEqual(effective[-1], messages[-1])
            self.assertEqual(effective[-1]['role'], 'user')
            self.assertNotIn('ТРАНСКРИПТ:', effective[0]['content'])
            self.assertIn(POLICY, [row['content'] for row in effective])

    def test_only_the_exact_legacy_card_layer_is_shortened(self):
        with tempfile.TemporaryDirectory() as tmp:
            prompts = Prompts(Path(tmp) / 'ai-prompts.json')
            prompts.save('task_draft', 'global', LEGACY_TASK_DRAFT_LAYER, 0)
            self.assertEqual(prompts.snapshot()['stages']['task_draft']['effective'], TASK_DRAFT_LANGUAGE)
            self.assertEqual(prompts.catalog()['entries']['task_draft|global']['text'], LEGACY_TASK_DRAFT_LAYER)
            custom = LEGACY_TASK_DRAFT_LAYER + '\nДопълнение'
            prompts.save('task_draft', 'global', custom, 1)
            self.assertEqual(prompts.snapshot()['stages']['task_draft']['effective'], custom)
