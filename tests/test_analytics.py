import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app import analytics
from app.service import DEFAULTS, MeetingService
from app.storage import atomic_json
from tests.test_calendar import FakeGoogle
from tests.test_http import HTTPTests

PROJECT = Path(__file__).resolve().parents[1]


def segment(start, end, text, speaker=None):
    return dict(start=start, end=end, text=text, speaker=speaker)


def turn(start, end, speaker):
    return dict(start=start, end=end, speaker=speaker)


class ConversationAnalyticsTests(unittest.TestCase):
    def test_talk_time_merges_overlap_and_excludes_silence(self):
        questions = []
        stats, total = analytics.speaker_statistics([
            turn(0, 5, 'Иван'), turn(4, 8, 'Иван'), turn(20, 22, 'Иван'),
            turn(8, 10, 'Мария'),
        ], questions)
        self.assertEqual(total, 12)
        ivan = next(row for row in stats if row['speaker'] == 'Иван')
        self.assertEqual(ivan['talk_seconds'], 10)
        self.assertEqual(ivan['turns'], 2)
        self.assertEqual(ivan['longest_monologue_seconds'], 8)
        self.assertEqual(ivan['average_turn_seconds'], 5)
        self.assertEqual(ivan['talk_percent'], 83.3)

    def test_segment_speaker_uses_maximum_overlap_then_midpoint(self):
        timeline = [turn(0, 4, 'A'), turn(4, 10, 'B'), turn(20, 25, 'C')]
        result = analytics.assign_speakers([
            segment(2, 6, 'mixed'), segment(10, 11, 'gap'), segment(21, 21, 'point'),
        ], timeline)
        self.assertEqual([row['speaker'] for row in result], ['A', None, 'C'])
        # A shorter overlap with B must not beat the longer overlap with A.
        self.assertEqual(result[0]['speaker'], 'A')

    def test_bulgarian_questions_without_question_mark_and_answered_state(self):
        previous = dict(questions=[dict(id='q-0-0', text='Кога започваме', speaker='Иван', timestamp=0.0, answered=True)])
        segments = [segment(0, 4, 'Кога започваме', 'Иван'), segment(4, 8, 'Това е решение. Може ли да продължим?', 'Мария'), segment(8, 9, 'Благодаря.')]
        questions = analytics.detect_questions(segments, previous)
        self.assertEqual(len(questions), 2)
        self.assertTrue(questions[0]['answered'])
        self.assertEqual(questions[1]['speaker'], 'Мария')
        self.assertFalse(questions[1]['answered'])

    def test_literal_topics_are_case_insensitive_with_timestamp_evidence(self):
        tracker = dict(id='budget', name='Бюджет', phrases=['БЮДЖЕТ', 'разходи'], semantic_matching=False)
        topics, error = analytics.build_topics([segment(12, 15, 'Имаме бюджет и разходи.', 'Иван')], [tracker])
        self.assertIsNone(error)
        self.assertEqual(topics[0]['match_count'], 1)
        self.assertEqual(topics[0]['matches'][0]['timestamp'], 12.0)
        self.assertEqual(topics[0]['matches'][0]['phrases'], ['БЮДЖЕТ', 'разходи'])

    def test_invalid_semantic_ids_keep_literal_matches_and_expose_error(self):
        tracker = dict(id='risk', name='Риск', phrases=['риск'], semantic_matching=True)
        with patch('app.local_ai.complete_json', return_value={'matches': [0, 99, True]}):
            topics, error = analytics.build_topics([segment(0, 2, 'Има риск.')], [tracker], {})
        self.assertEqual(topics[0]['match_count'], 1)
        self.assertFalse(topics[0]['matches'][0]['semantic'])
        self.assertIn('invalid transcript segment IDs', error)

    def test_semantic_matches_use_only_local_ai_and_are_deduplicated(self):
        tracker = dict(id='risk', name='Риск', phrases=['риск'], semantic_matching=True)
        with patch('app.local_ai.complete_json', return_value={'matches': [0, 1, 1]}) as complete:
            topics, error = analytics.build_topics([segment(0, 2, 'Има риск.'), segment(2, 4, 'Опасност за срока.')], [tracker], {'local_ai_base_url': 'http://localhost:1235/v1'})
        self.assertIsNone(error)
        self.assertEqual(topics[0]['match_count'], 2)
        self.assertTrue(topics[0]['matches'][1]['semantic'])
        self.assertEqual(complete.call_count, 1)

    def test_analyze_is_idempotent_and_import_has_no_invented_talk_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            atomic_json(directory / 'transcript.json', [segment(0, 4, 'Дали сме готови?', 'Иван')])
            first = analytics.analyze(directory, {}, [])
            second = analytics.analyze(directory, {}, [])
        self.assertEqual(first, second)
        self.assertEqual(first['speakers'], [])
        self.assertEqual(first['total_speech_seconds'], 0)
        self.assertEqual(first['unanswered_questions'], 1)


class AnalyticsServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.service = MeetingService(Path(self.tmp.name), PROJECT, google=FakeGoogle())

    def tearDown(self):
        self.service.close()
        self.tmp.cleanup()

    def meeting(self, title='Среща', when='2026-10-24T10:00:00+03:00'):
        meeting = self.service.library.create(title, 'in_person', dict(DEFAULTS, diarization_enabled=False))
        self.service.library.update(meeting['id'], status='ready', duration=100, started_at=when, created=when)
        return meeting['id'], self.service.library.directory(meeting['id'])

    def test_generic_speaker_rename_updates_all_segments_timeline_and_stats(self):
        meeting_id, directory = self.meeting()
        atomic_json(directory / 'transcript.json', [segment(0, 4, 'Здравей', 'SPEAKER_00'), segment(4, 8, 'Дали сме готови?', 'SPEAKER_00')])
        atomic_json(directory / 'speaker-timeline.json', [turn(0, 4, 'SPEAKER_00'), turn(4, 8, 'SPEAKER_00')])
        source = json.loads((directory / 'transcript.json').read_text())
        source[0]['speaker'] = 'Иван'
        self.service.edit(meeting_id, {'transcript': source})
        saved = json.loads((directory / 'transcript.json').read_text())
        timeline = json.loads((directory / 'speaker-timeline.json').read_text())
        result = json.loads((directory / 'analytics.json').read_text())
        self.assertEqual([row['speaker'] for row in saved], ['Иван', 'Иван'])
        self.assertEqual({row['speaker'] for row in timeline}, {'Иван'})
        self.assertEqual(result['speakers'][0]['speaker'], 'Иван')
        self.assertEqual(result['speakers'][0]['questions'], 1)
        self.assertIn('Иван', self.service.library.speakers())
        self.assertNotIn('SPEAKER_00', self.service.library.speakers())

    def test_question_toggle_is_persistent_and_stale_text_is_rejected(self):
        meeting_id, directory = self.meeting()
        atomic_json(directory / 'transcript.json', [segment(0, 4, 'Кога започваме?', 'Иван')])
        result = analytics.analyze(directory, {}, [])
        question = result['questions'][0]
        updated = self.service.update_question(meeting_id, question['id'], True, question['text'])
        self.assertEqual(updated['unanswered_questions'], 0)
        self.assertTrue(self.service.detail(meeting_id)['analytics']['questions'][0]['answered'])
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.service.update_question(meeting_id, question['id'], False, 'old text')

    def test_analytics_failure_does_not_fail_ready_job_or_replace_previous_file(self):
        meeting_id, directory = self.meeting()
        atomic_json(directory / 'transcript.json', [segment(0, 4, 'Разговор')])
        previous = analytics.analyze(directory, {}, [])
        with patch('app.service.conversation.analyze', side_effect=ValueError('analytics failed')):
            self.service._process(meeting_id, 'reanalyze', dict(DEFAULTS, diarization_enabled=False), '')
        meeting = self.service.library.get(meeting_id)
        self.assertEqual(meeting['status'], 'ready')
        self.assertIsNone(meeting['error'])
        self.assertEqual(meeting['analytics_error'], 'analytics failed')
        self.assertEqual(json.loads((directory / 'analytics.json').read_text()), previous)

    def test_diarization_failure_preserves_transcript_and_builds_literal_analytics(self):
        meeting_id, directory = self.meeting()
        atomic_json(directory / 'transcript.json', [segment(0, 4, 'Дали сме готови?')])
        (directory / 'recording.wav').write_bytes(b'not-used-by-mocked-diarizer')
        with patch('app.service.diarization.diarize', side_effect=RuntimeError('model unavailable')):
            self.service._process(meeting_id, 'reanalyze', dict(DEFAULTS, diarization_enabled=True), '')
        meeting = self.service.library.get(meeting_id)
        self.assertEqual(meeting['status'], 'ready')
        self.assertEqual(meeting['diarization_error'], 'model unavailable')
        self.assertEqual(len(self.service.detail(meeting_id)['analytics']['questions']), 1)

    def test_cross_meeting_aggregation_and_filters(self):
        tracker = dict(id='budget', name='Бюджет', phrases=['бюджет'], semantic_matching=False)
        self.service.save_trackers([tracker])
        first, first_dir = self.meeting('Първа', '2026-10-20T10:00:00+03:00')
        second, second_dir = self.meeting('Втора', '2026-10-24T10:00:00+03:00')
        for directory, speaker, text, seconds in [
            (first_dir, 'Иван', 'Бюджет и разходи. Кога плащаме?', 10),
            (second_dir, 'Иван', 'Дали сме готови?', 20),
            (second_dir, 'Мария', 'Бюджетът е потвърден.', 5),
        ]:
            path = directory / 'transcript.json'
            rows = json.loads(path.read_text()) if path.exists() else []
            rows.append(segment(len(rows) * 10, len(rows) * 10 + 5, text, speaker))
            atomic_json(path, rows)
            timeline_path = directory / 'speaker-timeline.json'
            timeline = json.loads(timeline_path.read_text()) if timeline_path.exists() else []
            timeline.append(turn(len(timeline) * 30, len(timeline) * 30 + seconds, speaker))
            atomic_json(timeline_path, timeline)
            analytics.analyze(directory, {}, [tracker])
        overview = self.service.analytics_overview()
        self.assertEqual(overview['meeting_count'], 2)
        self.assertEqual(overview['total_speech_seconds'], 35)
        self.assertEqual(overview['questions'], 2)
        self.assertEqual(next(row for row in overview['topics'] if row['name'] == 'Бюджет')['matches'], 2)
        ivan = self.service.analytics_overview(speaker='иван')
        self.assertEqual(ivan['total_speech_seconds'], 30)
        self.assertEqual(ivan['speakers'][0]['longest_monologue_seconds'], 20)
        topic = self.service.analytics_overview(topic='budget')
        self.assertEqual(topic['meeting_count'], 2)
        self.assertEqual(topic['topics'][0]['matches'], 2)
        dates = self.service.analytics_overview(from_date='2026-10-21', to_date='2026-10-24')
        self.assertEqual(dates['meeting_count'], 1)
        self.assertEqual(dates['meetings'][0]['id'], second)
        with self.assertRaises(ValueError):
            self.service.analytics_overview(from_date='2026-10-25', to_date='2026-10-20')

    def test_tracker_validation_and_defaults(self):
        saved = self.service.save_trackers([dict(name=' Продажби ', phrases=[' оферта ', 'оферта'], semantic_matching=False)])
        self.assertEqual(saved['trackers'][0]['name'], 'Продажби')
        self.assertEqual(saved['trackers'][0]['phrases'], ['оферта'])
        self.assertTrue(saved['trackers'][0]['id'])
        with self.assertRaises(ValueError):
            self.service.save_trackers([dict(name='Bad', phrases=[], semantic_matching=False)])
        with self.assertRaises(ValueError):
            self.service.save_settings({'diarization_enabled': 'yes'})


