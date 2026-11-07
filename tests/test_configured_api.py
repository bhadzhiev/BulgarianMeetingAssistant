"""A configured OpenAI-compatible API in the cloud: its own key, sent only to it, and a cloud label."""
import inspect
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import analytics, gmail_ai, local_ai, meeting_automation, notes_consolidation, service as service_module, worker
from app.service import DEFAULTS, MeetingService
from tests.test_calendar import FakeGoogle

PROJECT = Path(__file__).resolve().parents[1]


class FakeStore:
    def __init__(self): self.value = None
    def get(self): return self.value
    def set(self, value): self.value = value
    def delete(self): self.value = None


class RemoteTests(unittest.TestCase):
    def test_this_mac_and_its_network_are_not_cloud(self):
        for url in ['http://127.0.0.1:1234/v1', 'http://localhost:1235/v1', 'http://192.168.1.20:1234/v1',
                    'http://10.0.0.5/v1', 'http://studio.local:1234/v1', 'http://[::1]:8080/v1']:
            self.assertFalse(local_ai.is_remote(url), url)
        for url in ['https://api.moonshot.ai/v1', 'https://api.openai.com/v1', 'http://8.8.8.8/v1']:
            self.assertTrue(local_ai.is_remote(url), url)


class KeyTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        store = FakeStore()
        with patch('app.local_ai.KeyStore', return_value=store), patch.dict('os.environ', {}, clear=False):
            self.s = MeetingService(Path(tmp.name) / 'library', PROJECT, google=FakeGoogle(), backup_dir=Path(tmp.name) / 'backups')
        self.addCleanup(self.s.close)
        self.store = store

    def test_each_provider_gets_only_its_own_key(self):
        self.s.api_key, self.s.local_ai_api_key = 'openai-key', 'configured-key'
        self.assertEqual(self.s.ai_key('openai'), 'openai-key')
        self.assertEqual(self.s.ai_key('local'), 'configured-key')
        self.assertEqual(self.s.ai_key('none'), '')
        self.assertEqual(self.s.redact('failed with configured-key and openai-key'), 'failed with [redacted] and [redacted]')

    def test_the_key_is_saved_in_keychain_and_never_in_settings(self):
        saved = self.s.save_settings(dict(local_ai_base_url='https://api.moonshot.ai/v1', local_ai_api_key=' sk-test '))
        self.assertTrue(saved['local_ai_api_key_configured']); self.assertTrue(saved['local_ai_remote'])
        self.assertEqual(self.store.value, dict(api_key='sk-test'))
        self.assertNotIn('sk-test', self.s.settings_path.read_text())
        self.assertTrue(self.s.local_ai_marker.exists())
        self.assertNotIn('sk-test', self.s.local_ai_marker.read_text())
        forgotten = self.s.save_settings(dict(local_ai_api_key=''))
        self.assertFalse(forgotten['local_ai_api_key_configured']); self.assertIsNone(self.store.value)

    def test_the_model_context_is_a_bounded_setting(self):
        self.assertEqual(self.s.save_settings(dict(local_ai_context=262144))['settings']['local_ai_context'], 262144)
        for value in (1024, 3_000_000, '262144'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.s.save_settings(dict(local_ai_context=value))

    def test_a_cloud_api_without_a_key_stops_before_processing(self):
        source = inspect.getsource(MeetingService)
        self.assertIn("if uses_local and is_remote(settings.get('local_ai_base_url')) and not local_key:", source)
        self.assertIn("step_key(settings.get('summarizer'))", source)
        self.assertIn("step_key(settings.get('transcript_correction'))", source)


class RequestKeyTests(unittest.TestCase):
    def test_complete_json_sends_the_given_key_as_bearer(self):
        sent = {}
        def post(url, payload, headers=None, timeout=600):
            sent.update(headers or {})
            return dict(choices=[dict(message=dict(content='{}'), finish_reason='stop')])
        with patch('meeting_assistant.post_json', side_effect=post):
            local_ai.complete_json(dict(DEFAULTS, local_ai_base_url='https://api.moonshot.ai/v1'), [dict(role='user', content='x')], {}, 'meeting_title', api_key='sk-test')
        self.assertEqual(sent, {'Authorization': 'Bearer sk-test'})

    def test_server_temperature_leaves_it_out(self):
        sent = []
        def post(url, payload, headers=None, timeout=600):
            sent.append(payload)
            return dict(choices=[dict(message=dict(content='{}'), finish_reason='stop')])
        with patch('meeting_assistant.post_json', side_effect=post):
            for value in ('zero', 'server'):
                local_ai.complete_json(dict(DEFAULTS, local_ai_temperature=value), [dict(role='user', content='x')], {}, 'meeting_title')
        self.assertEqual(sent[0]['temperature'], 0)
        self.assertNotIn('temperature', sent[1])

    def test_notes_pass_the_temperature_setting_to_the_request(self):
        from app import processing
        self.assertIn("local_ai_temperature=settings.get('local_ai_temperature', 'zero')", inspect.getsource(processing.summarize))

    def test_every_local_ai_step_passes_its_key(self):
        self.assertIn('api_key=getattr(args, "api_key", "")', inspect.getsource(__import__('meeting_assistant').generate_minutes))
        self.assertIn("'meeting_consolidation', api_key=api_key", inspect.getsource(notes_consolidation.consolidate))
        self.assertIn("'meeting_title', timeout=600, api_key=api_key", inspect.getsource(meeting_automation.generate_title))
        self.assertIn("api_key=api_key", inspect.getsource(analytics.semantic_topic_matches))
        self.assertIn("api_key=api_key", inspect.getsource(gmail_ai.extract))
        self.assertIn("analytics.analyze(directory, settings, trackers, progress, key)", inspect.getsource(worker.execute))
        self.assertIn("extract(settings['gmail_ai_input'],settings,progress,key)", inspect.getsource(worker.execute))


if __name__ == '__main__':
    unittest.main()
