"""Cancellation and per-stage timing without coupling inference to the recorder."""
from contextlib import contextmanager
import time


class JobCancelled(Exception):
    pass


class Job:
    def __init__(self, cancel, publish):
        self.cancel = cancel
        self.publish = publish
        self.started = time.monotonic()
        self.stage = 'Queued'
        self.stage_started = self.started
        self.timings = {'Queued': 0.0}
        self.started_at = time.time()
        self.phase = None
        self.phase_started = self.started

    def finish_phase(self):
        if self.phase:
            key = self.stage + ' / ' + self.phase
            self.timings[key] = round(self.timings.get(key, 0) + time.monotonic() - self.phase_started, 3)
            self.phase = None

    def classify(self, message):
        phase = None
        for prefix, value in [('Downloading', 'Model download'), ('Loading', 'Model loading'),
                              ('Preparing audio', 'Audio preparation'), ('Checking saved', 'Checkpoint check'),
                              ('Resuming', 'Checkpoint reuse'), ('Transcribing', 'Speech inference'),
                              ('Generating notes', 'AI requests'), ('AI correction', 'AI requests'),
                              ('Publishing', 'Publishing')]:
            if message.startswith(prefix):
                phase = value
                break
        if phase and phase != self.phase:
            self.finish_phase()
            self.phase, self.phase_started = phase, time.monotonic()

    def check(self):
        if self.cancel.is_set():
            raise JobCancelled('Processing cancelled. Saved audio and completed checkpoints are preserved.')

    def update(self, message):
        self.check()
        self.classify(message)
        self.publish(progress=message, processing_stage=self.stage,
                     processing_started_at=self.started_at, processing_stage_started_at=time.time() - (time.monotonic() - self.stage_started),
                     processing_elapsed=round(time.monotonic() - self.started, 2),
                     stage_elapsed=round(time.monotonic() - self.stage_started, 2),
                     processing_timings=dict(self.timings))

    @contextmanager
    def step(self, name):
        self.check()
        self.stage, self.stage_started = name, time.monotonic()
        self.update(name)
        try:
            yield
        finally:
            self.finish_phase()
            self.timings[name] = round(time.monotonic() - self.stage_started, 3)
            self.publish(processing_timings=dict(self.timings),
                         processing_elapsed=round(time.monotonic() - self.started, 2))
