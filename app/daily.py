"""The agenda and explicit review of one recurring daily stand-up."""
import copy
import datetime as dt
import re
import uuid

from . import items, meeting_types
from .live import read_json
from .prompts import digest
from .storage import atomic_json
from .task_progress import normalized_time
from .work_items import WorkItemConflict

LIMIT = 3
FIELDS = ('decisions', 'tasks', 'updates', 'blockers', 'needs_decision', 'open_questions')
CHANGES = {'workflow_state', 'due_date', 'follow_up_date'}
RECEIPTS = 'daily-review.json'


def validate_agenda(rows):
    if not isinstance(rows, list) or len(rows) > LIMIT:
        raise ValueError('A daily agenda can hold up to three topics')
    ids = set()
    for row in rows:
        if (not isinstance(row, dict) or set(row) != {'id', 'text', 'created', 'task_id'}
                or not isinstance(row['id'], str) or not re.fullmatch('[a-f0-9]{12}', row['id'])
                or row['id'] in ids or not isinstance(row['text'], str) or not 1 <= len(row['text'].strip()) <= 500
                or not isinstance(row['created'], str) or not normalized_time(row['created'])
                or row['task_id'] is not None and (not isinstance(row['task_id'], str) or not re.fullmatch('[a-f0-9]{1,64}', row['task_id']))):
            raise ValueError('Invalid daily agenda topic')
        ids.add(row['id'])
    return rows


def create_series(service, body):
    with service.lock, service.projects.lock:
        project = service.projects.get('projects', body.get('project_id'))
        if not project or project.get('archived'):
            raise ValueError('Choose an active project')
        name = body.get('name')
        if not isinstance(name, str):
            raise ValueError('Enter a daily series name')
        existing = next((row for row in service.projects.data['series']
                         if row['project_id'] == project['id'] and row['name'].casefold() == name.strip().casefold()), None)
        if existing and service._series_type(existing['id']) != 'daily':
            raise ValueError('A series with this name already has a different meeting type')
        key = service.projects.ensure_series({'name': name}, project['id'])
        service.projects.set_series_type(key, 'daily')
        service.projects.save()
        return dict(series_id=key, projects=service.projects.data)


def agenda(series):
    return series.get('daily_agenda', [])


def change_agenda(service, body):
    with service.lock, service.projects.lock:
        series = service.projects.get('series', body.get('series_id'))
        if not series or service._series_type(series['id']) != 'daily':
            raise ValueError('Choose a daily stand-up series')
        rows = agenda(series)
        if body.get('revision') != digest(rows):
            raise WorkItemConflict('The daily agenda changed. Reload it and try again.')
        action = body.get('action')
        if action == 'add':
            text = body.get('text')
            if not isinstance(text, str):
                raise ValueError('Enter a topic')
            task_id = body.get('task_id')
            if task_id is not None:
                with service.items.lock:
                    task = service.items.items.get(task_id) if isinstance(task_id, str) else None
                    if not eligible(service, task, series['project_id']):
                        raise ValueError('Choose an open task in this project')
            updated = [*rows, dict(id=uuid.uuid4().hex[:12], text=text.strip(),
                                   created=dt.datetime.now(dt.timezone.utc).isoformat(), task_id=task_id)]
        elif action == 'remove':
            updated = [row for row in rows if row['id'] != body.get('id')]
            if len(updated) == len(rows):
                raise ValueError('This agenda topic no longer exists')
            if body.get('meeting_id'):
                meeting = service.library.get(body['meeting_id'])
                if meeting.get('series_id') != series['id'] or body['id'] not in {row['id'] for row in prior_topics(series, meeting)}:
                    raise WorkItemConflict('This topic belongs to another daily')
                directory = service.library.directory(meeting['id'])
                if (meeting['id'] == service.active or meeting['id'] in service.busy
                        or not service._minutes(meeting['id']) or meeting.get('notes_need_refresh')
                        or (directory / 'minutes.proposed.json').exists()):
                    raise ValueError('Wait until the saved daily notes are ready')
        else:
            raise ValueError('Choose a daily agenda action')
        validate_agenda(updated)
        service.projects.guard_write()
        series['daily_agenda'] = updated
        try:
            service.projects.save()
        except Exception:
            series['daily_agenda'] = rows
            raise
        return dict(topics=updated, revision=digest(updated))


