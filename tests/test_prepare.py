import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.service import MeetingService
from app.storage import atomic_json
from tests.test_app import FakeRecorder, wait_for
from tests.test_calendar import FakeGoogle

PROJECT = Path(__file__).resolve().parents[1]
LATE = (dt.date.today() - dt.timedelta(days=2)).isoformat()


def task(text, owner=None, due_date=None):
    return dict(task=text, owner=owner, deadline=None, due_date=due_date, evidence_timestamp='00:00:00')


def item(text, review='ai'):
    return dict(text=text, evidence_timestamp='00:00:00', review=review)


def notes(tasks=(), decisions=(), decide=(), discuss=()):
    return dict(summary=[], decisions=list(decisions), tasks=list(tasks), needs_decision=list(decide), open_questions=list(discuss))


class PrepareTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.service = MeetingService(self.root / 'library', PROJECT, google=FakeGoogle(), backup_dir=self.root / 'backups')

    def tearDown(self):
        self.service.close()
        self.tmp.cleanup()

    def meeting(self, title, when, minutes, project=None, series=None):
        meeting = self.service.library.create(title, 'in_person', {})
        self.service.library.update(meeting['id'], status='ready', duration=60, started_at=when, created=when)
        atomic_json(self.service.library.directory(meeting['id']) / 'transcript.json', [dict(start=0, end=5, text='Да.', speaker=None)])
        self.service.edit(meeting['id'], {'minutes': minutes})
        if project:
            self.service.set_scope(meeting['id'], project, series)
        return meeting['id']

    def scenario(self):
        devops, weekly = {'name': 'DevOps'}, {'name': 'Weekly'}
        first = self.meeting('Weekly 1', '2026-10-19T10:00:00+03:00', notes(
            [task('Провери VPN failover', 'Иван', LATE), task('Купи UPS за сървърното')],
            [item('Резервният интернет е LTE рутер', 'verified')],
            [item('Кой плаща лиценза за VPN?')], [item('Дали ще сменим доставчика на интернет?')]), devops, weekly)
        second = self.meeting('Weekly 2', '2026-10-23T10:00:00+03:00', notes(
            [task('Обнови документацията на API')],
            [item('Сменяме доставчика на интернет с оптика от Виваком', 'verified')],
            [item('Кой плаща лиценза за VPN')]), devops, weekly)
        done = next(t for t in self.service.tasks() if t['text'].startswith('Обнови'))
        self.service.update_item(done['id'], done['text'], {'status': 'done'})
        atomic_json(self.service.library.directory(second) / 'markers.json', [dict(id='m', time=75, kind='check', note='Бюджет за UPS')])
        self.meeting('DevOps planning', '2026-10-20T10:00:00+03:00', notes([task('Резервирай зала за демото')]), devops)
        self.meeting('Client X', '2026-10-21T10:00:00+03:00', notes([task('Изпрати оферта на клиента')]), {'name': 'Client X'})
        data = self.service.projects.data
        project_id = next(p['id'] for p in data['projects'] if p['name'] == 'DevOps')
        return first, second, project_id, data['series'][0]['id']

    def test_series_briefing_brings_open_work_questions_decisions_and_an_agenda(self):
        first, second, _, series_id = self.scenario()
        result = self.service.prepare(series_id=series_id)
        self.assertEqual(result['title'], 'DevOps · Weekly')
        self.assertEqual([m['title'] for m in result['meetings']], ['Weekly 1', 'Weekly 2'])
        self.assertEqual([(t['text'], t['overdue']) for t in result['tasks']], [('Провери VPN failover', True), ('Купи UPS за сървърното', False)])
        self.assertEqual(result['tasks'][0]['source']['meeting_id'], first)
        self.assertEqual([d['text'] for d in result['decisions']], ['Сменяме доставчика на интернет с оптика от Виваком', 'Резервният интернет е LTE рутер'])
        questions = {q['text']: q for q in result['questions']}
        self.assertEqual(set(questions), {'Кой плаща лиценза за VPN', 'Дали ще сменим доставчика на интернет?'})
        self.assertEqual(questions['Кой плаща лиценза за VPN']['source']['meeting_id'], second)
        self.assertEqual(questions['Дали ще сменим доставчика на интернет?']['maybe_answered_by']['text'], 'Сменяме доставчика на интернет с оптика от Виваком')
        self.assertEqual([a['title'] for a in result['agenda']], [
            'Overdue: Провери VPN failover (Иван)', 'Decide: Кой плаща лиценза за VPN',
            'Give an owner and a date to 1 open task', 'Check: Бюджет за UPS', 'New tasks, owners and dates'])
        self.assertEqual(result['agenda'][3]['sources'][0], dict(meeting_id=second, meeting_title='Weekly 2', meeting_date='2026-10-23T10:00:00+03:00', timestamp='00:01:15'))
        self.assertIn('1. Overdue: Провери VPN failover (Иван)', result['markdown'])
        self.assertIn('- [ ] Купи UPS за сървърното — Weekly 1 00:00:00', result['markdown'])

    def test_project_briefing_includes_meetings_outside_the_series_only_of_that_project(self):
        _, _, project_id, _ = self.scenario()
        texts = [t['text'] for t in self.service.prepare(project_id=project_id)['tasks']]
        self.assertIn('Резервирай зала за демото', texts)
        self.assertNotIn('Изпрати оферта на клиента', texts)
        with self.assertRaisesRegex(ValueError, 'Choose a project'):
            self.service.prepare()

    def test_projects_and_series_are_created_reused_validated_and_removed(self):
        meeting_id = self.meeting('Среща', '2026-10-19T10:00:00+03:00', notes())
        detail = self.service.set_scope(meeting_id, {'name': ' DevOps '}, {'name': 'Weekly'})
        again = self.service.set_scope(meeting_id, {'name': 'devops'}, {'name': 'weekly'})
        self.assertEqual((again['project_id'], again['series_id']), (detail['project_id'], detail['series_id']))
        self.assertEqual(len(self.service.projects.data['projects']), 1)
        with self.assertRaisesRegex(ValueError, 'Choose a project'):
            self.service.set_scope(meeting_id, None, {'name': 'Weekly'})
        other = self.service.projects.ensure_project({'name': 'Client X'})
        with self.assertRaisesRegex(ValueError, 'does not belong'):
            self.service.set_scope(meeting_id, {'id': other}, {'id': detail['series_id']})
        self.service.change_scope('projects', detail['project_id'], 'rename', 'DevOps team')
        self.assertEqual(self.service.projects.get('projects', detail['project_id'])['name'], 'DevOps team')
        self.service.change_scope('projects', detail['project_id'], 'delete')
        meeting = self.service.library.get(meeting_id)
        self.assertEqual((meeting['project_id'], meeting['series_id']), (None, None))
        self.assertEqual(self.service.projects.data['series'], [])

    def test_a_new_recording_can_start_in_a_series(self):
        project_id = self.service.projects.ensure_project({'name': 'DevOps'})
        series_id = self.service.projects.ensure_series({'name': 'Weekly'}, project_id)
        self.service.save_settings({'auto_process': False, 'live_transcription': False})
        with patch('app.service.devices', return_value=[{'id': 2}]), patch('app.service.Recorder', FakeRecorder):
            meeting = self.service.start('', 'in_person', 2, project_id, series_id)
            wait_for(lambda: self.service.library.get(meeting['id'])['status'] == 'recording')
            self.service.stop()
            wait_for(lambda: self.service.library.get(meeting['id'])['status'] == 'recorded')
        self.assertEqual(self.service.library.get(meeting['id'])['series_id'], series_id)

    def test_archives_keep_projects_and_task_history(self):
        _, _, project_id, _ = self.scenario()
        name = self.service.create_backup()['created']['name']
        history = {t['text']: len(t['history']) for t in self.service.tasks()}
        other = MeetingService(self.root / 'other', PROJECT, google=FakeGoogle(), backup_dir=self.root / 'backups')
        try:
            other.restore_backup(name)
            self.assertEqual(other.projects.get('projects', project_id)['name'], 'DevOps')
            self.assertEqual({t['text']: len(t['history']) for t in other.tasks()}, history)
            self.assertEqual(other.item_list()['pending'], [])
        finally:
            other.close()
