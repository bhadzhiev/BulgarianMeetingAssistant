"""The exact approved review input: dated records, safe source references and connected work timelines.

A timeline is joined only through explicit local links. Similar wording never joins two tasks.
Whole timelines are packed together; an oversized timeline fails visibly instead of losing its context.
"""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import re
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from .work_items import canonical

MAX_BATCH_CHARS = 60_000
REFERENCE = re.compile(r'[A-Za-z0-9_.:-]{1,128}')
CONTEXT_KINDS = {'review_context', 'team_observation'}
FACT_FIELDS = {'text', 'role', 'shared', 'state', 'until', 'to', 'before', 'after', 'owner', 'open_at_end',
               'kind', 'status', 'task_state', 'criterion', 'checked_by', 'result_evidence', 'event', 'unlinked',
               'hotfix', 'commits', 'due_date', 'finished', 'update', 'recorded_by', 'agreed_at', 'status_recorded_at'}


def moment(value: object) -> dt.datetime | None:
    if not isinstance(value, str):
        return None
    try:
        value = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
        return value.replace(tzinfo=ZoneInfo('Europe/Sofia')) if value.tzinfo is None else value
    except ValueError:
        return None


def reference(value: object) -> str | None:
    return value if isinstance(value, str) and REFERENCE.fullmatch(value) else None


def github_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        url = urlsplit(value)
    except ValueError:
        return None
    if url.scheme != 'https' or url.netloc != 'github.com' or url.query:
        return None
    if not re.fullmatch(r'/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/(?:pull|issues)/[1-9][0-9]*|/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/commit/[a-f0-9]{40}', url.path):
        return None
    if url.fragment and not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', url.fragment):
        return None
    return urlunsplit(url)


def source_reference(source: dict) -> dict:
    out = {key: value for key in ('item_id', 'meeting_id', 'review_id', 'agreement_id', 'evidence_id', 'observation_id')
           if (value := reference(source.get(key))) is not None}
    for key in ('record_source', 'context_field'):
        if value := reference(source.get(key)):
            out[key] = value
    origins = []
    for origin in source.get('origins', []) if isinstance(source.get('origins'), list) else []:
        if not isinstance(origin, dict):
            continue
        value = origin.get('source_id')
        if origin.get('provider') not in {'meeting', 'github', 'gmail', 'google_chat'} or not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.:/-]{1,256}', value) or value.startswith(('/', 'file:')):
            continue
        clean = source_reference({k: origin[k] for k in ('provider', 'timestamp') if k in origin})
        clean['source_id'] = value
        origins.append(clean)
    if origins:
        out['origins'] = origins[:20]
    if moment(source.get('review_period_end')):
        out['review_period_end'] = source['review_period_end']
    if isinstance(source.get('item_ids'), list):
        out['item_ids'] = sorted({value for key in source['item_ids'] if (value := reference(key))})
    if source.get('provider') in {'meeting', 'github', 'gmail', 'google_chat', 'manual', 'user'}:
        out['provider'] = source['provider']
    if isinstance(source.get('timestamp'), str) and re.fullmatch(r'\d{2,}:\d{2}:\d{2}(?:\.\d+)?', source['timestamp']):
        out['timestamp'] = source['timestamp']
    if type(source.get('revision')) is int and source['revision'] >= 0:
        out['revision'] = source['revision']
    for key in ('url', 'artifact_url'):
        if value := github_url(source.get(key)):
            out[key] = value
    return out


def evidence_type(kind: str, facts: dict) -> str:
    if kind == 'result_confirmed' and not all(facts.get(key) for key in ('criterion', 'checked_by', 'result_evidence')):
        return 'linked_update_without_recorded_check'
    return {'review_context': 'manager_perspective', 'team_observation': 'ai_interpretation',
            'task_taken_on': 'owner_words_at_source', 'task_existing': 'owner_words_at_source',
            'task_update': 'reported_update', 'task_completed': 'recorded_completion',
            'result_confirmed': 'recorded_human_check'}.get(kind, 'external_event' if kind.startswith('github_') else 'recorded_event')


