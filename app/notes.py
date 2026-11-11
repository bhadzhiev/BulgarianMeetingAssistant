"""Compare a new AI draft of meeting notes with the saved notes, and apply only the changes a person accepts.

Saved notes hold manual edits, checked statements and task status. A new AI run never replaces them;
it becomes a proposal that the person reviews change by change.
"""
from __future__ import annotations

import copy
import difflib
import re

from .meeting_types import SECTION_FIELDS

FIELDS = ('summary', 'decisions', 'updates', 'next_steps', 'needs_decision', 'tasks', 'open_questions', 'observations', *SECTION_FIELDS)
# A new description is a change a person can accept; an empty one never clears what the task has.
TASK_DETAILS = ('details', 'owner', 'deadline', 'due_date')
SIMILAR = 0.6
# Two statements of the same moment (within NEAR seconds) need less similar words to be one statement.
SAME_MOMENT = 0.4
NEAR = 10


def _seconds(stamp):
    try:
        h, m, s = (int(part) for part in str(stamp).split(':'))
        return h * 3600 + m * 60 + s
    except (TypeError, ValueError):
        return None


def _near(old, new):
    a, b = _seconds(old.get('evidence_timestamp')), _seconds(new.get('evidence_timestamp'))
    return a is not None and b is not None and abs(a - b) <= NEAR


def _text(field: str, item: dict) -> str:
    return item['task'] if field == 'tasks' else item['text']


def _key(text: str) -> str:
    return ' '.join(re.sub(r'[^\w\s]', ' ', text.casefold()).split())


def _source_differs(old: dict, new: dict) -> bool:
    """The same statement with another moment or another exact quote. A quote the AI did not find changes nothing."""
    return (new.get('evidence_timestamp') is not None and new.get('evidence_timestamp') != old.get('evidence_timestamp')
            or new.get('quote') is not None and new.get('quote') != old.get('quote'))


def _task_details_differ(old: dict, new: dict) -> bool:
    # A detail the AI did not find is no reason to replace one that a person entered.
    return any(new.get(name) is not None and new.get(name) != old.get(name) for name in TASK_DETAILS)


def _change(field, kind, old_index, new_index, old, new):
    return dict(id=f'{field}:{kind}:{"-" if old_index is None else old_index}:{"-" if new_index is None else new_index}',
                field=field, kind=kind, current_index=old_index, proposed_index=new_index, current=old, proposed=new)


def changes(current: dict | None, proposed: dict) -> list[dict]:
    """Each difference as added, changed, source (same words, new moment or quote) or removed."""
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
            elif _source_differs(old[match], new[j]):
                # The words stay; the moment or the quote that proves them is new. A person sees it and chooses.
                result.append(_change(field, 'source', match, j, old[match], new[j]))
        pairs = sorted(((difflib.SequenceMatcher(None, _key(_text(field, old[i])), _key(_text(field, new[j]))).ratio(), i, j)
                        for i in old_left for j in new_left), reverse=True)
        for ratio, i, j in pairs:
            if ratio < SIMILAR:
                break
            if i in old_left and j in new_left:
                old_left.remove(i)
                new_left.remove(j)
                result.append(_change(field, 'changed', i, j, old[i], new[j]))
        # A reworded statement of the same moment is the same statement: it is changed, not added next to the old one.
        # Without this, accepting the additions and not the removals kept two versions of one thought.
        pairs = sorted(((difflib.SequenceMatcher(None, _key(_text(field, old[i])), _key(_text(field, new[j]))).ratio(), i, j)
                        for i in old_left for j in new_left if _near(old[i], new[j])), reverse=True)
        for ratio, i, j in pairs:
            if ratio < SAME_MOMENT:
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
        elif change['kind'] == 'source':
            item = result[field][change['current_index']]
            item.update(evidence_timestamp=new.get('evidence_timestamp', item.get('evidence_timestamp')), quote=new.get('quote', item.get('quote')))
            item['review'] = 'ai'
        else:
            item = result[field][change['current_index']]
            # The quote proves the statement: a new statement takes its own quote, or none. The old quote proved the old words.
            item['quote'] = new.get('quote')
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


def name_speakers(minutes, renames):
    """The notes with each named speaker label (SPEAKER_00) replaced by the name, without AI.

    Only the written fields change: statement text, task text and owner. Quotes keep the words that were said.
    Returns a new dict, or None when nothing changed.
    """
    import copy
    import re
    labels = {old: new for old, new in (renames or {}).items() if isinstance(old, str) and re.fullmatch(r'SPEAKER[ _-]?\d+', old.strip(), re.I) and new}
    if not isinstance(minutes, dict) or not labels:
        return None
    pattern = re.compile(r'(?<![\w])(' + '|'.join(re.escape(old) for old in sorted(labels, key=len, reverse=True)) + r')(?![\w])')
    result, changed = copy.deepcopy(minutes), False
    for field in FIELDS:
        for entry in result.get(field) or []:
            if not isinstance(entry, dict):
                continue
            for key in ('text', 'task', 'owner'):
                value = entry.get(key)
                if isinstance(value, str) and pattern.search(value):
                    entry[key] = pattern.sub(lambda m: labels[m.group(1)], value)
                    changed = True
    return result if changed else None
