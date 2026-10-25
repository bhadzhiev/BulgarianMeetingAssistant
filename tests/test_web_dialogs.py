from pathlib import Path
import re
import unittest

WEB = Path(__file__).resolve().parents[1] / 'web'


class WebDialogTests(unittest.TestCase):
    def test_the_interface_uses_its_own_dialog_not_native_ones(self):
        # The desktop window (WKWebView) does not show confirm(), prompt() or alert(); they fail silently.
        code = re.sub(r'//[^\n]*', '', (WEB / 'app.js').read_text())
        self.assertEqual(re.findall(r'(?<![\w.])(?:window\.)?(?:confirm|prompt|alert)\(', code), [])
        self.assertIn('id="ask-dialog"', (WEB / 'index.html').read_text())
