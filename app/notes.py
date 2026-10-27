"""Compare a new AI draft of meeting notes with the saved notes, and apply only the changes a person accepts.

Saved notes hold manual edits, checked statements and task status. A new AI run never replaces them;
it becomes a proposal that the person reviews change by change.
"""
from __future__ import annotations

import copy
import difflib
import re

from .meeting_types import SECTION_FIELDS

FIELDS = ('summary', 'decisions', 'next_steps', 'needs_decision', 'tasks', 'open_questions', 'observations', *SECTION_FIELDS)
TASK_DETAILS = ('owner', 'deadline', 'due_date')
SIMILAR = 0.6


def _text(field: str, item: dict) -> str:
    return item['task'] if field == 'tasks' else item['text']


def _key(text: str) -> str:
    return ' '.join(re.sub(r'[^\w\s]', ' ', text.casefold()).split())


def _task_details_differ(old: dict, new: dict) -> bool:
    # A detail the AI did not find is no reason to replace one that a person entered.
    return any(new.get(name) is not None and new.get(name) != old.get(name) for name in TASK_DETAILS)


def _change(field, kind, old_index, new_index, old, new):
    return dict(id=f'{field}:{kind}:{"-" if old_index is None else old_index}:{"-" if new_index is None else new_index}',
                field=field, kind=kind, current_index=old_index, proposed_index=new_index, current=old, proposed=new)


def changes(current: dict | None, proposed: dict) -> list[dict]:
    """Each difference as added, changed or removed. Items with the same text are unchanged."""
    result = []
    for field in FIELDS:
        old, new = (current or {}).get(field, []), proposed.get(field, [])
        old_left, new_left = list(range(len(old))), list(range(len(new)))
        for j in list(new_left):
            match = next((i for i in old_left if _key(_text(field, old[i])) == _key(_text(field, new[j]))), None)
            if match is None:
                continue
            old_left.remove(match)
            new_left.remove(j)
            if field == 'tasks' and _task_details_differ(old[match], new[j]):
                result.append(_change(field, 'changed', match, j, old[match], new[j]))
        pairs = sorted(((difflib.SequenceMatcher(None, _key(_text(field, old[i])), _key(_text(field, new[j]))).ratio(), i, j)
                        for i in old_left for j in new_left), reverse=True)
        for ratio, i, j in pairs:
            if ratio < SIMILAR:
                break
            if i in old_left and j in new_left:
                old_left.remove(i)
                new_left.remove(j)
                result.append(_change(field, 'changed', i, j, old[i], new[j]))
        result.extend(_change(field, 'added', None, j, None, new[j]) for j in new_left)
        result.extend(_change(field, 'removed', i, None, old[i], None) for i in old_left)
    return result


def apply(current: dict | None, proposed: dict, accepted) -> dict:
    """Saved notes plus the accepted changes. Task status stays; changed statements need a new check."""
    available = {change['id']: change for change in changes(current, proposed)}
    unknown = set(accepted) - set(available)
    if unknown:
        raise ValueError('These notes changed. Reload the meeting and review the new notes again.')
    result = copy.deepcopy(current or {field: [] for field in FIELDS})
    removed = {field: [] for field in FIELDS}
    for change in available.values():
        if change['id'] not in accepted:
            continue
        field, new = change['field'], copy.deepcopy(change['proposed'])
        if change['kind'] == 'added':
            result.setdefault(field, []).append(dict(new, review='ai'))
        elif change['kind'] == 'removed':
            removed[field].append(change['current_index'])
        else:
            item = result[field][change['current_index']]
            if field == 'tasks':
                item.update(task=new['task'], evidence_timestamp=new['evidence_timestamp'],
                            **{name: new[name] for name in TASK_DETAILS if new.get(name) is not None})
            else:
                item.update(text=new['text'], evidence_timestamp=new['evidence_timestamp'])
            item['review'] = 'ai'
    # Indices refer to the saved notes, so remove from the end after all replacements.
    for field, indices in removed.items():
        for index in sorted(indices, reverse=True):
            del result[field][index]
    return result
