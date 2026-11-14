"""Selected private context for a 1:1. Saved AI observations stay interpretations, never confirmed facts."""
from __future__ import annotations

import hashlib
import json

from .team_facts import _time

FIELDS = {'role': 'Role and expectations', 'employee_view': 'The person’s view, recorded by the manager',
          'manager_support': 'Support and dependencies on the manager', 'focus': 'Development focus'}


def candidates(service, review: dict) -> list[dict]:
    from . import team_analysis
    person = service._team_person(review['person_id'])
    names = {n for n in service._person_names(person) if len(service.people.matching(n)) == 1}
    start, end = _time(review['period']['start']), _time(review['period']['end'])
    rows = []
    for meeting in service.library.list():
        when = _time(meeting.get('started_at') or meeting.get('created'))
        if when is None or not start <= when < end:
            continue
        saved = team_analysis.read(service, meeting['id'])
        if not saved or saved.get('stale'):
            continue
        analysis = saved['analysis']
        observations = []
        for p in analysis.get('people', []):
            if p.get('name', '').casefold() in names:
                observations += [(key, row) for key in ('ownership', 'proactivity', 'reporting') for row in p.get(key, [])]
        if saved.get('manager', '').casefold() in names:
            observations += [('manager_' + key, row) for key in ('keep', 'change', 'develop') for row in analysis.get('coaching', {}).get(key, [])]
        transcript = service.library.directory(meeting['id']) / 'transcript.json'
        segments = json.loads(transcript.read_text(encoding='utf-8')) if transcript.exists() else []
        from .transcripts import stamp_seconds
        for category, row in observations:
            stamp = row.get('evidence_timestamp')
            try:
                second = stamp_seconds(stamp)
            except (TypeError, ValueError):
                continue
            segment = next((s for s in segments if s.get('start', 0) <= second <= s.get('end', s.get('start', 0))), None)
            if not segment:
                continue
            entry = dict(meeting_id=meeting['id'], meeting_title=meeting['title'], occurred_at=when.isoformat(),
                         timestamp=stamp, category=category, text=row['text'], quote=segment.get('text', '')[:500],
                         transcript=saved['transcript'])
            entry['id'] = hashlib.sha256(json.dumps(entry, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:24]
            rows.append(entry)
    return sorted(rows, key=lambda r: (r['occurred_at'], r['timestamp']), reverse=True)[:200]


def records(review: dict) -> list[dict]:
    """Private records have distinct IDs after the public evidence. Only an explicit choice includes them in AI."""
    context = review.get('context') or {}
    if not context.get('include_in_ai'):
        return []
    first = max((int(r['id'][1:]) for r in review.get('evidence', [])), default=0)
    rows = []
    for key, label in FIELDS.items():
        if context.get(key):
            rows.append(dict(kind='review_context', confirmation_basis='Context recorded by the manager; not independent confirmation',
                             facts=dict(text=label + ': ' + context[key]), quote='',
                             source_ref=dict(review_id=review.get('id'), context_field=key, record_source='manager_context')))
    for observation in context.get('observations', []):
        rows.append(dict(kind='team_observation', confirmation_basis='AI interpretation selected for discussion; not a confirmed fact',
                         facts=dict(text=observation['text']), quote=observation['quote'],
                         source_ref=dict(meeting_id=observation['meeting_id'], timestamp=observation['timestamp'],
                                         review_id=review.get('id'), observation_id=observation['id'], record_source='team_analysis'),
                         occurred_at=observation['occurred_at']))
    return [dict(row, id='e' + str(first + i + 1)) for i, row in enumerate(rows)]
