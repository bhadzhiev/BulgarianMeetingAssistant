"""The facts of a 1:1 review: what a person was assigned, took on, finished and decided in a period. No AI.

Only confirmed facts count. A person chose the owner, a person set the state, a person accepted the decision,
or the transcript has the person's own words at the moment of the task. Everything else goes to "Excluded from
the analysis": an owner that matches by name only, an owner that the AI suggested, an unidentified speaker.

Attribution:
- The accountable person (the owner, the first assignee) gets "assigned", "taken on" and "overdue".
- The others of a shared task "took part"; a person removed from a task "took part until" that day.
- An overdue task counts for the person who owned it on its due date, not for a later owner.
- Every count comes from this code. The text of a review cites the evidence records e1…eN.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import re
from zoneinfo import ZoneInfo

from .live import read_json
from .transcripts import stamp_seconds

TZ = ZoneInfo('Europe/Sofia')
QUOTE = 500
FIELDS = ('owner', 'owner_person_id', 'assignee_person_ids', 'due_date', 'workflow_state', 'status', 'acceptance_state')
DONE = {'done'}
SPEAKER = re.compile(r'SPEAKER[ _-]?\d+', re.I)


def _time(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        moment = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None
    return moment.replace(tzinfo=TZ) if moment.tzinfo is None else moment


def _day_end(day):
    """The first moment after a due day ends, in Sofia."""
    return dt.datetime.combine(dt.date.fromisoformat(day) + dt.timedelta(days=1), dt.time(), TZ)


def _quote(text):
    text = ' '.join(str(text or '').split())
    return text if len(text) <= QUOTE else text[:QUOTE - 1].rsplit(' ', 1)[0] + '…'


def _fmt_day(value):
    return dt.date.fromisoformat(value[:10]).strftime('%d.%m.%Y')


def _fmt_time(moment):
    return moment.astimezone(TZ).strftime('%d.%m.%Y')


class Timeline:
    """The state of one task at any moment, rebuilt from its history."""

    def __init__(self, item):
        self.item = item
        self.events = sorted((e for e in item.get('history', []) if _time(e.get('at'))), key=lambda e: _time(e['at']))
        self.created = _time(item.get('created')) or (_time(self.events[0]['at']) if self.events else None)
        self.list_history = any('assignee_person_ids' in (e.get('changes') or {}) for e in self.events)

    def state(self, moment):
        if self.created and moment < self.created:
            return None
        state = {name: copy.deepcopy(self.item.get(name)) for name in FIELDS}
        for event in reversed(self.events):
            if _time(event['at']) <= moment:
                break
            for name, change in (event.get('changes') or {}).items():
                if name in state and isinstance(change, list) and len(change) == 2:
                    state[name] = copy.deepcopy(change[0])
        if not self.list_history or state.get('assignee_person_ids') is None:
            state['assignee_person_ids'] = [state['owner_person_id']] if state.get('owner_person_id') else []
        elif state.get('owner_person_id') and (not state['assignee_person_ids'] or state['assignee_person_ids'][0] != state['owner_person_id']):
            state['assignee_person_ids'] = [state['owner_person_id'], *[i for i in state['assignee_person_ids'] if i != state['owner_person_id']]]
        return state

    @staticmethod
    def role(state, person_id):
        if not state:
            return None
        ids = state.get('assignee_person_ids') or []
        if ids and ids[0] == person_id:
            return 'accountable'
        if person_id in ids[1:]:
            return 'co'
        return None

    def done_at(self):
        """When a person last set the task to done, if it is done now."""
        if self.item.get('status') != 'done' and self.item.get('workflow_state') != 'done':
            return None
        for event in reversed(self.events):
            changes = event.get('changes') or {}
            if changes.get('workflow_state', [None, None])[1] == 'done' or changes.get('status', [None, None])[1] == 'done':
                return _time(event['at'])
        return None


class Collector:
    def __init__(self, service, person, start, end, previous=None):
        self.s, self.person, self.start, self.end = service, person, _time(start), _time(end)
        self.previous = previous
        self.names = {n for n in service._person_names(person) if len(service.people.matching(n)) == 1}
        self.people = {p['id']: p for p in service.people.list()}
        self.evidence, self.excluded = [], []
        self.transcripts = {}
        self.meetings = {m['id']: m for m in service.library.list()}

    # Evidence -------------------------------------------------------------------------------------
    def add(self, kind, item, occurred_at, basis, facts, quote='', meeting_id=None, timestamp=None):
        record = dict(id='e' + str(len(self.evidence) + 1), kind=kind, person_id=self.person['id'],
                      source_ref=dict(item_id=item['id'] if item else None, meeting_id=meeting_id, timestamp=timestamp,
                                      provider=self.provider(item) if item else 'meeting'),
                      occurred_at=occurred_at.isoformat() if isinstance(occurred_at, dt.datetime) else occurred_at,
                      confirmation_basis=basis, facts=facts, quote=_quote(quote))
        self.evidence.append(record)
        return record['id']

    @staticmethod
    def provider(item):
        providers = {e.get('provider') for e in item.get('evidence', []) if e.get('provider')}
        return 'meeting' if not providers or 'meeting' in providers else sorted(providers)[0]

    def in_period(self, moment):
        return moment is not None and self.start <= moment < self.end

    def name(self, person_id):
        return self.people.get(person_id, {}).get('name', 'a removed person')

    # Transcripts ----------------------------------------------------------------------------------
    def transcript(self, meeting_id):
        if meeting_id not in self.transcripts:
            path = self.s.library.directory(meeting_id) / 'transcript.json' if meeting_id in self.meetings else None
            rows = read_json(path, []) if path and path.exists() else []
            self.transcripts[meeting_id] = [r for r in rows if isinstance(r, dict)]
        return self.transcripts[meeting_id]

    def speaker_at(self, meeting_id, timestamp):
        """The transcript segment at a moment, and whether this person said it."""
        try:
            second = stamp_seconds(timestamp)
        except (TypeError, ValueError):
            return None
        for row in self.transcript(meeting_id):
            if isinstance(row.get('start'), (int, float)) and row['start'] - 1 <= second <= (row.get('end') or row['start']) + 1:
                speaker = row.get('speaker') if isinstance(row.get('speaker'), str) else ''
                return dict(text=row.get('text', ''), mine=speaker.casefold() in self.names, unknown=not speaker or bool(SPEAKER.fullmatch(speaker)))
        return None

    def speaks_in(self, meeting_id):
        return any(isinstance(r.get('speaker'), str) and r['speaker'].casefold() in self.names for r in self.transcript(meeting_id))

    def own_words(self, item):
        """The person's own words at the moment of the task in a meeting: evidence that they took it on."""
        for ev in item.get('evidence', []):
            if ev.get('provider') == 'meeting' and ev.get('timestamp') and ev.get('source_id') in self.meetings:
                said = self.speaker_at(ev['source_id'], ev['timestamp'])
                if said and said['mine']:
                    return ev['source_id'], ev['timestamp'], said['text']
        for link in item.get('links', []):
            if link.get('evidence_timestamp') and link.get('meeting_id') in self.meetings and not link.get('detached'):
                said = self.speaker_at(link['meeting_id'], link['evidence_timestamp'])
                if said and said['mine']:
                    return link['meeting_id'], link['evidence_timestamp'], said['text']
        return None

    # Tasks ----------------------------------------------------------------------------------------
    def tasks(self, items):
        pid, rows = self.person['id'], []
        for item in items:
            if item['kind'] != 'task' or item.get('dismissed'):
                continue
            line = Timeline(item)
            moments = [self.start, *[_time(e['at']) for e in line.events if self.in_period(_time(e['at']))], self.end - dt.timedelta(microseconds=1)]
            roles = [(m, line.role(line.state(m), pid)) for m in moments]
            if not any(role for _, role in roles):
                self.exclude_task(item, line)
                continue
            rows.append(self.task_facts(item, line, roles))
        return rows

    def exclude_task(self, item, line):
        """A task that may belong to this person, but no person confirmed it."""
        state = line.state(self.end - dt.timedelta(microseconds=1))
        if not state:
            return
        owner = (state.get('owner') or '').strip()
        touched = any(self.in_period(_time(e['at'])) for e in line.events) or self.in_period(line.created)
        if not owner or not touched:
            return
        if owner.casefold() in self.names and not state.get('owner_person_id'):
            reason = 'The AI suggested this owner; nobody confirmed it' if item.get('acceptance_state') == 'proposed' or 'owner' not in item.get('manual', []) else 'The owner matches by name only; it is not linked to the person'
            self.excluded.append(dict(item_id=item['id'], text=item['text'], reason=reason))
        elif SPEAKER.fullmatch(owner) and any(self.speaks_in(l['meeting_id']) for l in item.get('links', []) if l.get('meeting_id') in self.meetings):
            self.excluded.append(dict(item_id=item['id'], text=item['text'], reason='The owner is an unidentified speaker in a meeting where the person speaks'))

    def task_facts(self, item, line, roles):
        pid = self.person['id']
        end_state = line.state(self.end - dt.timedelta(microseconds=1)) or {}
        end_role = line.role(end_state, pid)
        last_role = next((role for _, role in reversed(roles) if role), None)
        shared = any(len((line.state(m) or {}).get('assignee_person_ids') or []) > 1 for m, role in roles if role)
        facts = dict(item_id=item['id'], text=item['text'], role=end_role or last_role, shared=shared, refs=[], marks=[],
                     open_at_end=end_role is not None and end_state.get('status') != 'done' and end_state.get('workflow_state') != 'cancelled',
                     state=end_state.get('workflow_state'), due_date=end_state.get('due_date'), requester=item.get('requester_person_id'))
        base = dict(text=item['text'], shared=shared)
        # Assigned in the period, or taken away.
        before = roles[0][1]
        for moment, role in roles[1:]:
            event = next((e for e in line.events if _time(e['at']) == moment), None)
            by_person = event and event.get('by') == 'user'
            if role and not before and by_person:
                facts['refs'].append(self.add('task_assigned', item, moment, 'A person chose the owner' if role == 'accountable' else 'A person added them to the task', dict(base, role=role)))
                facts['marks'].append('assigned' if role == 'accountable' else 'joined')
            elif before and not role:
                new_owner = (line.state(moment) or {}).get('owner_person_id')
                kind = 'task_transferred' if before == 'accountable' and new_owner else 'task_left'
                facts['refs'].append(self.add(kind, item, moment, 'A person changed the assignees', dict(base, until=moment.date().isoformat(), to=self.name(new_owner) if new_owner else None)))
                facts['marks'].append('transferred' if kind == 'task_transferred' else 'left')
                facts['until'] = moment.date().isoformat()
            elif before == 'co' and role == 'accountable' or before == 'accountable' and role == 'co':
                facts['marks'].append('role changed')
            before = role
        if line.created and self.in_period(line.created) and roles[0][1] is None and 'assigned' not in facts['marks'] and 'joined' not in facts['marks']:
            first = line.role(line.state(line.created), pid)
            if first and (item.get('owner_person_id') or 'owner' in item.get('manual', [])):
                facts['refs'].append(self.add('task_assigned', item, line.created, 'A person chose the owner' if first == 'accountable' else 'A person added them to the task', dict(base, role=first)))
                facts['marks'].append('assigned' if first == 'accountable' else 'joined')
        # Taken on: the person's own words at the moment of the task.
        if (end_role or last_role) == 'accountable':
            words = self.own_words(item)
            if words:
                meeting_id, stamp, text = words
                when = _time(self.meetings[meeting_id].get('started_at') or self.meetings[meeting_id].get('created'))
                facts['refs'].append(self.add('task_taken_on', item, when, 'The person said it in a meeting (confirmed name)', base, text, meeting_id, stamp))
                facts['marks'].append('taken on')
        # Changes of the agreement: due dates.
        for event in line.events:
            moment = _time(event['at'])
            change = (event.get('changes') or {}).get('due_date')
            if self.in_period(moment) and event.get('by') == 'user' and isinstance(change, list) and line.role(line.state(moment), pid):
                facts['refs'].append(self.add('due_changed', item, moment, 'A person changed the due date', dict(base, before=change[0], after=change[1])))
                facts['marks'].append('due changed')
        # Done, cancelled, overdue.
        done = line.done_at()
        if done and self.in_period(done):
            role = line.role(line.state(done), pid)
            if role:
                facts['refs'].append(self.add('task_completed', item, done, 'A person set the state to done', dict(base, role=role)))
                facts['marks'].append('completed')
                verified = any(e.get('event') == 'progress_update' and e.get('evidence_id') and (_time(e['at']) or done) >= done for e in line.events)
                if verified:
                    facts['refs'].append(self.add('result_confirmed', item, done, 'An update after completion has evidence', base))
                    facts['marks'].append('result confirmed')
        for event in line.events:
            moment = _time(event['at'])
            if self.in_period(moment) and (event.get('changes') or {}).get('workflow_state', [None, None])[1] == 'cancelled' and line.role(line.state(moment), pid):
                facts['refs'].append(self.add('task_cancelled', item, moment, 'A person cancelled the task', base))
                facts['marks'].append('cancelled')
        due = end_state.get('due_date')
        if due:
            try:
                limit = _day_end(due)
            except ValueError:
                limit = None
            if limit and limit <= self.end and (not done or done >= limit) and end_state.get('workflow_state') != 'cancelled':
                at_due = line.state(limit - dt.timedelta(microseconds=1))
                # Overdue in this period, or still overdue and open at its end.
                if line.role(at_due, pid) == 'accountable' and (limit >= self.start or facts['open_at_end']):
                    facts['refs'].append(self.add('task_overdue', item, limit, 'The due date passed while the person owned the task', dict(base, due_date=due, finished=done.date().isoformat() if done else None)))
                    facts['marks'].append('overdue')
        if facts['open_at_end'] and not facts['refs']:
            facts['refs'].append(self.add('task_open', item, self.end, 'Current assignees, set by a person' if item.get('owner_person_id') else 'Current owner', dict(base, role=end_role, state=end_state.get('workflow_state'), due_date=end_state.get('due_date'))))
        return facts

    # Decisions ------------------------------------------------------------------------------------
    def decisions(self, items):
        rows = []
        for item in items:
            if item['kind'] != 'decision' or item.get('dismissed') or item.get('status') != 'accepted':
                continue
            line = Timeline(item)
            accepted = next((_time(e['at']) for e in reversed(line.events) if (e.get('changes') or {}).get('status', [None, None])[1] == 'accepted' and e.get('by') == 'user'), None)
            accepted = accepted or next((_time(e['at']) for e in line.events if e.get('event') in {'meeting_review_confirm', 'confirmed'} and e.get('by') == 'user'), None)
            if not self.in_period(accepted):
                continue
            role, quote, meeting_id, stamp = None, '', None, None
            for ev in item.get('evidence', []):
                if ev.get('provider') == 'meeting' and ev.get('timestamp') and ev.get('source_id') in self.meetings:
                    said = self.speaker_at(ev['source_id'], ev['timestamp'])
                    if said and said['mine']:
                        role, quote, meeting_id, stamp = 'said it', said['text'], ev['source_id'], ev['timestamp']
                        break
            if not role:
                meeting_id = next((l['meeting_id'] for l in item.get('links', []) if l.get('meeting_id') in self.meetings and self.speaks_in(l['meeting_id'])), None)
                role = 'took part in the meeting' if meeting_id else None
            if role:
                ref = self.add('decision', item, accepted, 'A person accepted the decision', dict(text=item['text'], role=role), quote, meeting_id, stamp)
                rows.append(dict(text=item['text'], role=role, ref=ref))
        return rows

    # Coverage -------------------------------------------------------------------------------------
    def coverage(self, items):
        meetings = [m for m in self.meetings.values() if self.in_period(_time(m.get('started_at') or m.get('created')))]
        transcribed = [m for m in meetings if self.transcript(m['id'])]
        speaking = [m for m in transcribed if self.speaks_in(m['id'])]
        identities = self.person.get('identities', [])
        sources = ['meetings', 'tasks', 'decisions']
        if any(i['provider'] == 'gmail' for i in identities): sources.append('gmail')
        if any(i['provider'] == 'google_chat' for i in identities): sources.append('google_chat')
        limitations = ['Only confirmed facts count. Talk time and counts of messages or tasks do not measure productivity.',
                       'Work that nobody recorded in Atlanta is not missing work.',
                       'GitHub contribution needs its own step: Collect GitHub contribution on the draft.']
        if len(transcribed) < len(meetings):
            limitations.append(f'{len(meetings) - len(transcribed)} of {len(meetings)} meetings in the period have no transcript.')
        if not any(i['provider'] in {'gmail', 'google_chat'} for i in identities):
            limitations.append('No confirmed Gmail or Chat identity: email and Chat facts come only from tasks and decisions with those sources.')
        if not self.names:
            limitations.append('The person has no unique confirmed name, so their words in transcripts cannot be found.')
        return dict(sources=sources, limitations=limitations, meetings=len(meetings), transcribed=len(transcribed), speaking=len(speaking),
                    work_items=sum(1 for i in items if i['kind'] in {'task', 'decision'}), excluded=len(self.excluded))

    # Previous agreements --------------------------------------------------------------------------
    def carried(self, items, tasks):
        if not self.previous:
            return []
        by_id = {i['id']: i for i in items}
        seen = {t['item_id'] for t in tasks}
        rows = []
        for record in self.previous.get('evidence', []):
            item_id = (record.get('source_ref') or {}).get('item_id')
            if not record.get('facts', {}).get('open_at_end') or item_id in {r['item_id'] for r in rows}:
                continue
            item = by_id.get(item_id)
            state = 'removed' if not item else 'done' if item.get('status') == 'done' else AtlantaState.get(item.get('workflow_state'), 'open')
            rows.append(dict(item_id=item_id, text=item['text'] if item else record['facts'].get('text', ''), state=state, again=item_id in seen))
        return rows


