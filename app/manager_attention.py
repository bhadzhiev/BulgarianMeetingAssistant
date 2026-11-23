"""Actionable local signals for the manager's daily review."""
from . import meeting_types
from .daily import applied_reviews, read_receipts, review_rows
from .live import read_json
from .people import in_team
from .question_sources import tracked_question


def build(service, person_id):
    person = service.people.get(person_id) if person_id else None
    with service.lock:
        today = service.task_summary()['today']
        groups = dict(decisions=[], help=[], checks=[])
        active = {p['id']: p['name'] for p in service.projects.data['projects'] if not p.get('archived')}
        latest, seen_questions = {}, set()
        with service.items.lock:
            applied = applied_reviews(service.items.items.values())
        meetings = sorted(service.library.list(), key=lambda row: row.get('started_at') or row['created'], reverse=True)
        for meeting in meetings:
            project = meeting.get('project_id')
            if project not in active or meeting_types.of(meeting)['id'] != 'daily':
                continue
            key = meeting.get('series_id') or project
            if meeting['id'] == service.active or meeting['id'] in service.busy:
                continue
            latest.setdefault(key, dict(project_id=project, series_id=meeting.get('series_id'), id=meeting['id'], title=meeting['title']))
            directory = service.library.directory(meeting['id'])
            saved = read_receipts(directory)
            for state in saved.values():
                help = state.get('help')
                if help and help['state'] == 'promise' and help.get('text'):
                    groups['help'].append(dict(text=help['text'], meeting_id=meeting['id'], project=active[project],
                                               task_id=help.get('task_id'), reason='You promised to help at the daily'))
            minutes = service._minutes(meeting['id'])
            if not minutes or meeting.get('notes_need_refresh') or (directory / 'minutes.proposed.json').exists():
                continue
            with service.items.lock:
                resolved = {**applied.get(meeting['id'], {}), **{key: value for key, value in saved.items() if value.get('state')}}
                rows = review_rows(minutes, read_json(directory / 'transcript.json', []))
                for row in rows:
                    if row['field'] != 'needs_decision':
                        continue
                    identity = key, ' '.join(row['text'].casefold().split())
                    if identity in seen_questions:
                        continue
                    seen_questions.add(identity)
                    question = tracked_question(service.items.items, meeting['id'], minutes['needs_decision'][row['index']])
                    if row['key'] not in resolved and (not question or question['status'] == 'open' and not question.get('dismissed')):
                        groups['decisions'].append(dict(text=row['text'], meeting_id=meeting['id'], project=active[project],
                                                        timestamp=row['timestamp'], reason='Raised for a decision at a daily'))
        series = [dict(id=row['id'], project_id=row['project_id'], name=row['name'], project=active[row['project_id']],
                       latest=latest.get(row['id'])) for row in service.projects.data['series']
                  if row['project_id'] in active and service._series_type(row['id']) == 'daily']
        for member in service.people.list():
            if not in_team(member):
                continue
            for agreement in service.team_reviews.outstanding(member['id']):
                if agreement['owner'] in {'manager', 'both'}:
                    groups['help'].append(dict(text=agreement['text'], review_id=agreement['review_id'], person=member['name'],
                                               date=agreement.get('due_date'), task_id=agreement.get('task_id'),
                                               reason='You agreed to help in a 1:1'))
        owned_help = {row['task_id'] for row in groups['help'] if row['task_id']}
        if person:
            for task in service.item_list()['items']:
                if (task['kind'] != 'task' or task.get('acceptance_state') != 'accepted'
                        # A finished task needs no check, as in My Work's Follow-up (2026-11-23).
                        or task.get('dismissed') or task.get('workflow_state') in {'done', 'cancelled'} or task['status'] == 'done'
                        or (task.get('snoozed_until') or '') > today):
                    continue
                projects = task['effective_project_ids']
                if projects and not any(project in active for project in projects):
                    continue
                owner, _ = service.people.owner_of(task)
                mine = bool(owner and owner['id'] == person_id)
                following = task.get('follower_person_id') == person_id
                # A shared task shows to the people who work on it too; the reason names the owner,
                # so the check keeps one accountable person (2026-11-23).
                shared = not mine and person_id in (task.get('assignee_person_ids') or [])[1:]
                if not (mine or following or shared):
                    continue
                due, check = task.get('due_date'), task.get('follow_up_date')
                if (check and check <= today) or (task['status']=='open' and due and due < today):
                    chosen = check if check and check <= today else due
                    reason = 'Next check is due' if check and check <= today else 'Deadline has passed'
                    if shared and not following and owner:
                        reason += ' · ' + owner['name'] + ' owns the check'
                    groups['checks'].append(dict(text=task['text'], task_id=task['id'], date=chosen, reason=reason))
                elif mine and task.get('workflow_state') == 'waiting' and not check and task['id'] not in owned_help:
                    groups['help'].append(dict(text=task['text'], task_id=task['id'], reason='Your task is waiting and has no check date'))
        for rows in groups.values():
            rows.sort(key=lambda row: (row.get('date') or '9999', row['text'].casefold()))
        return dict(groups=groups, series=series, person_id=person['id'] if person else None)
