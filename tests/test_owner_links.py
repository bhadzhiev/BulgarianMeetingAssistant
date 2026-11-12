from pathlib import Path
import tempfile
import unittest

from app.people import People
from app.service import MeetingService
from app.storage import atomic_json
from tests.test_calendar import FakeGoogle
from tests.test_people_github import PROJECT, ROWS
from tests.ai_meeting_tasks import setUpModule, tearDownModule  # noqa: F401  AI meeting tasks are on in these tests


class OwnerLinkTests(unittest.TestCase):
    """A commitment links to a person only when a person chooses; a name alone stays a suggestion."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.s = MeetingService(root / 'library', PROJECT, google=FakeGoogle(), backup_dir=root / 'archives')
        self.addCleanup(self.s.close)
        meeting = self.s.library.create('Platform sync', 'in_person', self.s.settings)['id']
        self.s.library.update(meeting, created='2026-10-27T08:00:00Z', started_at='2026-10-27T08:00:00Z', status='ready', duration=40)
        atomic_json(self.s.library.directory(meeting) / 'transcript.json', ROWS)
        self.s.edit(meeting, dict(minutes=dict(summary=[], open_questions=[], decisions=[],
            tasks=[dict(task='Обнови Kubernetes клъстера', owner='Иван', deadline='петък', evidence_timestamp='00:00:12')])))
        self.ivan = self.s.save_person(dict(name='Иван Петров', aliases=['Иван']))['person']
        self.maria = self.s.save_person(dict(name='Мария Георгиева', aliases=['Мария']))['person']

    def task(self):
        return next(i for i in self.s.item_list()['items'] if i['kind'] == 'task')

    def test_name_match_is_a_suggestion_until_a_person_links_it(self):
        self.assertEqual(self.s.people.owner_of(self.task())[1], 'name')
        self.assertEqual(self.s.person_profile(self.ivan['id'])['commitments'], [])
        task = self.task()
        self.s.update_item(task['id'], task['text'], {'owner_person_id': self.ivan['id']}, task['revision'])
        task = self.task()
        self.assertEqual((task['owner'], task['owner_person_id']), ('Иван', self.ivan['id']))
        self.assertIn('owner', task['manual'])
        self.assertEqual(self.s.people.owner_of(task)[1], 'linked')
        self.assertEqual([t['id'] for t in self.s.person_profile(self.ivan['id'])['commitments']], [task['id']])

    def test_linking_a_task_without_owner_uses_the_person_name(self):
        task = self.task()
        self.s.update_item(task['id'], task['text'], {'owner': None}, task['revision'])
        task = self.task()
        self.s.update_item(task['id'], task['text'], {'owner_person_id': self.maria['id']}, task['revision'])
        self.assertEqual(self.task()['owner'], 'Мария Георгиева')

    def test_a_new_owner_name_ends_the_link(self):
        task = self.task()
        self.s.update_item(task['id'], task['text'], {'owner_person_id': self.ivan['id']}, task['revision'])
        task = self.task()
        self.s.update_item(task['id'], task['text'], {'owner': 'Иван Петров'}, task['revision'])
        self.assertEqual(self.task()['owner_person_id'], self.ivan['id'])
        task = self.task()
        self.s.update_item(task['id'], task['text'], {'owner': 'Мария'}, task['revision'])
        task = self.task()
        self.assertIsNone(task['owner_person_id'])
        self.assertEqual(self.s.people.owner_of(task), (self.s.people.get(self.maria['id']), 'name'))

    def test_unknown_person_is_rejected(self):
        task = self.task()
        with self.assertRaisesRegex(ValueError, 'no longer exists'):
            self.s.update_item(task['id'], task['text'], {'owner_person_id': 'a' * 12}, task['revision'])

    def test_a_shared_name_links_nobody(self):
        people = People(Path(self.tmp.name) / 'people.json')
        people.people = [dict(id='a' * 12, name='Иван', aliases=[]), dict(id='b' * 12, name='Иван Иванов', aliases=['Иван'])]
        self.assertEqual(people.owner_of(dict(owner='иван')), (None, 'ambiguous'))
        self.assertEqual(people.owner_of(dict(owner='SPEAKER_01')), (None, None))
        self.assertEqual(people.owner_of(dict(owner='Иван', owner_person_id='b' * 12))[1], 'linked')


if __name__ == '__main__':
    unittest.main()
