"""The model must receive complete, dated, explicitly linked work, exactly as approved."""
import copy
import json
import unittest
from unittest.mock import patch

from app import team_ai
from app.review_evidence import input_data, timeline_batches, MAX_BATCH_CHARS
from app.team_github import collect, Reader, records
from app.team_facts import collect as collect_facts
from tests import test_team_facts as facts_fixture
from tests import test_team_ai as ai_fixture
from tests import test_team_github as github_fixture

PERIOD = dict(start='2026-11-01T00:00:00+02:00', end='2026-11-08T00:00:00+02:00', timezone='Europe/Sofia')


def record(number, task=None, when=None, kind='task_update', **source):
    return dict(id=f'e{number}', kind=kind, occurred_at=when, source_ref=dict(source, **({'item_id': task} if task else {})),
                confirmation_basis='Saved source', facts=dict(text='VPN rollout', update='Reported progress'), quote='I checked the test environment.')


def review(rows, **extra):
    return dict(id='review-one', person_name='Maria', period=PERIOD, evidence=rows, **extra)


class TimelineInputTests(unittest.TestCase):
    def test_preserves_dates_period_work_and_source_but_not_private_local_fields(self):
        row = record(1, 'vpn-task', '2026-11-03T09:00:00+02:00', provider='meeting', meeting_id='meeting-one', timestamp='00:12:03', revision=7)
        row.update(person_id='private-person', secret='key')
        row['source_ref'].update(local_path='/Users/private/file', token='credential', account='private@example.com')
        row['source_ref']['origins'] = [dict(provider='gmail', source_id='thread-123', account='private@example.com', token='credential')]
        data = input_data(review([row]))
        value = data['records'][0]
        self.assertEqual(data['period'], PERIOD)
        self.assertEqual(value['occurred_at'], row['occurred_at'])
        self.assertEqual(value['work_ids'], ['vpn-task'])
        self.assertEqual(value['source_ref']['timestamp'], '00:12:03')
        self.assertEqual(value['source_ref']['revision'], 7)
        self.assertEqual(value['source_ref']['origins'], [dict(provider='gmail', source_id='thread-123')])
        self.assertEqual(value['evidence_type'], 'reported_update')
        payload = json.dumps(data)
        for secret in ('private-person', '/Users/', 'credential', 'private@example.com'):
            self.assertNotIn(secret, payload)

    def test_a_task_with_more_than_forty_events_stays_whole_and_in_time_order(self):
        rows = [record(n, 'one-task', f'2026-11-03T09:{n % 60:02}:00+02:00') for n in range(1, 86)]
        data = input_data(review(rows[::-1]))
        parts = timeline_batches(data)
        self.assertEqual(len(parts), 1)
        self.assertEqual(len(parts[0]['records']), 85)
        dates = [r['occurred_at'] for r in parts[0]['records']]
        self.assertEqual(dates, sorted(dates))
        self.assertEqual(len(parts[0]['timelines']), 1)
        self.assertEqual(set(parts[0]['timelines'][0]['record_ids']), {r['id'] for r in rows})

    def test_scattered_events_of_a_task_are_not_split_at_a_batch_boundary(self):
        rows = [record(1, 'vpn', '2026-11-01T09:00:00+02:00', kind='task_assigned')]
        rows += [record(n, 'other-'+str(n), f'2026-11-02T09:{n:02}:00+02:00') for n in range(2, 42)]
        rows += [record(42, 'vpn', '2026-11-05T10:00:00+02:00', kind='task_completed'), record(43, 'vpn', '2026-11-06T10:00:00+02:00', kind='result_confirmed')]
        parts = timeline_batches(input_data(review(rows)))
        self.assertEqual(len(parts), 2)
        containing = [p for p in parts if any(r['id'] == 'e1' for r in p['records'])]
        self.assertEqual(len(containing), 1)
        self.assertTrue({'e1', 'e42', 'e43'} <= {r['id'] for r in containing[0]['records']})
        self.assertEqual(sum(len(p['records']) for p in parts), len(rows))

    def test_same_words_are_not_a_link_and_explicit_github_links_bridge_sources(self):
        rows = [record(1, 'a'), record(2, 'b'), record(3, provider='github', url='https://github.com/acme/app/pull/7', item_ids=['a'])]
        data = input_data(review(rows));by_id = {r['id']: r for r in data['records']}
        self.assertEqual(by_id['e1']['timeline_id'], by_id['e3']['timeline_id'])
        self.assertNotEqual(by_id['e1']['timeline_id'], by_id['e2']['timeline_id'])
        rows.append(record(4, provider='github', url='https://github.com/acme/app/pull/7#r1', artifact_url='https://github.com/acme/app/pull/7', item_ids=['b']))
        data = input_data(review(rows))
        self.assertEqual(len({r['timeline_id'] for r in data['records']}), 1)
        self.assertEqual(timeline_batches(data)[0]['timelines'][0]['work_ids'], ['a', 'b'])

    def test_stable_agreement_identity_links_versions_without_an_associated_task(self):
        data = input_data(review([record(1, kind='agreement', review_id='old', agreement_id='agreed-action'), record(2, kind='agreement', review_id='new', agreement_id='agreed-action')]))
        self.assertEqual(len({r['timeline_id'] for r in data['records']}), 1)
        self.assertNotEqual(data['records'][0]['source_ref']['review_id'], data['records'][1]['source_ref']['review_id'])

    def test_missing_dates_are_unknown_and_snapshots_are_not_events(self):
        rows = [record(1, 'a', 'bad-date'), record(2, 'a', '2026-10-20T12:00:00Z'),
                record(3, 'a', PERIOD['end'], kind='task_open'), record(4, 'a', '2026-11-09T12:00:00+02:00', kind='agreement')]
        data = input_data(review(rows));values = {r['id']: r for r in data['records']}
        self.assertIsNone(values['e1']['occurred_at'])
        self.assertEqual(values['e1']['period_relation'], 'unknown')
        self.assertEqual(values['e2']['period_relation'], 'before_period')
        self.assertEqual(values['e3']['time_basis'], 'period_end_snapshot')
        self.assertEqual(values['e4']['time_basis'], 'current_saved_state')
        self.assertEqual(values['e4']['period_relation'], 'after_period')

    def test_private_context_is_opt_in_and_repeated_exactly_for_each_batch(self):
        rows = [record(n, 'task-'+str(n)) for n in range(1, 50)]
        context = dict(role='Responsible for safe restores', include_in_ai=False, observations=[])
        self.assertFalse(any(r['kind'] == 'review_context' for r in input_data(review(rows, context=context))['records']))
        context['include_in_ai'] = True
        parts = timeline_batches(input_data(review(rows, context=context)))
        self.assertEqual(len(parts), 2)
        private = [[r for r in p['records'] if r['kind'] == 'review_context'] for p in parts]
        self.assertEqual(private[0], private[1])
        self.assertEqual(private[0][0]['evidence_type'], 'manager_perspective')

    def test_whole_timeline_limit_fails_explicitly_without_truncation(self):
        row = record(1, 'too-large');row['facts']['text'] = 'x' * MAX_BATCH_CHARS
        original = copy.deepcopy(row)
        with self.assertRaisesRegex(ValueError, 'will not be split or truncated'):
            timeline_batches(input_data(review([row])))
        self.assertEqual(row, original)

    def test_legacy_totals_and_linked_updates_do_not_become_verified_results(self):
        old = record(1, 'vpn-task', kind='result_confirmed')
        data = input_data(review([old], coverage=dict(counts={'taken on': 11})))
        self.assertNotIn('counts', data['coverage'])
        self.assertEqual(data['coverage']['counts_status'], 'legacy_rules_ignored')
        self.assertEqual(data['records'][0]['evidence_type'], 'linked_update_without_recorded_check')
        old['facts'].update(criterion='Restore a test copy', checked_by='Manager', result_evidence='Restore demonstrated')
        current = input_data(review([old], coverage=dict(fact_version=2, counts={'result confirmed': 1})))
        self.assertEqual(current['coverage']['counts']['result confirmed'], 1)
        self.assertEqual(current['records'][0]['evidence_type'], 'recorded_human_check')

    def test_unsafe_urls_do_not_enter_input_or_connect_timelines(self):
        for url in ['file:///Users/private/key', 'https://github.com/acme/app/pull/1?token=secret', 'https://user:secret@github.com/acme/app/pull/1', 'https://example.com/api']:
            self.assertNotIn('url', input_data(review([record(1, url=url)]))['records'][0]['source_ref'])

    def test_repeated_context_observation_is_not_counted_as_repeated_behaviour(self):
        observation = dict(section='context', text='Clarify priorities', evidence=['e1'], attribution='uncertain')
        part = dict(observations=[observation], questions=[], not_enough_data=False, rejected=0)
        joined = team_ai.join([part, dict(part, observations=[dict(observation, evidence=['e2'])])])
        self.assertEqual(len(joined['observations']), 1)
        self.assertEqual(joined['observations'][0]['evidence'], ['e1', 'e2'])
        self.assertEqual(observation['evidence'], ['e1'])

    def test_github_collection_retains_explicit_task_links_in_evidence(self):
        reader = Reader(github_fixture.FakeGitHub(), {}, lambda data: None)
        found = collect(reader, 'maria', github_fixture.START, github_fixture.END, {'acme/app'},
                        lambda repo, n: [dict(resource=dict(kind='item', id='vpn-task'))] if n == 1 else [])
        evidence = records(found, 'not-sent-person', 1)
        merged = next(r for r in evidence if r['kind'] == 'github_pr_merged')
        self.assertEqual(merged['source_ref']['item_ids'], ['vpn-task'])
        data = input_data(review([record(99, 'vpn-task'), merged]))
        self.assertEqual(len({r['timeline_id'] for r in data['records']}), 1)


