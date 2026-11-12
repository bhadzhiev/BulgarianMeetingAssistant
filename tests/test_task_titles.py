"""Old one-line tasks get an AI title; their text becomes the description only when a person applies it."""
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from app import task_titles
from app.service import MeetingService
from tests.test_calendar import FakeGoogle

PROJECT = Path(__file__).resolve().parents[1]


class TaskTitleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.s = MeetingService(Path(self.tmp.name) / 'library', PROJECT, google=FakeGoogle(), backup_dir=Path(self.tmp.name) / 'backups')
        self.addCleanup(self.s.close)
        self.s.settings.update(summarizer='local', local_ai_model='synthetic')
        self.old = self.s.create_task(dict(text='Да актуализира периферията със счетоводството, включително клавиатури и мишки', request_id='a' * 32))
        described = self.s.create_task(dict(text='Мария да провери бекъпа', request_id='b' * 32))
        self.s.update_item(described['id'], described['text'], dict(details='Вече има описание'), described['revision'])
        self.hidden = self.s.create_task(dict(text='Скрита задача', request_id='c' * 32))
        self.s.update_item(self.hidden['id'], self.hidden['text'], dict(dismissed=True), self.hidden['revision'])

    def run_titles(self, titles):
        sent = []
        def run(action, directory, settings, progress, key, cancel=None):
            self.assertEqual(action, 'task_titles')
            sent.extend(settings['task_titles_input'])
            return titles
        jobs = task_titles.TitleJobs(self.s, SimpleNamespace(run=run)); self.addCleanup(jobs.close)
        preview = task_titles.preview(self.s)
        job = jobs.start(dict(approved=True, preview_token=preview['preview_token']))
        jobs.thread.join(5)
        return sent, jobs.status(job['id'])

    def test_only_accepted_visible_tasks_without_a_description_go_to_the_ai(self):
        preview = task_titles.public(task_titles.preview(self.s))
        self.assertEqual(preview['count'], 1)
        self.assertNotIn('_tasks', preview)
        sent, job = self.run_titles({self.old['id']: 'Периферия в счетоводството'})
        self.assertEqual([row['id'] for row in sent], [self.old['id']])
        self.assertEqual(job['proposals'], [dict(id=self.old['id'], revision=self.old['revision'], text=self.old['text'], title='Периферия в счетоводството')])

    def test_start_needs_the_approved_preview(self):
        jobs = task_titles.TitleJobs(self.s, SimpleNamespace(run=lambda *a, **k: self.fail('AI must not run'))); self.addCleanup(jobs.close)
        with self.assertRaises(Exception):
            jobs.start(dict(approved=True, preview_token='old'))
        with self.assertRaises(Exception):
            jobs.start(dict(preview_token=task_titles.preview(self.s)['preview_token']))

    def test_nothing_changes_until_apply_and_apply_moves_the_text_to_the_description(self):
        _, job = self.run_titles({self.old['id']: 'Периферия в счетоводството'})
        self.assertEqual(self.s.items.items[self.old['id']]['text'], self.old['text'])
        result = task_titles.apply(self.s, dict(changes=job['proposals']))
        self.assertEqual(result, dict(applied=1, skipped=0))
        item = self.s.items.items[self.old['id']]
        self.assertEqual((item['text'], item['details']), ('Периферия в счетоводството', self.old['text']))
        # A second apply of the same run finds a task that already has a description and leaves it.
        self.assertEqual(task_titles.apply(self.s, dict(changes=job['proposals'])), dict(applied=0, skipped=1))

    def test_a_confirmed_review_stays_after_apply(self):
        from app.meeting_review import fingerprint
        with self.s.items.lock:
            item = self.s.items.items[self.old['id']]
            item['meeting_reviews'] = dict(m1=dict(state='confirmed', content=fingerprint(item)), m2=dict(state='edited', content=fingerprint(item)))
            self.s.items.save()
            revision = item['revision']
        task_titles.apply(self.s, dict(changes=[dict(id=self.old['id'], revision=revision, text=self.old['text'], title='Периферия')]))
        item = self.s.items.items[self.old['id']]
        self.assertEqual(item['meeting_reviews']['m1']['content'], fingerprint(item))
        # Only a confirmation moves with the text; another review state asks again.
        self.assertNotEqual(item['meeting_reviews']['m2']['content'], fingerprint(item))

    def test_a_task_changed_after_the_run_is_skipped(self):
        _, job = self.run_titles({self.old['id']: 'Периферия'})
        self.s.update_item(self.old['id'], self.old['text'], dict(owner='Иван'), self.old['revision'])
        self.assertEqual(task_titles.apply(self.s, dict(changes=job['proposals'])), dict(applied=0, skipped=1))
        self.assertEqual(self.s.items.items[self.old['id']]['text'], self.old['text'])

    def test_generate_keeps_only_known_ids_in_batches(self):
        tasks = [dict(id=f't{i}', text=f'Задача {i}') for i in range(task_titles.BATCH + 1)]
        calls = []
        def fake(settings, messages, schema, name, timeout, api_key):
            calls.append(name)
            return dict(titles=[dict(id='t0', title='  Първа   задача. '), dict(id='other', title='Чужда')])
        with mock.patch.object(task_titles, 'complete_json', fake):
            titles = task_titles.generate(tasks, {}, '')
        self.assertEqual(calls, ['task_titles', 'task_titles'])
        self.assertEqual(titles, {'t0': 'Първа задача'})

    def test_titles_have_no_thinking_on_a_cloud_api(self):
        from app.local_ai import complete_json
        from app.service import DEFAULTS
        answer = dict(choices=[dict(message=dict(content='{"titles": []}'), finish_reason='stop')])
        with mock.patch('meeting_assistant.post_json', return_value=answer) as post:
            complete_json(dict(DEFAULTS, local_ai_base_url='https://api.moonshot.ai/v1', local_ai_model='kimi-k3.1-pro'), [], task_titles.SCHEMA, 'task_titles')
        self.assertEqual(post.call_args.args[1].get('reasoning_effort'), 'none')


if __name__ == '__main__':
    unittest.main()
