import copy
from pathlib import Path
import tempfile
import unittest

from app.service import MeetingService
from app.items import Registry
from app.work_items import normalize
from tests.test_calendar import FakeGoogle

PROJECT = Path(__file__).resolve().parents[1]


class SharedTaskTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.s = MeetingService(Path(self.tmp.name) / 'library', PROJECT, google=FakeGoogle(), backup_dir=Path(self.tmp.name) / 'backups'); self.addCleanup(self.s.close)
        self.maria = self.s.save_person(dict(name='Maria'))['person']['id']
        self.ivan = self.s.save_person(dict(name='Ivan'))['person']['id']
        self.elena = self.s.save_person(dict(name='Elena'))['person']['id']
        self.task = self.s.create_task(dict(text='Roll out the VPN', owner='Maria', request_id='a' * 32))

    def change(self, **changes):
        self.task = self.s.update_item(self.task['id'], self.task['text'], changes, self.task['revision'])
        return self.task

    def test_migration_from_the_owner_link_is_idempotent(self):
        old = dict(copy.deepcopy(self.task), owner_person_id=self.maria); old.pop('assignee_person_ids', None)
        once = normalize(copy.deepcopy(old)); twice = normalize(copy.deepcopy(once))
        self.assertEqual(once['assignee_person_ids'], [self.maria]); self.assertEqual(once, twice)
        legacy = dict(copy.deepcopy(self.task), owner_person_id=None); legacy.pop('assignee_person_ids', None)
        self.assertEqual(normalize(legacy)['assignee_person_ids'], [])

    def test_first_assignee_is_the_owner_and_others_share_the_task(self):
        task = self.change(assignee_person_ids=[self.maria, self.ivan, self.elena])
        self.assertEqual((task['owner_person_id'], task['owner'], task['assignee_person_ids']), (self.maria, 'Maria', [self.maria, self.ivan, self.elena]))
        # One state for everybody.
        task = self.change(workflow_state='in_progress')
        self.assertEqual(task['assignee_person_ids'], [self.maria, self.ivan, self.elena])
        # Choosing another owner keeps the others.
        task = self.change(owner_person_id=self.ivan)
        self.assertEqual((task['owner'], task['assignee_person_ids']), ('Ivan', [self.ivan, self.maria, self.elena]))
        # The history keeps every change of the list.
        changes = [e['changes']['assignee_person_ids'] for e in task['history'] if 'assignee_person_ids' in e.get('changes', {})]
        self.assertEqual(changes[0], [[], [self.maria, self.ivan, self.elena]])

    def test_removing_the_owner_makes_the_next_one_accountable(self):
        self.change(assignee_person_ids=[self.maria, self.ivan])
        task = self.change(owner_person_id=None, owner=None)
        self.assertEqual((task['owner_person_id'], task['owner'], task['assignee_person_ids']), (self.ivan, 'Ivan', [self.ivan]))

    def test_removing_the_last_assignee_falls_back_to_the_text_owner(self):
        self.change(assignee_person_ids=[self.maria, self.ivan])
        task = self.change(assignee_person_ids=[])
        self.assertEqual((task['owner_person_id'], task['owner'], task['assignee_person_ids']), (None, 'Maria', []))

    def test_a_typed_owner_cannot_drop_a_shared_task_link(self):
        self.change(assignee_person_ids=[self.maria, self.ivan])
        with self.assertRaises(ValueError): self.change(owner='Somebody else')
        with self.assertRaises(ValueError): self.change(assignee_person_ids=[self.maria, self.maria])
        with self.assertRaises(ValueError): self.change(assignee_person_ids=['f' * 12])

    def test_the_list_survives_a_reload_and_shows_in_the_profile(self):
        self.change(assignee_person_ids=[self.maria, self.ivan])
        self.assertEqual(Registry(self.s.items.path).items[self.task['id']]['assignee_person_ids'], [self.maria, self.ivan])
        profile = self.s.person_profile(self.ivan)
        self.assertEqual([t['id'] for t in profile['shared']], [self.task['id']])
        self.assertEqual([t['id'] for t in self.s.person_profile(self.maria)['commitments']], [self.task['id']])


if __name__ == '__main__':
    unittest.main()