class TimelineCollectorTests(unittest.TestCase):
    setUp = facts_fixture.TeamFactTests.setUp
    task = facts_fixture.TeamFactTests.task
    times = facts_fixture.TeamFactTests.times
    run_week = facts_fixture.TeamFactTests.run_week

    def test_progress_and_state_events_keep_original_times_on_the_same_work_item(self):
        task = self.task('Restore backup', 'a', owner_person_id=self.maria['id'])
        task = self.s.update_item(task['id'], task['text'], dict(workflow_state='in_progress'), task['revision'])
        task = self.s.update_item(task['id'], task['text'], dict(update_note='Restored a test copy'), task['revision'])
        self.times(task, facts_fixture.DAY(3), facts_fixture.DAY(3), facts_fixture.DAY(4), facts_fixture.DAY(5), created=facts_fixture.DAY(3))
        result = self.run_week()
        selected = [r for r in result['evidence'] if r['kind'] in {'task_update', 'task_state_changed'}]
        self.assertEqual([r['kind'] for r in selected], ['task_state_changed', 'task_update'])
        self.assertEqual(selected[1]['occurred_at'], facts_fixture.DAY(5))
        self.assertEqual(selected[1]['quote'], 'Restored a test copy')
        data = input_data(review(selected))
        self.assertEqual(len({r['timeline_id'] for r in data['records']}), 1)
        self.assertEqual(data['records'][1]['work_ids'], [task['id']])

    def test_ai_progress_report_preserves_original_quote_separately_from_summary(self):
        task = self.task('Restore backup', 'a', owner_person_id=self.maria['id'])
        self.times(task, facts_fixture.DAY(3), facts_fixture.DAY(3), created=facts_fixture.DAY(3))
        item = self.s.items.items[task['id']]
        item['history'].append(dict(event='progress_update', at=facts_fixture.DAY(5), by='ai', text='Reports completion',
            quote='I restored a test copy, but production is still pending.', meeting_id=self.meeting, evidence_timestamp='00:00:11', changes={}))
        self.s.items.save()
        result = self.run_week()
        report = next(r for r in result['evidence'] if r['kind'] == 'task_update')
        self.assertEqual(report['facts']['update'], 'Reports completion')
        self.assertEqual(report['quote'], 'I restored a test copy, but production is still pending.')
        projected = input_data(review([report]))['records'][0]
        self.assertEqual(projected['quote_basis'], 'source_excerpt')
        self.assertEqual(projected['source_ref']['timestamp'], '00:00:11')


