import base64
import email
import email.policy
import tempfile
import unittest
from pathlib import Path

from app import task_email
from app.service import MeetingService
from tests.test_followup_email import DraftGoogle

PROJECT = Path(__file__).resolve().parents[1]


class TaskEmailTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.google = DraftGoogle()
        self.s = MeetingService(Path(self.tmp.name) / 'library', PROJECT, google=self.google, backup_dir=Path(self.tmp.name) / 'backups')
        self.addCleanup(self.s.close)
        self.maria = self.s.save_person(dict(name='Maria', emails=['maria@example.test']))['person']
        self.s.save_person(dict(name='Guest', emails=['guest@example.test']))
        self.first = self.task('Update the runbook', 'Maria', '2026-11-12', 'a')
        self.second = self.task('Check the backup', None, None, 'b')

    def task(self, text, owner, due, key):
        return self.s.create_task(dict(text=text, owner=owner, due_date=due, request_id=key * 32))

    def message(self, index=-1):
        raw = self.google.sent[index][0]
        return email.message_from_bytes(base64.urlsafe_b64decode(raw), policy=email.policy.default)

    def test_one_task_prepares_text_and_preselects_the_owner(self):
        data = task_email.prepare(self.s, dict(item_id=self.first['id']))
        self.assertEqual(data['subject'], 'Задача: Update the runbook')
        self.assertIn('Отговорник: Maria', data['body'])
        self.assertIn('Срок: 12.11.2026', data['body'])
        self.assertEqual([r['email'] for r in data['recipients'] if r['involved']], ['maria@example.test'])
        self.assertIsNone(data['draft'])
        self.assertTrue(data['body'].endswith('—\nГенерирано от Atlanta'))

    def test_saving_marks_the_task_and_adds_history(self):
        result = task_email.save_draft(self.s, dict(item_ids=[self.first['id']], to=['Maria@Example.test'],
                                                    subject='Задача', body='Текст'))
        self.assertFalse(result['updated'])
        self.assertEqual(self.message()['To'], 'maria@example.test')
        # A text without the Atlanta note gets it at the end.
        self.assertTrue(self.message().get_content().rstrip().endswith('Текст\n\n—\nГенерирано от Atlanta'))
        item = self.s.items.items[self.first['id']]
        self.assertEqual(item['email_draft']['draft_id'], result['draft_id'])
        self.assertEqual(item['email_draft']['to'], ['maria@example.test'])
        self.assertEqual(item['history'][-1]['event'], 'email_draft')
        self.assertIn('Draft created for maria@example.test', item['history'][-1]['text'])
        # The mark and the history survive a reload from the store.
        self.s.items.data, self.s.items.revision = self.s.items.store.load()
        self.assertIn('email_draft', self.s.items.items[self.first['id']])
        # Saving again updates the same Gmail draft and adds one more history entry.
        again = task_email.save_draft(self.s, dict(item_ids=[self.first['id']], to=['maria@example.test'], subject='Задача', body='Нов текст'))
        self.assertTrue(again['updated']);self.assertEqual(self.google.sent[-1][1], result['draft_id'])
        self.assertEqual([e['event'] for e in self.s.items.items[self.first['id']]['history']].count('email_draft'), 2)

    def test_several_tasks_go_in_one_email_and_each_task_is_marked(self):
        ids = [self.first['id'], self.second['id']]
        data = task_email.prepare(self.s, dict(item_ids=ids))
        self.assertTrue(data['subject'].startswith('Задачи (2): Update the runbook; Check the backup'))
        self.assertIn('1. Update the runbook', data['body']);self.assertIn('2. Check the backup', data['body'])
        self.assertIn('Отговорник: без отговорник', data['body']);self.assertIn('Срок: без срок', data['body'])
        result = task_email.save_draft(self.s, dict(item_ids=ids, to=['guest@example.test'], subject=data['subject'], body=data['body']))
        self.assertEqual(len(self.google.sent), 1)
        for item_id in ids:
            item = self.s.items.items[item_id]
            self.assertEqual(item['email_draft']['draft_id'], result['draft_id'])
            self.assertIn('2 tasks in one email', item['history'][-1]['text'])
        # The shared draft is offered for update only for the same tasks together.
        self.assertIsNotNone(task_email.prepare(self.s, dict(item_ids=ids))['draft'])
        third = self.task('Third', None, None, 'c')
        self.assertIsNone(task_email.prepare(self.s, dict(item_ids=ids + [third['id']]))['draft'])

    def test_invalid_input_is_refused_before_gmail(self):
        for body in [dict(item_ids=[]), dict(item_ids=['missing']), dict(item_ids=[self.first['id']] * 2)]:
            with self.assertRaises(ValueError):
                task_email.save_draft(self.s, dict(body, to=['maria@example.test'], subject='S', body='B'))
        with self.assertRaises(ValueError):
            task_email.save_draft(self.s, dict(item_ids=[self.first['id']], to=['not an email'], subject='S', body='B'))
        self.assertEqual(self.google.sent, [])
        self.assertNotIn('email_draft', self.s.items.items[self.first['id']])


if __name__ == '__main__':
    unittest.main()
