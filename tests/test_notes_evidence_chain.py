"""Transcript → evidence → review → follow-up: the proof of a statement follows the statement and its moment."""
import copy
import unittest

from app import followup_email, notes
from meeting_assistant import TranscriptSegment, verify_quotes
from tests import test_followup_email


def saved():
    return dict(summary=[], decisions=[dict(text='Миграцията е в петък', evidence_timestamp='00:00:00',
                quote='Пускаме в петък.', review='verified')], tasks=[], open_questions=[])


class EvidenceReviewTests(unittest.TestCase):
    def test_an_accepted_new_wording_takes_its_own_quote(self):
        old = saved(); new = copy.deepcopy(old)
        new['decisions'][0].update(text='Миграцията е в понеделник', evidence_timestamp='00:01:00', quote='Пускаме в понеделник.')
        result = notes.apply(old, new, {c['id'] for c in notes.changes(old, new)})
        self.assertEqual((result['decisions'][0]['text'], result['decisions'][0]['quote']), ('Миграцията е в понеделник', 'Пускаме в понеделник.'))

    def test_a_new_wording_without_a_quote_drops_the_old_quote(self):
        old = saved(); new = copy.deepcopy(old)
        new['decisions'][0].update(text='Миграцията е в понеделник', quote=None)
        result = notes.apply(old, new, {c['id'] for c in notes.changes(old, new)})
        self.assertIsNone(result['decisions'][0]['quote'])

    def test_a_new_source_for_the_same_words_is_a_change_to_review(self):
        old = saved(); new = copy.deepcopy(old)
        new['decisions'][0].update(evidence_timestamp='00:01:00', quote='Потвърждаваме петък.')
        found = notes.changes(old, new)
        self.assertEqual([c['kind'] for c in found], ['source'])
        result = notes.apply(old, new, {found[0]['id']})
        item = result['decisions'][0]
        self.assertEqual((item['text'], item['evidence_timestamp'], item['quote'], item['review']),
                         ('Миграцията е в петък', '00:01:00', 'Потвърждаваме петък.', 'ai'))
        # Not accepted: the saved proof stays.
        self.assertEqual(notes.apply(old, new, set())['decisions'][0]['quote'], 'Пускаме в петък.')

    def test_a_quote_the_ai_did_not_find_is_no_source_change(self):
        old = saved(); new = copy.deepcopy(old)
        new['decisions'][0]['quote'] = None
        self.assertEqual(notes.changes(old, new), [])


class QuoteMomentTests(unittest.TestCase):
    def test_a_quote_of_another_moment_is_not_evidence(self):
        data = dict(tasks=[dict(task='Да пуснем в петък', evidence_timestamp='00:00:00', quote='Пускаме в петък.')])
        source = [TranscriptSegment(0, 5, 'Няма да пускаме днес.'), TranscriptSegment(60, 65, 'Пускаме в петък.')]
        self.assertEqual(verify_quotes(data, source), 1)
        self.assertIsNone(data['tasks'][0]['quote'])

    def test_a_quote_over_short_segments_of_one_turn_stays(self):
        source = [TranscriptSegment(0, 2, 'Добре, това, което ме интересува, когато', speaker='A'),
                  TranscriptSegment(2.5, 4, 'потребител се регистрира.', speaker='A'),
                  TranscriptSegment(5, 7, 'Да.', speaker='B')]
        data = dict(tasks=[dict(task='x', evidence_timestamp='00:00:02', quote='което ме интересува, когато потребител се регистрира')])
        self.assertEqual(verify_quotes(data, source), 0)

    def test_a_statement_without_a_moment_checks_the_whole_text(self):
        data = dict(summary=[dict(text='x', evidence_timestamp=None, quote='Пускаме в петък.')])
        self.assertEqual(verify_quotes(data, [TranscriptSegment(0, 5, 'Днес.'), TranscriptSegment(60, 65, 'Пускаме в петък.')]), 0)


class FollowupFreshnessTests(unittest.TestCase):
    def setUp(self):
        # The follow-up fixture: one meeting with an accepted decision and task. Its own tests do not run here.
        fixture = test_followup_email.FollowupEmailTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.s, self.mid = fixture.s, fixture.mid

    def test_followup_waits_for_notes_that_need_an_update(self):
        self.s.library.update(self.mid, duration=16)
        detail = self.s.detail(self.mid)
        transcript = copy.deepcopy(detail['transcript'])
        transcript[0]['text'] = 'We will not release on Friday.'
        self.s.edit(self.mid, dict(transcript=transcript, transcript_revision=detail['transcript_revision'], defer_analysis=True))
        self.assertTrue(self.s.library.get(self.mid)['notes_need_refresh'])
        with self.assertRaisesRegex(ValueError, 'The notes wait for an update'):
            followup_email.prepare(self.s, dict(meeting_id=self.mid))
        self.s.settings.update(summarizer='local', local_ai_model='synthetic')
        with self.assertRaisesRegex(ValueError, 'The notes wait for an update'):
            followup_email.generate(self.s, dict(meeting_id=self.mid), complete=lambda *a, **k: dict(subject='S', body='B'))


if __name__ == '__main__':
    unittest.main()