def prior_topics(series, meeting):
    start = normalized_time(meeting.get('started_at') or meeting.get('created'))
    return [row for row in agenda(series) if start and normalized_time(row['created']) <= start]


def before(service, result, series, meetings, registry):
    follow = result['followup']
    today = service.task_summary()['today']
    tasks = {row['item_id']: row for row in follow['commitments']}
    project_tasks = {item['id']: item for item in registry if item['kind'] == 'task' and item.get('status') == 'open'
                     and item.get('acceptance_state') == 'accepted' and not item.get('dismissed')
                     and item.get('workflow_state') != 'cancelled' and (item.get('snoozed_until') or '') <= today}
    groups = dict(
        changed=[row for row in follow['updated'] if row['updates_since']]
                + [row for row in follow['externally_updated'] if not row['updates_since']]
                + [row for row in follow['completed'] if not row['updates_since'] and not row['github_updates']],
        decisions=[row for row in follow['questions'] if row['status'] == 'open'],
        blockers=[*follow['blocked'], *[row for row in follow['waiting'] if not row['follow_up_date'] or row['follow_up_date'] <= today]],
        checks=[tasks.get(key) or dict(item_id=key, kind='task', text=item['text'], owner=item.get('owner'))
                for key, item in project_tasks.items()
                if (item.get('follow_up_date') or '9999') <= today or (item.get('due_date') or '9999') <= today],
    )
    groups['decisions'] = [row for row in groups['decisions'] if row['source']]
    known_questions = {row['text'].casefold().strip() for row in groups['decisions']}
    groups['decisions'].extend(row for row in result['questions'] if row['kind'] == 'decide'
                               and not row['maybe_answered_by'] and row['text'].casefold().strip() not in known_questions)
    latest = max((m for m in meetings if meeting_types.of(m)['id'] == 'daily'),
                 key=lambda m: m.get('started_at') or m['created'], default=None)
    if latest:
        ids = {row['item_id'] for row in groups['changed']}
        for item in registry:
            event = next((event for event in reversed(item.get('history', []))
                          if event.get('meeting_id') == latest['id'] and event.get('daily_review_key')), None)
            if item['id'] not in ids and item['kind'] == 'task' and not item.get('dismissed') and event:
                groups['changed'].append(dict(item_id=item['id'], kind='task', text=item['text'], owner=item.get('owner'),
                                               source=dict(meeting_id=latest['id'], meeting_title=latest['title'],
                                                           meeting_date=latest.get('started_at') or latest['created'],
                                                           timestamp=event.get('evidence_timestamp'))))
    return dict(topics=agenda(series), agenda_revision=digest(agenda(series)), groups=groups,
                latest_meeting=dict(id=latest['id'], title=latest['title']) if latest else None)


def review_rows(minutes, transcript):
    from meeting_assistant import timestamp
    by_stamp = {timestamp(row['start']): row for row in reversed(transcript)}
    rows = {}
    for field in FIELDS:
        for index, entry in enumerate(minutes.get(field, [])):
            text = entry.get('task' if field == 'tasks' else 'text')
            if not text:
                continue
            row = dict(field=field, text=text, timestamp=entry.get('evidence_timestamp'),
                       owner=entry.get('owner'), due_date=entry.get('due_date'), details=entry.get('details'))
            segment = by_stamp.get(row['timestamp'])
            row['quote'] = segment['text'] if segment else None
            key = digest(row)
            if key not in rows:
                rows[key] = dict(row, key=key, index=index, item_id=entry.get('item_id'))
    return list(rows.values())


REVIEWED, HELP = {'confirmed', 'skipped'}, {'promise', 'helped'}


def read_receipts(directory):
    """Saved daily receipts: the review of a line and a promise to help are separate (2026-11-23).

    A promise to help does not review the line, so the line can still update a task. Older receipts kept the
    promise as the review state; they read as a promise on a line that is not reviewed.
    """
    receipts = {}
    for key, value in read_json(directory / RECEIPTS, {}).items():
        if not isinstance(value, dict):
            continue
        if value.get('state') in HELP:
            value = dict(help=dict(state=value['state'], text=value.get('text'), task_id=value.get('task_id')))
        entry = {}
        if value.get('state') in REVIEWED:
            entry['state'] = value['state']
        help = value.get('help')
        if isinstance(help, dict) and help.get('state') in HELP:
            entry['help'] = dict(state=help['state'], text=help.get('text'), task_id=help.get('task_id'))
        if entry:
            receipts[key] = entry
    return receipts


