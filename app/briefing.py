"""The "Prepare me" view: what to bring to the next meeting of a project or series.

Everything comes from saved data, not from a new AI run, so each line links to a meeting and a moment:
open tasks, questions without a decision, decisions in force, moments marked "check later",
and an agenda built from them. The meeting type of a series changes the agenda: a daily starts with the
blockers of the last daily and with stalled tasks; an incident review starts with hypotheses to confirm
and corrective actions; a sprint review starts with the work done since the last review. An own template
uses the agenda of the built-in type that it names.
"""
from __future__ import annotations

import datetime as dt

from . import meeting_types
from .items import MATCH, similarity

RECENT_MEETINGS = 3
LIMIT = 5
STALLED_DAYS = 3


def _date(meeting) -> str:
    return meeting.get('started_at') or meeting['created']


def _last_change(item) -> str:
    return max([item.get('created') or ''] + [event.get('at') or '' for event in item.get('history', [])])[:10]


def _done_at(item) -> str:
    """The day a person marked the task done, or an empty string."""
    days = [event.get('at') or '' for event in item.get('history', []) if (event.get('changes') or {}).get('status', [None, None])[-1] == 'done']
    return max(days)[:10] if days else ''


def build(meetings: list[dict], minutes: dict, registry: list[dict], markers: dict, today: dt.date, title: str,
          meeting_type: str | dict = meeting_types.DEFAULT) -> dict:
    definition = meeting_type if isinstance(meeting_type, dict) else meeting_types.definition(meeting_type)
    style = definition['style']
    meetings = sorted(meetings, key=_date)
    ids, dates = {m['id'] for m in meetings}, {m['id']: _date(m) for m in meetings}
    titles = {m['id']: m['title'] for m in meetings}

    def source(meeting_id, stamp=None):
        return dict(meeting_id=meeting_id, meeting_title=titles[meeting_id], meeting_date=dates[meeting_id], timestamp=stamp)

    def last_source(item):
        links = sorted((link for link in item['links'] if link['meeting_id'] in ids), key=lambda link: dates[link['meeting_id']])
        return source(links[-1]['meeting_id'], links[-1].get('evidence_timestamp')) if links else None

    in_scope = [item for item in registry if any(link['meeting_id'] in ids for link in item['links'])]
    soon = (today + dt.timedelta(days=7)).isoformat()
    tasks = []
    for item in in_scope:
        if item['kind'] == 'task' and item['status'] == 'open':
            due, changed = item.get('due_date'), _last_change(item)
            idle = (today - dt.date.fromisoformat(changed)).days if changed else 0
            tasks.append(dict(item_id=item['id'], text=item['text'], owner=item.get('owner'), deadline=item.get('deadline'),
                              due_date=due, overdue=bool(due and due < today.isoformat()),
                              due_soon=bool(due and today.isoformat() <= due <= soon), idle_days=idle, source=last_source(item)))
    tasks.sort(key=lambda task: (not task['overdue'], task['due_date'] or '9999', task['text'].casefold()))
    newest = lambda entry: entry['source']['meeting_date'] if entry['source'] else ''
    decisions = sorted((dict(item_id=item['id'], text=item['text'], source=last_source(item)) for item in in_scope
                        if item['kind'] == 'decision' and item['status'] == 'accepted'), key=newest, reverse=True)
    proposed = sorted((dict(item_id=item['id'], text=item['text'], source=last_source(item)) for item in in_scope
                       if item['kind'] == 'decision' and item['status'] == 'proposed'), key=newest, reverse=True)

    by_id = {item['id']: item for item in in_scope}
    questions = []
    for meeting in reversed(meetings[-RECENT_MEETINGS:]):
        for field, kind in (('needs_decision', 'decide'), ('open_questions', 'discuss')):
            for entry in (minutes.get(meeting['id']) or {}).get(field, []):
                text = entry['text'] if isinstance(entry, dict) else str(entry)
                # A newer meeting asked the same thing already; keep the newest wording.
                if any(similarity(text, known['text']) >= MATCH for known in questions):
                    continue
                stamp = entry.get('evidence_timestamp') if isinstance(entry, dict) else None
                answer = next((d for d in decisions if similarity(text, d['text']) >= MATCH
                               and any(_after(link, meeting['id'], stamp, dates) for link in by_id[d['item_id']]['links'] if link['meeting_id'] in ids)), None)
                questions.append(dict(text=text, kind=kind, source=source(meeting['id'], stamp), maybe_answered_by=answer))
    checks = []
    if meetings:
        last = meetings[-1]['id']
        checks = [dict(text=marker.get('note') or 'Marked "check later"', source=source(last, _stamp(marker['time'])))
                  for marker in markers.get(last, []) if marker.get('kind') == 'check']

    # The type sections of the last meeting, for example the blockers of the last daily.
    sections = []
    if meetings:
        last = meetings[-1]['id']
        for section in definition['sections']:
            entries = [dict(text=entry['text'], source=source(last, entry.get('evidence_timestamp')))
                       for entry in (minutes.get(last) or {}).get(section['key'], []) if isinstance(entry, dict)]
            if entries:
                sections.append(dict(key=section['key'], title=section['title'], items=entries))
    from_last = {section['key']: section['items'] for section in sections}
    for task in tasks:
        task['stalled'] = task['idle_days'] >= STALLED_DAYS

    agenda = []
    add = lambda text, entries: agenda.append(dict(title=text, sources=entries))
    owner = lambda task: f' ({task["owner"]})' if task['owner'] else ''
    open_questions = [q for q in questions if not q['maybe_answered_by']]
    for task in [t for t in tasks if t['overdue']]:
        add('Overdue: ' + task['text'] + owner(task), [task['source']])
    last_date = dates[meetings[-1]['id']][:10] if meetings else ''
    done = [dict(item_id=item['id'], text=item['text'], owner=item.get('owner'), source=last_source(item)) for item in in_scope
            if item['kind'] == 'task' and item['status'] == 'done' and _done_at(item) >= last_date]
    decide = [q for q in open_questions if q['kind'] == 'decide'][:LIMIT]
    if style == 'daily':
        for entry in from_last.get('blockers', []):
            add('Blocker from the last daily: ' + entry['text'], [entry['source']])
        for entry in from_last.get('coordination', []):
            add('Coordinate: ' + entry['text'], [entry['source']])
        for task in [t for t in tasks if t['stalled'] and not t['overdue']][:LIMIT]:
            add(f'No change for {task["idle_days"]} days: ' + task['text'] + owner(task), [task['source']])
        for task in [t for t in tasks if t['due_date'] == today.isoformat()]:
            add('Due today: ' + task['text'] + owner(task), [task['source']])
        for question in decide:
            add('Decide: ' + question['text'], [question['source']])
        add('Plans for today and new blockers', [])
    elif style == 'sprint_review':
        for task in done[:LIMIT * 2]:
            add('Show: ' + task['text'] + owner(task), [task['source']])
        for entry in from_last.get('carry_over', []):
            add('Not finished last time: ' + entry['text'], [entry['source']])
        for task in [t for t in tasks if not t['overdue']][:LIMIT]:
            add('Still open: ' + task['text'] + owner(task), [task['source']])
        add('Feedback and new requests', [])
    elif style == 'planning':
        for entry in from_last.get('goals', []):
            add('Last goal: ' + entry['text'], [entry['source']])
        unclear = [t for t in tasks if not t['owner'] or not t['due_date']]
        for task in unclear[:LIMIT * 2]:
            add('Plan: ' + task['text'] + (' · needs an owner' if not task['owner'] else '') + (' · needs a date' if not task['due_date'] else ''), [task['source']])
        for question in decide:
            add('Decide: ' + question['text'], [question['source']])
        if proposed:
            add(f'Confirm {len(proposed)} proposed decision' + ('s' if len(proposed) > 1 else ''), [d['source'] for d in proposed[:3]])
        add('Goals, capacity and risks for the period', [])
    elif style == 'cross_team':
        for entry in from_last.get('dependencies', []):
            add('Dependency: ' + entry['text'], [entry['source']])
        for entry in from_last.get('handoffs', []):
            add('Check the handoff: ' + entry['text'], [entry['source']])
        for entry in from_last.get('escalations', []):
            add('Escalated: ' + entry['text'], [entry['source']])
        for question in decide:
            add('Decide: ' + question['text'], [question['source']])
        add('New dependencies, owners and dates', [])
    elif style == 'client':
        for entry in from_last.get('commitments', []):
            add('Our commitment: ' + entry['text'], [entry['source']])
        for entry in from_last.get('client_requests', []):
            add('Answer the request: ' + entry['text'], [entry['source']])
        for task in [t for t in tasks if t['due_soon'] and not t['overdue']][:LIMIT]:
            add(f'Due by {task["due_date"]}: ' + task['text'], [task['source']])
        for question in [q for q in open_questions if q['kind'] == 'discuss'][:LIMIT]:
            add('Discuss: ' + question['text'], [question['source']])
        add('Next steps and dates to agree with the client', [])
    elif style == 'incident':
        for entry in from_last.get('hypotheses', []):
            add('Confirm or reject: ' + entry['text'], [entry['source']])
        for task in [t for t in tasks if not t['overdue']][:LIMIT * 2]:
            add('Corrective action: ' + task['text'] + owner(task) + (f' · due {task["due_date"]}' if task['due_date'] else ''), [task['source']])
        for question in open_questions[:LIMIT]:
            add(('Decide: ' if question['kind'] == 'decide' else 'Discuss: ') + question['text'], [question['source']])
        for check in checks:
            add('Check: ' + check['text'], [check['source']])
        add('New corrective actions, owners and dates', [])
        add('What we learned and what changes', [])
    else:
        for question in decide:
            add('Decide: ' + question['text'], [question['source']])
        for question in [q for q in open_questions if q['kind'] == 'discuss'][:LIMIT]:
            add('Discuss: ' + question['text'], [question['source']])
        for task in [t for t in tasks if t['due_soon']][:LIMIT]:
            add(f'Due by {task["due_date"]}: ' + task['text'], [task['source']])
        unclear = [t for t in tasks if not t['owner'] or not t['due_date']]
        if unclear:
            add(f'Give an owner and a date to {len(unclear)} open task' + ('s' if len(unclear) > 1 else ''), [t['source'] for t in unclear[:3]])
        if proposed:
            add(f'Confirm {len(proposed)} proposed decision' + ('s' if len(proposed) > 1 else ''), [d['source'] for d in proposed[:3]])
        for check in checks:
            add('Check: ' + check['text'], [check['source']])
        add('New tasks, owners and dates', [])

    return dict(title=title, meeting_type=definition['id'], done=done, meetings=[dict(id=m['id'], title=m['title'], date=_date(m)) for m in meetings],
                tasks=tasks, questions=questions, decisions=decisions[:10], proposed=proposed, checks=checks, sections=sections,
                agenda=agenda, markdown=markdown(title, today, agenda, tasks, questions, decisions[:10], sections))


