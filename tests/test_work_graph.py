import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.items import Registry
from app.work_graph import WorkGraph
from app.work_items import WorkItemConflict, WorkItemStore
from tests import test_work_items as foundation


class GraphTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'items.json'
        self.registry = Registry(self.path)
        self.graph = WorkGraph(self.registry)
        self.source = dict(provider='fixture', account='synthetic@example.invalid', external_id='thread-1',
                           revision='r1', text='Please review the backup. Which retention period?')
        self.suggestions = [dict(kind='task', text='Review backup', quote='review the backup', locator={'message':'m1'})]

    def ingest(self):
        return self.graph.ingest(self.source, self.suggestions)

    def proposal(self, result):
        return self.registry.data['proposals'][result['proposals'][0]]

    def test_idempotent_ingestion_survives_restart_and_dismissal(self):
        result = self.ingest()
        proposal = self.proposal(result)
        self.graph.review(proposal['id'], proposal['revision'], 'dismiss')
        revision = self.registry.revision
        graph = WorkGraph(Registry(self.path))
        self.assertEqual(graph.ingest(self.source, self.suggestions), result)
        reopened = Registry(self.path)
        self.assertEqual(len(reopened.data['proposals']), 1)
        self.assertEqual(reopened.data['proposals'][proposal['id']]['state'], 'dismissed')
        self.assertEqual(reopened.revision, revision)
        self.assertEqual(reopened.items, {})

    def test_invalid_later_proposal_rolls_back_entire_ingestion(self):
        before = self.registry.revision
        bad = self.suggestions + [dict(kind='task', text='Unsupported claim', quote='not in source')]
        with self.assertRaises(ValueError):
            self.graph.ingest(self.source, bad)
        self.assertEqual(Registry(self.path).revision, before)
        self.assertEqual(self.registry.data['sources'], {})
        self.assertEqual(self.registry.data['proposals'], {})

    def test_accept_is_atomic_and_not_repeatable(self):
        proposal = self.proposal(self.ingest())
        with patch.object(self.registry.store, 'save', side_effect=OSError('synthetic disk failure')):
            with self.assertRaises(OSError):
                self.graph.review(proposal['id'], 1, 'accept')
        self.assertEqual(Registry(self.path).items, {})
        accepted = self.graph.review(proposal['id'], 1, 'accept')
        item = self.registry.items[accepted['result_id']]
        self.assertEqual((item['status'], len(item['source_evidence'])), ('open', 1))
        self.assertFalse(next(iter(self.registry.data['sources'].values()))['ai_export_allowed'])
        with self.assertRaises(WorkItemConflict):
            self.graph.review(proposal['id'], 1, 'accept')
        self.assertEqual(len(self.registry.items), 1)

    def test_new_source_version_invalidates_pending_proposals(self):
        old = self.proposal(self.ingest())
        self.source.update(revision='r2', text='Please review the backup next month.')
        self.ingest()
        self.assertEqual(self.registry.data['proposals'][old['id']]['state'], 'stale')
        with self.assertRaises(WorkItemConflict):
            self.graph.review(old['id'], old['revision'], 'accept')
        self.assertEqual(len(self.registry.data['source_revisions']), 2)
        self.source['revision'] = 'r1'
        self.source['text'] = 'Please review the backup. Which retention period?'
        with self.assertRaises(WorkItemConflict):
            self.ingest()

    def test_same_external_revision_cannot_change_content(self):
        self.ingest()
        self.source['text'] = 'Changed content'
        with self.assertRaises(WorkItemConflict):
            self.graph.ingest(self.source, [])
        self.assertEqual(len(self.registry.data['source_revisions']), 1)

    def test_link_preserves_manual_fields_and_requires_target_revision(self):
        first = self.proposal(self.ingest())
        accepted = self.graph.review(first['id'], 1, 'accept')
        key = accepted['result_id']
        self.registry.update(key, dict(text='Human title', owner='Synthetic person', status='done'))
        self.registry.save()
        old_revision = self.registry.items[key]['revision']
        self.source['external_id'] = 'thread-2'
        second = self.proposal(self.ingest())
        self.registry.update(key, dict(owner='Another synthetic person'))
        self.registry.save()
        with self.assertRaises(WorkItemConflict):
            self.graph.review(second['id'], 1, 'link', target_id=key, target_revision=old_revision)
        self.graph.review(second['id'], 1, 'link', target_id=key, target_revision=self.registry.items[key]['revision'])
        item = self.registry.items[key]
        self.assertEqual((item['text'], item['status'], item['owner']), ('Human title', 'done', 'Another synthetic person'))
        self.assertEqual(len(item['source_evidence']), 2)

    def test_snooze_dismiss_restore_and_stale_review_tokens(self):
        p = self.proposal(self.ingest())
        snoozed = self.graph.review(p['id'], 1, 'snooze', snoozed_until='2099-01-01')
        self.assertEqual(snoozed['state'], 'pending')
        with self.assertRaises(WorkItemConflict):
            self.graph.review(p['id'], 1, 'dismiss')
        dismissed = self.graph.review(p['id'], 2, 'dismiss')
        restored = self.graph.review(p['id'], dismissed['revision'], 'restore')
        self.assertEqual((restored['state'], restored['snoozed_until']), ('pending', None))

    def test_missing_source_blocks_accept_without_changing_item_state(self):
        result = self.ingest()
        p = self.proposal(result)
        self.graph.availability(result['source_id'], result['source_revision'], False)
        with self.assertRaises(WorkItemConflict):
            self.graph.review(p['id'], 1, 'accept')
        self.assertEqual(self.registry.items, {})
        self.assertEqual(len(self.registry.data['source_evidence']), 1)

    def test_questions_require_answer_and_reject_stale_updates(self):
        q = self.graph.question('Which retention period?')
        with self.assertRaises(ValueError):
            self.graph.question(None, item_id=q['id'], revision=q['revision'], answer='')
        answered = self.graph.question(None, item_id=q['id'], revision=q['revision'], answer='Thirty days')
        self.assertEqual((answered['status'], answered['answer']), ('answered', 'Thirty days'))
        with self.assertRaises(WorkItemConflict):
            self.graph.question(None, item_id=q['id'], revision=q['revision'], answer='Other answer')
        reopened = self.graph.question(None, item_id=q['id'], revision=answered['revision'])
        self.assertEqual((reopened['status'], reopened['answer']), ('open', None))
        self.registry.prune(set())
        self.registry.save()
        self.assertIn(q['id'], Registry(self.path).items)

    def test_relationships_are_idempotent_and_cannot_cycle(self):
        a = self.graph.question('Synthetic A?')
        b = self.graph.question('Synthetic B?')
        edge = self.graph.relate(a['id'], b['id'], 'supports', a['revision'], b['revision'])
        self.assertEqual(self.graph.relate(a['id'], b['id'], 'supports', a['revision'], b['revision']), edge)
        with self.assertRaises(ValueError):
            self.graph.relate(b['id'], a['id'], 'supports', b['revision'], a['revision'])
        self.assertEqual(len(self.registry.data['relationships']), 1)

    def test_immutable_evidence_tampering_is_rejected_before_commit(self):
        self.ingest()
        before = self.registry.revision
        data = copy.deepcopy(self.registry.data)
        next(iter(data['source_evidence'].values()))['quote'] = 'invented quote'
        with self.assertRaises(ValueError):
            self.registry.store.save(data, before)
        self.assertEqual(Registry(self.path).revision, before)

    def test_dangling_relationship_is_rejected_before_database_commit(self):
        a = self.graph.question('Synthetic A?')
        b = self.graph.question('Synthetic B?')
        self.graph.relate(a['id'], b['id'], 'supports', a['revision'], b['revision'])
        data = copy.deepcopy(self.registry.data)
        del data['items'][b['id']]
        with self.assertRaisesRegex(ValueError, 'endpoint'):
            self.registry.store.save(data, self.registry.revision)
        self.assertIn(b['id'], Registry(self.path).items)

    def test_portable_full_graph_reimports_without_live_database(self):
        p = self.proposal(self.ingest())
        self.graph.review(p['id'], 1, 'accept')
        expected = copy.deepcopy(self.registry.data)
        other = Path(self.tmp.name) / 'import'
        other.mkdir()
        (other / 'items.json').write_text(json.dumps(expected))
        restored = Registry(other / 'items.json')
        for key in ('items', 'sources', 'source_revisions', 'source_evidence', 'proposals', 'relationships', 'activity'):
            self.assertEqual(restored.data[key], expected[key])


