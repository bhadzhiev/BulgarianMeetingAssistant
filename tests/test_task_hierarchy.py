import copy
import tempfile
import unittest
from pathlib import Path

from app import task_hierarchy, task_email
from app.items import WorkItemConflict
from app.service import MeetingService
from tests.test_followup_email import DraftGoogle

PROJECT = Path(__file__).resolve().parents[1]


class TaskHierarchyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.s = MeetingService(Path(self.tmp.name) / 'library', PROJECT, google=DraftGoogle(), backup_dir=Path(self.tmp.name) / 'backups')
        self.addCleanup(self.s.close)
        self.counter = 0
        self.parent = self.task('Main task')
        self.a = self.task('First task', owner='Maria', due_date='2026-11-20')
        self.b = self.task('Second task')

    def task(self, text, **fields):
        self.counter += 1
        return self.s.create_task(dict(text=text, request_id=f'{self.counter:032x}', **fields))

    def row(self, item):
        task = self.s.items.items[item['id']]
        return dict(id=task['id'], revision=task['revision'])

    def body(self, selected, parent=None, **extra):
        self.counter += 1
        body = dict(items=[self.row(t) for t in selected], request_id=f'{self.counter:032x}')
        if parent:
            body.update(parent_id=parent['id'], parent_revision=self.s.items.items[parent['id']]['revision'])
        else:
            body['parent_id'] = None
        body.update(extra)
        return body

    def attach(self, selected=None):
        return task_hierarchy.assign(self.s, self.body(selected or [self.a, self.b], self.parent))

    def test_group_and_detach_preserve_fields_evidence_and_history(self):
        before = copy.deepcopy(self.s.items.items[self.a['id']])
        self.attach()
        task = self.s.items.items[self.a['id']]
        self.assertEqual(task['parent_task_id'], self.parent['id'])
        for name in ('text', 'owner', 'due_date', 'links', 'evidence'):
            self.assertEqual(task.get(name), before.get(name))
        self.assertEqual(task['history'][:-1], before['history'])
        task_hierarchy.assign(self.s, self.body([self.a]))
        self.assertIsNone(self.s.items.items[self.a['id']]['parent_task_id'])
        self.s.items.data, self.s.items.revision = self.s.items.store.load()
        self.assertEqual(self.s.items.items[self.b['id']]['parent_task_id'], self.parent['id'])
        self.assertIn('First task', [e.get('text') for e in self.s.items.items[self.parent['id']]['history']])

    def test_new_main_task_is_atomic_and_retry_does_not_duplicate(self):
        body = self.body([self.a, self.b], new_parent_title='New programme')
        first = task_hierarchy.assign(self.s, body)
        self.assertEqual(first, task_hierarchy.assign(self.s, body))
        self.assertEqual(len(self.s.items.items), 4)
        self.assertEqual(self.s.items.items[first['parent_id']]['text'], 'New programme')
        with self.assertRaises(WorkItemConflict):
            task_hierarchy.assign(self.s, dict(body, new_parent_title='Different'))

    def test_validation_is_all_or_nothing(self):
        body = self.body([self.a, self.b], self.parent)
        body['items'][1]['revision'] += 1
        with self.assertRaises(WorkItemConflict):task_hierarchy.assign(self.s, body)
        self.assertFalse(self.s.items.items[self.a['id']].get('parent_task_id'))
        body = self.body([self.a], self.parent);body['parent_revision'] += 1
        with self.assertRaises(WorkItemConflict):task_hierarchy.assign(self.s, body)
        body = self.body([self.a], new_parent_title='Must not be created');body['items'][0]['revision'] += 1
        with self.assertRaises(WorkItemConflict):task_hierarchy.assign(self.s, body)
        self.assertEqual(len(self.s.items.items), 3)

    def test_cycles_and_multiple_levels_are_rejected(self):
        with self.assertRaises(ValueError):task_hierarchy.assign(self.s, self.body([self.parent], self.parent))
        self.attach([self.a])
        with self.assertRaises(ValueError):task_hierarchy.assign(self.s, self.body([self.parent], self.b))
        with self.assertRaises(ValueError):task_hierarchy.assign(self.s, self.body([self.b], self.a))
        with self.assertRaises(ValueError):task_hierarchy.assign(self.s, self.body([self.parent], new_parent_title='New root'))

    def test_a_subtask_can_move_between_roots(self):
        self.attach([self.a])
        task_hierarchy.assign(self.s, self.body([self.a], self.b))
        self.assertEqual(self.s.items.items[self.a['id']]['parent_task_id'], self.b['id'])
        self.assertFalse(task_hierarchy.children(self.s.items.items, self.parent['id']))

    def test_proposals_hidden_and_completed_parents_are_rejected(self):
        for changes in [dict(acceptance_state='proposed'), dict(dismissed=True), dict(workflow_state='done', status='done')]:
            parent = self.s.items.items[self.parent['id']]
            original = copy.deepcopy(parent)
            parent.update(changes);self.s.items.save()
            with self.assertRaises(ValueError):self.attach([self.a])
            self.s.items.items[self.parent['id']] = original;self.s.items.save()

    def test_completion_warns_without_changing_subtasks(self):
        self.attach()
        parent = self.s.items.items[self.parent['id']]
        with self.assertRaises(ValueError):self.s.update_item(parent['id'], parent['text'], dict(workflow_state='done'), parent['revision'])
        self.s.update_item(parent['id'], parent['text'], dict(workflow_state='done'), parent['revision'], confirm_subtasks=True)
        self.assertEqual(self.s.items.items[self.a['id']]['workflow_state'], 'todo')
        self.assertEqual(len(task_hierarchy.unfinished(self.s.items.items, parent['id'])), 2)

    def test_deleting_main_task_detaches_and_keeps_subtasks(self):
        self.attach()
        parent = self.s.items.items[self.parent['id']]
        self.s.delete_item(parent['id'], parent['text'], parent['revision'])
        self.assertIn(self.a['id'], self.s.items.items)
        self.assertIsNone(self.s.items.items[self.a['id']]['parent_task_id'])
        self.assertEqual(self.s.items.items[self.a['id']]['history'][-1]['event'], 'parent_changed')

    def test_updating_email_selection_removes_stale_draft_markers(self):
        self.attach()
        ids = [self.parent['id'], self.a['id'], self.b['id']]
        prepared = task_email.prepare(self.s, dict(item_ids=ids))
        task_email.save_draft(self.s, dict(item_ids=ids, to=['maria@example.test'], **{k: prepared[k] for k in ('subject', 'body')}))
        prepared = task_email.prepare(self.s, dict(item_ids=ids[:2]))
        result = task_email.save_draft(self.s, dict(item_ids=ids[:2], to=['maria@example.test'], **{k: prepared[k] for k in ('subject', 'body')}))
        self.assertTrue(result['updated'])
        self.assertNotIn('email_draft', self.s.items.items[self.b['id']])
        self.assertEqual(self.s.items.items[self.b['id']]['history'][-1]['event'], 'email_draft_removed')
        self.assertEqual(self.s.items.items[self.a['id']]['email_draft']['task_count'], 2)

    def test_storage_refuses_dangling_and_nested_parent_links(self):
        task = self.s.items.items[self.a['id']]
        task['parent_task_id'] = 'deadbeef'
        with self.assertRaises(ValueError):self.s.items.save()
        task.pop('parent_task_id')
        self.attach([self.a])
        self.s.items.items[self.b['id']]['parent_task_id'] = self.a['id']
        with self.assertRaises(ValueError):self.s.items.save()

    def test_merge_cannot_silently_destroy_grouping(self):
        self.attach([self.a])
        for a, b in [(self.parent, self.b), (self.a, self.b), (self.b, self.parent)]:
            with self.assertRaises(ValueError):self.s.merge_items(a['id'], b['id'])

    def test_email_uses_only_selected_tasks_in_hierarchical_order(self):
        self.attach()
        data = task_email.prepare(self.s, dict(item_ids=[self.b['id'], self.parent['id'], self.a['id']]))
        self.assertIn('1. Main task', data['body'])
        self.assertIn('1.1. Second task', data['body'])
        self.assertIn('1.2. First task', data['body'])
        self.assertEqual(data['body'].count('First task'), 1)
        self.assertEqual(len(data['available_tasks']), 3)
        data = task_email.prepare(self.s, dict(item_ids=[self.parent['id']]))
        self.assertNotIn('First task', data['body'])
        self.assertNotIn('Second task', data['body'])
        self.assertEqual(len(data['available_tasks']), 3)
        data = task_email.prepare(self.s, dict(item_ids=[self.a['id']]))
        self.assertIn('Основна задача: Main task', data['body'])
        self.assertIn('Отговорник: Maria', data['body'])
        self.assertIn('Срок: 20.11.2026', data['body'])
        formatted = task_email.formatted_body('1. Root\n\n1.1. Child <test>')
        self.assertIn('margin-left:20px', formatted);self.assertIn('&lt;test&gt;', formatted)


class TaskHierarchyHTTPTests(unittest.TestCase):
    from tests.test_http import HTTPTests as _HTTP
    setUp = _HTTP.setUp
    tearDown = _HTTP.tearDown
    request = _HTTP.request

    def test_group_route_requires_session_and_revisions(self):
        import json
        a = self.service.create_task(dict(text='Child', request_id='a' * 32))
        body = dict(items=[dict(id=a['id'], revision=a['revision'])], new_parent_title='Root', request_id='b' * 32)
        self.assertEqual(self.request('/api/items/hierarchy', body, headers={})[0], 403)
        status, result, _ = self.request('/api/items/hierarchy', body)
        self.assertEqual(status, 200)
        root = json.loads(result)['parent_id']
        self.assertEqual(self.service.items.items[a['id']]['parent_task_id'], root)
        status, _, _ = self.request('/api/items/hierarchy', dict(body, request_id='c' * 32))
        self.assertEqual(status, 409)
