import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app import search
from app.service import DEFAULTS, MeetingService
from app.storage import atomic_json
from tests.test_calendar import FakeGoogle

PROJECT = Path(__file__).resolve().parents[1]


class QueryTests(unittest.TestCase):
    def test_words_become_prefix_terms_and_quotes_an_exact_phrase(self):
        self.assertEqual(search.fts_query('Какво решихме за "резервния интернет"?'), '"резервния интернет"')
        self.assertEqual(search.fts_query('резервния интернет'), '"резер"* OR "интер"*')
        self.assertEqual(search.fts_query('VPN'), '"vpn"*')

    def test_search_syntax_never_reaches_fts(self):
        self.assertEqual(search.fts_query('NEAR(a b) OR * ^ "'), '"near"* OR "or"*')
        self.assertEqual(search.fts_query('???'), '')


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.service = MeetingService(Path(self.tmp.name), PROJECT, google=FakeGoogle())

    def tearDown(self):
        self.service.close()
        self.tmp.cleanup()

    def meeting(self, title, when, segments, minutes):
        meeting = self.service.library.create(title, 'in_person', {})
        self.service.library.update(meeting['id'], status='ready', duration=600, started_at=when, created=when)
        atomic_json(self.service.library.directory(meeting['id']) / 'transcript.json',
                    [dict(start=start, end=start + 5, text=text, speaker=speaker) for start, speaker, text in segments])
        self.service.edit(meeting['id'], {'minutes': minutes})
        return meeting['id']

    def scenario(self):
        first = self.meeting('Инфраструктура', '2026-10-19T10:00:00+03:00',
            [(0, 'Иван', 'Да видим резервния интернет за офиса.'), (75, 'Мария', 'Предлагам LTE рутер като резерв.')],
            dict(summary=[], tasks=[dict(task='Купи LTE рутер', owner='Мария', deadline=None, evidence_timestamp='00:01:15')],
                 decisions=[dict(text='Резервният интернет ще е LTE рутер', evidence_timestamp='00:01:15', review='verified')],
                 open_questions=[dict(text='Кой плаща абонамента за резервната връзка?', evidence_timestamp='00:00:00')]))
        second = self.meeting('Принтери', '2026-10-20T10:00:00+03:00', [(0, 'Иван', 'Новите принтери работят без сървър.')],
            dict(summary=[], tasks=[], open_questions=[], decisions=[dict(text='Купуваме принтери с директен печат', evidence_timestamp='00:00:00')]))
        return first, second

    def test_passages_have_highlights_speaker_meeting_and_moment(self):
        first, _ = self.scenario()
        results = self.service.find('резервен интернет')
        transcript = next(r for r in results if r['kind'] == 'transcript')
        self.assertEqual((transcript['meeting_id'], transcript['speaker'], transcript['timestamp']), (first, 'Иван', '00:00:00'))
        self.assertIn(search.MARK_START + 'резервния' + search.MARK_END, transcript['snippet'])
        decision = next(r for r in results if r['kind'] == 'decision')
        self.assertEqual((decision['status'], decision['timestamp'], decision['meeting_title']), ('accepted', '00:01:15', 'Инфраструктура'))
        self.assertEqual([r['kind'] for r in self.service.find('LTE', kind='tasks')], ['task'])
        self.assertTrue(all(r['kind'] in {'transcript', 'draft'} for r in self.service.find('LTE', kind='transcript')))

    def test_index_follows_changes_projects_and_deleted_meetings(self):
        first, second = self.scenario()
        self.service.set_scope(second, {'name': 'Офис'})
        project = self.service.library.get(second)['project_id']
        self.assertEqual({r['meeting_id'] for r in self.service.find('принтери', project=project)}, {second})
        self.assertEqual(self.service.find('LTE', project=project), [])
        minutes = json.loads((self.service.library.directory(second) / 'minutes.json').read_text())
        minutes['open_questions'] = [dict(text='Колко струва тонерът?', evidence_timestamp='00:00:00')]
        self.service.edit(second, {'minutes': minutes, 'minutes_revision': self.service.detail(second)['minutes_revision']})
        self.assertEqual([r['kind'] for r in self.service.find('тонерът')], ['question'])
        self.service.delete(second)
        self.assertEqual(self.service.find('тонерът'), [])
        self.assertTrue(self.service.find('резервния'))

    def test_an_answer_cites_only_found_sources(self):
        self.scenario()
        reply = {'found': True, 'answer': 'Решено е: LTE рутер.', 'sources': [1, 99]}
        with patch.object(self.service, 'settings', dict(DEFAULTS, summarizer='local')), \
                patch('app.local_ai.complete_json', return_value=reply) as model:
            result = self.service.ask('Какво решихме за резервния интернет?')
        self.assertTrue(result['decision_question'])
        self.assertEqual([r['text'] for r in result['confirmed']], ['Резервният интернет ще е LTE рутер'])
        self.assertEqual((result['ai']['answer'], result['ai']['cited']), ('Решено е: LTE рутер.', [1]))
        prompt = model.call_args.args[1][0]['content']
        self.assertIn('Не намирам потвърдено решение', prompt)
        self.assertIn('[1] Решение (accepted) · Инфраструктура, 2026-10-19 · 00:01:15', prompt)

    def test_a_replaced_decision_is_neither_proposed_nor_an_answer_source(self):
        first, _ = self.scenario()
        old = next(i for i in self.service.item_list()['items'] if i['kind'] == 'decision' and 'LTE' in i['text'])
        third = self.meeting('Инфраструктура 2', '2026-10-23T10:00:00+03:00', [(0, 'Иван', 'Сменяме резервния интернет.')],
            dict(summary=[], tasks=[], open_questions=[], decisions=[dict(text='Резервният интернет ще е оптика, не LTE рутер', evidence_timestamp='00:00:00', review='verified')]))
        mention = json.loads((self.service.library.directory(third) / 'minutes.json').read_text())['decisions'][0]
        self.service.resolve_link(third, 'decisions', 0, mention['text'], 'replaces', old['id'])
        with patch.object(self.service, 'settings', dict(DEFAULTS, summarizer='local')), \
                patch('app.local_ai.complete_json', return_value={'found': False, 'answer': '', 'sources': []}) as model:
            result = self.service.ask('Какво решихме за резервния интернет?')
        self.assertNotIn('Резервният интернет ще е LTE рутер', [r['text'] for r in result['proposed'] + result['sources']])
        self.assertEqual([r['text'] for r in result['confirmed']], ['Резервният интернет ще е оптика, не LTE рутер'])
        self.assertNotIn('LTE рутер (superseded)', model.call_args.args[1][0]['content'])
        self.assertNotIn('(superseded)', model.call_args.args[1][0]['content'])

    def test_no_confirmed_decision_and_uncited_answers(self):
        self.scenario()
        with patch.object(self.service, 'settings', dict(DEFAULTS, summarizer='local')), \
                patch('app.local_ai.complete_json', return_value={'found': True, 'answer': 'Може би.', 'sources': []}):
            result = self.service.ask('Какво решихме за принтерите?')
        self.assertEqual((result['confirmed'], [r['status'] for r in result['proposed']]), ([], ['proposed']))
        self.assertEqual(result['ai'], dict(found=False, answer=None, cited=[]))
        with patch('app.local_ai.complete_json') as model:
            empty = self.service.ask('Какво решихме за паркинга?')
        self.assertEqual((empty['sources'], empty['ai']), ([], None))
        model.assert_not_called()
        with patch.object(self.service, 'settings', dict(DEFAULTS, summarizer='local')), patch('app.local_ai.complete_json') as model:
            quick = self.service.ask('Какво решихме за резервния интернет?', ai=False)
        model.assert_not_called()
        self.assertEqual((quick['ai'], len(quick['confirmed'])), (None, 1))
        with patch.object(self.service, 'settings', dict(DEFAULTS, summarizer='none')):
            self.assertIsNone(self.service.ask('резервния интернет')['ai'])
