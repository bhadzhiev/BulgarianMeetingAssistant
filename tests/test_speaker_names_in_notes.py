import json
import tempfile
import unittest
from pathlib import Path

from app.notes import name_speakers
from app.service import MeetingService
from app.storage import atomic_json
from tests.test_calendar import FakeGoogle

PROJECT = Path(__file__).resolve().parents[1]


class NameSpeakersTests(unittest.TestCase):
    def test_labels_become_names_in_text_task_and_owner_not_in_quotes(self):
        minutes = dict(summary=[dict(text='SPEAKER_00 обясни плана.', evidence_timestamp='00:00:00')],
                       tasks=[dict(task='SPEAKER_00 да провери SPEAKER_01', owner='SPEAKER_00', deadline=None, evidence_timestamp='00:00:00',
                                   quote='SPEAKER_00 каза')],
                       decisions=[], open_questions=[])
        named = name_speakers(minutes, {'SPEAKER_00': 'Мария', 'SPEAKER_01': 'Иван', 'Петър': 'Пешо'})
        self.assertEqual(named['summary'][0]['text'], 'Мария обясни плана.')
        self.assertEqual((named['tasks'][0]['task'], named['tasks'][0]['owner']), ('Мария да провери Иван', 'Мария'))
        self.assertEqual(named['tasks'][0]['quote'], 'SPEAKER_00 каза')
        self.assertEqual(minutes['tasks'][0]['owner'], 'SPEAKER_00', 'the input stays as it was')

    def test_nothing_to_change_gives_none(self):
        self.assertIsNone(name_speakers(dict(summary=[dict(text='Мария обясни.')]), {'SPEAKER_00': 'Мария'}))
        self.assertIsNone(name_speakers(dict(summary=[dict(text='SPEAKER_010 обясни.')]), {'SPEAKER_01': 'Мария'}))
        self.assertIsNone(name_speakers(dict(summary=[dict(text='SPEAKER_00 обясни.')]), {'Иван': 'Мария'}))


class ServiceNamesSpeakersTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.s = MeetingService(Path(self.tmp.name), PROJECT, google=FakeGoogle());self.addCleanup(self.s.close)
        meeting = self.s.library.create('Среща', 'audio', {})
        self.mid = meeting['id']
        self.s.library.update(self.mid, status='ready', duration=20)
        self.dir = self.s.library.directory(self.mid)
        atomic_json(self.dir / 'transcript.json', [dict(start=0, end=10, speaker='SPEAKER_00', text='Аз ще проверя бекъпа.'),
                                                   dict(start=10, end=20, speaker='SPEAKER_01', text='Добре.')])
        self.s.edit(self.mid, dict(minutes=dict(summary=[dict(text='SPEAKER_00 ще провери бекъпа.', evidence_timestamp='00:00:00')],
                                                decisions=[], open_questions=[],
                                                tasks=[dict(task='SPEAKER_00 да провери бекъпа', owner='SPEAKER_00', deadline=None,
                                                            evidence_timestamp='00:00:00')])))

    def name(self, speaker, name):
        current = json.loads((self.dir / 'transcript.json').read_text())
        return self.s.edit(self.mid, dict(speaker_name=dict(speaker=speaker, name=name, revision=self.s._transcript_revision(current))))

    def test_naming_a_speaker_names_them_in_the_notes_and_the_task(self):
        self.name('SPEAKER_00', 'Мария')
        minutes = json.loads((self.dir / 'minutes.json').read_text())
        self.assertEqual(minutes['summary'][0]['text'], 'Мария ще провери бекъпа.')
        self.assertEqual((minutes['tasks'][0]['task'], minutes['tasks'][0]['owner']), ('Мария да провери бекъпа', 'Мария'))
        [task] = [i for i in self.s.items.items.values() if i['kind'] == 'task']
        self.assertEqual((task['text'], task['owner']), ('Мария да провери бекъпа', 'Мария'))
        self.assertIn('Мария', (self.dir / 'minutes.md').read_text())

        self.assertEqual(task['history'][-1]['event'], 'speaker_named')

    def task(self):
        return next(i for i in self.s.items.items.values() if i['kind'] == 'task')

    def test_a_text_that_a_person_changed_stays(self):
        task = self.task()
        self.s.update_item(task['id'], task['text'], dict(text='Провери бекъпа на файловия сървър'), task['revision'])
        self.name('SPEAKER_00', 'Мария')
        task = self.task()
        self.assertEqual(task['text'], 'Провери бекъпа на файловия сървър')
        self.assertEqual(task['owner'], 'Мария')
        minutes = json.loads((self.dir / 'minutes.json').read_text())
        self.assertEqual(minutes['tasks'][0]['task'], 'Мария да провери бекъпа')

    def test_a_confirmed_review_still_holds(self):
        from app.meeting_review import fingerprint
        task = self.task()
        task['meeting_reviews'] = {self.mid: dict(state='confirmed', content=fingerprint(task))}
        self.s.items.save()
        self.name('SPEAKER_00', 'Мария')
        task = self.task()
        self.assertEqual(task['meeting_reviews'][self.mid]['content'], fingerprint(task))


if __name__ == '__main__':
    unittest.main()
