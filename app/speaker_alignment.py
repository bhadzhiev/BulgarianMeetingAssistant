"""Post-recording alignment. Never invent word times from character positions."""
import hashlib
import json
import math

from .analytics import clean_intervals


def revision(segments):
    content = [{k: row.get(k) for k in ('start', 'end', 'text')} for row in segments]
    return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def group_units(units):
    result = []
    previous = 0
    for unit in units:
        start, end, text = unit['start'], unit['end'], unit['text']
        if (type(start) not in (int, float) or type(end) not in (int, float)
                or not math.isfinite(start) or not math.isfinite(end) or not previous <= start <= end
                or not isinstance(text, str) or not text.strip()):
            raise ValueError('Invalid Whisper alignment unit')
        previous = start
        row = dict(start=start, end=end, text=text.strip(), speaker=unit.get('speaker'))
        if (result and result[-1]['speaker'] == row['speaker']
                and 0 <= start - result[-1]['end'] < .8
                and end - result[-1]['start'] <= 10
                and len(result[-1]['text']) + len(text) < 180):
            result[-1]['text'] += ' ' + row['text']
            result[-1]['end'] = end
        else:
            result.append(row)
    return result


def align(source, saved, intervals):
    if (not isinstance(saved, dict) or saved.get('version') != 1
            or saved.get('source_revision') != revision(source)):
        raise ValueError('Word alignment does not match the current transcript')
    units = saved.get('units')
    if not isinstance(units, list) or not units or len(units) > 1000000:
        raise ValueError('No usable Whisper word boundaries')
    group_units(units)  # Validate before using any unit.
    if ' '.join(u['text'].strip() for u in units) != ' '.join(s['text'] for s in source):
        raise ValueError('Word alignment text does not match the transcript')
    timeline = clean_intervals(intervals)
    if not timeline:
        raise ValueError('No speaker intervals')
    rows, first = [], 0
    for unit in units:
        start, end = unit['start'], unit['end']
        while first < len(timeline) and timeline[first]['end'] < start:
            first += 1
        overlap = {}
        for index in range(first, len(timeline)):
            turn = timeline[index]
            if turn['start'] > end:
                break
            amount = max(0, min(end, turn['end']) - max(start, turn['start']))
            if amount:
                overlap[turn['speaker']] = overlap.get(turn['speaker'], 0) + amount
        best = sorted(overlap, key=overlap.get, reverse=True)
        # Equal overlap is ambiguous. Leave it unnamed rather than guessing.
        speaker = best[0] if best and (len(best) == 1 or overlap[best[0]] > overlap[best[1]]) else None
        rows.append(dict(unit, speaker=speaker))
    # Keep every original segment start: notes may already cite that timestamp.
    # Subdivide inside it, but never merge across an existing source boundary.
    result, offset = [], 0
    for segment in source:
        text, end = '', offset
        while end < len(rows) and text != segment['text']:
            text += (' ' if text else '') + rows[end]['text'].strip()
            end += 1
            if not segment['text'].startswith(text):
                raise ValueError('Word units do not match source segment boundaries')
        if text != segment['text'] or end == offset or rows[offset]['start'] != segment['start'] or rows[end-1]['end'] != segment['end']:
            raise ValueError('Word units do not match source segment boundaries')
        result.extend(group_units(rows[offset:end]))
        offset = end
    if offset != len(rows):
        raise ValueError('Unmatched word units')
    return result
