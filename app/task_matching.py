"""Match the tasks and updates of a meeting to existing tasks (PR 3 of docs/task-matching-plan.md).

1. A local sieve (text similarity, project, owner) picks a few candidates for each mention. It costs no tokens.
2. Only when a mention has candidates, one request asks the configured API to classify each mention.
3. The answer is checked: every ID must be one that was sent. Nothing changes a task here; the result
   waits for review (PR 4).

The existing tasks are context to recognize the same work. They are not evidence of what the meeting said.
"""
import datetime as dt
import hashlib
import json

from . import items as registry
from .work_items import canonical

PER_MENTION = 8          # candidates for one mention
PER_MEETING = 30         # unique candidates for one meeting
TITLE_LIMIT = 200
DETAIL_LIMIT = 300
UPDATES = 2
UPDATE_LIMIT = 200
TOKEN_BUDGET = 6000      # extra input for one meeting
RECENT_DAYS = 14         # a closed task is a candidate this long after it closed
THRESHOLD = 0.4          # lower than the link review (0.55): the AI decides; the sieve must not miss the task
TYPES = ('new_task', 'existing_mention', 'existing_update', 'proposed_change', 'uncertain')
CHANGE_FIELDS = ('owner', 'due_date', 'workflow_state')
WORKFLOW = ('todo', 'in_progress', 'waiting', 'done', 'cancelled')

SYSTEM = """You match what one meeting said to existing tasks.
untrusted_meeting.mentions are the tasks and updates of THIS meeting, with the words that were said.
existing_tasks are context to recognize the same work. They are not evidence of what the meeting said.
For each mention, choose one type:
- new_task: separate new work with its own result.
- existing_mention: the same work as one candidate, with no new information.
- existing_update: the same work, with new progress, a blocker or a clarification.
- proposed_change: the same work, and the meeting proposes a new owner, due date or state.
- uncertain: no clear basis to choose one candidate.
task_id is one of the candidate_ids of that mention, or null for new_task and uncertain.
Similar titles with a different project, result or period are not the same work.
A closed task stays closed: the meeting talking about it does not reopen it.
reason: one short sentence. update_text: only for existing_update, from the words of the meeting.
changes: only for proposed_change, only fields that the meeting said. Never invent an ID or a value."""

SCHEMA = dict(type='object', additionalProperties=False, required=['matches'], properties=dict(matches=dict(type='array', items=dict(
    type='object', additionalProperties=False,
    required=['mention_id', 'type', 'task_id', 'reason', 'update_text', 'changes'],
    properties=dict(
        mention_id=dict(type='string'),
        type=dict(type='string', enum=list(TYPES)),
        task_id=dict(type=['string', 'null']),
        reason=dict(type='string'),
        update_text=dict(type=['string', 'null']),
        changes=dict(type='array', items=dict(type='object', additionalProperties=False, required=['field', 'value'],
                                              properties=dict(field=dict(type='string', enum=list(CHANGE_FIELDS)),
                                                              value=dict(type=['string', 'null'])))))))))


def _cut(text, limit):
    text = ' '.join(str(text or '').split())
    return text if len(text) <= limit else text[:limit].rsplit(' ', 1)[0] + '…'


def _when(value):
    try:
        moment = dt.datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=dt.timezone.utc)


def cutoff(meeting):
    """The end of the meeting: its start plus its duration. Later records are not known at the meeting."""
    start = _when(meeting.get('created')) or dt.datetime.now(dt.timezone.utc)
    return start + dt.timedelta(seconds=max(0, float(meeting.get('duration') or 0)))


def mentions(minutes):
    """The tasks and updates of the notes, with the words that were said."""
    rows = []
    for index, task in enumerate(minutes.get('tasks', [])):
        if task.get('item_id') and task.get('review') == 'verified':
            continue  # a task that a person added or linked already has its identity
        rows.append(dict(id=f't{index}', kind='task', text=_cut(task.get('task'), TITLE_LIMIT), owner=task.get('owner'),
                         due_date=task.get('due_date'), quote=task.get('quote'), evidence_timestamp=task.get('evidence_timestamp')))
    for index, update in enumerate(minutes.get('updates', [])):
        rows.append(dict(id=f'u{index}', kind='update', text=_cut(update.get('text'), TITLE_LIMIT), quote=update.get('quote'),
                         evidence_timestamp=update.get('evidence_timestamp')))
    return rows


