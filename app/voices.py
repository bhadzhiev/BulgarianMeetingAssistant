"""Local voice prints: suggest a name for an unnamed speaker from the voices of earlier meetings.

A voice print is the mean speaker embedding of a speaker's longest turns in one meeting.
It stays in the meeting folder and never leaves this Mac. A suggestion is only a suggestion:
a person listens and applies the name, and the name then teaches the next meeting.

Thresholds come from same-person and different-person pairs across real meetings:
the same person scored 0.82-0.90, different people at most 0.68.
These observations do not establish identity; distinct confirmed people remain rivals.
"""
import hashlib
import json
import os
import secrets
import re
import threading
import wave

import numpy as np

from .storage import atomic_json

FILE = 'voiceprints.json'
GENERIC = re.compile(r'^SPEAKER[ _-]?\d+$', re.I)
MIN_TURN, MAX_TURN, ENOUGH = 1.0, 10.0, 60.0
MATCH, MARGIN, MIN_SECONDS = 0.75, 0.10, 10.0
_cache, _cache_lock = {}, threading.Lock()


def _unit(values):
    vector = np.asarray(values, dtype=np.float64)
    return vector / (np.linalg.norm(vector) or 1)


def turns_file(directory):
    for name in ('speaker-turns.json', 'speaker-timeline.json'):
        if (directory / name).exists():
            return directory / name
    return None


def compute(directory, embed, model, progress=lambda message: None):
    """Embed each speaker's longest turns; embed takes float32 16 kHz samples and returns a vector."""
    # Keep the original directory open: publishing must never recreate a deleted path.
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        return _compute(directory, fd, embed, model, progress)
    finally:
        os.close(fd)


def _compute(directory, fd, embed, model, progress):
    path = turns_file(directory)
    if path is None or not (directory / 'recording.wav').is_file():
        raise ValueError('Voice prints need a recording and speaker turns')
    data = path.read_bytes()
    turns = json.loads(data)
    speakers = {}
    with wave.open(str(directory / 'recording.wav'), 'rb') as audio:
        if audio.getsampwidth() != 2:
            raise ValueError('Voice prints need 16-bit audio')
        rate, channels = audio.getframerate(), audio.getnchannels()
        by_speaker = {}
        for turn in turns:
            if turn.get('speaker') and turn['end'] - turn['start'] >= MIN_TURN:
                by_speaker.setdefault(turn['speaker'], []).append(turn)
        for number, (speaker, rows) in enumerate(by_speaker.items(), 1):
            progress(f'Learning voices · speaker {number} of {len(by_speaker)}')
            vectors, weights = [], []
            for turn in sorted(rows, key=lambda t: t['end'] - t['start'], reverse=True):
                start, end = turn['start'], min(turn['end'], turn['start'] + MAX_TURN)
                audio.setpos(min(int(start * rate), audio.getnframes()))
                frames = np.frombuffer(audio.readframes(int((end - start) * rate)), dtype='<i2')
                samples = frames.reshape(-1, channels).mean(axis=1).astype(np.float32) / 32768
                if rate != 16000:
                    samples = np.interp(np.arange(0, len(samples), rate / 16000), np.arange(len(samples)), samples).astype(np.float32)
                if len(samples) < 16000 * MIN_TURN:
                    continue
                progress('Learning voice sample')
                vector = np.asarray(embed(samples), dtype=np.float64)
                if vector.ndim != 1 or not np.all(np.isfinite(vector)) or not np.linalg.norm(vector):
                    continue
                vectors.append(vector / np.linalg.norm(vector))
                weights.append(len(samples) / 16000)
                if sum(weights) >= ENOUGH:
                    break
            if vectors:
                mean = np.average(vectors, axis=0, weights=weights)
                speakers[speaker] = dict(vector=[round(float(v), 5) for v in mean / np.linalg.norm(mean)],
                                         seconds=round(sum(weights), 1))
    progress('Publishing voice profiles')
    if (turns_file(directory) != path or path.read_bytes() != data
            or os.stat(directory).st_ino != os.fstat(fd).st_ino):
        raise ValueError('Speaker turns changed during voice learning; retry from the saved corrections')
    _publish(fd, dict(model=model, turns=hashlib.sha256(data).hexdigest(), speakers=speakers))
    return speakers


