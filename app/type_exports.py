"""The result of a meeting in the format of its type: a daily update for a chat, a postmortem document,
a summary that can go to a client, or a general summary.

Built only from saved notes and tasks, not from a new AI run. Private observations never appear here.
Task lines show the current state of the task (owner, date, status), not only what the meeting said.
"""
from __future__ import annotations

import re

from . import meeting_types


def _date(meeting) -> str:
    value = (meeting.get('started_at') or meeting.get('created') or '')[:10]
    return '.'.join(reversed(value.split('-'))) if value else ''


def _tasks(minutes, items):
    """Each task of the meeting with its current state from the task registry."""
    result = []
    for mention in minutes.get('tasks', []):
        item = items.get(mention.get('item_id')) or {}
        result.append(dict(item_id=mention.get('item_id'), text=item.get('text') or mention.get('task', ''),
                           owner=item.get('owner', mention.get('owner')), due_date=item.get('due_date', mention.get('due_date')),
                           status=item.get('status', mention.get('status', 'open'))))
    return result


def _bullets(entries, empty=None):
    lines = [f'- {entry["text"]}' for entry in entries]
    return lines or ([f'- {empty}'] if empty else [])


def _task_line(task):
    details = ' · '.join(filter(None, [task['owner'], task['due_date'] and 'до ' + task['due_date']]))
    return f'- [{"x" if task["status"] == "done" else " "}] {task["text"]}' + (f' — {details}' if details else '')


def _cell(value):
    return str(value or '—').replace('|', '\\|').replace('\n', ' ')


def daily(meeting, minutes, tasks):
    lines = [f'**Daily · {meeting["title"]} · {_date(meeting)}**']
    for key, title, empty in (('today', 'Днес', None), ('blockers', 'Блокери', 'Няма блокери'), ('coordination', 'Нужна координация', None)):
        entries = _bullets(minutes.get(key, []), empty)
        if entries:
            lines += ['', f'**{title}**', *entries]
    if tasks:
        lines += ['', '**Задачи**', *map(_task_line, tasks)]
    if minutes.get('decisions'):
        lines += ['', '**Решения**', *_bullets(minutes['decisions'])]
    return '\n'.join(lines) + '\n'


def postmortem(meeting, minutes, tasks, links):
    lines = [f'# Postmortem: {meeting["title"]}', '', f'Дата на прегледа: {_date(meeting)}']
    for key, title in (('summary', 'Резюме'), ('facts', 'Въздействие и факти'), ('incident_timeline', 'Хронология')):
        lines += ['', f'## {title}', *_bullets(minutes.get(key, []), 'Не е записано.')]
    lines += ['', '## Хипотези за причината', '',
              '> Хипотеза не е факт. „Проверено“ значи, че някой я сравни със записа, не че е потвърдена причина.', '']
    lines += [f'- {h["text"]}' + (' — проверено' if h.get('review') == 'verified' else ' — непроверено')
              for h in minutes.get('hypotheses', [])] or ['- Няма записани хипотези.']
    lines += ['', '## Коригиращи действия', '', '| Действие | Отговорник | Срок | Статус | GitHub |', '|---|---|---|---|---|']
    for task in tasks:
        issues = ', '.join(f'[{link["repository"]}#{link["number"]}]({link["url"]})' for link in links.get(task['item_id'], []))
        lines.append('| ' + ' | '.join(_cell(v) for v in (task['text'], task['owner'], task['due_date'],
                                                            'Изпълнено' if task['status'] == 'done' else 'Отворено', issues)) + ' |')
    if not tasks:
        lines.append('| Няма записани действия | — | — | — | — |')
    for key, title in (('decisions', 'Решения'), ('open_questions', 'Отворени въпроси')):
        if minutes.get(key):
            lines += ['', f'## {title}', *_bullets(minutes[key])]
    lines += ['', '## Поуки', '', 'Попълнете след прегледа: какво работи добре и какво променяме.']
    return '\n'.join(lines) + '\n'


def client(meeting, minutes):
    lines = [f'# {meeting["title"]} · {_date(meeting)}']
    for key, title in (('summary', 'Резюме'), ('decisions', 'Решения'), ('client_requests', 'Вашите искания'),
                       ('commitments', 'Нашите ангажименти'), ('next_steps', 'Следващи стъпки')):
        if minutes.get(key):
            lines += ['', f'## {title}', *_bullets(minutes[key])]
    return '\n'.join(lines) + '\n'


def general(meeting, minutes, tasks, definition):
    lines = [f'# {meeting["title"]} · {_date(meeting)}']
    sections = [('summary', 'Резюме')] + [(s['key'], s['title_bg']) for s in definition['sections']] + [('decisions', 'Решения')]
    for key, title in sections:
        if minutes.get(key):
            lines += ['', f'## {title}', *_bullets(minutes[key])]
    if tasks:
        lines += ['', '## Задачи', *map(_task_line, tasks)]
    for key, title in (('next_steps', 'Следващи стъпки'), ('open_questions', 'Отворени въпроси')):
        if minutes.get(key):
            lines += ['', f'## {title}', *_bullets(minutes[key])]
    return '\n'.join(lines) + '\n'


def render(meeting, minutes, items, links) -> dict:
    """{title, filename, markdown, note} for the type of the meeting. links: {item ID: [GitHub links]}."""
    definition = meeting_types.of(meeting)
    tasks = _tasks(minutes, items)
    style = definition['id']
    if style == 'daily':
        markdown, note = daily(meeting, minutes, tasks), 'Short text for a chat. Private observations are not included.'
    elif style == 'incident':
        markdown, note = postmortem(meeting, minutes, tasks, links), 'Hypotheses stay marked as not confirmed. Private observations are not included.'
    elif style == 'client':
        markdown = client(meeting, minutes)
        note = 'Check the text before you send it. Private observations, internal questions, concerns and tasks are not included.'
    else:
        markdown, note = general(meeting, minutes, tasks, definition), 'Private observations are not included.'
    slug = re.sub(r'[^\w]+', '-', definition['export'].lower()).strip('-') or 'summary'
    return dict(title=definition['export'], filename=f'{slug}.md', markdown=markdown, note=note)