class TimelineApprovalTests(unittest.TestCase):
    setUp = ai_fixture.TeamAITests.setUp
    records = ai_fixture.TeamAITests.records

    def test_approval_covers_exact_requests_and_expires_when_a_source_reference_changes(self):
        self.records(45);ai = team_ai.ReviewAI(self.s, ai_fixture.FakeRunner())
        preview = ai.preview(self.review['id'])
        data = team_ai.ai_input(self.s.team_reviews.get(self.review['id']))
        self.assertEqual(preview['batch_inputs'], team_ai.batches(data))
        from app.work_items import canonical, WorkItemConflict
        self.assertEqual(preview['characters'], sum(len(canonical(p)) for p in preview['batch_inputs']))
        folder = self.s.team_reviews.directory(self.review['id']);rows = json.loads((folder/'evidence.json').read_text())
        rows[0]['source_ref']['meeting_id'] = 'new-source';(folder/'evidence.json').write_text(json.dumps(rows))
        with self.assertRaises(WorkItemConflict):
            ai.start(dict(id=self.review['id'], preview_token=preview['preview_token'], approved=True))

    def test_worker_output_with_unknown_citations_is_filtered_before_saving(self):
        self.records(2)
        class UncheckedRunner:
            def run(self, action, directory, settings, progress, key='', cancel=None):
                return dict(observations=[dict(section='tasks', text='Invented finding', evidence=['e999'], attribution='clear')], questions=[], not_enough_data=False)
        ai = team_ai.ReviewAI(self.s, UncheckedRunner());preview = ai.preview(self.review['id'])
        job = ai.start(dict(id=self.review['id'], preview_token=preview['preview_token'], approved=True));ai.thread.join(10)
        self.assertFalse(ai.thread.is_alive());self.assertIsNone(ai.status(job['id'])['error'])
        saved = self.s.team_reviews.get(self.review['id'])
        self.assertNotIn('Invented finding', saved['review_md']);self.assertNotIn('e999', saved['review_md'])
        self.assertEqual(saved['generator']['rejected'], 1)

    def test_builtin_prompt_change_invalidates_an_approved_preview(self):
        self.records(1);ai = team_ai.ReviewAI(self.s, ai_fixture.FakeRunner());preview = ai.preview(self.review['id'])
        from app.work_items import WorkItemConflict
        with patch.object(team_ai, 'SYSTEM', team_ai.SYSTEM + '\nChanged contract'):
            with self.assertRaises(WorkItemConflict):
                ai.start(dict(id=self.review['id'], preview_token=preview['preview_token'], approved=True))
