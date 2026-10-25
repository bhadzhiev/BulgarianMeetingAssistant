"""Tell open tabs when something changed, instead of letting each tab ask every second.

One watcher thread looks at the library while at least one tab listens. It compares file times,
which also catches writes by other processes such as the live caption worker. A tab gets a short
"state" event with the meetings that changed, and loads data only then. During a recording or a
microphone test, "live" events carry the timer and level, so the tab does not reload anything.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import threading

TICK = 0.5            # live values (timer, level) while a recording or test runs
CHECK_EVERY = 2       # file times every second (2 ticks)
HEARTBEAT = 15        # a ping keeps the connection open and finds closed tabs
LIBRARY_FILES = ('settings.json', 'speakers.json', 'trackers.json', 'projects.json', 'items.json')
MEETING_FILES = ('meeting.json', 'transcript.json', 'transcript.metadata.json', 'transcript.raw.json', 'minutes.json',
                 'minutes.proposed.json', 'markers.json', 'analytics.json', 'live.json', 'live-transcript.json', 'recording.wav')
MEETING_ID = re.compile(r'[a-f0-9]{32}')


def _stamp(path):
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0


class Watcher:
    def __init__(self, service):
        self.service = service
        self.condition = threading.Condition()
        self.listeners = 0
        self.state_seq = self.live_seq = 0
        self.version, self.meetings, self.live = None, {}, None
        self.thread = threading.Thread(target=self._run, name='change-watcher', daemon=True)
        self.thread.start()

    def fingerprint(self):
        """A cheap summary of everything that the state shows; a change in it means: reload."""
        service, root = self.service, self.service.library.root
        meetings = {}
        for directory in root.iterdir():
            if MEETING_ID.fullmatch(directory.name) and directory.is_dir():
                meetings[directory.name] = [_stamp(directory / name) for name in MEETING_FILES]
        with service.lock:
            memory = [service.active, service.preview is not None, sorted(service.busy), bool(service.api_key)]
        overall = [dt.date.today().isoformat(), memory, service.google.status(),
                   [_stamp(root / name) for name in LIBRARY_FILES], sorted(meetings.items())]
        return json.dumps(overall, sort_keys=True, default=str), meetings

    def check(self):
        version, meetings = self.fingerprint()
        with self.condition:
            if version != self.version:
                self.version, self.meetings = version, meetings
                self.state_seq += 1
                self.condition.notify_all()

    def _run(self):
        tick = 0
        while not self.service.closed.wait(TICK):
            with self.condition:
                if not self.listeners:
                    continue
            tick += 1
            try:
                live = self.service.live_values()
                with self.condition:
                    if live != self.live:
                        self.live = live
                        self.live_seq += 1
                        self.condition.notify_all()
                if tick % CHECK_EVERY == 0:
                    self.check()
            except Exception as exc:
                print(f'Change watcher: {exc}', flush=True)
        with self.condition:
            self.condition.notify_all()

    def events(self):
        """Events for one tab: hello, then state (with changed meeting IDs), live and ping."""
        with self.condition:
            self.listeners += 1
        try:
            self.check()
            with self.condition:
                seen_state, seen_live, meetings = self.state_seq, self.live_seq, dict(self.meetings)
            yield 'hello', {}
            while not self.service.closed.is_set():
                with self.condition:
                    self.condition.wait_for(lambda: self.state_seq != seen_state or self.live_seq != seen_live
                                            or self.service.closed.is_set(), timeout=HEARTBEAT)
                    state_seq, live_seq, live, current = self.state_seq, self.live_seq, self.live, dict(self.meetings)
                if self.service.closed.is_set():
                    return
                if state_seq != seen_state:
                    changed = sorted(key for key in set(current) | set(meetings) if current.get(key) != meetings.get(key))
                    seen_state, meetings = state_seq, current
                    yield 'state', {'changed': changed}
                elif live_seq != seen_live:
                    seen_live = live_seq
                    if live:
                        yield 'live', live
                else:
                    yield 'ping', {}
        finally:
            with self.condition:
                self.listeners -= 1