class AnalyticsHTTPTests(unittest.TestCase):
    setUp, tearDown, request = HTTPTests.setUp, HTTPTests.tearDown, HTTPTests.request

    def test_analytics_tracker_and_question_routes(self):
        meeting = self.service.library.create('Route', 'imported', dict(DEFAULTS))
        directory = self.service.library.directory(meeting['id'])
        self.service.library.update(meeting['id'], status='ready', duration=5)
        atomic_json(directory / 'transcript.json', [segment(0, 5, 'Дали сме готови?', 'Иван')])
        status, body, _ = self.request('/api/trackers', {'trackers': [dict(name='Готовност', phrases=['готови'], semantic_matching=False)]})
        self.assertEqual(status, 200)
        self.assertEqual(len(json.loads(self.request('/api/trackers')[1])['trackers']), 1)
        result = analytics.analyze(directory, {}, self.service.library.trackers())
        question = result['questions'][0]
        status, body, _ = self.request('/api/meetings/' + meeting['id'] + '/question', {'id': question['id'], 'text': question['text'], 'answered': True})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['unanswered_questions'], 0)
        self.assertEqual(self.request('/api/meetings/' + meeting['id'] + '/analytics')[0], 200)
        self.assertEqual(json.loads(self.request('/api/analytics')[1])['questions'], 1)
        self.assertEqual(self.request('/files/' + meeting['id'] + '/analytics.json')[0], 200)
        self.assertEqual(self.request('/api/analytics?from=bad')[0], 400)


if __name__ == '__main__':
    unittest.main()
