import http.client
from pathlib import Path
import queue
import tempfile
import threading
import unittest
from unittest.mock import patch

from app import events
from app.service import MeetingService
from tests.test_app import FakeRecorder, wait_for
from tests import test_http

PROJECT = Path(__file__).resolve().parents[1]


def listen(service):
    """Collect one tab's events in the background."""
    received, stream = queue.Queue(), service.watcher.events()
    threading.Thread(target=lambda: [received.put(item) for item in stream], daemon=True).start()
    return received


def next_event(received, kind, timeout=5):
    while True:
        event, data = received.get(timeout=timeout)
        if event == kind:
            return data


class WatcherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.service = MeetingService(Path(self.tmp.name), PROJECT)
        self.service.save_settings({'auto_process': False, 'live_transcription': False})

    def tearDown(self):
        self.service.close()
        self.tmp.cleanup()

    def test_a_tab_hears_which_meeting_changed(self):
        meeting = self.service.library.create('Среща', 'in_person', {})
        received = listen(self.service)
        self.assertEqual(received.get(timeout=5), ('hello', {}))
        self.service.library.update(meeting['id'], title='Нова')
        self.assertEqual(next_event(received, 'state')['changed'], [meeting['id']])
        self.service.save_speakers(['Иван'])
        self.assertEqual(next_event(received, 'state')['changed'], [])

    def test_nothing_is_checked_while_no_tab_listens(self):
        with patch.object(self.service.watcher, 'fingerprint', wraps=self.service.watcher.fingerprint) as checked:
            threading.Event().wait(1.5)
            self.assertEqual(checked.call_count, 0)
            received = listen(self.service)
            received.get(timeout=5)
            wait_for(lambda: checked.call_count >= 2)

    def test_live_values_during_a_recording_and_ping_when_quiet(self):
        received = listen(self.service)
        received.get(timeout=5)
        with patch('app.service.devices', return_value=[{'id': 2, 'name': 'Mic'}]), patch('app.service.Recorder', FakeRecorder):
            meeting_id = self.service.start('Запис', 'in_person', 2)['id']
            wait_for(lambda: self.service.library.get(meeting_id)['status'] == 'recording')
            live = next_event(received, 'live')
            self.assertEqual(live['meeting_id'], meeting_id)
            self.assertIn('duration', live)
            self.service.stop()
            wait_for(lambda: self.service.library.get(meeting_id)['status'] == 'recorded')
        with patch.object(events, 'HEARTBEAT', 0.5):
            quiet = listen(self.service)
            quiet.get(timeout=5)
            self.assertEqual(next_event(quiet, 'ping'), {})

    def test_the_stream_ends_when_the_app_closes(self):
        stream = self.service.watcher.events()
        self.assertEqual(next(stream)[0], 'hello')
        threading.Timer(0.3, self.service.close).start()
        self.assertEqual(list(stream), [])


class EventHTTPTests(unittest.TestCase):
    setUp, tearDown, request = test_http.HTTPTests.setUp, test_http.HTTPTests.tearDown, test_http.HTTPTests.request

    def test_events_need_the_session_and_stream_server_sent_events(self):
        self.assertEqual(self.request('/api/events', headers={})[0], 403)
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        connection.request('GET', '/api/events', headers=self.headers)
        response = connection.getresponse()
        self.assertEqual((response.status, response.getheader('Content-Type')), (200, 'text/event-stream; charset=utf-8'))
        self.assertEqual(response.readline(), b'event: hello\n')
        connection.close()

    def test_devices_are_scanned_on_request_only(self):
        with patch('app.service.devices', return_value=[dict(id=0, name='Mic', rate=48000)]) as listed:
            self.request('/api/state')
            status, body, _ = self.request('/api/devices')
        self.assertEqual(status, 200)
        self.assertEqual([c.kwargs.get('rescan', False) for c in listed.call_args_list], [False, True])
