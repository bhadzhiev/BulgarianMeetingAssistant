"""Tasks by email: one draft for one or more tasks, saved as a Gmail draft.

Atlanta never sends the email. The person opens the Gmail draft, checks it and sends it from Gmail.
A saved draft marks each task (email_draft) and adds an entry to the history of each task.
"""
from __future__ import annotations

import datetime as dt

from . import items
from .followup_email import PLACEHOLDER, addresses, clean, draft_url, mime

MAX_TASKS = 100
# A task in the email shows up to this many quotes and history lines; a long quote is cut.
MAX_QUOTES = 3
MAX_HISTORY = 8
QUOTE_CHARS = 300
# The email text limit is 20000 characters. Above this length, the tasks lose their quotes and history.
FULL_TEXT_CHARS = 18000
STATES = dict(todo='за изпълнение', in_progress='в процес', waiting='чака', done='готова', cancelled='отказана')
PROVIDERS = dict(gmail='Gmail', chat='Google Chat', github='GitHub', report='отчет за хранилище', manual='ваш текст')
# The note at the end shows that Atlanta made the draft. A saved draft always has it.
FOOTER = '—\nГенерирано от Atlanta'


def _date(value):
    try:
        return dt.date.fromisoformat(value).strftime('%d.%m.%Y')
    except (TypeError, ValueError):
        return ''


def _ids(body):
    ids = body.get('item_ids')
    if ids is None and body.get('item_id') is not None:
        ids = [body['item_id']]
    if not isinstance(ids, list) or not 1 <= len(ids) <= MAX_TASKS or not all(isinstance(i, str) for i in ids):
        raise ValueError(f'Choose 1 to {MAX_TASKS} tasks')
    if len(set(ids)) != len(ids):
        raise ValueError('Choose each task once')
    return ids


def _tasks(service, ids):
    with service.lock, service.items.lock:
        result = []
        for item_id in ids:
            item = service.items.items.get(item_id)
            if not item or item.get('kind') != 'task':
                raise ValueError('A chosen task no longer exists. Reload the list and try again.')
            if item.get('acceptance_state') == 'proposed':
                raise ValueError('Accept the task before you send it by email: ' + item['text'][:80])
            task = dict(item)
            # The saved quotes, with their sources, so the email can show where the task came from.
            graph = service.items.data
            task['_evidence'] = [dict(evidence, source=dict(graph.get('sources', {}).get(evidence.get('source_id')) or {}))
                                 for evidence in (graph.get('source_evidence', {}).get(key) for key in item.get('source_evidence') or [])
                                 if evidence]
            result.append(task)
        return result


def _owner(service, item):
    person, _ = service.people.owner_of(item)
    if person:
        return person
    owner = (item.get('owner') or '').strip()
    return None if not owner or PLACEHOLDER.fullmatch(owner) else dict(id=None, name=owner)


def _meeting(service, item):
    for link in item.get('links') or []:
        if link.get('detached'):
            continue
        try:
            meeting = service.library.get(link['meeting_id'])
        except (OSError, ValueError, KeyError):
            continue
        when = meeting.get('started_at') or meeting.get('created') or ''
        return meeting.get('title') or '', _date(when[:10])
    return '', ''


def recipients(service, tasks):
    """Every person with an email. The owners and the others on the tasks come first and are preselected."""
    involved = set()
    for item in tasks:
        owner = _owner(service, item)
        involved.update(pid for pid in [owner and owner.get('id'), *(item.get('assignee_person_ids') or [])] if pid)
    rows = [dict(person_id=p['id'], name=p['name'], email=email, involved=p['id'] in involved)
            for p in service.people.list() for email in p.get('emails') or []]
    return sorted(rows, key=lambda r: (not r['involved'], r['name'].casefold(), r['email']))


def _meeting_label(service, meeting_id):
    try:
        meeting = service.library.get(meeting_id)
    except (OSError, ValueError, KeyError, TypeError):
        return None
    day = _date((meeting.get('started_at') or meeting.get('created') or '')[:10])
    return '„' + (meeting.get('title') or 'Среща') + '“' + (' на ' + day if day else '')


def _short(value):
    value = ' '.join(str(value or '').split())
    return value if len(value) <= QUOTE_CHARS else value[:QUOTE_CHARS - 1].rstrip() + '…'


