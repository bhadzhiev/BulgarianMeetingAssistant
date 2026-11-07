from pathlib import Path
import subprocess
import unittest


class WebComponentsTests(unittest.TestCase):
    def test_shared_helpers_and_new_question(self):
        result = subprocess.run(
            ['node', 'tests/web_components_regressions.cjs'],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_all_frontend_regression_suites(self):
        root = Path(__file__).resolve().parents[1]
        for suite in sorted((root / 'tests').glob('web_*regressions.cjs')):
            if suite.name == 'web_components_regressions.cjs':
                continue
            with self.subTest(suite=suite.name):
                result = subprocess.run(
                    ['node', str(suite)], cwd=root,
                    capture_output=True, text=True, timeout=20,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_project_cancel_bypasses_required_name(self):
        from html.parser import HTMLParser

        class Buttons(HTMLParser):
            def __init__(self):
                super().__init__()
                self.buttons = {}

            def handle_starttag(self, tag, attrs):
                if tag == 'button':
                    values = dict(attrs)
                    self.buttons[values.get('id')] = values

        parser = Buttons()
        parser.feed((Path(__file__).resolve().parents[1] / 'web/index.html').read_text())
        cancel = parser.buttons['project-cancel']
        self.assertIn('formnovalidate', cancel)
        self.assertEqual(cancel['value'], 'cancel')
