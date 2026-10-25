"""The "Prepare me" view: what to bring to the next meeting of a project or series.

Everything comes from saved data, not from a new AI run, so each line links to a meeting and a moment:
open tasks, questions without a decision, decisions in force, moments marked "check later",
and an agenda built from them.
"""
from __future__ import annotations

import datetime as dt

from .items import MATCH, similarity

RECENT_MEETINGS = 3
LIMIT = 5


def _date(meeting) -> str:
    return meeting.get('started_at') or meeting['created']


def build(meetings: list[dict], minutes: dict, registry: list[dict], markers: dict, today: dt.date, title: str) -> dict:
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
            due = item.get('due_date')
            tasks.append(dict(item_id=item['id'], text=item['text'], owner=item.get('owner'), deadline=item.get('deadline'),
                              due_date=due, overdue=bool(due and due < today.isoformat()),
                              due_soon=bool(due and today.isoformat() <= due <= soon), source=last_source(item)))
    tasks.sort(key=lambda task: (not task['overdue'], task['due_date'] or '9999', task['text'].casefold()))
    newest = lambda entry: entry['source']['meeting_date'] if entry['source'] else ''
    decisions = sorted((dict(item_id=item['id'], text=item['text'], source=last_source(item)) for item in in_scope
                        if item['kind'] == 'decision' and item['status'] == 'accepted'), key=newest, reverse=True)
    proposed = sorted((dict(item_id=item['id'], text=item['text'], source=last_source(item)) for item in in_scope
                       if item['kind'] == 'decision' and item['status'] == 'proposed'), key=newest, reverse=True)

    questions = []
    for meeting in reversed(meetings[-RECENT_MEETINGS:]):
        for field, kind in (('needs_decision', 'decide'), ('open_questions', 'discuss')):
            for entry in (minutes.get(meeting['id']) or {}).get(field, []):
                text = entry['text'] if isinstance(entry, dict) else str(entry)
                # A newer meeting asked the same thing already; keep the newest wording.
                if any(similarity(text, known['text']) >= MATCH for known in questions):
                    continue
                answer = next((d for d in decisions if d['source'] and d['source']['meeting_date'] > dates[meeting['id']]
                               and similarity(text, d['text']) >= MATCH), None)
                questions.append(dict(text=text, kind=kind, source=source(meeting['id'], entry.get('evidence_timestamp') if isinstance(entry, dict) else None),
                                      maybe_answered_by=answer))
    checks = []
    if meetings:
        last = meetings[-1]['id']
        checks = [dict(text=marker.get('note') or 'Marked "check later"', source=source(last, _stamp(marker['time'])))
                  for marker in markers.get(last, []) if marker.get('kind') == 'check']

    agenda = []
    for task in [t for t in tasks if t['overdue']]:
        agenda.append(dict(title='Overdue: ' + task['text'] + (f' ({task["owner"]})' if task['owner'] else ''), sources=[task['source']]))
    open_questions = [q for q in questions if not q['maybe_answered_by']]
    for question in [q for q in open_questions if q['kind'] == 'decide'][:LIMIT]:
        agenda.append(dict(title='Decide: ' + question['text'], sources=[question['source']]))
    for question in [q for q in open_questions if q['kind'] == 'discuss'][:LIMIT]:
        agenda.append(dict(title='Discuss: ' + question['text'], sources=[question['source']]))
    for task in [t for t in tasks if t['due_soon']][:LIMIT]:
        agenda.append(dict(title=f'Due by {task["due_date"]}: ' + task['text'], sources=[task['source']]))
    unclear = [t for t in tasks if not t['owner'] or not t['due_date']]
    if unclear:
        agenda.append(dict(title=f'Give an owner and a date to {len(unclear)} open task' + ('s' if len(unclear) > 1 else ''),
                           sources=[t['source'] for t in unclear[:3]]))
    if proposed:
        agenda.append(dict(title=f'Confirm {len(proposed)} proposed decision' + ('s' if len(proposed) > 1 else ''),
                           sources=[d['source'] for d in proposed[:3]]))
    for check in checks:
        agenda.append(dict(title='Check: ' + check['text'], sources=[check['source']]))
    agenda.append(dict(title='New tasks, owners and dates', sources=[]))

    return dict(title=title, meetings=[dict(id=m['id'], title=m['title'], date=_date(m)) for m in meetings],
                tasks=tasks, questions=questions, decisions=decisions[:10], proposed=proposed, checks=checks,
                agenda=agenda, markdown=markdown(title, today, agenda, tasks, questions, decisions[:10]))


def _stamp(seconds) -> str:
    seconds = max(0, int(seconds))
    return f'{seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02}'


def _cite(source) -> str:
    if not source:
        return ''
    return f' — {source["meeting_title"]}' + (f' {source["timestamp"]}' if source.get('timestamp') else '')


def markdown(title, today, agenda, tasks, questions, decisions) -> str:
    """Plain text to paste into a calendar invitation or a chat."""
    lines = [f'# {title} · {today.isoformat()}', '', '## Agenda']
    lines += [f'{number}. {entry["title"]}' for number, entry in enumerate(agenda, 1)]
    if tasks:
        lines += ['', '## Open tasks']
        lines += [f'- [ ] {t["text"]}' + (f' · {t["owner"]}' if t['owner'] else '') + (f' · due {t["due_date"]}' if t['due_date'] else '')
                  + _cite(t['source']) for t in tasks]
    if questions:
        lines += ['', '## Questions without a decision']
        lines += [f'- {q["text"]}' + _cite(q['source']) for q in questions]
    if decisions:
        lines += ['', '## Decisions in force']
        lines += [f'- {d["text"]}' + _cite(d['source']) for d in decisions]
    return '\n'.join(lines) + '\n'