def _quotes(service, item):
    """The words the task came from. The quotes saved with the task come first; they are the exact words
    that the notes cite. A meeting moment without a saved quote gives the transcript words at that moment."""
    from meeting_assistant import quote_span
    from .live import read_json
    from .transcripts import segment_at
    rows, seen, moments = [], set(), set()

    def add(quote, where):
        quote = _short(quote)
        if quote and quote.casefold() not in seen:
            seen.add(quote.casefold())
            rows.append('„' + quote + '“' + (' (' + where + ')' if where else ''))

    def meeting_place(meeting_id, stamp):
        label = _meeting_label(service, meeting_id)
        return 'срещата ' + label + (', ' + stamp if stamp else '') if label else ''

    for evidence in item.get('_evidence') or []:
        locator, provider = evidence.get('locator') or {}, (evidence.get('source') or {}).get('provider')
        if provider == 'meeting' or locator.get('meeting_id'):
            moments.add((locator.get('meeting_id'), locator.get('evidence_timestamp')))
            add(evidence.get('quote'), meeting_place(locator.get('meeting_id'), locator.get('evidence_timestamp')))
        else:
            add(evidence.get('quote'), PROVIDERS.get(provider, ''))
    for link in item.get('links') or []:
        stamp = link.get('evidence_timestamp')
        if link.get('detached') or not stamp or (link.get('meeting_id'), stamp) in moments:
            continue
        place = meeting_place(link.get('meeting_id'), stamp)
        if not place:
            continue
        try:
            segments = read_json(service.library.directory(link['meeting_id']) / 'transcript.json', [])
            span = quote_span(segments, stamp)
            words = (' '.join(row.get('text', '') for row in segments[span[0]:span[1]]) if span
                     else (segment_at(segments, stamp) or {}).get('text'))
        except (OSError, ValueError, KeyError, TypeError):
            words = None
        add(words, place)
    return rows[:MAX_QUOTES]


def _pair(changes, key):
    value = changes.get(key)
    return value if isinstance(value, list) and len(value) == 2 and value[0] != value[1] else None


def _history(service, item):
    """The changes a reader cares about: creation, meetings, progress, owner, due date, state. Oldest first."""
    rows, meetings, created = [], set(), None
    for event in sorted(item.get('history') or [], key=lambda e: e.get('at') or ''):
        kind, day = event.get('event'), _date((event.get('at') or '')[:10])
        changes = event.get('changes') if isinstance(event.get('changes'), dict) else {}
        lines = []
        if kind == 'created':
            if created is not None:
                continue
            meetings.add(event.get('meeting_id'))
            label = _meeting_label(service, event.get('meeting_id')) if event.get('meeting_id') else None
            created = (day + ' · ' if day else '') + 'Създадена' + (' на срещата ' + label if label else '')
            continue
        elif kind in {'discussed', 'duplicate'} and event.get('meeting_id') not in meetings:
            # The same meeting again is a new run of its notes, not a new discussion.
            meetings.add(event.get('meeting_id'))
            label = _meeting_label(service, event.get('meeting_id'))
            if label:
                lines.append('Обсъдена отново на срещата ' + label)
        elif kind == 'progress_update' and (event.get('text') or '').strip():
            lines.append('Напредък: ' + _short(event['text']))
        elif kind == 'merged':
            lines.append('Обединена с друга задача')
        if kind in {'changed', 'confirmed', 'meeting_review_edit'}:
            owner = _pair(changes, 'owner')
            if owner and all(isinstance(name, str) and name for name in owner):
                lines.append('Отговорник: ' + owner[0] + ' → ' + owner[1])
            due = _pair(changes, 'due_date')
            if due:
                lines.append('Срок: ' + (_date(due[0]) or 'без срок') + ' → ' + (_date(due[1]) or 'без срок'))
            state = _pair(changes, 'workflow_state') or _pair(changes, 'status')
            if state and state[1] in STATES:
                lines.append('Статус: ' + STATES[state[1]])
        rows += [(day + ' · ' if day else '') + line for line in lines]
    # The creation stays first; a long history keeps its newest changes.
    return ([created] if created else []) + rows[-(MAX_HISTORY - bool(created)):]


def _block(service, item, number=None, full=True):
    owner = _owner(service, item)
    title, day = _meeting(service, item)
    lines = [(f'{number}. ' if number else '') + item['text']]
    if (item.get('details') or '').strip():
        lines += ['Подробности: ' + item['details'].strip()]
    if (item.get('completion_criteria') or '').strip():
        lines += ['Очакван резултат: ' + item['completion_criteria'].strip()]
    lines += ['Отговорник: ' + (owner['name'] if owner else 'без отговорник'),
              'Срок: ' + (_date(item.get('due_date')) or 'без срок')]
    state = item.get('workflow_state') or ('done' if item.get('status') == 'done' else 'todo')
    lines.append('Статус: ' + STATES.get(state, state))
    projects = [p['name'] for p in (service.projects.get('projects', key) for key in item.get('project_ids') or []) if p]
    if projects:
        lines.append(('Проекти: ' if len(projects) > 1 else 'Проект: ') + ', '.join(projects))
    if title:
        lines.append('От срещата: „' + title + '“' + (' на ' + day if day else ''))
    if full:
        quotes, history = _quotes(service, item), _history(service, item)
        if quotes:
            lines += ['', 'Цитати:'] + ['- ' + q for q in quotes]
        if history:
            lines += ['', 'История:'] + ['- ' + h for h in history]
    return lines


