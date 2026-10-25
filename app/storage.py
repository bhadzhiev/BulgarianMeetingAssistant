from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import threading
import uuid


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def atomic_json(path: Path, value) -> None:
    atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2) + '\n')


class Library:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.speakers_path = self.root / 'speakers.json'
        self.trackers_path = self.root / 'trackers.json'
        # Finish deletions that a crash interrupted after the meeting left the library.
        # Uploads that a crash interrupted never became meetings.
        for leftover in [*self.root.glob('.deleted-*'), *self.root.glob('.upload-*'), *self.root.glob('.restore-*')]:
            if leftover.is_dir() and not leftover.is_symlink():
                shutil.rmtree(leftover, ignore_errors=True)
        # Audio preparation that a crash interrupted leaves a large temporary WAV in the meeting folder.
        for leftover in self.root.glob('[0-9a-f]*/.transcription-*.wav'):
            if leftover.is_file() and not leftover.is_symlink():
                leftover.unlink(missing_ok=True)

    def directory(self, meeting_id: str) -> Path:
        if not re.fullmatch(r'[a-f0-9]{32}', meeting_id):
            raise ValueError('Invalid meeting ID')
        path = self.root / meeting_id
        if not path.is_dir() or path.is_symlink():
            raise FileNotFoundError('Meeting not found')
        return path

    def create(self, title: str, mode: str, settings: dict) -> dict:
        with self.lock:
            meeting_id = uuid.uuid4().hex
            directory = self.root / meeting_id
            directory.mkdir(mode=0o700)
            meeting = dict(id=meeting_id, title=title.strip()[:160] or 'Untitled meeting',
                           mode=mode, created=dt.datetime.now().astimezone().isoformat(),
                           status='starting', duration=0, error=None, settings=settings,
                           title_source='manual' if title.strip() else 'pending', title_revision=0,
                           title_status='manual' if title.strip() else 'pending',
                           warnings=[], progress='Preparing recording')
            atomic_json(directory / 'meeting.json', meeting)
            return meeting

    def get(self, meeting_id: str) -> dict:
        return json.loads((self.directory(meeting_id) / 'meeting.json').read_text())

    def update(self, meeting_id: str, **changes) -> dict:
        with self.lock:
            meeting = self.get(meeting_id)
            renamed = 'title' in changes and changes['title'] != meeting['title']
            meeting.update(changes)
            atomic_json(self.directory(meeting_id) / 'meeting.json', meeting)
            if renamed:
                from .transcripts import refresh_markdown
                refresh_markdown(self.directory(meeting_id))
            return meeting

    def delete(self, meeting_id: str) -> None:
        with self.lock:
            directory = self.directory(meeting_id)
            # Renaming first removes the meeting from the library atomically.
            trash = self.root / ('.deleted-' + meeting_id)
            os.replace(directory, trash)
        shutil.rmtree(trash, ignore_errors=True)

    def speakers(self) -> list[str]:
        try:
            names = json.loads(self.speakers_path.read_text())
        except (OSError, ValueError):
            return []
        return [name for name in names if isinstance(name, str)] if isinstance(names, list) else []

    def save_speakers(self, names) -> list[str]:
        if not isinstance(names, list) or len(names) > 500:
            raise ValueError('Invalid speaker list')
        result, seen = [], set()
        for name in names:
            if not isinstance(name, str):
                raise ValueError('Speaker names must be text')
            name = ' '.join(name.split())
            if not name:
                continue
            if len(name) > 80 or any(ord(c) < 32 for c in name):
                raise ValueError('Speaker names must be one line of at most 80 characters')
            if name.casefold() not in seen:
                seen.add(name.casefold())
                result.append(name)
        with self.lock:
            atomic_json(self.speakers_path, result)
        return result

    def add_speakers(self, names) -> list[str]:
        # Learned labels are best effort; invalid ones stay in the transcript only.
        valid = [' '.join(n.split()) for n in names if isinstance(n, str)]
        valid = [n for n in valid if n and len(n) <= 80 and not any(ord(c) < 32 for c in n)]
        with self.lock:
            known = self.speakers()
            folded = {n.casefold() for n in known}
            new = [n for n in dict.fromkeys(valid) if n.casefold() not in folded]
            if not new:
                return known
            return self.save_speakers((known + new)[:500])

    def trackers(self) -> list[dict]:
        try:
            value = json.loads(self.trackers_path.read_text())
        except (OSError, ValueError):
            return []
        return value if isinstance(value, list) else []

    def save_trackers(self, trackers) -> list[dict]:
        if not isinstance(trackers, list) or len(trackers) > 100:
            raise ValueError('Invalid topic tracker list')
        result, ids, names = [], set(), set()
        for tracker in trackers:
            if not isinstance(tracker, dict) or set(tracker) - {'id', 'name', 'phrases', 'semantic_matching'}:
                raise ValueError('Invalid topic tracker')
            name = tracker.get('name')
            phrases = tracker.get('phrases')
            semantic = tracker.get('semantic_matching', False)
            if not isinstance(name, str) or not name.strip() or len(name.strip()) > 100:
                raise ValueError('Topic names must be between 1 and 100 characters')
            if not isinstance(phrases, list) or not 1 <= len(phrases) <= 50:
                raise ValueError('Each topic needs between 1 and 50 phrases')
            if type(semantic) is not bool:
                raise ValueError('Semantic matching must be true or false')
            clean_phrases = []
            for phrase in phrases:
                if not isinstance(phrase, str) or not phrase.strip() or len(phrase.strip()) > 200:
                    raise ValueError('Topic phrases must be between 1 and 200 characters')
                clean_phrases.append(' '.join(phrase.split()))
            tracker_id = tracker.get('id') or uuid.uuid4().hex
            if not isinstance(tracker_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', tracker_id):
                raise ValueError('Invalid topic tracker ID')
            if tracker_id in ids or name.strip().casefold() in names:
                raise ValueError('Topic tracker IDs and names must be unique')
            ids.add(tracker_id)
            names.add(name.strip().casefold())
            result.append(dict(id=tracker_id, name=name.strip(), phrases=list(dict.fromkeys(clean_phrases)),
                               semantic_matching=semantic))
        with self.lock:
            atomic_json(self.trackers_path, result)
        return result

    def list(self, query: str = '') -> list[dict]:
        result = []
        with self.lock:
            for path in self.root.glob('*/meeting.json'):
                if path.parent.is_symlink():
                    continue
                try:
                    meeting = self.get(path.parent.name)
                    text = meeting['title']
                    if query:
                        transcript = path.parent / 'transcript.md'
                        if not transcript.exists():
                            transcript = path.parent / 'live-transcript.md'
                        text += '\n' + (transcript.read_text() if transcript.exists() else '')
                    if query.casefold() in text.casefold():
                        result.append(meeting)
                except (ValueError, OSError, KeyError):
                    continue
        return sorted(result, key=lambda item: item['created'], reverse=True)

    def recover(self) -> None:
        for meeting in self.list():
            if meeting['status'] in {'starting', 'recording', 'paused', 'stopping', 'processing'}:
                timing = {}
                capture = self.directory(meeting['id']) / 'capture.json'
                if capture.exists():
                    try:
                        info = json.loads(capture.read_text())
                        timing['duration'] = info.get('duration', meeting.get('duration', 0))
                        if not meeting.get('started_at') and info.get('started_at'):timing['started_at']=info['started_at']
                        if not meeting.get('ended_at') and info.get('checkpoint_at'):timing['ended_at']=info['checkpoint_at']
                    except (ValueError,OSError):pass
                self.update(meeting['id'], status='interrupted',
                            progress='Interrupted — saved audio can be recovered',
                            error='The app closed before this operation finished. Use Recover / Retry.', **timing)