AtlantaState = {'todo': 'to do', 'in_progress': 'in progress', 'waiting': 'waiting', 'done': 'done', 'cancelled': 'cancelled'}
COUNTS = (('assigned', 'Assigned'), ('taken on', 'Taken on (own words)'), ('completed', 'Completed'), ('result confirmed', 'Result confirmed'),
          ('overdue', 'Overdue'), ('cancelled', 'Cancelled'), ('transferred', 'Transferred to someone else'), ('joined', 'Added as a co-assignee'), ('left', 'Took part until a date'))


def collect(service, person, start, end, previous=None):
    """The evidence records, the coverage and the Markdown of a draft review."""
    c = Collector(service, person, start, end, previous)
    items = service.item_list()['items']
    tasks = c.tasks(items)
    decisions = c.decisions(items)
    # The open commitments of the last review carry over, also without new activity.
    for record in (previous or {}).get('evidence', []):
        item_id = (record.get('source_ref') or {}).get('item_id')
        if record.get('facts', {}).get('open_at_end') and item_id not in {t['item_id'] for t in tasks}:
            item = next((i for i in items if i['id'] == item_id), None)
            if item:
                line = Timeline(item)
                end_state = line.state(c.end - dt.timedelta(microseconds=1)) or {}
                facts = dict(item_id=item_id, text=item['text'], role=Timeline.role(end_state, person['id']), shared=len(end_state.get('assignee_person_ids') or []) > 1,
                             refs=[c.add('task_carried', item, c.start, 'Open in the last finalized review', dict(text=item['text'], state=end_state.get('workflow_state')))],
                             marks=['carried over'], open_at_end=Timeline.role(end_state, person['id']) is not None and end_state.get('status') != 'done',
                             state=end_state.get('workflow_state'), due_date=end_state.get('due_date'), requester=item.get('requester_person_id'))
                tasks.append(facts)
    for row in tasks:
        for ref in row['refs']:
            record = c.evidence[int(ref[1:]) - 1]
            record['facts'] = dict(record['facts'], open_at_end=row['open_at_end'])
    carried = c.carried(items, tasks)
    waits = blockers(c, items, tasks)
    coverage = c.coverage(items)
    counts = {key: sum(1 for t in tasks if key in t['marks']) for key, _ in COUNTS}
    coverage['counts'] = counts
    return dict(evidence=c.evidence, coverage=coverage, excluded=c.excluded,
                review_md=markdown(c, tasks, decisions, waits, carried, coverage, counts))


