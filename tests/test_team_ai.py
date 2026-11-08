import json
from pathlib import Path
import tempfile
import time
import unittest

from app import team_ai
from app.service import MeetingService
from app.team_ai import ReviewAI, join, markdown, validate
from app.work_items import WorkItemConflict
from tests.test_calendar import FakeGoogle

PROJECT = Path(__file__).resolve().parents[1]


class FakeRunner:
    """Answers each batch with one observation and one question about its first record."""

    def __init__(self, fail_on=None, invent=False):
        self.calls, self.fail_on, self.invent = [], fail_on, invent

    def run(self, action, directory, settings, progress, key='', cancel=None):
        assert action == 'team_review'
        batch = settings['team_review_input']
        self.calls.append([r['id'] for r in batch['records']])
        if self.fail_on is not None and len(self.calls) == self.fail_on:
            raise ValueError('The AI server stopped')
        first = batch['records'][0]['id']
        observations = [dict(section='tasks', text='Работи по задачата.', evidence=[first], attribution='clear')]
        if self.invent:
            observations.append(dict(section='tasks', text='Измислено.', evidence=['e999'], attribution='clear'))
        result = dict(observations=observations, questions=[dict(text='Какво ти помогна?', evidence=[first])], not_enough_data=False)
        clean, rejected = validate(result, {r['id'] for r in batch['records']})
        return dict(clean, rejected=rejected)


class TeamAITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.s = MeetingService(Path(self.tmp.name) / 'library', PROJECT, google=FakeGoogle(), backup_dir=Path(self.tmp.name) / 'backups'); self.addCleanup(self.s.close)
        self.s.settings['summarizer'] = 'local'
        self.person = self.s.save_person(dict(name='Maria'))['person']
        self.review = self.s.team_review_action('create', dict(person_id=self.person['id'], start='2026-11-01T00:00', end='2026-11-08T00:00'))

    def records(self, count):
        path = self.s.team_reviews.directory(self.review['id']) / 'evidence.json'
        path.write_text(json.dumps([dict(id=f'e{i}', kind='task_assigned', person_id=self.person['id'], source_ref={}, occurred_at='2026-11-02T10:00:00+02:00',
                                         confirmation_basis='A person chose the owner', facts=dict(text=f'Task {i}', role='accountable'), quote='') for i in range(1, count + 1)]))

    def run_ai(self, ai):
        preview = ai.preview(self.review['id'])
        job = ai.start(dict(id=self.review['id'], preview_token=preview['preview_token'], approved=True))
        ai.thread.join(10)
        return ai.status(job['id'])

    def test_validate_rejects_unknown_and_missing_ids(self):
        clean, rejected = validate(dict(observations=[dict(section='tasks', text='A', evidence=['e1'], attribution='clear'),
                                                      dict(section='tasks', text='B', evidence=['e9'], attribution='clear'),
                                                      dict(section='tasks', text='C', evidence=[], attribution='clear')],
                                        questions=[dict(text='Q', evidence=['e2', 'e1'])], not_enough_data=False), {'e1', 'e2'})
        self.assertEqual(([o['text'] for o in clean['observations']], clean['questions'][0]['evidence'], rejected), (['A'], ['e1', 'e2'], 2))
        with self.assertRaises(ValueError): validate(dict(observations=[], questions=[]), {'e1'})

    def test_not_enough_data_is_a_valid_answer_and_markdown_is_replaced_not_repeated(self):
        result = join([dict(observations=[], questions=[], not_enough_data=True, rejected=0)])
        text = markdown(self.review['review_md'], result)
        self.assertIn('_Not enough data for observations in this period._', text)
        self.assertEqual(markdown(text, result), text)
        self.assertIn('## Commitments', text)

    def test_approval_is_required_and_the_preview_names_the_destination(self):
        ai = ReviewAI(self.s, FakeRunner())
        preview = ai.preview(self.review['id'])
        self.assertEqual((preview['target']['provider'], preview['remote']), ('local', False))
        self.assertNotIn('person_id', json.dumps(preview['input']))
        with self.assertRaises(WorkItemConflict): ai.start(dict(id=self.review['id'], preview_token=preview['preview_token'], approved=False))
        with self.assertRaises(WorkItemConflict): ai.start(dict(id=self.review['id'], preview_token='x', approved=True))

    def test_long_period_goes_in_batches_and_saves_the_generator(self):
        self.records(85)
        runner = FakeRunner(invent=True)
        status = self.run_ai(ReviewAI(self.s, runner))
        self.assertEqual((status['status'], len(runner.calls)), ('Ready to review', 3))
        review = self.s.team_reviews.get(self.review['id'])
        self.assertIn('## AI observations', review['review_md'])
        self.assertIn('Какво ти помогна? [e1] [e41] [e81]', review['review_md'])
        self.assertNotIn('e999', review['review_md'])
        generator = review['generator']
        self.assertEqual((generator['complete'], generator['rejected'], generator['prompt']['stages']['team_review']['layers'] if 'layers' in generator['prompt']['stages']['team_review'] else []), (True, 3, []))
        self.assertTrue(generator['input_digest'] and generator['model'])
        self.s.team_reviews.finalize(review['id'], review['revision'])

    def test_retry_reuses_finished_parts_and_an_incomplete_run_blocks_finalize(self):
        self.records(85)
        status = self.run_ai(ReviewAI(self.s, FakeRunner(fail_on=2)))
        self.assertEqual(status['status'], 'Failed')
        review = self.s.team_reviews.get(self.review['id'])
        self.assertFalse(review['generator']['complete'])
        with self.assertRaises(ValueError): self.s.team_reviews.finalize(review['id'], review['revision'])
        runner = FakeRunner()
        self.assertEqual(self.run_ai(ReviewAI(self.s, runner))['status'], 'Ready to review')
        self.assertEqual(len(runner.calls), 2)  # the first part came from the checkpoint
        self.assertFalse((self.s.team_reviews.directory(self.review['id']) / '.ai-checkpoint.json').exists())

    def test_collect_again_clears_the_ai_run(self):
        self.records(2)
        self.run_ai(ReviewAI(self.s, FakeRunner()))
        review = self.s.team_reviews.get(self.review['id'])
        review = self.s.team_review_action('collect', dict(id=review['id'], revision=review['revision']))
        self.assertIsNone(review['generator']); self.assertNotIn('## AI observations', review['review_md'])


if __name__ == '__main__':
    unittest.main()
