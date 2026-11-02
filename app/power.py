"""Hold an idle-sleep assertion only while a recording is active."""
import os
from pathlib import Path
import subprocess


class RecordingPower:
    def __init__(self):
        self.child = None

    def start(self):
        if self.child is None and Path('/usr/bin/caffeinate').is_file():
            # -w also releases the assertion if the Python process crashes.
            self.child = subprocess.Popen(['/usr/bin/caffeinate', '-i', '-w', str(os.getpid())],
                                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def close(self):
        child, self.child = self.child, None
        if child is not None:
            if child.poll() is None:
                child.terminate()
            try:
                child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
