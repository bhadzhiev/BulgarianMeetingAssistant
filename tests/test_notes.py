import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app import notes, processing
from app.service import DEFAULTS, MeetingService
from app.storage import atomic_json
from meeting_assistant import TranscriptSegment, minutes_schema, note_item, save_minutes, save_transcript, validate_minutes
from tests.test_calendar import FakeGoogle

PROJECT = Path(__file__).resolve().parents[1]


def item(text, stamp='00:00:00', review='ai'):
    return dict(text=text, evidence_timestamp=stamp, review=review)


def task(text, **fields):
    return dict(dict(task=text, owner=None, deadline=None, due_date=None, evidence_timestamp='00:00:00', status='open', review='ai'), **fields)


def minutes(**fields):
    result = dict(summary=[], decisions=[], next_steps=[], needs_decision=[], tasks=[], open_questions=[], observations=[])
    result.update(fields)
    return result


class NoteItemTests(unittest.TestCase):
    def test_old_text_notes_become_items_with_their_cited_source(self):
        self.assertEqual(note_item('Избор на доставчик (00:29:46).'), item('Избор на доставчик.', '00:29:46'))
        self.assertEqual(note_item('В 00:12:00 Иван каза да'), item('В 00:12:00 Иван каза да', '00:12:00'))
        self.assertEqual(note_item('Без източник'), item('Без източник', None))
        old = dict(summary=['Резюме'], decisions=['Решение [00:00:00]'], tasks=[], open_questions=[])
        validate_minutes(old, [TranscriptSegment(0, 1, 'Да.')])
        self.assertEqual(old['decisions'], [item('Решение')])
        self.assertEqual(old['observations'], [])

    def test_validation_rejects_bad_sources_and_review_states(self):
        segments = [TranscriptSegment(0, 1, 'Да.')]
        with self.assertRaisesRegex(ValueError, 'does not reference'):
            validate_minutes(minutes(decisions=[item('Решение', '00:05:00')]), segments)
        with self.assertRaisesRegex(ValueError, 'Review state'):
            validate_minutes(minutes(decisions=[item('Решение', review='maybe')]), segments)
        with self.assertRaisesRegex(ValueError, 'need text'):
            validate_minutes(minutes(summary=[item('  ')]), segments)

    def test_ai_schema_asks_for_a_source_on_every_statement(self):
        schema = minutes_schema()
        for field in ['summary', 'decisions', 'next_steps', 'needs_decision', 'open_questions', 'observations']:
            self.assertEqual(schema['properties'][field]['items']['required'], ['text', 'evidence_timestamp'])


class ChangeTests(unittest.TestCase):
    def test_changes_are_added_changed_or_removed(self):
        current = minutes(decisions=[item('Използваме LTE за резервен интернет', review='verified'), item('Купуваме нов принтер')],
                          summary=[item('Обсъдихме бюджета')])
        proposed = minutes(decisions=[item('Използваме LTE за резервния интернет'), item('Отлагаме миграцията')],
                           summary=[item('Обсъдихме бюджета.')])
        found = {(change['field'], change['kind']): change for change in notes.changes(current, proposed)}
        self.assertEqual(set(found), {('decisions', 'changed'), ('decisions', 'added'), ('decisions', 'removed')})
        self.assertEqual(found['decisions', 'changed']['current_index'], 0)
        self.assertEqual(found['decisions', 'removed']['current']['text'], 'Купуваме нов принтер')

    def test_task_details_change_only_when_the_ai_found_a_value(self):
        current = minutes(tasks=[task('Провери VPN', owner='Иван', status='done')])
        self.assertEqual(notes.changes(current, minutes(tasks=[task('Провери VPN')])), [])
        changed = notes.changes(current, minutes(tasks=[task('Провери VPN', owner='Мария', due_date='2026-10-30')]))
        self.assertEqual([change['kind'] for change in changed], ['changed'])

    def test_apply_keeps_status_and_needs_a_new_check_for_changed_statements(self):
        a, b, c = 'Купуваме LTE рутер за резервен интернет', 'Отлагаме миграцията на принтерите', 'Тестваме Keycloak в понеделник'
        current = minutes(decisions=[item(a, review='verified'), item(b), item(c)],
                          tasks=[task('Провери VPN failover', owner='Иван', status='done', review='verified')])
        proposed = minutes(decisions=[item(a), item('Наемаме външен одитор за сигурността')],
                           tasks=[task('Провери VPN failover до петък', deadline='петък')])
        available = {change['id']: change for change in notes.changes(current, proposed)}
        accept = {id for id, change in available.items() if change['kind'] != 'removed' or change['current']['text'] == b}
        result = notes.apply(current, proposed, accept)
        self.assertEqual([entry['text'] for entry in result['decisions']], [a, c, 'Наемаме външен одитор за сигурността'])
        self.assertEqual(result['decisions'][0]['review'], 'verified')
        self.assertEqual(result['tasks'][0]['task'], 'Провери VPN failover до петък')
        self.assertEqual((result['tasks'][0]['status'], result['tasks'][0]['owner'], result['tasks'][0]['review']), ('done', 'Иван', 'ai'))
        with self.assertRaisesRegex(ValueError, 'changed'):
            notes.apply(current, proposed, {'decisions:added:-:99'})


