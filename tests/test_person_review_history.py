"""History, period accuracy, private preparation and explicit checks, using isolated synthetic data."""
import datetime as dt
import json
from unittest.mock import patch
import unittest

from app import team_reviews
from app.team_ai import ai_input, markdown
from app.team_facts import collect, comparable, TZ
from app.storage import atomic_json
from app.work_items import WorkItemConflict
from tests import test_team_facts as fixtures
from tests import test_team_protect as protect

DAY = fixtures.DAY


class ReviewHistoryTests(unittest.TestCase):
    setUp = protect.TeamProtectTests.setUp
    review = protect.TeamProtectTests.review
    agree = protect.TeamProtectTests.agree

    def test_history_highlights_use_only_period_events_and_keep_private_text_out(self):
        review = self.review()
        directory = self.s.team_reviews.directory(review['id'])
        atomic_json(directory / 'evidence.json', [
            dict(kind='task_completed', occurred_at='2026-10-21T10:00:00+03:00', source_ref=dict(item_id='one'), facts=dict(text='Delivered result')),
            dict(kind='task_completed', occurred_at='2026-10-19T10:00:00+03:00', source_ref=dict(item_id='old'), facts=dict(text='Earlier work'))])
        row = self.s.team_reviews.history(self.maria['id'])[0]
        self.assertEqual(row['highlights'], [dict(label='Recorded completion', text='Delivered result')])
        self.assertNotIn('review_md', row)
        self.assertNotIn('private_preparation', row)

    def test_overlap_requires_explicit_acknowledgment_and_boundaries_do_not_overlap(self):
        first = self.review()
        draft = self.review('2026-10-26T00:00', '2026-11-02T00:00', final=False)
        self.assertEqual([r['id'] for r in draft['overlaps']], [first['id']])
        with self.assertRaisesRegex(ValueError, 'overlaps'):
            self.s.team_review_action('finalize', dict(id=draft['id'], revision=draft['revision']))
        self.s.team_review_action('finalize', dict(id=draft['id'], revision=draft['revision'], acknowledge_overlap=True))
        next_review = self.review('2026-11-02T00:00', '2026-11-03T00:00', final=False)
        self.assertEqual(next_review['overlaps'], [])

    def test_finalization_is_not_a_conversation_and_date_uses_revision(self):
        review = self.review()
        self.assertIsNone(review.get('conversation_at'))
        saved = self.s.team_review_action('conversation', dict(id=review['id'], revision=review['revision'], conversation_at='2026-10-28T14:30'))
        self.assertEqual(saved['conversation_at'], '2026-10-28T14:30:00+02:00')
        self.assertEqual(saved['review_md'], review['review_md'])
        with self.assertRaises(WorkItemConflict):
            self.s.team_review_action('conversation', dict(id=review['id'], revision=review['revision'], conversation_at=None))
        with self.assertRaises(ValueError):
            self.s.team_review_action('conversation', dict(id=saved['id'], revision=saved['revision'], conversation_at='2099-01-01T12:00'))

    def test_unresolved_older_agreement_survives_an_empty_intermediate_review(self):
        first = self.agree(self.review(), [dict(kind='action', text='Manager supplies access', owner='manager', status='open')])
        middle = self.review('2026-10-27T00:00', '2026-11-03T00:00')
        last = self.review('2026-11-03T00:00', '2026-11-10T00:00', final=False)
        self.assertEqual(last['outstanding_agreements'][0]['review_id'], first['id'])
        self.assertIn('Manager supplies access', last['review_md'])
        history = self.s.team_reviews_list(self.maria['id'])['reviews']
        self.assertEqual(len(history), 3)
        self.assertEqual(history[-1]['agreements'][0]['id'], first['agreements'][0]['id'])
        self.assertNotIn('review_md', history[-1])

    def test_new_version_preserves_notes_agreements_conversation_and_private_context(self):
        draft = self.review(final=False)
        draft = self.s.team_review_action('context', dict(id=draft['id'], revision=draft['revision'], context=dict(role='Own backups', observation_ids=[])))
        draft = self.s.team_review_action('notes', dict(id=draft['id'], revision=draft['revision'], notes_md='My notes'))
        draft = self.agree(draft, [dict(kind='goal', text='Restore demo', owner='person', status='open')])
        draft = self.s.team_review_action('conversation', dict(id=draft['id'], revision=draft['revision'], conversation_at='2026-10-28T14:30'))
        draft = self.s.team_review_action('finalize', dict(id=draft['id'], revision=draft['revision']))
        version = self.s.team_review_action('version', dict(id=draft['id']))
        self.assertEqual((version['notes_md'], version['agreements'], version['conversation_at'], version['context']),
                         (draft['notes_md'], draft['agreements'], draft['conversation_at'], draft['context']))
        self.assertEqual(version['overlaps'], [])

    def test_context_is_opt_in_ai_input_and_private_output_does_not_replace_export_text(self):
        review = self.review(final=False)
        context = dict(role='Run safe restores', employee_view='I need a test machine', manager_support='Supply the machine', observation_ids=[])
        saved = self.s.team_review_action('context', dict(id=review['id'], revision=review['revision'], context=context))
        self.assertFalse(any(r['kind'] == 'review_context' for r in ai_input(saved)['records']))
        saved = self.s.team_review_action('context', dict(id=saved['id'], revision=saved['revision'], context=dict(context, include_in_ai=True)))
        private = ai_input(saved)['records']
        self.assertTrue(any('test machine' in r['facts'].get('text', '') for r in private))
        output = self.s.team_reviews.apply_ai(saved['id'], saved['revision'], 'Private questions', dict(private=True, complete=True))
        self.assertEqual(output['review_md'], review['review_md'])
        self.assertEqual(output['private_preparation'], 'Private questions')
        self.assertNotIn('Private questions', output['review_md'])
        with self.assertRaises(ValueError):
            self.s.team_review_action('context', dict(id=output['id'], revision=output['revision'], context=dict(observation_ids=['invented'], observations=[dict(text='forged')])))

    def test_refresh_preview_preserves_manual_edits_and_rejects_a_stale_proposal(self):
        review = self.review(final=False)
        review = self.s.team_review_action('save', dict(id=review['id'], revision=review['revision'], review_md='# Manual draft'))
        preview = self.s.team_review_action('preview-collect', dict(id=review['id'], revision=review['revision']))
        self.assertEqual(self.s.team_reviews.get(review['id'])['review_md'], '# Manual draft')
        self.assertNotEqual(preview['review_md'], '# Manual draft')
        changed = self.s.team_review_action('notes', dict(id=review['id'], revision=review['revision'], notes_md='Keep this'))
        with self.assertRaises(ValueError):
            self.s.team_review_action('apply-collect', dict(id=review['id'], revision=review['revision'], token=preview['token']))
        preview = self.s.team_review_action('preview-collect', dict(id=changed['id'], revision=changed['revision']))
        applied = self.s.team_review_action('apply-collect', dict(id=changed['id'], revision=changed['revision'], token=preview['token']))
        self.assertEqual(applied['notes_md'], 'Keep this')
        self.assertEqual(applied['review_md'], preview['review_md'])

    def test_result_check_requires_criteria_evidence_and_keeps_append_only_history(self):
        review = self.review()
        row = dict(kind='action', text='Restore demo', owner='person', status='done', verified=True)
        with self.assertRaises(ValueError): self.agree(review, [row])
        saved = self.agree(review, [dict(row, expected_result='Restore a backup', result_evidence='Demonstration on test machine')])
        check = saved['agreements'][0]
        self.assertTrue(check['verified_at']); self.assertTrue(check['verified_by'])
        again = self.agree(saved, [check])
        self.assertEqual(again['agreements'][0]['history'], check['history'])
        changed = self.agree(again, [dict(check, verified=False, status='open')])
        self.assertEqual(changed['agreements'][0]['history'][:-1], check['history'])
        self.assertIsNone(changed['agreements'][0]['verified_at'])

    def test_link_task_persists_identity_and_rejects_replacement(self):
        review = self.agree(self.review(), [dict(kind='action', text='Restore demo', owner='person', status='open')])
        task = self.s.create_task(dict(text='Restore demo', request_id='a' * 32))
        linked = self.s.team_review_action('link-task', dict(id=review['id'], revision=review['revision'], agreement_id=review['agreements'][0]['id'], task_id=task['id']))
        self.assertEqual(linked['agreements'][0]['task_id'], task['id'])
        other = self.s.create_task(dict(text='Different work', request_id='b' * 32))
        with self.assertRaises(ValueError):
            self.s.team_review_action('link-task', dict(id=linked['id'], revision=linked['revision'], agreement_id=linked['agreements'][0]['id'], task_id=other['id']))

    def test_private_ai_run_uses_context_without_replacing_public_review(self):
        from app.team_ai import ReviewAI
        from tests.test_team_ai import FakeRunner
        self.s.settings['summarizer'] = 'local'
        review = self.review(final=False)
        saved = self.s.team_review_action('context', dict(id=review['id'], revision=review['revision'],
            context=dict(employee_view='I need clearer priorities', observation_ids=[], include_in_ai=True)))
        runner = FakeRunner(); ai = ReviewAI(self.s, runner)
        preview = ai.preview(saved['id'])
        job = ai.start(dict(id=saved['id'], preview_token=preview['preview_token'], approved=True))
        ai.thread.join(10)
        self.assertFalse(ai.thread.is_alive())
        self.assertIsNone(ai.status(job['id'])['error'])
        result = self.s.team_reviews.get(saved['id'])
        self.assertEqual(result['review_md'], review['review_md'])
        self.assertIn('## AI observations', result['private_preparation'])
        self.assertTrue(result['generator']['private'])
        self.assertTrue(runner.calls)

    def test_context_and_private_preparation_are_in_verified_backup(self):
        import tarfile
        review = self.review(final=False)
        review = self.s.team_review_action('context', dict(id=review['id'], revision=review['revision'], context=dict(role='Restore backups', observation_ids=[])))
        self.s.team_reviews.apply_ai(review['id'], review['revision'], 'Private preparation', dict(private=True, complete=True))
        archive = self.s.create_backup()['created']
        self.assertTrue(archive['verified'])
        with tarfile.open(self.root / 'backups' / archive['name']) as tar:
            names = tar.getnames()
        self.assertTrue(any(n.endswith('/review-context.json') for n in names))
        self.assertTrue(any(n.endswith('/private-preparation.md') for n in names))


