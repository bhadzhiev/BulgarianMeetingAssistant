import subprocess
from pathlib import Path
import unittest

class LibraryCalendarTests(unittest.TestCase):
    def test_calendar_dates_and_navigation(self):
        root=Path(__file__).resolve().parents[1]
        result=subprocess.run(['node','tests/web_calendar_regressions.cjs'],cwd=root,capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
