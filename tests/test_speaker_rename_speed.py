"""A speaker rename keeps the text, so it reuses the AI topic matches instead of a new AI call."""
import inspect
import unittest
from unittest.mock import patch

from app import analytics, service
from app.local_ai import complete_json
from app.service import DEFAULTS

TRACKER = dict(id='t1', name='Budget', phrases=['budget'], semantic_matching=True)


def segments(speaker='SPEAKER_00', text='We talk about money.'):
    return [dict(start=0.0, end=4.0, text='Hello.', speaker=speaker), dict(start=5.0, end=9.0, text=text, speaker=speaker)]


def ai_answer(settings, messages, schema, name, **_):
    return dict(matches=[1])


class TopicReuseTests(unittest.TestCase):
    def first(self):
        with patch('app.local_ai.complete_json', side_effect=ai_answer):
            return analytics.build_analytics(segments(), [], [TRACKER], dict(DEFAULTS))

    def test_a_rename_reuses_the_matches_with_the_new_speaker(self):
        previous = self.first()
        self.assertTrue(previous['topics'][0]['semantic_key'])
        with patch('app.local_ai.complete_json', side_effect=AssertionError('no AI call for a rename')):
            result = analytics.build_analytics(segments('Ivan Petrov'), [], [TRACKER], dict(DEFAULTS, reuse_semantic_topics=True), previous)
        match = result['topics'][0]['matches'][0]
        self.assertEqual((match['segment_index'], match['speaker'], match['semantic']), (1, 'Ivan Petrov', True))
        self.assertEqual(result['topics'][0]['match_count'], 1)

    def test_changed_text_or_a_changed_tracker_asks_the_ai_again(self):
        previous = self.first()
        for segs, tracker in [(segments(text='Another subject.'), TRACKER), (segments(), dict(TRACKER, phrases=['cost']))]:
            with self.subTest(tracker=tracker['phrases']), patch('app.local_ai.complete_json', side_effect=ai_answer) as ai:
                analytics.build_analytics(segs, [], [tracker], dict(DEFAULTS, reuse_semantic_topics=True), previous)
                self.assertEqual(ai.call_count, 1)

    def test_a_requested_analysis_and_an_old_file_ask_the_ai_again(self):
        previous = self.first()
        old = dict(previous, topics=[{k: v for k, v in previous['topics'][0].items() if k != 'semantic_key'}])
        for settings, before in [(dict(DEFAULTS), previous), (dict(DEFAULTS, reuse_semantic_topics=True), old)]:
            with patch('app.local_ai.complete_json', side_effect=ai_answer) as ai:
                analytics.build_analytics(segments(), [], [TRACKER], settings, before)
                self.assertEqual(ai.call_count, 1)

    def test_a_failed_check_is_not_reused(self):
        with patch('app.local_ai.complete_json', side_effect=ValueError('down')):
            previous = analytics.build_analytics(segments(), [], [TRACKER], dict(DEFAULTS))
        self.assertNotIn('semantic_key', previous['topics'][0])

    def test_only_an_edit_turns_on_the_reuse(self):
        self.assertIn('reuse_semantic_topics=True', inspect.getsource(service.MeetingService.edit))
        self.assertEqual(inspect.getsource(service).count('reuse_semantic_topics'), 1)


class TopicReasoningTests(unittest.TestCase):
    def payload(self, base_url):
        with patch('meeting_assistant.post_json', return_value=dict(choices=[dict(message=dict(content='{"matches": []}'), finish_reason='stop')])) as post:
            complete_json(dict(DEFAULTS, local_ai_base_url=base_url, local_ai_model='some-model'), [], dict(type='object'), 'topic_matches')
        return post.call_args.args[1]

    def test_topic_matching_has_no_thinking_on_a_cloud_api(self):
        self.assertEqual(self.payload('https://api.example.com/v1').get('reasoning_effort'), 'none')
        self.assertNotIn('reasoning_effort', self.payload('http://127.0.0.1:1234/v1'))


if __name__ == '__main__':
    unittest.main()
