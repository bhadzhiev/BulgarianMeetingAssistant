"""Team analysis of one meeting: private, one confirmed request, every observation with its moment (2026-11-13)."""
import json
from pathlib import Path
import tempfile
import unittest

from app import team_analysis
from app.service import MeetingService
from app.storage import atomic_json
from tests.test_calendar import FakeGoogle

PROJECT = Path(__file__).resolve().parents[1]
SEGMENTS = [dict(start=0, end=10, text='Какво е направено вчера?', speaker='Ана'),
            dict(start=11, end=20, text='Пуснах мониторинга, но не знам параметрите.', speaker='Борис'),
            dict(start=21, end=25, text='Седни с Вера и ги изберете.', speaker='Ана'),
            dict(start=26, end=30, text='Добре.', speaker='Борис')]


def answer(stamp='00:00:11'):
    obs = lambda text, at=stamp: dict(text=text, evidence_timestamp=at)
    return dict(people=[dict(name='Борис', summary='Пуска работа, без да я разбира.', ownership=[obs('Не ескалира неясното.')],
                             proactivity=[obs('Пусна мониторинга сам.')], reporting=[obs('Казва какво не знае.'), obs('  ')])],
                dynamics=dict(overview='Ана води.', observations=[obs('Ана задава кратки въпроси.', '00:00:00')]),
                discourse=dict(overview='Кратки реплики.', observations=[dict(speaker='Борис', text='„Добре“ без срок.', evidence_timestamp='00:00:26')]),
                coaching=dict(keep=[obs('Ясна следваща стъпка.', '00:00:21')], change=[obs('Питай за целта.', '09:99:99')], develop=[]))


class TeamAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.service = MeetingService(Path(self.tmp.name), PROJECT, google=FakeGoogle())
        self.service.save_settings(dict(summarizer='local'))
        meeting = self.service.library.create('Daily', 'in_person', {})
        self.meeting_id = meeting['id']
        self.directory = self.service.library.directory(self.meeting_id)
        atomic_json(self.directory / 'transcript.json', SEGMENTS)

    def tearDown(self):
        self.service.close()
        self.tmp.cleanup()

    def run_analysis(self, result=None, **body):
        calls = []
        def complete(target, messages, schema, name, timeout, api_key):
            calls.append(dict(target=target, messages=messages, schema=schema, name=name, timeout=timeout))
            full = result or answer()
            return {key: full.get(key) for key in schema['required']}
        saved = team_analysis.generate(self.service, dict(meeting_id=self.meeting_id, **body), complete=complete)
        return saved, calls

    def test_talk_shares_and_turns(self):
        self.assertEqual(team_analysis.talk(SEGMENTS), [dict(speaker='Ана', percent=52, turns=2), dict(speaker='Борис', percent=48, turns=2)])

    def test_two_parallel_requests_with_the_manager_the_transcript_and_the_talk(self):
        saved, calls = self.run_analysis(self_name='Ана')
        # Two parallel requests, each carrying only the instructions of its part; the output limit fits one part
        # and a cloud API is asked for low thinking (2026-11-13).
        by_part = {tuple(call['schema']['required']): call for call in calls}
        self.assertEqual(set(by_part), {('people',), ('dynamics', 'discourse', 'coaching')})
        self.assertEqual({call['target']['local_ai_max_tokens'] for call in calls}, {8192})
        self.assertEqual({call['timeout'] for call in calls}, {1200})
        people, team = by_part[('people',)], by_part[('dynamics', 'discourse', 'coaching')]
        self.assertIn('В този отговор върни само: people.', people['messages'][0]['content'])
        self.assertIn('освен Ана', people['messages'][0]['content'])
        self.assertNotIn('coaching: управленските действия', people['messages'][0]['content'])
        self.assertEqual(team['name'], 'team_analysis')
        system, request = team['messages'][0]['content'], team['messages'][1]['content']
        self.assertIn('за\nмениджъра Ана, включително приноса на мениджъра', system)
        self.assertIn('coaching: управленските действия на Ана.', system)
        self.assertNotIn('освен Ана', system)
        self.assertIn('Без диагнози и психологически\n  етикети.', system)
        self.assertIn('Започни интерпретацията с „Хипотеза:“', system)
        self.assertIn('Мълчанието не е незаинтересованост.', system)
        self.assertIn('Делът на говорене и броят реплики са изчислени от приложението', system)
        self.assertIn('observations: 0–5, по значимост.', system)
        self.assertNotIn('скрит', system)
        self.assertNotIn('работното изпълнение', system + people['messages'][0]['content'])
        self.assertIn('кажи го в наблюдението и не оценявай човека по нея', system)
        self.assertIn('Мениджър: Ана', request)
        self.assertIn('Говорене (изчислено от приложението): Ана 52%, 2 реплики; Борис 48%, 2 реплики', request)
        self.assertIn('[00:00:11] Борис: Пуснах мониторинга', request)
        self.assertEqual(team['schema']['properties']['coaching']['required'], ['keep', 'change', 'develop'])
        self.assertIn('00:00:21', team['schema']['properties']['dynamics']['properties']['observations']['items']['properties']['evidence_timestamp']['enum'])
        self.assertEqual(self.service.settings['self_name'], 'Ана')
        self.assertEqual(saved['manager'], 'Ана')

    def test_the_result_is_cleaned_and_saved_privately(self):
        saved, _ = self.run_analysis()
        analysis = saved['analysis']
        self.assertEqual(analysis['people'][0]['reporting'], [dict(text='Казва какво не знае.', evidence_timestamp='00:00:11')])
        self.assertEqual(analysis['coaching']['change'], [dict(text='Питай за целта.', evidence_timestamp=None)])
        self.assertEqual(analysis['discourse']['observations'][0]['speaker'], 'Борис')
        on_disk = json.loads((self.directory / 'team-analysis.json').read_text())
        self.assertEqual(on_disk['analysis'], analysis)
        detail = self.service.detail(self.meeting_id)
        self.assertEqual(detail['team_analysis']['analysis'], analysis)
        self.assertFalse(detail['team_analysis']['stale'])
        self.assertNotIn('team-analysis.json', detail['files'])
        # A changed transcript marks the analysis as stale; it is not deleted.
        atomic_json(self.directory / 'transcript.json', SEGMENTS[:3])
        self.assertTrue(self.service.detail(self.meeting_id)['team_analysis']['stale'])

    def test_an_empty_or_broken_answer_saves_nothing(self):
        with self.assertRaisesRegex(ValueError, 'empty analysis'):
            self.run_analysis(dict(people=[], dynamics={}, discourse={}, coaching={}))
        self.assertFalse((self.directory / 'team-analysis.json').exists())
        self.assertIsNone(self.service.detail(self.meeting_id)['team_analysis'])

    def test_preview_names_the_model_and_the_unnamed_speakers(self):
        atomic_json(self.directory / 'transcript.json', SEGMENTS + [dict(start=31, end=33, text='Да.', speaker='SPEAKER_02')])
        preview = team_analysis.preview(self.service, dict(meeting_id=self.meeting_id))
        self.assertEqual(preview['model'], self.service.settings['local_ai_model'])
        self.assertEqual(preview['unnamed'], ['SPEAKER_02'])
        self.assertGreater(preview['characters'], 50)

    def test_it_needs_a_transcript_and_a_provider_and_a_valid_name(self):
        with self.assertRaisesRegex(ValueError, 'Invalid name'):
            self.run_analysis(self_name='a\nb')
        self.service.save_settings(dict(summarizer='none'))
        with self.assertRaisesRegex(ValueError, 'notes AI provider'):
            self.run_analysis()
        self.service.save_settings(dict(summarizer='local'))
        (self.directory / 'transcript.json').unlink()
        with self.assertRaisesRegex(ValueError, 'transcript is needed'):
            self.run_analysis()
        with self.assertRaisesRegex(ValueError, 'at most 100 characters'):
            self.service.save_settings(dict(self_name='x' * 101))


    def test_a_cloud_model_thinks_at_low_level(self):
        # The default thinking of Kimi spent a whole output budget and 9.5 minutes (2026-11-13): ask for low.
        from unittest import mock
        from app.local_ai import complete_json
        from app.service import DEFAULTS
        reply = dict(choices=[dict(message=dict(content=json.dumps(answer())), finish_reason='stop')])
        with mock.patch('meeting_assistant.post_json', return_value=reply) as post:
            complete_json(dict(DEFAULTS, local_ai_base_url='https://api.moonshot.ai/v1', local_ai_model='kimi-k3.1-pro'), [],
                          team_analysis.schema(['00:00:00']), 'team_analysis')
        self.assertEqual(post.call_args.args[1].get('reasoning_effort'), 'low')

    def test_the_background_job_saves_the_analysis_and_reports_progress(self):
        import time
        from unittest import mock
        reply = dict(choices=[dict(message=dict(content=json.dumps(answer())), finish_reason='stop')])
        with mock.patch('meeting_assistant.post_json', return_value=reply):
            job = self.service.team_analysis_job.start(dict(meeting_id=self.meeting_id))
            self.assertTrue(job['running'])
            self.assertEqual(job['total'], 2)
            while self.service.team_analysis_job.status(job['id'])['running']:
                time.sleep(0.01)
            status = self.service.team_analysis_job.status(job['id'])
        self.assertEqual((status['status'], status['done'], status['error']), ('Ready', 2, None))
        self.assertTrue((self.directory / 'team-analysis.json').exists())
        self.assertIsNotNone(self.service.detail(self.meeting_id)['team_analysis'])
        with self.assertRaisesRegex(ValueError, 'no longer available'):
            self.service.team_analysis_job.status('no-such-job')

    def test_one_job_at_a_time_and_a_stop_keeps_the_old_analysis(self):
        import threading
        import time
        from unittest import mock
        gate = threading.Event()

        def slow(url, payload, timeout=0, **kwargs):
            gate.wait(10)
            return dict(choices=[dict(message=dict(content=json.dumps(answer())), finish_reason='stop')])

        with mock.patch('meeting_assistant.post_json', side_effect=slow):
            job = self.service.team_analysis_job.start(dict(meeting_id=self.meeting_id))
            with self.assertRaisesRegex(ValueError, 'finish or stop'):
                self.service.team_analysis_job.start(dict(meeting_id=self.meeting_id))
            stopped = self.service.team_analysis_job.stop(job['id'])
            self.assertIn('Cancelling', stopped['status'])
            gate.set()
            while self.service.team_analysis_job.status(job['id'])['running']:
                time.sleep(0.01)
            status = self.service.team_analysis_job.status(job['id'])
        self.assertEqual(status['status'], 'Cancelled')
        self.assertFalse((self.directory / 'team-analysis.json').exists())

    def test_a_local_model_keeps_its_default_level(self):
        # A local server has no per-token cost; the person's own setting applies (none by default).
        from unittest import mock
        from app.local_ai import complete_json
        from app.service import DEFAULTS
        reply = dict(choices=[dict(message=dict(content=json.dumps(answer())), finish_reason='stop')])
        with mock.patch('meeting_assistant.post_json', return_value=reply) as post:
            complete_json(dict(DEFAULTS, local_ai_base_url='http://127.0.0.1:1234/v1'), [],
                          team_analysis.schema(['00:00:00']), 'team_analysis')
        self.assertNotIn('reasoning_effort', post.call_args.args[1])


if __name__ == '__main__':
    unittest.main()