class GraphBackupTests(unittest.TestCase):
    setUp = foundation.FoundationTests.setUp
    tearDown = foundation.FoundationTests.tearDown
    # Reuse a real service with a synthetic library, including the existing foundation checks.
    def test_graph_only_archive_restore_preserves_questions_and_proposals(self):
        graph = WorkGraph(self.service.items)
        q = graph.question('Synthetic archive question?')
        graph.question(None, item_id=q['id'], revision=q['revision'], answer='Saved synthetic answer')
        result = graph.ingest(dict(provider='fixture', account='synthetic', external_id='message', revision='1', text='Review backups'),
                              [dict(kind='task', text='Review backups', quote='Review backups')])
        graph.review(result['proposals'][0], 1, 'accept')
        expected = copy.deepcopy(self.service.items.data)
        archive = self.service.create_backup()['created']['name']
        from app.service import MeetingService
        from tests.test_calendar import FakeGoogle
        restored = MeetingService(self.root / 'restored', self.service.project, google=FakeGoogle(), backup_dir=self.root / 'backups')
        try:
            restored.restore_backup(archive)
            for key in ('items', 'sources', 'source_revisions', 'source_evidence', 'proposals', 'relationships', 'activity'):
                self.assertEqual(restored.items.data[key], expected[key])
        finally:
            restored.close()


class GraphHTTPTests(unittest.TestCase):
    setUp = foundation.test_http.HTTPTests.setUp
    tearDown = foundation.test_http.HTTPTests.tearDown
    request = foundation.test_http.HTTPTests.request

    def test_ingest_review_and_question_routes_enforce_session_and_versions(self):
        body = dict(source=dict(provider='fixture', account='synthetic', external_id='thread', revision='1', text='Review backup'),
                    suggestions=[dict(kind='task', text='Review backup', quote='Review backup')])
        self.assertEqual(self.request('/api/work/ingest', body, headers={})[0], 403)
        self.assertEqual(self.request('/api/work/ingest', body, headers=dict(self.headers, Origin='https://example.invalid'))[0], 403)
        status, raw, _ = self.request('/api/work/ingest', body)
        self.assertEqual(status, 200)
        result = json.loads(raw)
        review = dict(id=result['proposals'][0], revision=1, action='accept')
        self.assertEqual(self.request('/api/work/review', review)[0], 200)
        self.assertEqual(self.request('/api/work/review', review)[0], 409)
        status, raw, _ = self.request('/api/work/question', dict(text='Synthetic question?'))
        self.assertEqual(status, 200)
        q = json.loads(raw)
        answer = dict(id=q['id'], revision=q['revision'], answer='Synthetic answer')
        self.assertEqual(self.request('/api/work/question', answer)[0], 200)
        self.assertEqual(self.request('/api/work/question', answer)[0], 409)
        _, raw, _ = self.request('/api/items')
        self.assertEqual(len(json.loads(raw)['graph']['proposals']), 1)