def blockers(c, items, tasks):
    """Who the person waits for, and who waits for the person. From task states and requesters only."""
    pid, rows = c.person['id'], dict(waits=[], waited_on=[])
    for t in tasks:
        if not t['open_at_end']:
            continue
        if t['role'] == 'accountable' and t['state'] == 'waiting':
            rows['waits'].append(dict(text=t['text'], on=None, ref=t['refs'][-1]))
        if t['requester'] and t['requester'] != pid:
            rows['waited_on'].append(dict(text=t['text'], by=c.name(t['requester']), ref=t['refs'][-1]))
    for item in items:
        if item['kind'] != 'task' or item.get('dismissed') or item.get('status') == 'done' or item.get('workflow_state') == 'cancelled':
            continue
        owner = item.get('owner_person_id')
        if item.get('requester_person_id') == pid and owner and owner != pid:
            ref = c.add('waits_for', item, c.end, 'A person recorded who asked for the task', dict(text=item['text'], owner=c.name(owner)))
            rows['waits'].append(dict(text=item['text'], on=c.name(owner), ref=ref))
    return rows


def markdown(c, tasks, decisions, waits, carried, coverage, counts):
    person = c.person['name']
    period = f"{c.start.astimezone(TZ).strftime('%d.%m.%Y %H:%M')} – {c.end.astimezone(TZ).strftime('%d.%m.%Y %H:%M')} (Europe/Sofia)"
    ref = lambda refs: ' ' + ' '.join(f'[{r}]' for r in refs) if refs else ''
    shared = lambda t: ' · shared' if t['shared'] else ''
    out = [f'# 1:1 review · {person}', '', f'Period: {period}', '']
    out += ['## Coverage', '']
    out.append(f"- Meetings in the period: {coverage['meetings']} · with a transcript: {coverage['transcribed']} · where {person} speaks: {coverage['speaking']}")
    out.append(f"- Sources: {', '.join({'meetings': 'Meetings', 'tasks': 'Tasks', 'decisions': 'Decisions', 'gmail': 'Gmail', 'google_chat': 'Google Chat'}[s] for s in coverage['sources'])}")
    out += [f'- {text}' for text in coverage['limitations']]
    if c.excluded:
        out += ['', '### Excluded from the analysis · needs confirmation', '']
        out += [f"- {row['text']} · {row['reason']}" for row in c.excluded]
    out += ['', '## Commitments', '']
    mine = [t for t in tasks if t['role'] == 'accountable']
    if not mine:
        out.append('_No confirmed commitments in this period._')
    for t in mine:
        state = 'done' if 'completed' in t['marks'] else AtlantaState.get(t['state'] or '', t['state'] or 'open')
        due = f" · due {_fmt_day(t['due_date'])}" if t['due_date'] else ''
        out.append(f"- {t['text']} · {state}{due}{shared(t)} · {', '.join(t['marks']) or 'open'}{ref(t['refs'])}")
    out += ['', '## Tasks', '', '| Fact | Count |', '|---|---|']
    out += [f'| {label} | {counts[key]} |' for key, label in COUNTS]
    others = [t for t in tasks if t['role'] != 'accountable']
    if others:
        out += ['', 'Took part in (another person is accountable):', '']
        for t in others:
            until = f" · until {_fmt_day(t['until'])}" if t.get('until') else ''
            out.append(f"- {t['text']}{shared(t)}{until}{ref(t['refs'])}")
    out += ['', '## Decisions', '']
    out += [f"- {d['text']} · {d['role']} [{d['ref']}]" for d in decisions] or ['_No accepted decisions with this person in this period._']
    out += ['', '## Blockers', '']
    lines = [f"- {person} waits{(' for ' + w['on']) if w['on'] else ''}: {w['text']} [{w['ref']}]" for w in waits['waits']]
    lines += [f"- {w['by']} waits for {person}: {w['text']} [{w['ref']}]" for w in waits['waited_on']]
    out += lines or ['_No recorded waiting in this period._']
    out += ['', '## GitHub contribution', '', '_Not collected yet. Choose Collect GitHub contribution… on the draft._', '']
    out += ['## Previous agreements and goals', '']
    if c.previous is None:
        out.append('_This is the first review. There are no earlier agreements yet._')
    else:
        out += [f"- {r['text']} · now {r['state']}" for r in carried] or ['_The last review had no open commitments._']
        out.append('- The notes of the last 1:1 are in that review.')
    out += ['', '## Questions for the conversation', '', '_The AI step suggests questions later. Add your own here._', '']
    return '\n'.join(out)
