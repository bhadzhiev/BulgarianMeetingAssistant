from pathlib import Path
import tempfile
import unittest

from app.meeting_review import snapshot, act
from app.service import MeetingService
from app.storage import atomic_json
from tests.test_calendar import FakeGoogle
from tests.test_people_github import PROJECT, ROWS
from tests.ai_meeting_tasks import setUpModule, tearDownModule  # noqa: F401  AI meeting tasks are on in these tests


class ReviewRoutingTests(unittest.TestCase):
    """Each Review item has its own project and destination; routing never changes what a person confirmed."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.s = MeetingService(root / 'library', PROJECT, google=FakeGoogle(), backup_dir=root / 'archives')
        self.addCleanup(self.s.close)
        self.platform = self.s.create_project('Platform')['id']
        self.mobile = self.s.create_project('Mobile')['id']
        self.s.set_project_repositories(self.platform, ['example/platform'])
        self.s.set_project_repositories(self.mobile, ['example/mobile'])
        self.meeting = self.s.library.create('Platform sync', 'in_person', self.s.settings)['id']
        self.s.library.update(self.meeting, created='2026-10-27T08:00:00Z', started_at='2026-10-27T08:00:00Z', status='ready', duration=40, project_id=self.platform)
        atomic_json(self.s.library.directory(self.meeting) / 'transcript.json', ROWS)
        self.s.edit(self.meeting, dict(minutes=dict(summary=[], open_questions=[], decisions=[],
            tasks=[dict(task='Обнови Kubernetes клъстера', owner='Иван', deadline='петък', evidence_timestamp='00:00:12')])))

    def row(self):
        return snapshot(self.s, self.meeting)['items'][0]

    def test_item_inherits_the_meeting_project_and_its_repositories(self):
        row = self.row()
        self.assertEqual((row['project_ids'], row['effective_project_ids']), (None, [self.platform]))
        self.assertEqual((row['repositories'], row['destination_repository']), (['example/platform'], None))

    def test_destination_must_be_a_repository_of_the_item_project(self):
        row = self.row()
        with self.assertRaisesRegex(ValueError, 'repository of the task project'):
            self.s.update_item(row['id'], row['text'], {'destination_repository': 'example/mobile'}, row['revision'])
        self.s.update_item(row['id'], row['text'], {'destination_repository': 'example/platform'}, row['revision'])
        self.assertEqual(self.row()['destination_repository'], 'example/platform')
        draft = self.s.github_draft(dict(resource=dict(kind='item', id=row['id']), format='issue'))
        self.assertEqual(draft['repository'], 'example/platform')

    def test_project_choice_per_item_changes_its_repositories_but_keeps_the_review(self):
        row = self.row()
        act(self.s, dict(meeting_id=self.meeting, item_id=row['id'], action='confirm', source=snapshot(self.s, self.meeting)['source'], content=row['content']))
        self.s.work_graph_action('project', dict(id=row['id'], revision=self.row()['revision'], project_ids=[self.mobile]))
        row = self.row()
        self.assertEqual((row['project_ids'], row['repositories'], row['state']), ([self.mobile], ['example/mobile'], 'confirmed'))


if __name__ == '__main__':
    unittest.main()
