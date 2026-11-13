"""The goal of a project: free text, set at creation or later, carried by merge (2026-11-13)."""
import tempfile
from pathlib import Path
import unittest

from app.projects import Projects
from app.service import MeetingService
from tests.test_calendar import FakeGoogle

PROJECT = Path(__file__).resolve().parents[1]


class ProjectGoalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = Projects(Path(self.tmp.name) / 'projects.json')

    def test_create_with_goal_keeps_newlines(self):
        key = self.store.ensure_project({'name': 'Atlas', 'goal': 'Move the platform to Kubernetes.\nCut deploy time to minutes.'})
        self.assertEqual(self.store.get('projects', key)['goal'], 'Move the platform to Kubernetes.\nCut deploy time to minutes.')

    def test_create_without_goal_has_none(self):
        key = self.store.ensure_project({'name': 'Atlas'})
        self.assertNotIn('goal', self.store.get('projects', key))

    def test_invalid_goal_rejected(self):
        with self.assertRaisesRegex(ValueError, 'goal'):
            self.store.ensure_project({'name': 'Atlas', 'goal': 'x' * 501})
        with self.assertRaisesRegex(ValueError, 'goal'):
            self.store.ensure_project({'name': 'Atlas', 'goal': 'bad\x01text'})

    def test_set_and_clear_goal(self):
        key = self.store.ensure_project({'name': 'Atlas'})
        self.store.set_goal(key, '  Ship the mobile app.  ')
        self.assertEqual(self.store.get('projects', key)['goal'], 'Ship the mobile app.')
        self.store.set_goal(key, '')
        self.assertNotIn('goal', self.store.get('projects', key))

    def test_goal_survives_validation_and_merge(self):
        key = self.store.ensure_project({'name': 'Atlas', 'goal': 'Own the reliability budget.'})
        self.store.save()
        loaded = Projects(Path(self.tmp.name) / 'projects.json')
        self.assertEqual(loaded.get('projects', key)['goal'], 'Own the reliability budget.')
        other = dict(projects=[dict(id='x1', name='Beta', goal='Win client X.')], series=[])
        loaded.merge(other)
        merged = next(p for p in loaded.data['projects'] if p['name'] == 'Beta')
        self.assertEqual(merged['goal'], 'Win client X.')

    def test_merge_rejects_bad_goal(self):
        other = dict(projects=[dict(id='x1', name='Beta', goal='x' * 501)], series=[])
        with self.assertRaises(ValueError):
            self.store.merge(other)


class ProjectGoalServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.s = MeetingService(Path(self.tmp.name) / 'library', PROJECT, google=FakeGoogle(), backup_dir=Path(self.tmp.name) / 'archives')
        self.addCleanup(self.s.close)

    def test_create_project_with_goal(self):
        created = self.s.create_project('Atlas', goal='Move the platform to Kubernetes.')
        entry = next(p for p in created['projects']['projects'] if p['id'] == created['id'])
        self.assertEqual(entry['goal'], 'Move the platform to Kubernetes.')

    def test_change_scope_goal_and_validation(self):
        key = self.s.create_project('Atlas')['id']
        self.s.change_scope('projects', key, 'goal', value='Cut costs.')
        entry = next(p for p in self.s.projects.data['projects'] if p['id'] == key)
        self.assertEqual(entry['goal'], 'Cut costs.')
        self.s.change_scope('projects', key, 'goal', value='')
        self.assertNotIn('goal', entry)
        with self.assertRaises(ValueError):
            self.s.change_scope('series', key, 'goal', value='Cut costs.')


if __name__ == '__main__':
    unittest.main()
