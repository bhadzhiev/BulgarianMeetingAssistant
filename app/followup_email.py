"""Follow-up email after a meeting: a draft from reviewed notes, saved as a Gmail draft.

Only what a person reviewed goes in: accepted decisions, accepted tasks and checked summary,
next-step and open-question items. Private observations and AI proposals stay out. Nothing is sent from
here: the person opens the Gmail draft, checks it and sends it from Gmail.
"""
from __future__ import annotations

import base64
import datetime as dt
from email.message import EmailMessage
from email.utils import formataddr
import re
import urllib.parse

from .people import EMAIL
from .work_items import canonical

PLACEHOLDER = re.compile(r'SPEAKER[ _-]?\d+', re.I)
MAX_RECIPIENTS = 50
SCHEMA = dict(type='object', additionalProperties=False, required=['subject', 'body'],
              properties=dict(subject=dict(type='string', minLength=1, maxLength=200),
                              body=dict(type='string', minLength=1, maxLength=20000)))
SYSTEM = """Write one follow-up email from the supplied reviewed meeting notes DATA.
Return only JSON with subject and body, matching the schema. body is plain text, not HTML or Markdown tables.
A person edits this draft and sends it from Gmail, so leave a section out rather than invent content for it.
- Use only the supplied data. Do not add decisions, tasks, owners, dates, meetings or promises.
- Copy owner names and due dates exactly as supplied. Write "без срок" when a task has no due date.
- List each task on its own line as: task — owner — due date.
- List open_questions as unresolved questions, without owners or answers. Leave the section out when the list is empty.
- Do not add a signature, a name for the sender or placeholders such as [Име]."""


def _date(value):
    try:
        return dt.datetime.fromisoformat(value).astimezone().strftime('%d.%m.%Y')
    except (TypeError, ValueError):
        return ''


def _owner(service, item):
    person, _ = service.people.owner_of(item)
    if person:
        return person['name']
    owner = (item.get('owner') or '').strip()
    return '' if not owner or PLACEHOLDER.fullmatch(owner) else owner


def source(service, meeting_id):
    """The reviewed content of one meeting. Raises when nothing is reviewed yet."""
    meeting = service.detail(meeting_id)
    minutes = meeting.get('minutes') or {}
    items = meeting.get('items') or {}
    checked = lambda field: [m['text'] for m in minutes.get(field) or [] if m.get('review') == 'verified' and m.get('text')]
    decisions, tasks, seen = [], [], set()
    for mention in minutes.get('decisions') or []:
        item = items.get(mention.get('item_id'))
        if item and item['id'] not in seen and not item.get('dismissed') and item.get('status') == 'accepted':
            seen.add(item['id']);decisions.append(item['text'])
    for mention in minutes.get('tasks') or []:
        item = items.get(mention.get('item_id'))
        if (not item or item['id'] in seen or item.get('dismissed') or item.get('acceptance_state') != 'accepted'
                or item.get('workflow_state') == 'cancelled'):
            continue
        seen.add(item['id'])
        tasks.append(dict(task=item['text'], owner=_owner(service, item), due_date=item.get('due_date') or None,
                          said_deadline=item.get('deadline') or None))
    # Manual tasks of this meeting count too; they have no mention in the notes.
    for item in items.values():
        if (item['id'] not in seen and item.get('kind') == 'task' and item.get('acceptance_state') == 'accepted'
                and not item.get('dismissed') and item.get('workflow_state') != 'cancelled'):
            seen.add(item['id'])
            tasks.append(dict(task=item['text'], owner=_owner(service, item), due_date=item.get('due_date') or None,
                              said_deadline=item.get('deadline') or None))
    if not decisions and not tasks:
        raise ValueError('Accept at least one decision or task in Review before you write the follow-up email.')
    return dict(meeting_title=meeting['title'], meeting_date=_date(meeting.get('started_at') or meeting.get('created')),
                summary=checked('summary'), decisions=decisions, tasks=tasks, open_questions=checked('open_questions'),
                next_steps=checked('next_steps'))


def recipients(service, meeting_id):
    """Every person with an email. Participants and task owners come first and are preselected."""
    meeting = service.detail(meeting_id)
    involved = set()
    for name in {row.get('speaker') for row in meeting.get('transcript') or []}:
        person = service.people.match(name)
        if person:involved.add(person['id'])
    for item in (meeting.get('items') or {}).values():
        person, _ = service.people.owner_of(item)
        if person:involved.add(person['id'])
    rows = [dict(person_id=p['id'], name=p['name'], email=email, involved=p['id'] in involved)
            for p in service.people.list() for email in p.get('emails') or []]
    return sorted(rows, key=lambda r: (not r['involved'], r['name'].casefold(), r['email']))


