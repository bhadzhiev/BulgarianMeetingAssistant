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

    def test_the_text_has_the_project_the_state_the_quotes_and_the_history(self):
        project = self.s.create_project('Labels')
        item = self.s.items.items[self.first['id']]
        self.s.update_item(item['id'], item['text'], dict(due_date='2026-11-14', workflow_state='in_progress',
                                                         project_ids=[project['id']], update_note='Готов е първият раздел'))
        # A saved quote from Gmail, as a task draft from a message saves it.
        with self.s.items.lock:
            data = self.s.items.data
            data.setdefault('sources', {})['s1'] = dict(id='s1', provider='gmail', account='me@example.test')
            data.setdefault('source_evidence', {})['e1'] = dict(id='e1', source_id='s1', quote='Моля, обновете   ръководството', locator={})
            self.s.items.items[item['id']]['source_evidence'] = ['e1']
        body = task_email.prepare(self.s, dict(item_id=item['id']))['body']
        self.assertIn('Статус: в процес', body)
        self.assertIn('Проект: Labels', body)
        self.assertIn('Цитати:\n- „Моля, обновете ръководството“ (Gmail)', body)
        self.assertIn('История:\n- ', body)
        self.assertIn('Създадена', body)
        self.assertIn('Срок: 12.11.2026 → 14.11.2026', body)
        self.assertIn('Статус: в процес', body.split('История:')[1])
        self.assertIn('Напредък: Готов е първият раздел', body)
        # Internal review steps are not history for the reader.
        self.assertNotIn('project_ids', body);self.assertNotIn('dismissed', body)
        self.assertTrue(body.endswith('—\nГенерирано от Atlanta'))

    def test_the_history_starts_with_the_creation_and_skips_a_repeated_meeting(self):
        with self.s.items.lock:
            history = self.s.items.items[self.first['id']]['history']
            history += [dict(at=f'2026-11-09T10:{n:02d}:00+02:00', event='progress_update', by='user', changes={}, text=f'Стъпка {n}')
                        for n in range(12)]
            history.append(dict(at='2026-11-09T11:00:00+02:00', event='discussed', by='ai', changes={}, meeting_id='missing'))
        body = task_email.prepare(self.s, dict(item_id=self.first['id']))['body']
        lines = body.split('История:\n')[1].split('\n\n')[0].splitlines()
        self.assertEqual(len(lines), task_email.MAX_HISTORY)
        self.assertIn('Създадена', lines[0]);self.assertIn('Стъпка 11', lines[-1]);self.assertNotIn('Стъпка 0', body)
        self.assertNotIn('Обсъдена', body)

    def test_a_task_without_quotes_or_changes_has_no_empty_sections(self):
        body = task_email.prepare(self.s, dict(item_id=self.second['id']))['body']
        self.assertIn('Статус: за изпълнение', body)
        self.assertNotIn('Цитати:', body);self.assertNotIn('Проект', body)

    def test_a_long_email_keeps_the_task_fields_and_drops_quotes_and_history(self):
        ids = [self.s.create_task(dict(text=f'Task {n}', request_id=f'{n + 4096:032x}'))['id'] for n in range(40)]
        with self.s.items.lock:
            for key in ids:
                self.s.items.items[key]['details'] = 'x' * 300
                self.s.items.items[key]['history'] += [dict(at='2026-11-09T10:00:00+02:00', event='progress_update', by='user',
                                                            changes={}, text='y' * 280)] * 8
        body = task_email.prepare(self.s, dict(item_ids=ids))['body']
        self.assertLessEqual(len(body), 20000)
        self.assertNotIn('История:', body);self.assertIn('40. Task 39', body)

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
