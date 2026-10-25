"""An older copy, a restore or a merge must not undo or hide what another action did."""
import json
from pathlib import Path
import tempfile
import unittest

from app.service import MeetingService
from meeting_assistant import TranscriptSegment, save_transcript
from tests.test_calendar import FakeGoogle

PROJECT = Path(__file__).resolve().parents[1]


def task(text, owner=None):
    return dict(task=text, owner=owner, deadline=None, due_date=None, evidence_timestamp='00:00:00')


def notes(tasks=(), summary=()):
    return dict(summary=[dict(text=s, evidence_timestamp=None) for s in summary], decisions=[], tasks=list(tasks), open_questions=[])


class EditSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.service = MeetingService(self.root / 'library', PROJECT, google=FakeGoogle(), backup_dir=self.root / 'backups')

    def tearDown(self):
        self.service.close()
        self.tmp.cleanup()

    def meeting(self, minutes, title='Среща'):
        meeting = self.service.library.create(title, 'in_person', {})
        self.service.library.update(meeting['id'], status='ready', duration=60)
        save_transcript(self.service.library.directory(meeting['id']), [TranscriptSegment(0, 5, 'Да.')])
        self.service.edit(meeting['id'], {'minutes': minutes})
        return meeting['id']

    def minutes(self, meeting_id):
        return json.loads((self.service.library.directory(meeting_id) / 'minutes.json').read_text())

    def test_an_older_copy_does_not_undo_a_newer_change(self):
        meeting_id = self.meeting(notes([task('Провери бекъпа')], ['Старо резюме']))
        old = self.service.detail(meeting_id)
        [item] = self.service.tasks()
        self.service.update_item(item['id'], item['text'], {'status': 'done'})
        # The old copy adds a summary line; its task is still open in that copy.
        summary = old['minutes']['summary'] + [dict(text='Добавено резюме', evidence_timestamp=None, review='verified')]
        self.service.edit(meeting_id, {'minutes_fields': {'summary': summary}, 'minutes_base': {'summary': old['minutes']['summary']},
                                       'minutes_revision': old['minutes_revision']})
        self.assertEqual([s['text'] for s in self.minutes(meeting_id)['summary']], ['Старо резюме', 'Добавено резюме'])
        self.assertEqual((self.service.tasks()[0]['status'], self.minutes(meeting_id)['tasks'][0]['status']), ('done', 'done'))
        with self.assertRaisesRegex(ValueError, 'changed after you opened'):
            self.service.edit(meeting_id, {'minutes': old['minutes'], 'minutes_revision': old['minutes_revision']})
        with self.assertRaisesRegex(ValueError, 'summary'):
            self.service.edit(meeting_id, {'minutes_fields': {'summary': []}, 'minutes_base': {'summary': old['minutes']['summary']},
                                           'minutes_revision': old['minutes_revision']})
        self.assertEqual(self.service.tasks()[0]['status'], 'done')

    def test_restore_brings_back_only_items_of_restored_meetings(self):
        self.meeting(notes([task('Купи UPS за сървърното')]))
        name = self.service.create_backup()['created']['name']
        [item] = self.service.tasks()
        self.service.delete_item(item['id'], item['text'])
        self.assertEqual(self.service.tasks(), [])  # the registry has seen the deletion before the restore
        result = self.service.restore_backup(name)
        self.assertEqual(result['restored'], [])
        self.assertEqual((self.service.tasks(), self.service.item_list()['pending']), ([], []))

    def test_merge_in_one_meeting_keeps_the_chosen_text_and_a_quiet_history(self):
        meeting_id = self.meeting(notes([task('Провери VPN failover на офиса'), task('Провери VPN failover')]))
        pending = self.service.item_list()['pending']
        for entry in pending:
            self.service.resolve_link(meeting_id, 'tasks', entry['index'], entry['text'], 'new')
        tasks = {t['text']: t for t in self.service.tasks()}
        into = tasks['Провери VPN failover']
        self.service.merge_items(tasks['Провери VPN failover на офиса']['id'], into['id'])
        [merged] = self.service.tasks()
        self.assertEqual(merged['text'], 'Провери VPN failover')
        self.assertEqual([t['task'] for t in self.minutes(meeting_id)['tasks']], ['Провери VPN failover'])
        history = len(merged['history'])
        self.service._sync_items(meeting_id)
        self.service._sync_items(meeting_id)
        self.assertEqual(len(self.service.tasks()[0]['history']), history)

    def test_two_mentions_of_one_item_in_a_meeting_do_not_rewrite_it(self):
        meeting_id = self.meeting(notes([task('Подготви оферта за клиента')]))
        [item] = self.service.tasks()
        minutes = self.minutes(meeting_id)
        minutes['tasks'].append(task('Подготви офертата за клиента до петък'))
        self.service.edit(meeting_id, {'minutes': minutes, 'minutes_revision': self.service.detail(meeting_id)['minutes_revision']})
        self.service.resolve_link(meeting_id, 'tasks', 1, 'Подготви офертата за клиента до петък', 'duplicate', item['id'])
        history = len(self.service.tasks()[0]['history'])
        self.service._sync_items(meeting_id)
        self.service._sync_items(meeting_id)
        [item] = self.service.tasks()
        self.assertEqual((item['text'], len(item['history'])), ('Подготви оферта за клиента', history))

    def test_a_shared_task_is_found_in_each_project(self):
        first = self.meeting(notes([task('Обнови сертификатите на принтерите')]), 'A')
        second = self.meeting(notes([task('Обнови сертификатите на принтерите')]), 'B')
        [item] = self.service.tasks()
        self.service.resolve_link(second, 'tasks', 0, 'Обнови сертификатите на принтерите', 'same', item['id'])
        self.service.set_scope(first, {'name': 'Проект A'})
        self.service.set_scope(second, {'name': 'Проект B'})
        for meeting_id in (first, second):
            project = self.service.library.get(meeting_id)['project_id']
            [found] = self.service.find('сертификатите', kind='tasks', project=project)
            self.assertEqual((found['item_id'], found['meeting_id']), (item['id'], meeting_id))
        self.assertEqual(len(self.service.find('сертификатите', kind='tasks')), 1)