class FakeArgs:
    pass


class ProposalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.service = MeetingService(Path(self.tmp.name), PROJECT, google=FakeGoogle())
        meeting = self.service.library.create('Среща', 'in_person', dict(DEFAULTS, summarizer='local'))
        self.service.library.update(meeting['id'], status='ready', duration=10)
        self.id, self.directory = meeting['id'], self.service.library.directory(meeting['id'])
        save_transcript(self.directory, [TranscriptSegment(0, 2, 'Решаваме LTE.'), TranscriptSegment(2, 4, 'Иван проверява VPN.')])

    def tearDown(self):
        self.service.close()
        self.tmp.cleanup()

    def summarize(self, output):
        with patch('meeting_assistant.generate_minutes', return_value=output):
            processing.summarize(self.directory, dict(DEFAULTS, summarizer='local'), lambda _: None)

    def test_first_notes_are_saved_and_a_new_run_waits_for_review(self):
        self.summarize(minutes(decisions=[dict(text='LTE резерв', evidence_timestamp='00:00:00')],
                               summary=[dict(text='Резюме', evidence_timestamp='09:99:99')]))
        saved = json.loads((self.directory / 'minutes.json').read_text())
        self.assertIsNone(saved['summary'][0]['evidence_timestamp'])
        saved['decisions'][0]['review'] = 'verified'
        save_minutes(self.directory, saved)
        self.summarize(minutes(decisions=[dict(text='LTE резерв', evidence_timestamp='00:00:00'),
                                          dict(text='Нов доставчик', evidence_timestamp='00:00:02')]))
        self.assertEqual(json.loads((self.directory / 'minutes.json').read_text()), saved)
        proposal = self.service.detail(self.id)['minutes_proposal']
        self.assertEqual([(change['field'], change['kind']) for change in proposal['changes']], [('summary', 'removed'), ('decisions', 'added')])

    def test_apply_archives_previous_notes_and_rejects_stale_reviews(self):
        self.summarize(minutes(decisions=[dict(text='LTE резерв', evidence_timestamp='00:00:00')]))
        self.summarize(minutes(decisions=[dict(text='LTE резерв', evidence_timestamp='00:00:00'),
                                          dict(text='Нов доставчик', evidence_timestamp='00:00:02')]))
        proposal = self.service.detail(self.id)['minutes_proposal']
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.service.review_notes(self.id, 'apply', [], 'old-revision')
        detail = self.service.review_notes(self.id, 'apply', [proposal['changes'][0]['id']], proposal['revision'])
        self.assertEqual([entry['text'] for entry in detail['minutes']['decisions']], ['LTE резерв', 'Нов доставчик'])
        self.assertIsNone(detail['minutes_proposal'])
        self.assertEqual(len(list((self.directory / 'versions').glob('*/minutes.json'))), 1)

    def test_discard_keeps_saved_notes(self):
        self.summarize(minutes(decisions=[dict(text='LTE резерв', evidence_timestamp='00:00:00')]))
        before = (self.directory / 'minutes.json').read_text()
        self.summarize(minutes(decisions=[dict(text='Друго', evidence_timestamp='00:00:00')]))
        revision = self.service.detail(self.id)['minutes_proposal']['revision']
        self.assertIsNone(self.service.review_notes(self.id, 'discard', [], revision)['minutes_proposal'])
        self.assertEqual((self.directory / 'minutes.json').read_text(), before)