class ReviewPeriodTests(unittest.TestCase):
    setUp = fixtures.TeamFactTests.setUp
    task = fixtures.TeamFactTests.task
    times = fixtures.TeamFactTests.times
    link = fixtures.TeamFactTests.link
    run_week = fixtures.TeamFactTests.run_week

    def test_old_commitment_is_context_and_never_a_new_taken_on_count(self):
        task = self.task('Roll out VPN', 'a', owner_person_id=self.maria['id'])
        self.times(task, DAY(1), DAY(1), created=DAY(1)); self.link(task, '00:00:11')
        self.s.library.update(self.meeting, started_at=DAY(1))
        result = self.run_week()
        self.assertEqual(result['coverage']['counts']['taken on'], 0)
        self.assertIn('Carried from before this period', result['review_md'])
        self.assertTrue(any(e['kind'] == 'task_existing' and e['quote'] for e in result['evidence']))

    def test_future_meeting_cannot_be_a_commitment_or_context_in_the_period(self):
        task = self.task('Roll out VPN', 'a', owner_person_id=self.maria['id'])
        self.times(task, DAY(3), DAY(3), created=DAY(3));self.link(task, '00:00:11')
        self.s.library.update(self.meeting, started_at=DAY(15))
        result = self.run_week()
        self.assertEqual(result['coverage']['counts']['taken on'], 0)
        self.assertFalse(any(e['kind'] in {'task_taken_on', 'task_existing'} for e in result['evidence']))

    def test_short_periods_report_hours_not_zero_days(self):
        previous = dict(period=dict(start=DAY(3, 9), end=DAY(3, 10)))
        ok, reason = comparable(previous, dt.datetime.fromisoformat(DAY(3, 10)), dt.datetime.fromisoformat(DAY(3, 14)), dict(sources=[]))
        self.assertFalse(ok);self.assertIn('1h 0m and 4h 0m', reason);self.assertNotIn('0 days', reason)

    def test_linked_progress_note_does_not_confirm_result(self):
        task = self.task('Roll out VPN', 'a', owner_person_id=self.maria['id'])
        task = self.s.update_item(task['id'], task['text'], dict(workflow_state='done'), task['revision'])
        self.times(task, DAY(3), DAY(3), DAY(5), created=DAY(3))
        item = self.s.items.items[task['id']]
        item['history'].append(dict(event='progress_update', at=DAY(6), evidence_id='some-link', by='user'))
        self.s.items.save()
        self.assertEqual(self.run_week()['coverage']['counts']['result confirmed'], 0)


