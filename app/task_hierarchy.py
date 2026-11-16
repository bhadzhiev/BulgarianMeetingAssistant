"""Reversible task grouping. Source identity, task fields and evidence stay on each task."""
from __future__ import annotations

import copy
import hashlib
import re
import uuid

from . import items
from .work_graph import WorkGraph
from .work_items import canonical


def children(registry: dict, parent_id: str) -> list[dict]:
    return [task for task in registry.values() if task.get('kind') == 'task' and task.get('parent_task_id') == parent_id]


def unfinished(registry: dict, parent_id: str) -> list[dict]:
    return [task for task in children(registry, parent_id)
            if task.get('workflow_state', 'done' if task.get('status') == 'done' else 'todo') not in {'done', 'cancelled'}]


def assign(service, body: dict) -> dict:
    selected = body.get('items')
    parent_id, title, operation = body.get('parent_id'), body.get('new_parent_title'), body.get('request_id')
    if not isinstance(selected, list) or not 1 <= len(selected) <= 100:
        raise ValueError('Select 1–100 tasks')
    if not isinstance(operation, str) or not re.fullmatch('[a-f0-9]{32}', operation):
        raise ValueError('A grouping request ID is required')
    if title is not None and (parent_id is not None or not isinstance(title, str) or not 1 <= len(title.strip()) <= 1000):
        raise ValueError('Enter a main task title up to 1000 characters')
    if parent_id is not None and not isinstance(parent_id, str):
        raise ValueError('Choose a main task')
    ids = []
    for row in selected:
        if not isinstance(row, dict) or not isinstance(row.get('id'), str) or type(row.get('revision')) is not int:
            raise ValueError('Reload the task selection')
        ids.append(row['id'])
    if len(set(ids)) != len(ids):
        raise ValueError('Choose each task once')
    payload = hashlib.sha256(canonical(body).encode()).hexdigest()
    with service.lock, service.items.lock, service.items.store.serialized():
        service.items.data, service.items.revision = service.items.store.load()
        registry = service.items.items
        old = next((e for e in service.items.data['activity'].values()
                    if e.get('event') == 'task_hierarchy_changed' and e.get('request_id') == operation), None)
        if old:
            if old['payload'] != payload:
                raise items.WorkItemConflict('This request already grouped a different selection')
            return dict(parent_id=old['parent_id'], updated=old['item_ids'])
        parent = registry.get(parent_id) if parent_id else None
        if parent_id and (not parent or type(body.get('parent_revision')) is not int or parent.get('revision') != body.get('parent_revision')):
            raise items.WorkItemConflict('The main task changed. Reload and try again.')
        if parent and (parent['kind'] != 'task' or parent.get('parent_task_id') or parent.get('dismissed') or parent.get('acceptance_state') == 'proposed'):
            raise ValueError('Choose an accepted main task, not a subtask')
        if parent and parent.get('workflow_state') in {'done', 'cancelled'}:
            raise ValueError('Reopen the main task before adding subtasks')
        for row in selected:
            task = registry.get(row['id'])
            if not task or task['kind'] != 'task' or task.get('revision') != row['revision']:
                raise items.WorkItemConflict('A selected task changed. Reload; no tasks were grouped.')
            if task.get('dismissed') or task.get('acceptance_state') == 'proposed':
                raise ValueError('Choose accepted, visible tasks')
            if parent_id == task['id']:
                raise ValueError('A task cannot be its own subtask')
            if (parent_id or title) and children(registry, task['id']):
                raise ValueError('A main task with subtasks cannot become a subtask. Detach its subtasks first.')
        previous = copy.deepcopy(service.items.data)
        try:
            if title is not None:
                parent_id = uuid.uuid4().hex[:16]
                parent = dict(id=parent_id, kind='task', text=title.strip(), status='open', workflow_state='todo',
                              acceptance_state='accepted', created=items.now(), created_by='user', manual=['text'],
                              owner=None, due_date=None, deadline=None, links=[], history=[], supersedes=[], superseded_by=None)
                registry[parent_id] = parent
                service.items._event(parent, 'created', by='user')
            for key in ids:
                task = registry[key]
                before = task.get('parent_task_id')
                if before == parent_id:
                    continue
                task['parent_task_id'] = parent_id
                service.items._event(task, 'parent_changed', changes={'parent_task_id': [before, parent_id]}, by='user',
                                     text=('Added to: ' + parent['text']) if parent else 'Detached from main task')
                if before in registry:
                    service.items._event(registry[before], 'subtask_removed', by='user', text=task['text'])
                if parent:
                    service.items._event(parent, 'subtask_added', by='user', text=task['text'])
            WorkGraph._activity(service.items.data, 'task_hierarchy_changed', request_id=operation, payload=payload,
                                parent_id=parent_id, item_ids=ids)
            service.items.save()
        except items.WorkItemConflict:
            raise
        except Exception:
            service.items.data = previous
            raise
        return dict(parent_id=parent_id, updated=ids)
