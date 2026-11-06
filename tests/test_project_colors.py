import tempfile
from pathlib import Path
import unittest
from app.projects import Projects
from app.service import MeetingService
from tests.test_calendar import FakeGoogle
PROJECT = Path(__file__).resolve().parents[1]


class ProjectColorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = Projects(Path(self.tmp.name) / 'projects.json')

    def test_create_with_color_is_normalized(self):
        key = self.store.ensure_project({'name': 'Atlas', 'color': ' #5B8DEF '})
        self.assertEqual(self.store.get('projects', key)['color'], '#5b8def')

    def test_create_without_color_has_none(self):
        key = self.store.ensure_project({'name': 'Atlas'})
        self.assertNotIn('color', self.store.get('projects', key))

    def test_invalid_color_rejected(self):
        with self.assertRaises(ValueError):
            self.store.ensure_project({'name': 'Atlas', 'color': 'blue'})
        with self.assertRaises(ValueError):
            self.store.ensure_project({'name': 'Atlas', 'color': '#12345'})

    def test_set_and_clear_color(self):
        key = self.store.ensure_project({'name': 'Atlas'})
        self.store.set_color(key, '#E2B33C')
        self.assertEqual(self.store.get('projects', key)['color'], '#e2b33c')
        self.store.set_color(key, None)
        self.assertNotIn('color', self.store.get('projects', key))

    def test_color_survives_validation_and_merge(self):
        key = self.store.ensure_project({'name': 'Atlas', 'color': '#4cb782'})
        self.store.save()
        loaded = Projects(Path(self.tmp.name) / 'projects.json')
        self.assertEqual(loaded.get('projects', key)['color'], '#4cb782')
        other = dict(projects=[dict(id='x1', name='Beta', color='#C9699E')], series=[])
        loaded.merge(other)
        merged = next(p for p in loaded.data['projects'] if p['name'] == 'Beta')
        self.assertEqual(merged['color'], '#c9699e')

    def test_merge_rejects_bad_color(self):
        other = dict(projects=[dict(id='x1', name='Beta', color='red')], series=[])
        with self.assertRaises(ValueError):
            self.store.merge(other)


class ProjectColorServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.s = MeetingService(Path(self.tmp.name) / 'library', PROJECT, google=FakeGoogle(), backup_dir=Path(self.tmp.name) / 'archives')
        self.addCleanup(self.s.close)

    def test_create_project_with_color(self):
        created = self.s.create_project('Atlas', color='#5B8DEF')
        entry = next(p for p in created['projects']['projects'] if p['id'] == created['id'])
        self.assertEqual(entry['color'], '#5b8def')

    def test_change_scope_color_and_validation(self):
        key = self.s.create_project('Atlas')['id']
        self.s.change_scope('projects', key, 'color', value='#e2b33c')
        entry = next(p for p in self.s.projects.data['projects'] if p['id'] == key)
        self.assertEqual(entry['color'], '#e2b33c')
        with self.assertRaises(ValueError):
            self.s.change_scope('projects', key, 'color', value='not-a-color')
        with self.assertRaises(ValueError):
            self.s.change_scope('series', key, 'color', value='#e2b33c')


if __name__ == '__main__':
    unittest.main()