def template(service, tasks):
    """The email text from the task fields, the saved quotes and the task history. No AI."""
    def text(full):
        if len(tasks) == 1:
            lines = ['Здравейте,', '', 'Изпращам ви задача:', ''] + _block(service, tasks[0], full=full)
        else:
            lines = ['Здравейте,', '', f'Изпращам ви {len(tasks)} задачи:']
            for number, item in enumerate(tasks, 1):
                lines += [''] + _block(service, item, number, full)
        return '\n'.join(lines + ['', FOOTER])
    body = text(True)
    if len(body) > FULL_TEXT_CHARS:
        body = text(False)  # Too long for one email; the task fields stay.
    if len(tasks) == 1:
        subject = 'Задача: ' + ' '.join(tasks[0]['text'].split())
    else:
        subject = f'Задачи ({len(tasks)}): ' + '; '.join(' '.join(t['text'].split()) for t in tasks[:3])
    return dict(subject=subject[:200], body=body)


def _previous(tasks, account):
    """The draft to update: only when every chosen task has the same draft of this account."""
    drafts = [t.get('email_draft') for t in tasks]
    first = drafts[0]
    if first and first.get('account') == account and all(d and d.get('draft_id') == first.get('draft_id') for d in drafts):
        return first
    return None


def prepare(service, body):
    """Open the editor: the plain text, the recipients and the Gmail state."""
    tasks = _tasks(service, _ids(body))
    status = service.google.status()
    previous = _previous(tasks, status.get('account'))
    return dict(template(service, tasks), tasks=[dict(id=t['id'], text=t['text']) for t in tasks],
                recipients=recipients(service, tasks),
                draft=dict(previous, url=draft_url(previous['account'], previous.get('message_id'))) if previous else None,
                gmail=dict(account=status.get('account', ''), drafts=bool(status.get('capabilities', {}).get('gmail_compose'))))


def save_draft(service, body):
    """Create the Gmail draft, or update the one these tasks already share. Then mark each task."""
    ids = _ids(body)
    tasks = _tasks(service, ids)
    to = addresses(body.get('to'))
    content = clean(dict(subject=body.get('subject'), body=body.get('body')))
    if FOOTER not in content['body']:
        content['body'] += '\n\n' + FOOTER
    raw = mime(to, content['subject'], content['body'])
    account = service.google.status().get('account')
    previous = _previous(tasks, account)
    draft = service.google.gmail_draft(raw, previous['draft_id'] if previous else None, expected_account=account)
    saved = dict(draft_id=draft['id'], message_id=draft.get('message', {}).get('id'), account=account, to=to,
                 subject=content['subject'], task_count=len(ids),
                 saved_at=dt.datetime.now().astimezone().isoformat(timespec='seconds'))
    updated = bool(previous) and previous['draft_id'] == saved['draft_id']
    text = (('Draft updated' if updated else 'Draft created') + ' for ' + ', '.join(to) + ' · ' + content['subject']
            + (f' · {len(ids)} tasks in one email' if len(ids) > 1 else ''))
    with service.lock, service.items.lock:
        marked, before = [], {}
        try:
            for item_id in ids:
                task = service.items.items.get(item_id)
                if not task:
                    continue  # Deleted while Gmail saved the draft; the other tasks still get the mark.
                before[item_id] = task.get('email_draft')
                task['email_draft'] = saved
                task['history'].append(dict(at=items.now(), event='email_draft', by='user', meeting_id=None,
                                            changes={}, text=text))
                marked.append(item_id)
            service.items.save()
        except items.WorkItemConflict:
            raise  # Registry.save already reloaded the winning revision
        except Exception:
            for item_id in marked:
                task = service.items.items[item_id]
                task['history'].pop()
                if before[item_id] is None:
                    task.pop('email_draft', None)
                else:
                    task['email_draft'] = before[item_id]
            raise
    return dict(saved, updated=updated, marked=marked, url=draft_url(account, saved['message_id']))