def _closed_at(item):
    """When the task closed, from its history; None when it is open."""
    if item.get('status') != 'done' and item.get('workflow_state') not in ('done', 'cancelled'):
        return None
    moments = [_when(e.get('at')) for e in item.get('history', [])
               if (e.get('changes') or {}).get('status', [None, None])[1] == 'done'
               or (e.get('changes') or {}).get('workflow_state', [None, None])[1] in ('done', 'cancelled')]
    moments = [m for m in moments if m]
    return max(moments) if moments else _when(item.get('created'))


def eligible(item, end, meeting_id):
    """Accepted, visible tasks that existed at the meeting: open, or closed in the last RECENT_DAYS before it.
    Proposed and hidden tasks never go to the AI (decision of 8 November 2026)."""
    if item.get('kind') != 'task' or item.get('acceptance_state') == 'proposed' or item.get('dismissed'):
        return False
    created = _when(item.get('created'))
    if created and created > end:
        return False
    # A task that only this meeting made is this meeting's own task.
    if item.get('links') and all(link.get('meeting_id') == meeting_id for link in item['links']):
        return False
    closed = _closed_at(item)
    return closed is None or end - dt.timedelta(days=RECENT_DAYS) <= closed <= end


def view(item, end, project_names, people):
    """What the AI may see of one candidate. Records after the meeting are not shown as known at the meeting."""
    later = any((_when(e.get('at')) or end) > end for e in item.get('history', []))
    updates = [e for e in item.get('history', []) if e.get('event') == 'progress_update' and e.get('text') and (_when(e.get('at')) or end) <= end]
    owner = next((p['name'] for p in people if p['id'] == item.get('owner_person_id')), None) or item.get('owner')
    return dict(
        id=item['id'], revision=item.get('revision'), title=_cut(item.get('text'), TITLE_LIMIT),
        projects=[project_names[key] for key in item.get('effective_project_ids', []) if key in project_names],
        owner=owner, due_date=item.get('due_date'),
        state=item.get('workflow_state') or ('done' if item.get('status') == 'done' else 'todo'),
        # History keeps when a change was recorded, not when it happened: the state is approximate.
        state_note='current; it changed after the meeting' if later else 'as recorded at the meeting',
        expected_result=_cut(item.get('completion_criteria') or item.get('details'), DETAIL_LIMIT) or None,
        updates=[dict(date=str(e.get('at'))[:10], text=_cut(e['text'], UPDATE_LIMIT), origin='person') for e in updates[-UPDATES:]])


def tokens(value):
    """A cautious estimate: Bulgarian text takes about one token for every three characters."""
    return len(canonical(value)) // 3 + 1


def select(tasks, minutes, meeting, project_names=None, people=()):
    """The input for one meeting, within the limits; None when no mention has a candidate."""
    project_names = project_names or {}
    end = cutoff(meeting)
    rows = mentions(minutes)
    pool = [item for item in tasks if eligible(item, end, meeting.get('id'))]
    project = meeting.get('project_id')
    scored = {}
    for mention in rows:
        found = []
        for item in pool:
            score = registry.similarity(mention['text'], item.get('text') or '')
            if mention.get('owner') and mention['owner'] == item.get('owner'):
                score += 0.05
            if project and project in item.get('effective_project_ids', []):
                score += 0.05
            if score >= THRESHOLD:
                found.append((round(min(score, 1.0), 3), item['id']))
        found.sort(reverse=True)
        mention['candidate_ids'] = [key for _, key in found[:PER_MENTION]]
        for score, key in found[:PER_MENTION]:
            scored[key] = max(scored.get(key, 0), score)
    if not scored:
        return None
    # The meeting limit: the best scored candidates stay; a mention loses only the candidates that went.
    keep = sorted(scored, key=lambda key: -scored[key])[:PER_MEETING]
    by_id = {item['id']: item for item in pool}
    candidates = {key: view(by_id[key], end, project_names, people) for key in keep}
    data = None
    while True:
        for mention in rows:
            mention['candidate_ids'] = [key for key in mention['candidate_ids'] if key in candidates]
        data = dict(meeting=dict(date=end.date().isoformat()),
                    mentions=[m for m in rows if m['candidate_ids']],
                    existing_tasks=sorted(candidates.values(), key=lambda c: -scored[c['id']]))
        if not data['mentions']:
            return None
        if tokens(data) <= TOKEN_BUDGET or len(candidates) == 1:
            break
        # Over the budget: the lowest scored candidate goes. A quote of the meeting is never cut.
        candidates.pop(min(candidates, key=lambda key: scored[key]))
    return data


