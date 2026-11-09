import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from app import meeting_proposals, task_matching
from app.service import MeetingService
from app.storage import atomic_json
from tests.test_calendar import FakeGoogle

PROJECT = Path(__file__).resolve().parents[1]


class SpeakerTaskUpdateTests(unittest.TestCase):
    """What a speaker says about their own open task is added to it after the notes."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.s = MeetingService(Path(self.tmp.name), PROJECT, google=FakeGoogle());self.addCleanup(self.s.close)
        self.ivan = self.s.save_person(dict(name='Иван'))['person']
        self.maria = self.s.save_person(dict(name='Мария'))['person']
        self.offer = self.task('Подготви офертата за клиента', self.ivan, 'a')
        self.server = self.task('Инсталирай новия сървър', self.maria, 'b')
        self.answers = {}
        self.inputs = []
        real = self.s._execute

        def execute(action, directory, settings, progress, key='', *rest):
            if action != 'task_matching':
                return real(action, directory, settings, progress, key, *rest)
            data = settings['task_matching_input'];self.inputs.append(data)
            return task_matching.validate(dict(matches=[dict(mention_id=m['id'], type='existing_update', task_id=self.answers[m['id']],
                                                             reason='Same work', update_text=text, changes=[])
                                                        for m in data['mentions'] for text in [f'Ново за {m["id"]}']]), data)
        self.s._execute = execute

    def task(self, text, person, key):
        item = self.s.create_task(dict(text=text, request_id=key * 32))
        return self.s.update_item(item['id'], item['text'], dict(owner_person_id=person['id']), item['revision'])

    def meeting(self):
        meeting = self.s.library.create('Седмична среща', 'in_person', {})
        when = '2026-11-20T10:00:00+02:00'
        self.s.library.update(meeting['id'], status='ready', duration=60, started_at=when, created=when)
        atomic_json(self.s.library.directory(meeting['id']) / 'transcript.json', [
            dict(start=0, end=10, speaker='Иван', text='Чакам цените от доставчика, после пращам.'),
            dict(start=10, end=20, speaker='Мария', text='Иван още чака цените.')])
        self.s.edit(meeting['id'], {'minutes': dict(summary=[], decisions=[], tasks=[], open_questions=[], updates=[
            dict(text='Чака цени от доставчика', evidence_timestamp='00:00:00', quote='Чакам цените от доставчика'),
            dict(text='Подготвя офертата за клиента, още чака цените', evidence_timestamp='00:00:10', quote='Иван още чака цените')])})
        return meeting['id']

    def run_step(self, meeting_id):
        directory = self.s.library.directory(meeting_id)
        self.s._match_tasks(meeting_id, directory, dict(self.s.settings, summarizer='local'), lambda *a, **k: None, '')
        return json.loads((directory / 'task-matching.json').read_text())

    def updates(self, item):
        return [e for e in self.s.items.items[item['id']]['history'] if e.get('event') == 'progress_update']

    def test_speaker_tasks_are_candidates_even_with_other_words(self):
        mid = self.meeting()
        self.answers = dict(u0=self.offer['id'], u1=self.offer['id'])
        self.run_step(mid)
        [data] = self.inputs
        first = next(m for m in data['mentions'] if m['id'] == 'u0')
        self.assertEqual(first['speaker'], 'Иван')
        self.assertEqual(first['candidate_ids'][0], self.offer['id'])
        self.assertNotIn(self.server['id'], first['candidate_ids'])
        self.assertEqual(data['speaker_ids'], dict(u0=self.ivan['id'], u1=self.maria['id']))
        # The person IDs stay on this Mac: the request has only the mentions and the tasks.
        with mock.patch('app.local_ai.complete_json', return_value=dict(matches=[])) as complete:
            task_matching.generate(data, dict(local_ai_base_url='http://127.0.0.1:1', local_ai_model='m'))
        self.assertNotIn('speaker_ids', complete.call_args[0][1][1]['content'])

    def test_only_the_speaker_own_open_task_gets_the_update(self):
        mid = self.meeting()
        # u0: Иван about his own task. u1: Мария about the task of Иван — that waits for review.
        self.answers = dict(u0=self.offer['id'], u1=self.offer['id'])
        record = self.run_step(mid)
        self.assertEqual(record['applied'], ['u0'])
        [update] = self.updates(self.offer)
        self.assertEqual((update['by'], update['text'], update['meeting_id'], update['evidence_timestamp']), ('ai', 'Ново за u0', mid, '00:00:00'))
        self.assertEqual(update['quote'], 'Чакам цените от доставчика')
        # Running again adds nothing.
        self.run_step(mid)
        self.assertEqual(len(self.updates(self.offer)), 1)
        # For review shows only the mention that was not added.
        _, found = meeting_proposals.suggestions(self.s, mid)
        self.assertEqual([meta['index'] for _, meta in found], [1])

    def test_closed_task_gets_no_update(self):
        mid = self.meeting()
        offer = self.s.items.items[self.offer['id']]
        self.s.update_item(offer['id'], offer['text'], dict(workflow_state='done'), offer['revision'])
        self.answers = dict(u0=self.offer['id'], u1=self.server['id'])
        record = self.run_step(mid)
        # The update of Мария about her own open task is added; the closed task of Иван gets nothing.
        self.assertEqual(record.get('applied', []), ['u1'])
        self.assertEqual(self.updates(self.offer), [])
        self.assertEqual(len(self.updates(self.server)), 1)

    def test_unknown_speaker_adds_nothing(self):
        mid = self.meeting()
        rows = json.loads((self.s.library.directory(mid) / 'transcript.json').read_text())
        for row in rows:row['speaker'] = 'SPEAKER_01'
        atomic_json(self.s.library.directory(mid) / 'transcript.json', rows)
        self.answers = dict(u0=self.offer['id'], u1=self.offer['id'])
        record = self.run_step(mid)
        self.assertEqual(record.get('applied', []), [])
        self.assertEqual(self.updates(self.offer), [])

    def test_a_person_can_remove_an_added_update(self):
        mid = self.meeting()
        self.answers = dict(u0=self.offer['id'], u1=self.server['id'])
        self.run_step(mid)
        [update] = self.updates(self.offer)
        self.s.remove_meeting_update(self.offer['id'], dict(meeting_id=mid, evidence_timestamp='00:00:00', text=update['text']))
        self.assertEqual(self.updates(self.offer), [])
        self.assertEqual(self.s.items.items[self.offer['id']]['history'][-1]['event'], 'meeting_update_removed')
        # A person update is never removed this way.
        with self.assertRaises(Exception):
            self.s.remove_meeting_update(self.offer['id'], dict(meeting_id=mid, evidence_timestamp='00:00:00', text=update['text']))


if __name__ == '__main__':
    unittest.main()
