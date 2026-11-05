"""Post-recording alignment. Never invent word times from character positions."""
import hashlib
import json
import math

from .analytics import clean_intervals

# Diarization flickers between speakers in turns shorter than this during interruptions.
MIN_TURN = .3
# A word in a pause shorter than this belongs to the nearest turn.
MAX_GAP = .5
# Unnamed words between two parts of one speaker's speech belong to that speaker within this time.
MAX_FILL = 3.
# Word times and turn boundaries disagree by a few words; move a change to a sentence end this close.
SNAP_WORDS = 2
# Never move a word further than this from the turn boundary.
SNAP_SECONDS = 1.
SENTENCE_END = ('.', '?', '!', '…', '-', '—')


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


def _speaker(timeline, first, start, end):
    overlap, nearest = {}, None
    for index in range(max(0, first - 1), len(timeline)):
        turn = timeline[index]
        if turn['start'] > end + MAX_GAP:
            break
        amount = max(0, min(end, turn['end']) - max(start, turn['start']))
        if amount:
            overlap[turn['speaker']] = overlap.get(turn['speaker'], 0) + amount
        distance = max(0, turn['start'] - end, start - turn['end'])
        if distance <= MAX_GAP and (nearest is None or distance < nearest[0]):
            nearest = (distance, turn['speaker'])
    best = sorted(overlap, key=overlap.get, reverse=True)
    if best:
        # Equal overlap is ambiguous. Leave it unnamed rather than guessing.
        return best[0] if len(best) == 1 or overlap[best[0]] > overlap[best[1]] else None
    # A zero-length word or a word in a short pause has no overlap; use the closest turn.
    return nearest[1] if nearest else None


def _fill(rows):
    """Give an isolated word, or an unnamed pause, the speaker on both sides of it."""
    ends = lambda index: rows[index]['text'].rstrip().endswith(SENTENCE_END)
    index = 1
    while index < len(rows) - 1:
        before = rows[index - 1]['speaker']
        last = index
        if rows[index]['speaker'] is None:
            while last + 1 < len(rows) and rows[last + 1]['speaker'] is None:
                last += 1
            short = rows[last]['end'] - rows[index]['start'] <= MAX_FILL
        else:
            # One word inside another speaker's sentence is diarization flicker; a reply ends a sentence.
            short = not ends(index)
        if (before and last + 1 < len(rows) and rows[last + 1]['speaker'] == before
                and rows[index]['speaker'] != before and short):
            for i in range(index, last + 1):
                rows[i]['speaker'] = before
        index = last + 1
    return rows


def _snap(rows):
    """Move a speaker change to a nearby sentence end. Word times lag turn boundaries."""
    ends = lambda index: rows[index]['text'].rstrip().endswith(SENTENCE_END)
    for index in range(1, len(rows)):
        before, after = rows[index - 1]['speaker'], rows[index]['speaker']
        if not before or not after or before == after or ends(index - 1):
            continue
        for shift in sorted(range(-SNAP_WORDS, SNAP_WORDS + 1), key=abs):
            cut = index + shift
            if shift and 0 < cut < len(rows) and ends(cut - 1):
                span = range(index, cut) if shift > 0 else range(cut, index)
                boundary = (rows[index - 1]['end'] + rows[index]['start']) / 2
                if all(rows[i]['speaker'] in {before, after} and rows[i]['start'] - SNAP_SECONDS <= boundary
                       <= rows[i]['end'] + SNAP_SECONDS for i in span):
                    for i in span:
                        rows[i]['speaker'] = before if shift > 0 else after
                break
    return rows


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
    # Keep a speaker who has only short turns; drop only flicker inside other speech.
    kept = [turn for turn in timeline if turn['end'] - turn['start'] >= MIN_TURN]
    present = {turn['speaker'] for turn in kept}
    timeline = [turn for turn in timeline if turn in kept or turn['speaker'] not in present]
    rows, first = [], 0
    for unit in units:
        start, end = unit['start'], unit['end']
        while first < len(timeline) and timeline[first]['end'] < start:
            first += 1
        rows.append(dict(unit, speaker=_speaker(timeline, first, start, end)))
    for index, row in enumerate(rows):
        # Scribe returns some punctuation as separate zero-length words; it ends the previous word.
        if index and not any(c.isalnum() for c in row['text']):
            row['speaker'] = rows[index - 1]['speaker']
    rows = _snap(_fill(rows))
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