def _publish(fd, value):
    temporary = '.voiceprints-' + secrets.token_hex(12)
    handle = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=fd)
    try:
        with os.fdopen(handle, 'w') as output:
            json.dump(value, output, ensure_ascii=False, allow_nan=False)
            output.write('\n'); output.flush(); os.fsync(output.fileno())
        os.replace(temporary, FILE, src_dir_fd=fd, dst_dir_fd=fd)
    finally:
        try:
            os.unlink(temporary, dir_fd=fd)
        except FileNotFoundError:
            pass


def current(directory):
    """True when the voice prints were made from the present speaker turns."""
    path = turns_file(directory)
    prints = read(directory)
    try:
        return bool(prints and path and prints.get('turns') == hashlib.sha256(path.read_bytes()).hexdigest())
    except OSError:
        return False


def read(directory):
    path = directory / FILE
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    stamp = (stat.st_mtime_ns, stat.st_size)
    with _cache_lock:
        hit = _cache.get(path)
        if hit and hit[0] == stamp:
            return hit[1]
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    with _cache_lock:
        _cache[path] = (stamp, value)
    return value


def rename(directory, renames, turns_hash=None):
    """Follow a speaker name change. Two labels named as one person merge, weighted by audio."""
    prints = read(directory)
    if not prints or not renames:
        return
    merged = {}
    for speaker, row in prints['speakers'].items():
        name = renames.get(speaker, speaker)
        if name in merged:
            a, b = merged[name], row
            mean = np.add(np.multiply(a['vector'], a['seconds']), np.multiply(b['vector'], b['seconds']))
            merged[name] = dict(vector=[round(float(v), 5) for v in mean / np.linalg.norm(mean)], seconds=round(a['seconds'] + b['seconds'], 1))
        else:
            merged[name] = row
    # The rename also relabels the turns file; the prints still describe the same audio.
    atomic_json(directory / FILE, dict(prints, speakers=merged, turns=turns_hash or prints.get('turns')))


def bank(library, exclude, identity, model):
    """Named voice prints from other meetings, grouped by person. identity(name) -> (key, display name)."""
    groups = {}
    for meeting in library.list():
        if meeting['id'] == exclude:
            continue
        directory = library.directory(meeting['id'])
        prints = read(directory)
        if not current(directory) or not prints or prints.get('model') != model:
            continue
        for name, row in prints['speakers'].items():
            if GENERIC.match(name) or row['seconds'] < MIN_SECONDS:
                continue
            key, display = identity(name)
            group = groups.setdefault(key, dict(name=display, vectors=[], meetings=set(), person=key[0] == 'person'))
            group['vectors'].append(_unit(row['vector']))
            group['meetings'].add(meeting['id'])
    return groups


def suggest(prints, groups, present):
    """Suggest a person for each unnamed speaker; skip near ties and people already in the meeting."""
    candidates = {k: g for k, g in groups.items() if k not in present}
    scored = []
    for speaker, row in (prints or {}).get('speakers', {}).items():
        if not GENERIC.match(speaker) or row['seconds'] < MIN_SECONDS:
            continue
        vector = _unit(row['vector'])
        scores = sorted(((float(max(v @ vector for v in g['vectors'])), k) for k, g in candidates.items()), key=lambda row: row[0], reverse=True)
        if not scores or scores[0][0] < MATCH:
            continue
        # Identity aliases were grouped by bank(); voice similarity cannot merge identities.
        if len(scores) > 1 and scores[0][0] - scores[1][0] < MARGIN:
            continue
        scored.append((scores[0][0], scores[0][1], speaker))
    result, used = {}, set()
    for score, key, speaker in sorted(scored, key=lambda row: row[0], reverse=True):
        if key in used:
            continue
        used.add(key)
        result[speaker] = dict(name=candidates[key]['name'], similarity=round(score, 2), meetings=len(candidates[key]['meetings']))
    return result
