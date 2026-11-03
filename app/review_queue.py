"""One list of the meetings that still wait for a person, across the whole library.

A meeting is in the queue when it has speakers without a name, items that its Review tab
shows as needs_review, or notes that wait for an update. The queue reads only; each row
links to the meeting view where a person resolves it.
"""
import hashlib
import json
import re
import threading
from . import items
from .meeting_review import linked, meeting_state, source_digest

GENERIC = re.compile(r'^SPEAKER[ _-]?\d+$', re.I)
_cache, _cache_lock = {}, threading.Lock()


def _cached(path, read):
    """Parse a file once per change; a large library opens the queue without a full reread."""
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    stamp = (stat.st_mtime_ns, stat.st_size)
    with _cache_lock:
        hit = _cache.get(path)
        if hit and hit[0] == stamp:
            return hit[1]
    value = read(path.read_bytes())
    with _cache_lock:
        _cache[path] = (stamp, value)
    return value


def _transcript(data):
    transcript = json.loads(data)
    return dict(revision=hashlib.sha256(json.dumps(transcript, sort_keys=True).encode()).hexdigest(),
                speakers=len({s['speaker'] for s in transcript if s.get('speaker') and GENERIC.match(s['speaker'])}))


def _minutes(data):
    from meeting_assistant import validate_minutes
    minutes, ids = json.loads(data), set()
    try:
        validate_minutes(minutes)
    except ValueError:
        # The meeting view shows no items for notes that do not validate; the queue does the same.
        return dict(revision=hashlib.sha256(data).hexdigest(), ids=ids)
    for field in items.FIELD.values():
        for mention in minutes.get(field, []):
            ids.add(mention.get('item_id'))
            ids.update(c.get('item_id') for c in (mention.get('link') or {}).get('candidates', []))
    return dict(revision=hashlib.sha256(data).hexdigest(), ids=ids)


def build(service):
    with service.lock, service.items.lock:
        rows = []
        for meeting in service.library.list():
            if meeting.get('status') != 'ready':
                continue
            directory = service.library.directory(meeting['id'])
            transcript = _cached(directory / 'transcript.json', _transcript)
            if transcript is None:
                continue
            minutes = _cached(directory / 'minutes.json', _minutes) or dict(revision=None, ids=set())
            source = source_digest(transcript['revision'], minutes['revision'])
            pending = [item for key in minutes['ids'] if (item := service.items.items.get(key))
                       and linked(item, meeting['id']) and meeting_state(item, meeting['id'], source) == 'needs_review']
            notes = ('proposal' if (directory / 'minutes.proposed.json').exists()
                     else 'refresh' if meeting.get('notes_need_refresh') or meeting.get('notes_refresh_error') else None)
            if not (pending or transcript['speakers'] or notes):
                continue
            rows.append(dict(id=meeting['id'], title=meeting['title'], created=meeting['created'],
                             speakers=transcript['speakers'], notes=notes,
                             items=len(pending)))
        return dict(meetings=rows, totals=dict(meetings=len(rows), speakers=sum(r['speakers'] for r in rows),
                                               items=sum(r['items'] for r in rows), notes=sum(bool(r['notes']) for r in rows)))
