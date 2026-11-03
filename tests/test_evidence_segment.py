import unittest
from app.transcripts import segment_at

# Notes cite a segment's start cut to whole seconds; the previous segment often still runs then.
ROWS = [dict(start=0.0, end=12.9, text='First speaker talks.', speaker='A'),
        dict(start=12.7, end=15.2, text=' The cited words.', speaker='B'),
        dict(start=15.4, end=15.9, text='More', speaker='B'),
        dict(start=15.95, end=18.0, text='words.', speaker='B')]


class EvidenceSegmentTests(unittest.TestCase):
    def test_segment_that_starts_in_the_cited_second_wins(self):
        segment = segment_at(ROWS, '00:00:12')
        self.assertEqual(segment['text'], 'The cited words.')
        self.assertEqual((segment['start'], segment['end'], segment['speaker']), (12.7, 15.2, 'B'))

    def test_segments_that_start_in_the_same_second_form_one_span(self):
        segment = segment_at(ROWS, '00:00:15')
        self.assertEqual((segment['text'], segment['start'], segment['end']), ('More words.', 15.4, 18.0))

    def test_time_inside_a_segment_falls_back_to_that_segment(self):
        self.assertEqual(segment_at(ROWS, '00:00:05')['text'], 'First speaker talks.')
        self.assertIsNone(segment_at(ROWS, '00:01:00'))


if __name__ == '__main__':
    unittest.main()
