"""AI topic matches are evidence: the segment itself is about the topic, never a one- or two-word reply."""
import unittest
from unittest.mock import patch

from app import analytics, prompts
from app.service import DEFAULTS

TRACKER = dict(id='t1', name='Laptops', phrases=['laptop'], semantic_matching=True)
SEGMENTS = [dict(start=float(i), end=i + .5, text=text, speaker='A') for i, text in enumerate(
    ['Да.', 'Добре, ок.', 'Регистрацията на един лаптоп отнема петнайсет минути.', 'Сървърът е в офиса.'])]


class TopicPrecisionTests(unittest.TestCase):
    def run_with(self, ids):
        sent = {}
        def answer(settings, messages, schema, name, **_):
            sent['system'] = messages[0]['content']
            return dict(matches=ids)
        with patch('app.local_ai.complete_json', side_effect=answer):
            return analytics.semantic_topic_matches(SEGMENTS, TRACKER, dict(DEFAULTS)), sent['system']

    def test_short_replies_never_match_even_when_the_model_returns_them(self):
        matches, _ = self.run_with([0, 1, 2])
        self.assertEqual([m['segment_index'] for m in matches], [2])

    def test_the_rules_ask_for_the_segment_own_words(self):
        _, system = self.run_with([])
        self.assertIn('its own words are about the topic', system)
        self.assertIn('only because the segments near it', system)
        self.assertIn('Do not match short replies', system)
        self.assertIn('Не избирай сегмент само защото съседните са за темата', prompts.STAGES['topic_matches'][1])


if __name__ == '__main__':
    unittest.main()
