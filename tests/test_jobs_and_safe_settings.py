"""A running task draft is in the job list; a damaged settings file does not stop the app."""
import json
from pathlib import Path
import tempfile
import unittest

from app.service import DEFAULTS, MeetingService
from tests.test_calendar import FakeGoogle

PROJECT = Path(__file__).resolve().parents[1]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def service(self):
        s = MeetingService(self.root / 'library', PROJECT, google=FakeGoogle(), backup_dir=self.root / 'backups')
        self.addCleanup(s.close)
        return s


class TaskDraftJobTests(Base):
    def test_a_running_task_draft_is_a_running_job_with_its_source(self):
        s = self.service()
        s.task_drafts.job = dict(id='draft1', running=True, status='Generating task draft', started_at=1)
        s.task_drafts.body = dict(provider='gmail', id='thread1')
        listing = s.jobs.listing()
        self.assertEqual(listing['summary']['running'], 1)
        row = next(r for r in listing['jobs'] if r['family'] == 'task_draft')
        self.assertEqual((row['label'], row['target']), ('Task draft with AI', dict(view='work', id='gmail')))

    def test_a_failed_task_draft_stays_until_dismissed(self):
        s = self.service()
        s.task_drafts.job = dict(id='draft2', running=False, status='Failed', error='Synthetic failure', started_at=1)
        s.task_drafts.body = dict(provider='meeting', id='a' * 32)
        row = next(r for r in s.jobs.listing()['jobs'] if r['family'] == 'task_draft')
        self.assertEqual((row['state'], row['target']), ('failed', dict(view='meeting', id='a' * 32)))
        s.jobs.dismiss(row['id'])
        self.assertFalse(any(r['family'] == 'task_draft' for r in s.jobs.listing()['jobs']))


class SafeSettingsTests(Base):
    def write(self, text):
        library = self.root / 'library'
        library.mkdir(parents=True, exist_ok=True)
        (library / 'settings.json').write_text(text)
        return library

    def test_damaged_settings_start_safe_and_keep_the_original(self):
        library = self.write('{broken')
        s = self.service()
        self.assertIn('Settings could not be read', s.settings_error)
        self.assertEqual((s.settings['auto_process'], s.settings['calendar_enabled'], s.settings['summarizer']), (False, False, 'none'))
        copies = list(library.glob('settings.corrupt-*.json'))
        self.assertEqual([c.read_text() for c in copies], ['{broken'])
        self.assertEqual((library / 'settings.json').read_text(), '{broken')  # nothing is written until a person saves
        self.assertIn(copies[0].name, s.settings_error)

    def test_settings_that_are_not_an_object_are_damaged_too(self):
        self.write('[1, 2]')
        self.assertIsNotNone(self.service().settings_error)

    def test_saving_valid_settings_ends_the_safe_mode(self):
        library = self.write('{broken')
        s = self.service()
        s.save_settings(dict(auto_process=False))
        self.assertIsNone(s.settings_error)
        self.assertEqual(json.loads((library / 'settings.json').read_text())['auto_process'], False)

    def test_valid_settings_have_no_error(self):
        self.write(json.dumps(dict(DEFAULTS, summarizer='local')))
        s = self.service()
        self.assertIsNone(s.settings_error)
        self.assertEqual(s.settings['summarizer'], 'local')


if __name__ == '__main__':
    unittest.main()
