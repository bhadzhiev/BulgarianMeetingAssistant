"""Share the public meeting record as an editable, deterministic email draft."""
from __future__ import annotations

import datetime as dt
import re

from . import followup_email, meeting_types, task_email

FOOTER = '—\nГенерирано от АТЛАНТА'
MAX_BODY = 100000


def recipients(service, meeting: dict, self_person_id=None) -> dict:
    account = (service.google.status().get('account') or '').casefold()
    people = service.people.list()
    own_ids = {p['id'] for p in people if p['id'] == self_person_id or account and account in ({e.casefold() for e in p.get('emails', [])} | {i.get('external_id', '').casefold() for i in p.get('identities', []) if i.get('provider') == 'gmail'})}
    own_emails = {email.casefold() for p in people if p['id'] in own_ids for email in p.get('emails', [])}
    if account:
        own_emails.add(account)
    involved, missing = set(), set()
    for name in {row.get('speaker') for row in meeting.get('transcript', []) if row.get('speaker')}:
        person = service.people.match(name)
        if person:
            if person['id'] not in own_ids:
                involved.add(person['id'])
                if not person.get('emails'):
                    missing.add(person['name'])
        elif not followup_email.PLACEHOLDER.fullmatch(name):
            missing.add(name)
        else:
            missing.add('Неидентифициран участник')
    rows, seen = [], set()
    for person in people:
        if person['id'] in own_ids:
            continue
        for index, email in enumerate(person.get('emails', [])):
            email = email.casefold()
            if email in seen or email in own_emails:
                continue
            seen.add(email)
            rows.append(dict(person_id=person['id'], name=person['name'], email=email,
                             involved=person['id'] in involved and index == 0))
    return dict(recipients=sorted(rows, key=lambda r: (not r['involved'], r['name'].casefold(), r['email'])),
                excluded_emails=sorted(own_emails), missing_participants=sorted(missing))


def template(service, meeting: dict) -> dict:
    minutes = meeting.get('minutes') or {}
    items = meeting.get('items') or {}
    day = followup_email._date(meeting.get('started_at') or meeting.get('created'))
    lines = ['Здравейте,', '', 'Изпращам бележките, решенията и задачите от срещата „' + meeting['title'] + '“'
             + (' от ' + day if day else '') + '.']

    def section(title, rows):
        if rows:
            lines.extend(['', title + ':', ''] + ['- ' + text for text in rows])

    def texts(field):
        return [row['text'] for row in minutes.get(field, []) if isinstance(row, dict) and row.get('text')]

    section('Обобщение', texts('summary'))
    for topic in minutes.get('discussion', []):
        section('Обсъждане — ' + topic.get('topic', ''), [p['text'] for p in topic.get('points', []) if p.get('text')])
    titles = meeting_types.titles_bg(meeting)
    for field in dict.fromkeys(meeting_types.SECTION_FIELDS):
        section(titles.get(field) or 'Допълнителни бележки', texts(field))
    section('Напредък по започната работа', texts('updates'))
    decisions, proposed_decisions, seen = [], [], set()
    for note in minutes.get('decisions', []):
        item = items.get(note.get('item_id'))
        if item and (item.get('dismissed') or item.get('status') == 'superseded'):
            continue
        text = item['text'] if item else note.get('text')
        if text and text not in seen:
            seen.add(text)
            (decisions if (item.get('status') == 'accepted' if item else note.get('review') == 'verified')
             else proposed_decisions).append(text)
    section('Решения', decisions)
    section('Решения от бележките — за потвърждение', proposed_decisions)
    tasks, suggestions, seen = [], [], set()
    for note in minutes.get('tasks', []):
        item = items.get(note.get('item_id'))
        if item:
            if item.get('dismissed') or item['id'] in seen:
                continue
            seen.add(item['id'])
            if item.get('acceptance_state') == 'accepted':
                tasks.append(item)
                continue
        title = note.get('task') or ''
        if title:
            owner = (note.get('owner') or '').strip()
            owner = owner if owner and not followup_email.PLACEHOLDER.fullmatch(owner) else 'не е посочен'
            due = task_email._date(note.get('due_date')) or note.get('deadline') or 'не е посочен'
            suggestions.append(title + ' — предложен отговорник: ' + owner + '; предложен срок: ' + due
                               + ('\n  Подробности: ' + note['details'] if note.get('details') else ''))
    tasks.extend(item for item in items.values() if item.get('kind') == 'task' and item['id'] not in seen
                 and item.get('acceptance_state') == 'accepted' and not item.get('dismissed'))
    if tasks:
        lines.extend(['', 'Задачи в My Work:', ''])
        selected = {task['id']: task for task in tasks}
        ordered = [t for t in tasks if t.get('parent_task_id') not in selected]
        for number, task in enumerate(ordered, 1):
            block = task_email._block(service, task, number, full=False)
            lines.extend([line for line in block if not line.startswith('От срещата:')])
            lines.append('')
            for index, child in enumerate([t for t in tasks if t.get('parent_task_id') == task['id']], 1):
                lines.extend(line for line in task_email._block(service, child, f'{number}.{index}', full=False)
                             if not line.startswith('От срещата:'))
                lines.append('')
    section('Предложения за задачи — още не са приети', suggestions)
    section('Въпроси за решение', texts('needs_decision'))
    section('Отворени въпроси', texts('open_questions'))
    section('Следващи стъпки', texts('next_steps'))
    lines.extend(['', 'Моля, прегледайте обобщението и отговорете на това писмо, ако са необходими уточнения или корекции.', '', 'Благодаря за съдействието.', '', FOOTER])
    return dict(subject=('Бележки и задачи от среща: ' + meeting['title'] + (' | ' + day if day else ''))[:200],
                body=re.sub(r'\n{3,}', '\n\n', '\n'.join(lines)))