def _seconds(stamp):
    try:
        hours, minutes, seconds = (int(part) for part in stamp.split(':'))
        return hours * 3600 + minutes * 60 + seconds
    except (AttributeError, ValueError):
        return None


def _after(link, meeting_id, stamp, dates) -> bool:
    """A decision mention comes after a question: a later meeting, or later in the same meeting.

    In the same meeting a mention without a time counts as after; the decision was made there.
    """
    if link['meeting_id'] != meeting_id:
        return dates[link['meeting_id']] > dates[meeting_id]
    asked, decided = _seconds(stamp), _seconds(link.get('evidence_timestamp'))
    return asked is None or decided is None or decided >= asked


def _stamp(seconds) -> str:
    seconds = max(0, int(seconds))
    return f'{seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02}'


def _cite(source) -> str:
    if not source:
        return ''
    return f' — {source["meeting_title"]}' + (f' {source["timestamp"]}' if source.get('timestamp') else '')


def markdown(title, today, agenda, tasks, questions, decisions, sections=()) -> str:
    """Plain text to paste into a calendar invitation or a chat."""
    lines = [f'# {title} · {today.isoformat()}', '', '## Agenda']
    lines += [f'{number}. {entry["title"]}' for number, entry in enumerate(agenda, 1)]
    for section in sections:
        lines += ['', f'## {section["title"]} · last meeting']
        lines += [f'- {entry["text"]}' + _cite(entry['source']) for entry in section['items']]
    if tasks:
        lines += ['', '## Open tasks']
        lines += [f'- [ ] {t["text"]}' + (f' · {t["owner"]}' if t['owner'] else '') + (f' · due {t["due_date"]}' if t['due_date'] else '')
                  + _cite(t['source']) for t in tasks]
    unresolved = [q for q in questions if not q['maybe_answered_by']]
    if unresolved:
        lines += ['', '## Questions without a decision']
        lines += [f'- {q["text"]}' + _cite(q['source']) for q in unresolved]
    answered = [q for q in questions if q['maybe_answered_by']]
    if answered:
        lines += ['', '## Questions that a decision may answer']
        lines += [f'- {q["text"]} → {q["maybe_answered_by"]["text"]}' + _cite(q['source']) for q in answered]
    if decisions:
        lines += ['', '## Decisions in force']
        lines += [f'- {d["text"]}' + _cite(d['source']) for d in decisions]
    return '\n'.join(lines) + '\n'