class SelectedObservationTests(unittest.TestCase):
    setUp = ReviewPeriodTests.setUp
    task = ReviewPeriodTests.task
    times = ReviewPeriodTests.times
    link = ReviewPeriodTests.link
    run_week = ReviewPeriodTests.run_week

    def test_selection_keeps_source_and_detects_a_changed_transcript(self):
        from app.review_context import candidates
        from app.team_analysis import signature
        directory = self.s.library.directory(self.meeting)
        segments = json.loads((directory / 'transcript.json').read_text())
        atomic_json(directory / 'team-analysis.json', dict(version=1, transcript=signature(segments), manager='Someone else',
            analysis=dict(people=[dict(name='Maria', ownership=[dict(text='Clarifies the result', evidence_timestamp='00:00:11')], proactivity=[], reporting=[])])))
        review = self.s.team_review_action('create', dict(person_id=self.maria['id'], start=DAY(2, 0), end=DAY(9, 0)))
        offered = candidates(self.s, review)
        self.assertEqual(len(offered), 1)
        self.assertEqual(offered[0]['quote'], 'I will finish the VPN rollout by Friday.')
        review = self.s.team_review_action('context', dict(id=review['id'], revision=review['revision'], context=dict(observation_ids=[offered[0]['id']], include_in_ai=True)))
        self.assertEqual(ai_input(review)['records'][-1]['kind'], 'team_observation')
        segments[0]['text'] = 'Corrected words';atomic_json(directory / 'transcript.json', segments)
        self.assertEqual(candidates(self.s, review), [])
        self.assertEqual(self.s.team_review(review['id'])['context_changes'], [offered[0]['id']])
        self.assertEqual(self.s.team_review(review['id'])['context']['observations'][0]['quote'], offered[0]['quote'])

    def test_explicit_check_counts_when_linked_to_completed_work_in_period(self):
        task = self.task('Restore backup', 'a', owner_person_id=self.maria['id'])
        task = self.s.update_item(task['id'], task['text'], dict(workflow_state='done'), task['revision'])
        self.times(task, DAY(3), DAY(3), DAY(5), created=DAY(3))
        review = self.s.team_review_action('create', dict(person_id=self.maria['id'], start=DAY(1, 0), end=DAY(2, 0)))
        review = self.s.team_review_action('agreements', dict(id=review['id'], revision=review['revision'], agreements=[dict(kind='action', text='Restore backup', owner='person', status='done', task_id=task['id'], expected_result='Files restored', result_evidence='Demonstrated restore', verified=True)]))
        rows = review['agreements'];rows[0]['verified_at'] = DAY(6)
        atomic_json(self.s.team_reviews.directory(review['id']) / 'agreements.json', rows)
        result = self.run_week()
        self.assertEqual(result['coverage']['counts']['result confirmed'], 1)
        check = next(e for e in result['evidence'] if e['kind'] == 'result_confirmed')
        self.assertEqual(check['facts']['criterion'], 'Files restored')