def input_data(review: dict) -> dict:
    from .review_context import records
    period = {k: v for k, v in (review.get('period') or {}).items() if k in {'start', 'end', 'timezone'}}
    start, end = moment(period.get('start')), moment(period.get('end'))
    rows = []
    for record in [*review.get('evidence', []), *records(review)]:
        source = source_reference(record.get('source_ref') or {})
        kind, when = record['kind'], moment(record.get('occurred_at'))
        scope = 'unknown'
        if when and start and end:
            scope = 'before_period' if when < start else 'after_period' if when >= end else 'in_period'
        basis = 'event_time'
        if kind == 'task_open':
            basis, scope = 'period_end_snapshot', 'period_end_snapshot'
        elif kind in {'agreement', 'waits_for'}:
            basis = 'current_saved_state'  # These states can have been updated after the analysed period.
        elif kind == 'review_context':
            basis = 'undated_perspective'
        elif kind == 'team_observation':
            basis = 'source_meeting_time'
        work = sorted({source.get('item_id'), *(source.get('item_ids') or [])} - {None})
        rows.append(dict(id=record['id'], kind=kind, evidence_type=evidence_type(kind, record.get('facts') or {}),
                         occurred_at=record.get('occurred_at') if when else None, time_basis=basis, period_relation=scope,
                         work_ids=work, source_ref=source, confirmation_basis=record.get('confirmation_basis', ''),
                         facts={k: copy.deepcopy(v) for k, v in (record.get('facts') or {}).items() if k in FACT_FIELDS},
                         quote=record.get('quote', ''), quote_basis=record.get('quote_basis', 'saved_source_excerpt')))
    # Python's stable sort preserves source order for simultaneous/unknown events.
    rows.sort(key=lambda row: (moment(row['occurred_at']) is None, moment(row['occurred_at']) or dt.datetime.max.replace(tzinfo=dt.timezone.utc)))
    _assign_timelines(rows)
    coverage = review.get('coverage') or {}
    safe_coverage = {k: copy.deepcopy(v) for k, v in coverage.items() if k in {'fact_version', 'sources', 'limitations', 'meetings', 'transcribed', 'speaking', 'excluded'}}
    safe_coverage['counts_status'] = 'current_rules' if coverage.get('fact_version', 1) >= 2 else 'legacy_rules_ignored'
    if coverage.get('fact_version', 1) >= 2 and 'counts' in coverage:
        safe_coverage['counts'] = copy.deepcopy(coverage['counts'])
    return dict(person=review['person_name'], review_id=review.get('id'), period=period,
                conversation_at=review.get('conversation_at'),
                coverage=safe_coverage,
                records=rows)


def _assign_timelines(rows: list[dict]) -> None:
    parents = {}
    def root(key):
        parents.setdefault(key, key)
        if parents[key] != key:
            parents[key] = root(parents[key])
        return parents[key]
    refs = []
    for row in rows:
        source = row['source_ref']
        keys = ['item:' + key for key in row['work_ids']]
        if source.get('agreement_id'):
            keys.append('agreement:' + source['agreement_id'])
        if url := source.get('artifact_url') or source.get('url'):
            keys.append('github:' + url.split('#', 1)[0])
        if not keys:
            keys = ['context' if row['kind'] in CONTEXT_KINDS else 'record:' + row['id']]
        for key in keys:
            left, right = root(keys[0]), root(key)
            if left != right:
                parents[max(left, right)] = min(left, right)
        refs.append(keys[0])
    for row, key in zip(rows, refs):
        row['timeline_id'] = 'tl-' + hashlib.sha256(root(key).encode()).hexdigest()[:16]


def _payload(data: dict, rows: list[dict], context: list[dict]) -> dict:
    records = sorted([*rows, *context], key=lambda row: (moment(row.get('occurred_at')) is None,
        moment(row.get('occurred_at')) or dt.datetime.max.replace(tzinfo=dt.timezone.utc)))
    groups = {}
    for row in records:
        group = groups.setdefault(row['timeline_id'], dict(id=row['timeline_id'], work_ids=set(), record_ids=[]))
        group['work_ids'].update(row['work_ids'])
        group['record_ids'].append(row['id'])
    return dict({k: copy.deepcopy(v) for k, v in data.items() if k != 'records'}, records=records,
                timelines=[dict(g, work_ids=sorted(g['work_ids'])) for g in groups.values()])


def timeline_batches(data: dict, soft_limit: int = 40) -> list[dict]:
    # Unlinked private context applies to all work; it is repeated, exactly as shown in the preview.
    context, groups = [], {}
    for row in data['records']:
        if row['kind'] in CONTEXT_KINDS and not row['work_ids']:
            context.append(row)
        else:
            groups.setdefault(row['timeline_id'], []).append(row)
    chunks, pending = [], []
    for group in groups.values():
        one = _payload(data, group, context)
        if len(canonical(one)) > MAX_BATCH_CHARS:
            label = (group[0].get('facts') or {}).get('text', group[0]['id'])[:100]
            raise ValueError('One work timeline is too large for AI preparation: ' + label + '. Choose a shorter period or fewer context observations; its history will not be split or truncated.')
        candidate = _payload(data, pending + group, context)
        if pending and (len(pending) + len(group) + len(context) > soft_limit or len(canonical(candidate)) > MAX_BATCH_CHARS):
            chunks.append(_payload(data, pending, context))
            pending = []
        pending += group
    if pending or not chunks:
        last = _payload(data, pending, context)
        if len(canonical(last)) > MAX_BATCH_CHARS:
            raise ValueError('The private review context is too large. Select fewer observations or shorten it.')
        chunks.append(last)
    return chunks
