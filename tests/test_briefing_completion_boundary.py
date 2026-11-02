import datetime as dt
import unittest
from app.briefing import build

class CompletionBoundaryTests(unittest.TestCase):
    def test_missing_completion_date_is_not_recent_completion(self):
        meeting = dict(id='a', title='Review', created='2026-01-01', meeting_type='sprint_review')
        item = dict(id='x', kind='task', status='done', text='Old task', links=[dict(meeting_id='a')], history=[])
        result = build([meeting], {}, [item], {}, dt.date(2026, 2, 1), 'Review', 'sprint_review')
        self.assertEqual(result['done'], [])
        self.assertEqual(result['done_unknown'][0]['text'], 'Old task')
        self.assertTrue(any(row['title'].startswith('Completed, date unknown: Old task') for row in result['agenda']))
        self.assertFalse(any(row['title'].startswith('Show: Old task') for row in result['agenda']))
    def test_no_anchor_cannot_prove_completion_since_last_review(self):
        meeting = dict(id='a', title='Daily', created='2026-01-01', meeting_type='daily')
        item = dict(id='x', kind='task', status='done', text='Done', links=[dict(meeting_id='a')], history=[dict(at='2026-01-02', changes={'status':['open','done']})])
        result = build([meeting], {}, [item], {}, dt.date(2026, 2, 1), 'Review', 'sprint_review')
        self.assertEqual(result['done'], [])