def save_receipt(directory, key, *, state=None, help=None, clear_state=False):
    """Change one part of a receipt and keep the other part."""
    saved = read_receipts(directory)
    entry = saved.get(key, {})
    if clear_state:
        entry.pop('state', None)
    if state:
        entry['state'] = state
    if help:
        entry['help'] = help
    if entry:
        saved[key] = entry
    else:
        saved.pop(key, None)
    atomic_json(directory / RECEIPTS, saved)
    return entry


def applied_reviews(items, meeting_id=None):
    by_meeting = {}
    for item in items:
        for event in item.get('history', []):
            origin, key = event.get('meeting_id'), event.get('daily_review_key')
            if origin and key and (meeting_id is None or origin == meeting_id):
                by_meeting.setdefault(origin, {})[key] = dict(state='applied', task_id=item['id'])
    return by_meeting


def receipt_states(service, directory, meeting_id):
    """The review state (an applied update, or a saved review) and the help promise of each line."""
    applied = applied_reviews(service.items.items.values(), meeting_id).get(meeting_id, {})
    saved = read_receipts(directory)
    states = {}
    for key in {*applied, *saved}:
        own = saved.get(key, {})
        entry = dict(state=own['state']) if own.get('state') else dict(applied.get(key, {}))
        if own.get('help'):
            entry['help'] = own['help']
        states[key] = entry
    return states


def eligible(service, item, project_id, meetings=None):
    """An open task the daily can update. A project daily updates the tasks of its project. A shared daily
    without a project updates the tasks of every active project and the tasks without one (2026-11-25)."""
    if not (item and item['kind'] == 'task' and item['status'] == 'open'
            and item.get('acceptance_state') == 'accepted' and not item.get('dismissed')
            and item.get('workflow_state') != 'cancelled'):
        return False
    projects = service.effective_project_ids(item, meetings)
    if project_id:
        return project_id in projects
    active = {p['id'] for p in service.projects.data['projects'] if not p.get('archived')}
    return not projects or any(project in active for project in projects)


def after(service, meeting, directory):
    if meeting_types.of(meeting)['id'] != 'daily':
        return None
    series = service.projects.get('series', meeting.get('series_id')) or {}
    result = dict(series_id=series.get('id'), project_id=meeting.get('project_id'),
                  topics=prior_topics(series, meeting), agenda_revision=digest(agenda(series)), rows=[], tasks=[])
    if not meeting['minutes']:
        return dict(result, status='waiting')
    if meeting.get('notes_need_refresh') or meeting.get('minutes_proposal'):
        return dict(result, status='stale')
    with service.items.lock:
        rows = review_rows(meeting['minutes'], meeting['transcript'])
        states = receipt_states(service, directory, meeting['id'])
        meetings = service._meeting_refs()
        names = {p['id']: p['name'] for p in service.projects.data['projects']}
        tasks = []
        for item in service.items.items.values():
            if eligible(service, item, meeting.get('project_id'), meetings):
                tasks.append({key: item.get(key) for key in ('id', 'revision', 'text', 'owner', 'due_date', 'follow_up_date', 'workflow_state')})
                tasks[-1]['project'] = ', '.join(names[p] for p in service.effective_project_ids(item, meetings) if p in names)
        for row in rows:
            item = service.items.items.get(row['item_id'])
            entry = meeting['minutes'][row['field']][row['index']]
            default = 'confirmed' if row['field'] == 'decisions' and entry.get('review') == 'verified' else 'pending'
            state = dict(states.get(row['key'], {}))
            state.setdefault('state', default)
            if row['field'] == 'tasks' and item and item.get('acceptance_state') == 'accepted' and state['state'] == 'pending':
                state.update(state='applied', task_id=item['id'])
            row.update(state)
        # An update or blocker that names an open task leads the review, and the form preselects that task.
        # Other status lines wait under Context (2026-11-25).
        for row in rows:
            if row['field'] in {'updates', 'blockers'} and row['state'] == 'pending' and tasks:
                score, task_id = max((items.similarity(row['text'], task['text']), task['id']) for task in tasks)
                if score >= items.MATCH:
                    row['task_match'] = task_id
        current = {row['key'] for row in rows}
        for key, state in states.items():
            help = state.get('help')
            if key not in current and help and help['state'] == 'promise' and help.get('text'):
                # The line left the notes; the promise stays until help is provided.
                rows.append(dict(key=key, field='updates', text=help['text'], task_id=help.get('task_id'), help=help,
                                 state='changed', timestamp=None, source_changed=True))
        return dict(result, status='ready', revision=service._notes_revision(directory), rows=rows,
                    tasks=sorted(tasks, key=lambda item: item['text'].casefold()))


