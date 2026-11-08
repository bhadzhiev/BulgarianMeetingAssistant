import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest

from app.people import People, in_team
from app.service import MeetingService
from app.storage import atomic_json
from app.work_items import WorkItemConflict
from tests.test_calendar import FakeGoogle

PROJECT = Path(__file__).resolve().parents[1]


class TeamMembershipTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'library'; self.root.mkdir()

    def test_old_profiles_load_without_team_and_keep_their_ids(self):
        atomic_json(self.root / 'people.json', [dict(id='a1b2c3d4e5f6', name='Maria', emails=[], aliases=[], identities=[], github=None, notes='', revision=3)])
        person = People(self.root / 'people.json').get('a1b2c3d4e5f6')
        self.assertEqual((person['id'], person['revision'], person['team']), ('a1b2c3d4e5f6', 3, []))

    def test_leave_and_rejoin_keep_the_history(self):
        people = People(self.root / 'people.json')
        p = people.save(dict(name='Maria'))
        p = people.team_change(p['id'], p['revision'], 'join', '2026-01-05')
        self.assertTrue(in_team(p, '2026-01-05'))
        with self.assertRaises(ValueError): people.team_change(p['id'], p['revision'], 'join', '2026-01-06')
        with self.assertRaises(ValueError): people.team_change(p['id'], p['revision'], 'leave', '2026-01-01')
        p = people.team_change(p['id'], p['revision'], 'leave', '2026-04-01')
        self.assertTrue(in_team(p, '2026-03-31')); self.assertFalse(in_team(p, '2026-04-01'))
        with self.assertRaises(ValueError): people.team_change(p['id'], p['revision'], 'join', '2026-03-31')
        p = people.team_change(p['id'], p['revision'], 'join', '2026-06-01')
        self.assertEqual(p['team'], [dict(start='2026-01-05', end='2026-04-01'), dict(start='2026-06-01', end=None)])
        with self.assertRaises(WorkItemConflict): people.team_change(p['id'], p['revision'] - 1, 'leave', '2026-07-01')

    def test_profile_edit_keeps_team_periods(self):
        people = People(self.root / 'people.json')
        p = people.save(dict(name='Maria'))
        p = people.team_change(p['id'], p['revision'], 'join', '2026-01-05')
        p = people.save(dict(id=p['id'], revision=p['revision'], name='Maria', notes='Backend'))
        self.assertEqual(p['team'], [dict(start='2026-01-05', end=None)])

    def test_overview_lists_members_and_their_projects_without_analysis(self):
        service = MeetingService(self.root, PROJECT, google=FakeGoogle(), backup_dir=Path(self.tmp.name) / 'archives'); self.addCleanup(service.close)
        project = service.create_project('Atlas')['id']
        meeting = service.library.create('Planning', 'in_person', service.settings)
        service.library.update(meeting['id'], status='ready', project_id=project)
        atomic_json(service.library.directory(meeting['id']) / 'transcript.json', [dict(start=0, end=5, speaker='Maria', text='I take the VPN rollout.')])
        maria = service.save_person(dict(name='Maria'))['person']; ivan = service.save_person(dict(name='Ivan'))['person']
        self.assertEqual(service.team_overview(), dict(members=[]))
        today = dt.date.today().isoformat()
        result = service.team_change(dict(id=maria['id'], revision=maria['revision'], action='join', date=today))
        self.assertEqual(result['team']['members'], [dict(id=maria['id'], active=True, periods=[dict(start=today, end=None)], project_ids=[project])])
        self.assertNotIn(ivan['id'], [m['id'] for m in result['team']['members']])
        self.assertFalse(list(self.root.glob('team-reviews*')))


if __name__ == '__main__':
    unittest.main()
