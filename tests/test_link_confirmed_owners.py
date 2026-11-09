import tempfile
import unittest
from pathlib import Path

from app.meeting_review import fingerprint
from app.service import MeetingService
from tests.test_calendar import FakeGoogle

PROJECT = Path(__file__).resolve().parents[1]


class LinkConfirmedOwnersTests(unittest.TestCase):
    """A confirmed owner name of exactly one person links the task to that person."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.s = MeetingService(Path(self.tmp.name), PROJECT, google=FakeGoogle());self.addCleanup(self.s.close)
        self.maria = self.s.save_person(dict(name='Мария Петрова', aliases=['Мария']))['person']

    def tasks(self, *owners):
        """Create all tasks first: a new task reloads the store, so the items are read after it."""
        ids = [self.s.create_task(dict(text=f'Задача {n}', owner=owner, request_id=f'{n:032x}'))['id'] for n, owner in enumerate(owners, 1)]
        items = [self.s.items.items[key] for key in ids]
        for item in items:
            item['owner_person_id'] = None
        return items

    def test_a_confirmed_name_of_one_person_links_and_keeps_the_review(self):
        [item] = self.tasks('Мария')
        item['meeting_reviews'] = {'m1': dict(state='confirmed', content=fingerprint(item))}
        self.assertEqual(self.s._link_confirmed_owners(), 1)
        self.assertEqual(item['owner_person_id'], self.maria['id'])
        self.assertEqual(item['history'][-1]['event'], 'owner_linked')
        self.assertEqual(item['meeting_reviews']['m1']['content'], fingerprint(item))
        self.assertEqual(self.s._link_confirmed_owners(), 0)

    def test_unconfirmed_unknown_placeholder_and_proposed_owners_stay(self):
        unconfirmed, proposed, unknown, speaker = self.tasks('Мария Петрова', 'Мария Петрова', 'Иван', 'SPEAKER_01')
        unconfirmed['manual'].remove('owner')
        proposed['acceptance_state'] = 'proposed'
        self.assertEqual(self.s._link_confirmed_owners(), 0)
        for item in (unconfirmed, proposed, unknown, speaker):
            self.assertIsNone(item['owner_person_id'])

    def test_a_chosen_person_is_never_replaced(self):
        [item] = self.tasks('Мария')
        other = self.s.save_person(dict(name='Иван'))['person']
        item = self.s.items.items[item['id']];item['owner_person_id'] = other['id']
        self.assertEqual(self.s._link_confirmed_owners(), 0)
        self.assertEqual(item['owner_person_id'], other['id'])

    def test_the_task_list_links_and_saves(self):
        [item] = self.tasks('Мария')
        self.s.item_list()
        self.s.items.data, self.s.items.revision = self.s.items.store.load()
        self.assertEqual(self.s.items.items[item['id']]['owner_person_id'], self.maria['id'])


if __name__ == '__main__':
    unittest.main()