def review(service, meeting_id, body):
    with service.lock, service.items.lock:
        meeting = service.library.get(meeting_id)
        directory = service.library.directory(meeting_id)
        if meeting_types.of(meeting)['id'] != 'daily' or meeting_id == service.active or meeting_id in service.busy:
            raise ValueError('Review a processed daily stand-up')
        if meeting.get('notes_need_refresh') or (directory / 'minutes.proposed.json').exists():
            raise WorkItemConflict('Review the newer meeting notes first')
        if not body.get('revision') or body['revision'] != service._notes_revision(directory):
            raise WorkItemConflict('The notes or transcript changed. Reopen the daily review.')
        minutes = service._minutes(meeting_id)
        if minutes is None:
            raise ValueError('Generate meeting notes first')
        rows = review_rows(minutes, read_json(directory / 'transcript.json', []))
        row = next((row for row in rows if row['key'] == body.get('key')), None)
        key = body.get('key')
        action = body.get('action')
        state = receipt_states(service, directory, meeting_id).get(key) if isinstance(key, str) else None
        if action == 'helped' and state and state.get('help'):
            return save_receipt(directory, key, help=dict(state['help'], state='helped'))
        if row is None:
            raise WorkItemConflict('This daily suggestion changed. Reopen the daily review.')
        item = service.items.items.get(row['item_id'])
        if action == 'promise':
            if row['field'] not in {'tasks', 'updates', 'blockers'} or not row['quote']:
                raise ValueError('Choose sourced work or a blocker from the daily')
            task_id = state.get('task_id') if state else None
            if not task_id and item and item.get('acceptance_state') == 'accepted':
                task_id = item['id']
            return save_receipt(directory, row['key'], help=dict(state='promise', task_id=task_id, text=row['text']))
        if row['field'] == 'tasks' and item and item.get('acceptance_state') == 'accepted':
            return dict(state='applied', task_id=item['id'])
        if state and state.get('state'):
            if action == 'reopen' and state['state'] in REVIEWED:
                return dict(save_receipt(directory, row['key'], clear_state=True), state='pending')
            return state
        if action == 'confirm' and row['field'] == 'decisions':
            decisions = copy.deepcopy(minutes['decisions'])
            decisions[row['index']]['review'] = 'verified'
            service.edit(meeting_id, dict(minutes_fields=dict(decisions=decisions),
                                          minutes_base=dict(decisions=minutes['decisions']),
                                          minutes_revision=service._minutes_revision(directory)))
            return dict(state='confirmed')
        if action in {'skip', 'confirm'}:
            return save_receipt(directory, row['key'], state='skipped' if action == 'skip' else 'confirmed')
        if action != 'update':
            raise ValueError('Choose a daily review action')
        task_id = body.get('task_id')
        task = service.items.items.get(task_id) if isinstance(task_id, str) else None
        changes = body.get('changes')
        if (not eligible(service, task, meeting.get('project_id')) or type(body.get('task_revision')) is not int
                or not isinstance(changes, dict) or set(changes) - CHANGES):
            raise ValueError('Choose an open project task and review its changes')
        if not row['quote']:
            raise ValueError('This note has no matching transcript moment. Review it in the meeting notes.')
        evidence = dict(meeting_id=meeting_id, evidence_timestamp=row['timestamp'], quote=row['quote'][:500],
                        daily_review_key=row['key'])
        service.update_item(task_id, task['text'], dict(changes, update_note=row['text']), body['task_revision'],
                            confirm_subtasks=body.get('confirm_subtasks') is True, meeting_update=evidence)
        return dict(state='applied', task_id=task_id)
