"""Closing the service wakes its background worker at once; tests and app exit do not wait for a timeout."""
import tempfile
import time
import unittest
from pathlib import Path

from app.service import MeetingService
from tests.test_calendar import FakeGoogle

PROJECT = Path(__file__).resolve().parents[1]


class ServiceCloseTests(unittest.TestCase):
    def test_close_does_not_wait_for_the_worker_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = MeetingService(Path(tmp), PROJECT, google=FakeGoogle())
            started = time.monotonic()
            service.close()
            # The worker waited up to 0.2 s for its queue on every close; 541 tests paid it.
            self.assertLess(time.monotonic() - started, .15)
            self.assertFalse(service.automation.thread.is_alive())


if __name__ == '__main__':
    unittest.main()