def template(data):
    """The same structure without AI, from the reviewed data only."""
    lines = [f"Здравейте,", '', f"Благодаря за срещата „{data['meeting_title']}“" + (f" на {data['meeting_date']}." if data['meeting_date'] else '.')]
    lines += data['summary'][:3]
    if data['decisions']:
        lines += ['', 'Основни решения:'] + ['- ' + text for text in data['decisions']]
    if data['tasks']:
        lines += ['', 'План за действие:']
        for task in data['tasks']:
            due = _date(task['due_date'] + 'T12:00:00') if task['due_date'] else 'без срок'
            lines.append('- ' + ' — '.join([task['task'], task['owner'] or 'без отговорник', due]))
    if data['open_questions']:
        lines += ['', 'Отворени въпроси:'] + ['- ' + text for text in data['open_questions'][:5]]
    if data['next_steps']:
        lines += ['', 'Следващи стъпки:'] + ['- ' + text for text in data['next_steps']]
    subject = 'Follow-up: ' + data['meeting_title'] + (' · ' + data['meeting_date'] if data['meeting_date'] else '')
    return dict(subject=subject[:200], body='\n'.join(lines))


def prepare(service, body):
    """Open the editor at once: the plain template, the recipients and what the AI and Gmail steps need."""
    meeting_id = body.get('meeting_id')
    data = source(service, meeting_id)
    try:
        target = service.repo_reports.target();ai = dict(available=True, model=target['local_ai_model'], provider=target['provider'])
    except ValueError as exc:
        ai = dict(available=False, reason=str(exc))
    status = service.google.status()
    previous = service.library.get(meeting_id).get('followup_draft')
    if previous and previous.get('account') == status.get('account'):
        previous = dict(previous, url=draft_url(previous['account'], previous.get('message_id')))
    else:
        previous = None
    return dict(template(data), ai=ai, recipients=recipients(service, meeting_id), draft=previous,
                gmail=dict(account=status.get('account', ''), drafts=bool(status.get('capabilities', {}).get('gmail_compose'))))


def clean(result):
    if not isinstance(result, dict) or set(result) != {'subject', 'body'}:
        raise ValueError('Invalid follow-up email response')
    subject, body = result['subject'], result['body']
    if not isinstance(subject, str) or not 1 <= len(subject.strip()) <= 200 or any(ord(c) < 32 for c in subject):
        raise ValueError('The subject must be one line of 1 to 200 characters')
    if not isinstance(body, str) or not 1 <= len(body.strip()) <= 20000:
        raise ValueError('The email text must have 1 to 20000 characters')
    return dict(subject=' '.join(subject.split()), body=body.strip())


def generate(service, body, complete=None):
    """A draft written by the saved Notes & AI provider, or the plain template without AI."""
    data = source(service, body.get('meeting_id'))
    try:
        target = service.repo_reports.target()
    except ValueError as exc:
        return dict(template(data), ai=False, note=str(exc) + ' · The draft uses the plain template.', recipients=recipients(service, body['meeting_id']))
    from .prompts import select_stages
    target['_prompt_snapshot'] = select_stages(service.prompts.snapshot(), ('followup_email',))
    if not service.processing_slot.acquire(blocking=False):
        raise ValueError('Wait until recording or processing finishes before you write the email with AI.')
    try:
        if complete is None:
            from .local_ai import complete_json as complete
        messages = [dict(role='system', content=SYSTEM), dict(role='user', content=canonical(dict(reviewed_meeting_notes=data)))]
        result = complete(target, messages, SCHEMA, 'followup_email', timeout=180,
                          api_key=service.api_key if target['provider'] == 'openai' else '')
    finally:
        service.processing_slot.release()
    return dict(clean(result), ai=True, note='Written by ' + target['local_ai_model'] + '. Check it before you save the draft.',
                recipients=recipients(service, body['meeting_id']))


def addresses(values):
    if not isinstance(values, list) or not values or len(values) > MAX_RECIPIENTS:
        raise ValueError(f'Choose 1 to {MAX_RECIPIENTS} recipients')
    result = []
    for value in values:
        email = value.strip().casefold() if isinstance(value, str) else ''
        if not EMAIL.fullmatch(email):
            raise ValueError(f'"{value}" is not an email address')
        if email not in result:result.append(email)
    return result


def mime(to, subject, text):
    message = EmailMessage()
    message['To'] = ', '.join(formataddr(('', email)) for email in to)
    message['Subject'] = subject
    message.set_content(text)
    return base64.urlsafe_b64encode(message.as_bytes()).decode()


def save_draft(service, body):
    """Create the Gmail draft, or update the one this meeting already has."""
    meeting_id = body.get('meeting_id')
    meeting = service.library.get(meeting_id)
    to = addresses(body.get('to'))
    content = clean(dict(subject=body.get('subject'), body=body.get('body')))
    raw = mime(to, content['subject'], content['body'])
    previous = meeting.get('followup_draft') or {}
    account = service.google.status().get('account')
    draft = service.google.gmail_draft(raw, previous.get('draft_id') if previous.get('account') == account else None,
                                       expected_account=account)
    saved = dict(draft_id=draft['id'], message_id=draft.get('message', {}).get('id'), account=account,
                 saved_at=dt.datetime.now().astimezone().isoformat(timespec='seconds'), recipients=len(to))
    service.library.update(meeting_id, followup_draft=saved)
    return dict(saved, url=draft_url(account, saved['message_id']))


def draft_url(account, message_id):
    base = 'https://mail.google.com/mail/?authuser=' + urllib.parse.quote(account or '', safe='@')
    return base + ('#drafts?compose=' + message_id if message_id else '#drafts')
