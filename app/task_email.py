"""Tasks by email: one draft for one or more tasks, saved as a Gmail draft.

Atlanta never sends the email. The person opens the Gmail draft, checks it and sends it from Gmail.
A saved draft marks each task (email_draft) and adds an entry to the history of each task.
"""
from __future__ import annotations

import datetime as dt

from . import items
from .followup_email import PLACEHOLDER, addresses, clean, draft_url, mime

MAX_TASKS = 100
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
            result.append(dict(item))
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


def _block(service, item, number=None):
    owner = _owner(service, item)
    title, day = _meeting(service, item)
    lines = [(f'{number}. ' if number else '') + item['text']]
    if (item.get('details') or '').strip():
        lines += ['Подробности: ' + item['details'].strip()]
    if (item.get('completion_criteria') or '').strip():
        lines += ['Очакван резултат: ' + item['completion_criteria'].strip()]
    lines += ['Отговорник: ' + (owner['name'] if owner else 'без отговорник'),
              'Срок: ' + (_date(item.get('due_date')) or 'без срок')]
    if title:
        lines.append('От срещата: „' + title + '“' + (' на ' + day if day else ''))
    return lines


def template(service, tasks):
    """The email text from the task fields only. No AI."""
    if len(tasks) == 1:
        lines = ['Здравейте,', '', 'Изпращам ви задача:', ''] + _block(service, tasks[0])
        subject = 'Задача: ' + ' '.join(tasks[0]['text'].split())
    else:
        lines = ['Здравейте,', '', f'Изпращам ви {len(tasks)} задачи:']
        for number, item in enumerate(tasks, 1):
            lines += [''] + _block(service, item, number)
        subject = f'Задачи ({len(tasks)}): ' + '; '.join(' '.join(t['text'].split()) for t in tasks[:3])
    return dict(subject=subject[:200], body='\n'.join(lines + ['', FOOTER]))


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
