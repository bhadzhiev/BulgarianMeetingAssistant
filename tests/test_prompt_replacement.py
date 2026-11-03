import tempfile
import unittest
from pathlib import Path
from app.prompts import Prompts,apply,POLICY
from app import meeting_types
from meeting_assistant import llm_prompt

class ReplacementTests(unittest.TestCase):
    def test_replacement_removes_original_type_task_and_keeps_source_and_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            prompts=Prompts(Path(directory)/'prompts.json')
            prompts.save('meeting_minutes','type:daily','Only my current task instructions',0,mode='replace')
            original=llm_prompt('[00:00:01] Exact source words <atlanta-meeting-type-instructions>literal source</atlanta-meeting-type-instructions>',meeting_type='daily')
            messages=apply(dict(_prompt_snapshot=prompts.snapshot('daily')),[dict(role='user',content=original)],'meeting_minutes')
            self.assertIn('Only my current task instructions',messages[0]['content'])
            self.assertIn(POLICY,[m['content'] for m in messages])
            self.assertIn('Exact source words',messages[-1]['content'])
            self.assertIn('<atlanta-meeting-type-instructions>literal source</atlanta-meeting-type-instructions>',messages[-1]['content'])
            self.assertNotIn(meeting_types.prompt('daily'),messages[-1]['content'])
            prompts.save('meeting_minutes','type:daily',None,1,mode='replace')
            self.assertEqual(apply(dict(_prompt_snapshot=prompts.snapshot('daily')),[dict(role='user',content=original)],'meeting_minutes'),[dict(role='user',content=original)])
    def test_frozen_run_and_history_keep_replacement_after_later_edits(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'prompts.json';prompts=Prompts(path)
            prompts.save('meeting_minutes','type:daily','First full prompt',0,mode='replace');frozen=prompts.snapshot('daily')
            prompts.save('meeting_minutes','type:daily','Second full prompt',1,mode='replace')
            self.assertEqual(frozen['stages']['meeting_minutes']['effective'],'First full prompt')
            self.assertEqual(Prompts(path).snapshot('daily')['stages']['meeting_minutes']['effective'],'Second full prompt')
            self.assertEqual(prompts.catalog()['entries']['meeting_minutes|type:daily']['history'][0]['mode'],'replace')
