from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
import re

from .storage import atomic_text

STAMP = re.compile(r'^\s*\[(?:(\d{1,2}):)?(\d{1,2}):(\d{2})(?:[.,]\d+)?\]\s*(.*)$')
SRT_TIME = re.compile(r'(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})')
SPEAKER = re.compile(r'^([^:.,!?;\[\]()]{1,60}?):\s+(.*)$')
DATE = re.compile(r'\b(\d{1,2}) (Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* (\d{4})\b')
MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']


def _seconds(hours, minutes, seconds, millis='0'):
    return int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds) + int(millis.ljust(3, '0')) / 1000


def _speakers(items, known, header):
    """Split "Name: text" only when the prefix looks like a name.

    A single "Защото пише: ..." line must stay text, not become a speaker.
    """
    candidates = [SPEAKER.match(text) for _, _, text in items]
    counts = {}
    for match in candidates:
        if match and len(match[1].split()) <= 5:
            counts[match[1].strip()] = counts.get(match[1].strip(), 0) + 1
    folded = {name.casefold() for name in known}
    result = []
    for (start, end, text), match in zip(items, candidates):
        name = match[1].strip() if match else ''
        capitalized = all(word[:1].isupper() for word in name.split())
        if name and (counts.get(name, 0) >= 2 or name.casefold() in folded or name in header or capitalized):
            result.append(dict(start=start, end=end, text=match[2].strip(), speaker=name))
        else:
            result.append(dict(start=start, end=end, text=text.strip(), speaker=None))
    return result


def _parse_srt(text):
    items = []
    for block in re.split(r'\n\s*\n', text):
        lines = [line.strip() for line in block.strip().splitlines()]
        for index, line in enumerate(lines):
            match = SRT_TIME.search(line)
            if match:
                body = ' '.join(lines[index + 1:]).strip()
                if body:
                    items.append((_seconds(*match.groups()[:4]), _seconds(*match.groups()[4:]), body))
                break
    return items


def _parse_stamped(lines):
    items, open_item, gap = [], None, False
    for line in lines:
        match = STAMP.match(line)
        if match:
            open_item = [_seconds(*match.groups()[:3]), None, match[4].strip()]
            items.append(open_item)
            gap = False
        elif not line.strip():
            gap = True
        elif open_item and not gap:
            # Wrapped lines continue a segment. Text after a blank line (a signature) is dropped.
            open_item[2] += ' ' + line.strip()
    for index, item in enumerate(items):
        following = items[index + 1][0] if index + 1 < len(items) else None
        words = len(item[2].split())
        item[1] = following if following is not None and following >= item[0] else item[0] + max(2, words * 0.4)
    return [tuple(item) for item in items if item[2]]


def parse_transcript(text: str, known_speakers=()) -> dict:
    """Read "[00:00:00] Name: text" lines, or SRT cues, into transcript segments."""
    text = text.replace('\r\n', '\n').replace('\r', '\n').lstrip('﻿')
    lines = text.split('\n')
    first = next((i for i, line in enumerate(lines) if STAMP.match(line)), None)
    items = _parse_srt(text) if first is None and SRT_TIME.search(text) else _parse_stamped(lines)
    if not items:
        raise ValueError('No timestamps found. Use lines like "[00:00:00] Name: text", or an SRT file.')
    previous = 0
    for start, end, _ in items:
        if start < previous:
            raise ValueError('Timestamps must go forward through the transcript')
        previous = start
    header = [line.strip() for line in lines[:first or 0] if line.strip()]
    # Prefer "<name>: transcript", then "Transcript: <name>", then a Markdown heading.
    title = None
    for pattern in [r'^#*\s*(.+?):\s*transcript$', r'^#*\s*transcript:\s*(.+)$', r'^#+\s*(.+)$']:
        title = next((m[1].strip() for m in (re.match(pattern, line, re.I) for line in header) if m and len(m[1]) <= 160), None)
        if title:
            break
    match = DATE.search(title or '') or next((m for m in map(DATE.search, header) if m), None)
    date = dt.date(int(match[3]), MONTHS.index(match[2]) + 1, int(match[1])) if match else None
    return dict(title=title, date=date, segments=_speakers(items, known_speakers, '\n'.join(header)))


def transcript_markdown(segments, title=None) -> str:
    from meeting_assistant import timestamp
    get = lambda segment, key: segment[key] if isinstance(segment, dict) else getattr(segment, key)
    speakers = list(dict.fromkeys(get(s, 'speaker') for s in segments if get(s, 'speaker')))
    minutes = max(1, round(max((get(s, 'end') for s in segments), default=0) / 60))
    lines = [f'# {title}: transcript' if title else '# Transcript', '']
    lines.append((', '.join(speakers) + '. ' if speakers else '') + f'{minutes} min.')
    for segment in segments:
        speaker = get(segment, 'speaker')
        lines += ['', f"[{timestamp(get(segment, 'start'))}] {speaker + ': ' if speaker else ''}{get(segment, 'text')}"]
    return '\n'.join(lines) + '\n'


def meeting_title(directory: Path):
    try:
        return json.loads((directory / 'meeting.json').read_text())['title']
    except (OSError, ValueError, KeyError, TypeError):
        return None


def refresh_markdown(directory: Path) -> None:
    """Rewrite the Markdown copies so their heading follows a renamed meeting."""
    title = meeting_title(directory)
    for source, target in [('transcript.json', 'transcript.md'), ('live-transcript.json', 'live-transcript.md')]:
        try:
            segments = json.loads((directory / source).read_text())
        except (OSError, ValueError):
            continue
        if isinstance(segments, list):
            atomic_text(directory / target, transcript_markdown(segments, title))
