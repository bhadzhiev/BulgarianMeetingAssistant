from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app import capture
from app.service import MeetingService

PROJECT = Path(__file__).resolve().parents[1]
MAC = dict(name='MacBook Air Microphone', max_input_channels=1, default_samplerate=48000)
SPEAKERS = dict(name='MacBook Air Speakers', max_input_channels=0, default_samplerate=48000)
IPHONE = dict(name='iPhone Microphone', max_input_channels=1, default_samplerate=48000)


class DeviceTests(unittest.TestCase):
    def setUp(self):
        capture._scanned = 0.0

    def test_a_rescan_finds_a_device_that_connected_later_and_is_throttled(self):
        lists = [[MAC, SPEAKERS], [MAC, SPEAKERS, IPHONE]]
        with patch('sounddevice.query_devices', side_effect=lambda: lists[0]), \
                patch('sounddevice._terminate'), patch('sounddevice._initialize', side_effect=lambda: lists.pop(0)) as init:
            self.assertEqual([d['name'] for d in capture.devices(rescan=True)], ['MacBook Air Microphone', 'iPhone Microphone'])
            capture.devices(rescan=True)
            capture.devices()
        self.assertEqual(init.call_count, 1)

    def test_no_rescan_while_a_stream_is_open_and_the_name_decides(self):
        with tempfile.TemporaryDirectory() as root:
            service = MeetingService(Path(root), PROJECT)
            try:
                with patch('app.service.devices', return_value=[]) as listed:
                    service.preview = object()
                    service.snapshot()
                    service.preview = None
                    service.snapshot()
                self.assertEqual([c.kwargs['rescan'] for c in listed.call_args_list], [False, True])
                renumbered = [dict(id=0, name='MacBook Air Microphone', rate=48000), dict(id=1, name='iPhone Microphone', rate=48000)]
                with patch('app.service.devices', return_value=renumbered):
                    self.assertEqual(service._input_device(2, 'iPhone Microphone'), 1)
                    self.assertEqual(service._input_device(0), 0)
                    with self.assertRaisesRegex(ValueError, 'available microphone'):
                        service._input_device(1, 'USB Microphone')
            finally:
                service.preview = None
                service.close()
