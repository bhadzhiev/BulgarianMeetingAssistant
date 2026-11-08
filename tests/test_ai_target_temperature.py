import io
import json
from pathlib import Path
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

from app.local_ai import complete_json, server_reason
from app.service import MeetingService
from tests.test_calendar import FakeGoogle

PROJECT = Path(__file__).resolve().parents[1]


class AITargetTemperatureTests(unittest.TestCase):
    def test_a_cloud_target_keeps_the_server_temperature(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        s = MeetingService(Path(tmp.name) / 'library', PROJECT, google=FakeGoogle(), backup_dir=Path(tmp.name) / 'backups'); self.addCleanup(s.close)
        s.settings.update(summarizer='local', local_ai_base_url='https://api.moonshot.ai/v1', local_ai_model='kimi-k3.1-pro', local_ai_temperature='server')
        target = s.repo_reports.target()
        self.assertEqual(target['local_ai_temperature'], 'server')
        with patch('meeting_assistant.post_json', return_value=dict(choices=[dict(message=dict(content='{}'), finish_reason='stop')])) as post:
            complete_json(target, [dict(role='user', content='x')], {}, 'team_review')
        payload = post.call_args.args[1]
        self.assertNotIn('temperature', payload)
        self.assertEqual(payload['reasoning_effort'], 'none')

    def test_the_error_names_the_server_reason_without_a_key(self):
        body = json.dumps(dict(error=dict(message='invalid temperature: only 1 is allowed for this model, key sk-abcdefghijklmnop'))).encode()
        error = urllib.error.HTTPError('https://api.moonshot.ai/v1/chat/completions', 400, 'Bad Request', {}, io.BytesIO(body))
        reason = server_reason(error)
        self.assertEqual(reason, ' The server answered HTTP 400: invalid temperature: only 1 is allowed for this model, key sk-…')
        self.assertEqual(server_reason(ValueError('x')), '')


if __name__ == '__main__':
    unittest.main()