def signature(data, settings):
    """The same input to the same target gives the same answer: a retry uses it again."""
    value = dict(data=data, target=dict(base_url=settings.get('local_ai_base_url'), model=settings.get('local_ai_model')))
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def generate(data, settings, key=''):
    """Worker step: one request, then the check."""
    from .local_ai import complete_json
    result = complete_json(settings, [dict(role='system', content=SYSTEM),
                                      dict(role='user', content=canonical(dict(untrusted_meeting=dict(date=data['meeting']['date'], mentions=data['mentions']),
                                                                               existing_tasks=data['existing_tasks'])))],
                           SCHEMA, 'task_matching', timeout=600, api_key=key)
    return validate(result, data)


def validate(result, data):
    """Keep only answers that refer to what was sent. An unknown ID or value is dropped, never guessed."""
    if not isinstance(result, dict) or not isinstance(result.get('matches'), list):
        raise ValueError('The task matching answer is not valid JSON of the expected shape')
    sent = {m['id']: m for m in data['mentions']}
    clean, rejected, seen = [], [], set()
    for row in result['matches']:
        reason = 'invalid'
        try:
            mention = sent.get(row.get('mention_id'))
            kind, task_id = row.get('type'), row.get('task_id')
            if not mention or mention['id'] in seen:
                reason = 'unknown or repeated mention'
            elif kind not in TYPES:
                reason = 'unknown type'
            elif kind in ('new_task', 'uncertain') and task_id is not None:
                reason = 'a new or uncertain match has no task'
            elif kind not in ('new_task', 'uncertain') and task_id not in mention['candidate_ids']:
                reason = 'a task that was not a candidate of this mention'
            else:
                changes = _changes(row.get('changes') or [], kind)
                text = row.get('update_text')
                text = ' '.join(text.split())[:1000] if kind == 'existing_update' and isinstance(text, str) and text.strip() else None
                if kind == 'existing_update' and not text:
                    reason = 'an update without text'
                elif kind == 'proposed_change' and not changes:
                    reason = 'a change without a field'
                else:
                    seen.add(mention['id'])
                    clean.append(dict(mention_id=mention['id'], type=kind, task_id=task_id,
                                      reason=_cut(row.get('reason'), 300), update_text=text, changes=changes))
                    continue
        except (AttributeError, TypeError, ValueError):
            reason = 'invalid'
        rejected.append(dict(mention_id=str(row.get('mention_id') if isinstance(row, dict) else '')[:20], reason=reason))
    return dict(matches=clean, rejected=rejected)


def _changes(rows, kind):
    if kind != 'proposed_change':
        return []
    clean, fields = [], set()
    for row in rows:
        field, value = row.get('field'), row.get('value')
        if field not in CHANGE_FIELDS or field in fields:
            raise ValueError('unknown field')
        if field == 'due_date' and value is not None:
            dt.date.fromisoformat(value)
        if field == 'workflow_state' and value not in WORKFLOW:
            raise ValueError('unknown state')
        if field == 'owner' and value is not None and (not isinstance(value, str) or not value.strip()):
            raise ValueError('empty owner')
        fields.add(field)
        clean.append(dict(field=field, value=value))
    return clean
