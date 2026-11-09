import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from app import gmail
from app.gmail import GmailSync
from app.google_calendar import CalendarError, http_json
from tests.test_gmail import FakeMailGoogle, thread


def google_error(code, reason):
    body = json.dumps(dict(error=dict(code=code, message='Synthetic message text', errors=[dict(reason=reason, domain='usageLimits')])))
    return urllib.error.HTTPError('https://gmail.googleapis.com/x', code, 'Error', {}, io.BytesIO(body.encode()))


class HttpReasonTests(unittest.TestCase):
    def call(self, error):
        with mock.patch('urllib.request.urlopen', side_effect=error):
            with self.assertRaises(CalendarError) as caught:
                http_json('https://gmail.googleapis.com/x', token='synthetic')
        return caught.exception

    def test_rate_limit_403_is_named_and_keeps_only_the_reason(self):
        error = self.call(google_error(403, 'userRateLimitExceeded'))
        self.assertEqual((error.status, error.reason), (403, 'userRateLimitExceeded'))
        self.assertIn('slow down', str(error));self.assertNotIn('Synthetic message text', str(error))

    def test_permission_403_still_asks_to_reconnect(self):
        error = self.call(google_error(403, 'insufficientPermissions'))
        self.assertEqual(error.reason, 'insufficientPermissions');self.assertIn('Reconnect', str(error))

    def test_body_without_json_gives_no_reason(self):
        error = self.call(urllib.error.HTTPError('https://x', 500, 'Error', {}, io.BytesIO(b'<html>')))
        self.assertEqual(error.reason, '')


class SyncRetryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.google = FakeMailGoogle()
        self.sync = GmailSync(Path(self.tmp.name), self.google);self.addCleanup(self.sync.close)
        patch = mock.patch.object(gmail, 'RETRY_DELAYS', (0, 0));patch.start();self.addCleanup(patch.stop)

    def run_sync(self):
        self.sync.start();self.sync.thread.join(5)
        return self.sync.status()

    def failing(self, failures, code=403, reason='rateLimitExceeded'):
        count = dict(left=failures)
        def handler(path, query):
            if path.startswith('/threads/') and count['left']:
                count['left'] -= 1
                error = CalendarError('limited');error.status = code;error.reason = reason;raise error
            if path == '/profile':return dict(emailAddress=self.google.account, historyId='100')
            if path == '/threads':return dict(threads=[dict(id='t1')])
            if path == '/history':return dict(historyId='100', history=[])
            return thread(path.rsplit('/', 1)[-1])
        self.google.handler = handler

    def test_rate_limit_waits_and_continues(self):
        for code, reason in ((403, 'rateLimitExceeded'), (429, '')):
            self.sync.clear(self.google.account);self.failing(2, code, reason)
            state = self.run_sync()
            self.assertEqual(state['job']['status'], 'synced');self.assertEqual(state['count'], 1)

    def test_rate_limit_stops_after_the_last_retry_and_keeps_the_queue(self):
        self.failing(3)
        state = self.run_sync()
        self.assertEqual(state['job']['status'], 'error');self.assertEqual(state['sync']['pending'], ['t1'])

    def test_permission_error_is_not_retried(self):
        self.failing(1, 403, 'insufficientPermissions')
        state = self.run_sync()
        self.assertEqual(state['job']['status'], 'error')
        self.assertEqual(len([c for c in self.google.calls if c[0] == '/threads/t1']), 1)


if __name__ == '__main__':
    unittest.main()
