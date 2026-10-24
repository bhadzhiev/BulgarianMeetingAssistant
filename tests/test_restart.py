import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

PROJECT=Path(__file__).resolve().parents[1]


def wait_for(check,timeout=30):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        result=check()
        if result:return result
        time.sleep(0.2)
    raise AssertionError('Timed out')


class RestartTests(unittest.TestCase):
    def start(self,library):
        return subprocess.Popen([sys.executable,'desktop_app.py','--no-browser','--port','0','--library',library],
            cwd=PROJECT,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    def running_url(self,library):
        try:return json.loads((Path(library)/'.running.json').read_text())['url']
        except (OSError,ValueError):return None
    def test_new_start_stops_the_running_copy(self):
        with tempfile.TemporaryDirectory() as library:
            first=self.start(library)
            try:
                old=wait_for(lambda:self.running_url(library))
                second=self.start(library)
                try:
                    self.assertEqual(first.wait(timeout=60),0)
                    new=wait_for(lambda:(url:=self.running_url(library)) and url!=old and url)
                    self.assertNotEqual(new,old);self.assertIsNone(second.poll())
                finally:
                    second.terminate();second.wait(timeout=60)
            finally:
                if first.poll() is None:first.kill()
                first.wait()


if __name__=='__main__':
    unittest.main()
