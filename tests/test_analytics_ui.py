from pathlib import Path
import re
import unittest

PROJECT = Path(__file__).resolve().parents[1]


class AnalyticsInterfaceTests(unittest.TestCase):
    def test_every_static_javascript_element_reference_exists(self):
        html = (PROJECT / 'web' / 'index.html').read_text()
        javascript = (PROJECT / 'web' / 'app.js').read_text()
        ids = set(re.findall(r'\bid="([A-Za-z0-9_-]+)"', html))
        references = set(re.findall(r"\$\('([A-Za-z0-9_-]+)'\)", javascript))
        self.assertEqual(references - ids, set())

    def test_analytics_views_and_tracker_controls_are_present(self):
        html = (PROJECT / 'web' / 'index.html').read_text()
        self.assertIn('id="open-analytics"', html)
        self.assertIn('id="meeting-analytics-panel"', html)
        self.assertIn('data-tab="trackers"', html)
        self.assertIn('id="diarization-enabled"', html)
        self.assertNotIn('sentiment', html.lower())


if __name__ == '__main__':
    unittest.main()