def prepare(service, body: dict) -> dict:
    meeting = service.detail(body.get('meeting_id'))
    if meeting.get('notes_need_refresh'):
        raise ValueError(followup_email.STALE)
    if not meeting.get('minutes') and not meeting.get('items'):
        raise ValueError('Generate or add meeting notes before preparing the email')
    contact = recipients(service, meeting, body.get('self_person_id'))
    content = template(service, meeting)
    if len(content['body']) > MAX_BODY:
        raise ValueError('The meeting notes exceed 100000 characters. Shorten the notes or share the exported document.')
    status = service.google.status()
    previous = service.library.get(meeting['id']).get('meeting_email_draft')
    if previous and previous.get('account') == status.get('account'):
        previous = dict(previous, url=followup_email.draft_url(previous['account'], previous.get('message_id')))
    else:
        previous = None
    return dict(content, **contact, mode='meeting', ai=dict(available=False, reason='This template uses saved meeting notes without AI'), draft=previous,
                gmail=dict(account=status.get('account', ''), drafts=bool(status.get('capabilities', {}).get('gmail_compose'))))


def save_draft(service, body: dict) -> dict:
    meeting = service.detail(body.get('meeting_id'))
    contact = recipients(service, meeting, body.get('self_person_id'))
    to = [email for email in followup_email.addresses(body.get('to')) if email not in contact['excluded_emails']]
    if not to:
        raise ValueError('Choose at least one recipient other than yourself')
    subject = followup_email.clean(dict(subject=body.get('subject'), body='x'))['subject']
    text = body.get('body')
    if not isinstance(text, str) or not text.strip():
        raise ValueError('Enter the email text')
    text = text.strip()
    if not text.endswith(FOOTER):
        text += '\n\n' + FOOTER
    if len(text) > MAX_BODY:
        raise ValueError('The email text must have at most 100000 characters')
    account = service.google.status().get('account')
    previous = service.library.get(meeting['id']).get('meeting_email_draft') or {}
    raw = followup_email.mime(to, subject, text, html=task_email.formatted_body(text))
    draft = service.google.gmail_draft(raw, previous.get('draft_id') if previous.get('account') == account else None, expected_account=account)
    saved = dict(draft_id=draft['id'], message_id=draft.get('message', {}).get('id'), account=account,
                 saved_at=dt.datetime.now().astimezone().isoformat(timespec='seconds'), recipients=len(to))
    service.library.update(meeting['id'], meeting_email_draft=saved)
    return dict(saved, url=followup_email.draft_url(account, saved['message_id']))
