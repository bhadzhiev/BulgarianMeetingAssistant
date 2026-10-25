"""Different actions on the same task or decision keep one identity, one history and one state."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app import processing
from app.service import DEFAULTS, MeetingService
from app.storage import atomic_json
from meeting_assistant import TranscriptSegment, save_transcript
from tests.test_calendar import FakeGoogle

PROJECT = Path(__file__).resolve().parents[1]
JOB = dict(DEFAULTS, diarization_enabled=False, transcript_correction='none', summarizer='local')


def task(text, owner=None):
    return dict(task=text, owner=owner, deadline=None, due_date=None, evidence_timestamp='00:00:00')


def decision(text, review='ai'):
    return dict(text=text, evidence_timestamp='00:00:00', review=review)


def notes(tasks=(), decisions=()):
    return dict(summary=[], decisions=list(decisions), tasks=list(tasks), open_questions=[])


class ConsistencyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.service = MeetingService(Path(self.tmp.name), PROJECT, google=FakeGoogle())

    def tearDown(self):
        self.service.close()
        self.tmp.cleanup()

    def meeting(self, minutes, when='2026-10-19T10:00:00+03:00'):
        meeting = self.service.library.create('Среща', 'in_person', JOB)
        self.service.library.update(meeting['id'], status='ready', duration=60, started_at=when, created=when)
        directory = self.service.library.directory(meeting['id'])
        (directory / 'recording.wav').write_bytes(b'')  # the jobs below never read it; they only check it exists
        save_transcript(directory, [TranscriptSegment(0, 5, 'Да.')])
        self.service.edit(meeting['id'], {'minutes': minutes})
        return meeting['id']

    def minutes(self, meeting_id):
        return json.loads((self.service.library.directory(meeting_id) / 'minutes.json').read_text())

    def transcribe_again(self, meeting_id):
        def transcribe(directory, *args):
            # What the real job does with the notes: archive them, then remove them.
            processing.archive(directory, ['minutes.json', 'minutes.md'])
            for name in ('minutes.json', 'minutes.md'):
                (directory / name).unlink()
            save_transcript(directory, [TranscriptSegment(0, 5, 'Да.')])
        with patch('app.processing.transcribe', side_effect=transcribe):
            self.service._process(meeting_id, 'transcribe', dict(JOB, summarizer='none'), '')

    def new_notes(self, meeting_id, minutes):
        with patch('meeting_assistant.generate_minutes', return_value=minutes):
            self.service._process(meeting_id, 'summarize', JOB, '')
        self.assertEqual(self.service.library.get(meeting_id)['status'], 'ready')

    def test_transcribing_again_keeps_a_done_task_with_its_manual_owner(self):
        meeting_id = self.meeting(notes([task('Провери VPN failover', 'Иван')]))
        [item] = self.service.tasks()
        self.service.update_item(item['id'], item['text'], {'owner': 'Мария', 'status': 'done'})
        self.transcribe_again(meeting_id)
        [item] = self.service.tasks()
        self.assertEqual((item['status'], item['owner'], item['history'][-1]['event']), ('done', 'Мария', 'detached'))
        self.new_notes(meeting_id, notes([task('Провери VPN failover', 'Иван')]))
        [item] = self.service.tasks()
        self.assertEqual((item['status'], item['owner']), ('done', 'Мария'))
        self.assertEqual(self.minutes(meeting_id)['tasks'][0]['status'], 'done')
        self.assertEqual(self.service.item_list()['pending'], [])

    def test_a_reworded_task_after_transcribing_again_waits_for_review_even_when_done(self):
        meeting_id = self.meeting(notes([task('Провери VPN failover на офиса', 'Иван')]))
        [item] = self.service.tasks()
        self.service.update_item(item['id'], item['text'], {'status': 'done'})
        self.transcribe_again(meeting_id)
        self.new_notes(meeting_id, notes([task('Провери failover на VPN в офиса', 'Иван')]))
        [pending] = self.service.item_list()['pending']
        self.assertEqual(pending['candidates'][0]['item_id'], item['id'])
        self.service.resolve_link(meeting_id, 'tasks', 0, pending['text'], 'same', item['id'])
        [item] = self.service.tasks()
        self.assertEqual((item['status'], self.minutes(meeting_id)['tasks'][0]['status']), ('done', 'done'))

    def test_a_changed_ai_decision_is_proposed_again(self):
        meeting_id = self.meeting(notes(decisions=[decision('Резервният интернет е LTE рутер', 'verified')]))
        self.assertEqual(self.service.item_list()['items'][0]['status'], 'accepted')
        self.new_notes(meeting_id, notes(decisions=[decision('Резервният интернет е LTE рутер от Виваком')]))
        proposal = self.service.detail(meeting_id)['minutes_proposal']
        self.service.review_notes(meeting_id, 'apply', [c['id'] for c in proposal['changes']], proposal['revision'])
        [item] = self.service.item_list()['items']
        self.assertEqual((item['text'], item['status']), ('Резервният интернет е LTE рутер от Виваком', 'proposed'))
        self.assertEqual([r['status'] for r in self.service.find('Виваком', kind='decisions')], ['proposed'])

    def test_a_status_change_in_one_meeting_reaches_every_linked_meeting(self):
        first = self.meeting(notes([task('Купи UPS за сървърното')], [decision('Сървърите остават в офиса')]))
        second = self.meeting(notes([task('Купи UPS за сървърното')], [decision('Сървърите остават в офиса')]), '2026-10-23T10:00:00+03:00')
        task_id = next(i['id'] for i in self.service.tasks())
        decision_id = next(i['id'] for i in self.service.item_list()['items'] if i['kind'] == 'decision')
        self.service.resolve_link(second, 'tasks', 0, 'Купи UPS за сървърното', 'same', task_id)
        self.service.resolve_link(second, 'decisions', 0, 'Сървърите остават в офиса', 'same', decision_id)
        self.service.update_task(first, 0, 'Купи UPS за сървърното', {'status': 'done'})
        self.assertEqual([self.minutes(m)['tasks'][0]['status'] for m in (first, second)], ['done', 'done'])
        self.assertIn('Изпълнена', (self.service.library.directory(second) / 'minutes.md').read_text())
        self.service.update_item(decision_id, 'Сървърите остават в офиса', {'status': 'accepted'})
        self.assertEqual([self.minutes(m)['decisions'][0]['review'] for m in (first, second)], ['verified', 'verified'])
        minutes = self.minutes(second)
        minutes['decisions'][0]['review'] = 'ai'
        self.service.edit(second, {'minutes': minutes})
        self.assertEqual(next(i for i in self.service.item_list()['items'] if i['id'] == decision_id)['status'], 'proposed')
        self.assertEqual(self.minutes(first)['decisions'][0]['review'], 'ai')

    def test_filters_apply_before_the_result_limit(self):
        meeting = self.service.library.create('Интернет', 'in_person', {})
        directory = self.service.library.directory(meeting['id'])
        atomic_json(directory / 'transcript.json', [dict(start=i, end=i + 1, text=f'Резервният интернет, опит {i}.', speaker=None)
                                                    for i in range(401)])
        self.service.edit(meeting['id'], {'minutes': notes(decisions=[decision('Резервният интернет е LTE рутер')])})
        self.assertEqual([r['kind'] for r in self.service.find('резервния интернет', kind='decisions')], ['decision'])
        self.assertEqual(self.service.find('резервния интернет', project='nothing'), [])
