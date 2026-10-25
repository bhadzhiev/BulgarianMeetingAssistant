import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from app.desktop import watch_parent
from app.service import MeetingService
from tests.test_app import FakeRecorder

PROJECT = Path(__file__).resolve().parents[1]


class DesktopTests(unittest.TestCase):
    def test_parent_disconnect_and_shutdown_command_both_stop(self):
        for value in ('', 'shutdown\n', 'ignored\nshutdown\n'):
            stopped = []
            thread = watch_parent(io.StringIO(value), lambda: stopped.append(True))
            thread.join(1)
            self.assertEqual(stopped, [True])

    def test_window_exit_finalizes_an_active_recording(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = MeetingService(Path(tmp), PROJECT)
            service.save_settings({'auto_process': True, 'live_transcription': False, 'auto_title': False})
            try:
                with patch('app.service.devices', return_value=[{'id': 2, 'name': 'Test mic'}]), patch('app.service.Recorder', FakeRecorder):
                    meeting = service.start('Test recording', 'in_person', 2)
                    service.start_thread.join(2)
                service.close(finalize_recording=True)
                self.assertEqual(service.library.get(meeting['id'])['status'], 'recorded')
                self.assertTrue((service.library.directory(meeting['id']) / 'recording.wav').is_file())
                self.assertFalse(service.busy)
                self.assertTrue(service.closed.is_set())
            finally:
                if not service.closed.is_set(): service.close()

    def test_private_ready_channel_shutdown_and_eof(self):
        for command in (b'shutdown\n', b''):
            with tempfile.TemporaryDirectory() as tmp:
                process = subprocess.Popen([sys.executable, '-B', str(PROJECT / 'desktop_app.py'),
                    '--desktop-control', '--no-browser', '--port', '0', '--library', tmp],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                try:
                    # communicate closes stdin: EOF must work even without a shutdown command.
                    stdout, stderr = process.communicate(command, timeout=15)
                    self.assertEqual(process.returncode, 0, stderr.decode())
                    self.assertEqual(len(stdout.splitlines()), 1)
                    ready = json.loads(stdout.splitlines()[0])
                    self.assertEqual(ready['event'], 'ready')
                    self.assertTrue(ready['url'].startswith('http://127.0.0.1:'))
                    self.assertFalse((Path(tmp) / '.running.json').exists())
                finally:
                    if process.poll() is None: process.kill(); process.communicate()

    def test_desktop_refuses_to_replace_a_server_that_owns_the_library(self):
        with tempfile.TemporaryDirectory() as tmp:
            command = [sys.executable, '-B', str(PROJECT / 'desktop_app.py'), '--no-browser',
                       '--port', '0', '--library', tmp]
            owner = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                marker = Path(tmp) / '.running.json'
                deadline = time.monotonic() + 10
                while not marker.exists() and time.monotonic() < deadline:
                    time.sleep(.05)
                self.assertTrue(marker.exists())
                original = marker.read_bytes()
                attempt = subprocess.run(command + ['--desktop-control'], input=b'shutdown\n',
                                         capture_output=True, timeout=10)
                self.assertNotEqual(attempt.returncode, 0)
                self.assertIsNone(owner.poll())
                self.assertEqual(marker.read_bytes(), original)
            finally:
                owner.terminate()
                owner.wait(timeout=10)

    def test_diagnostics_reach_stderr_without_leaking_the_ready_credential(self):
        code = """
import os
from app.desktop import control_output, ready
control = control_output()
print('Task registry: startup diagnostic', flush=True)
os.write(1, b'Native stdout diagnostic\\n')
ready('http://127.0.0.1:1234/?token=private-test-token', control)
print('Monitor: runtime diagnostic', flush=True)
control.close()
"""
        result = subprocess.run([sys.executable, '-B', '-c', code], cwd=PROJECT,
                                capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertEqual(len(result.stdout.splitlines()), 1)
        self.assertEqual(json.loads(result.stdout)['event'], 'ready')
        self.assertIn(b'Task registry: startup diagnostic', result.stderr)
        self.assertIn(b'Native stdout diagnostic', result.stderr)
        self.assertIn(b'Monitor: runtime diagnostic', result.stderr)
        self.assertNotIn(b'private-test-token', result.stderr)
