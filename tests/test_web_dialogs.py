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

    def test_meeting_review_is_a_tab_not_a_dialog(self):
        # Review keeps the transcript, notes and player of the meeting one click away.
        page, code = (WEB / 'index.html').read_text(), (WEB / 'app.js').read_text()
        self.assertNotIn('meeting-review-dialog', page + code)
        self.assertIn('id="tab-review"', page)
        self.assertIn('<div id="review-panel" class="card" hidden>', page)
        self.assertIn("['review','review-panel']", code)
        self.assertIn("['review','outcomes','notes','team','analytics'].includes(tab)", code)
