"""Near-real-time local captions from immutable snapshots of durable PCM tracks.

Whisper runs in a child process so native inference cannot hold the recorder's GIL.
The draft and final transcript have separate files and lifecycles.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import math
from pathlib import Path
import subprocess
import sys
import threading
import time

import numpy as np

from .capture import ffmpeg_path
from .storage import atomic_json, atomic_text
from .model_cache import ensure_model
from .whisper import repeats_prompt

RATE = 16000
INTERVAL = 2.5
MAX_WINDOW = 12.0


def read_json(path: Path, fallback):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return fallback


def read_window(directory: Path, info: dict, start: float, end: float) -> np.ndarray:
    """Read only this bounded time range; missing/late track tails are silence."""
    length = round((end - start) * RATE)
    if length <= 0 or end - start > MAX_WINDOW + .01:
        raise ValueError('Invalid live audio window')
    mixed = np.zeros(length, dtype=np.float32)
    tracks = [('microphone.pcm', info['microphone_rate'])]
    if info['mode'] == 'online':
        tracks.append(('system.pcm', info['system_rate']))
    for name, rate in tracks:
        path = directory / name
        if not path.exists():
            continue
        with path.open('rb') as source:
            source.seek(round(start * rate) * 2)
            raw = source.read(round((end - start) * rate) * 2)
        raw = raw[:len(raw) // 2 * 2]
        if not raw:
            continue
        result = subprocess.run([ffmpeg_path(), '-hide_banner', '-loglevel', 'error',
            '-f', 's16le', '-ar', str(rate), '-ac', '1', '-i', 'pipe:0',
            '-f', 'f32le', '-ar', str(RATE), '-ac', '1', 'pipe:1'],
            input=raw, capture_output=True, timeout=15)
        if result.returncode:
            raise RuntimeError('Live audio conversion failed: ' + result.stderr.decode(errors='replace')[-500:])
        samples = np.frombuffer(result.stdout, dtype='<f4')
        count = min(length, len(samples))
        mixed[:count] += samples[:count]
    return np.clip(mixed, -1, 1)


def speech_bounds(samples: np.ndarray):
    """Energy gate on short frames; return voiced span with a little context."""
    frame_size = 480
    count = len(samples) // frame_size
    if not count:
        return None
    frames = samples[:count * frame_size].reshape(-1, frame_size)
    active = np.flatnonzero(np.sqrt(np.mean(frames ** 2, axis=1)) >= .006)
    if len(active) < 5:  # avoid decoding a transient click
        return None
    first = max(0, int(active[0]) * frame_size - 4800)
    last = min(len(samples), (int(active[-1]) + 1) * frame_size + 4800)
    silence = (len(samples) - (int(active[-1]) + 1) * frame_size) / RATE
    return first, last, silence


class CaptionEngine:
    """Small, deterministic caption state machine, independent of model loading."""
    def __init__(self, directory: Path, decode):
        self.directory = directory
        self.decode = decode
        self.cursor = 0.0
        self.last_end = 0.0
        self.state = dict(status='listening', message='Listening for speech',
                          segments=[], partial=None, processed_until=0, error=None)
        self.publish()

    def publish(self):
        atomic_json(self.directory / 'live.json', self.state)

    def step(self, info: dict, end: float, stopping: bool = False):
        from meeting_assistant import clean_text
        if end <= self.cursor + .05:
            return False
        end = min(end, self.cursor + MAX_WINDOW)
        if (not stopping and end - self.last_end < INTERVAL
                and end - self.cursor < MAX_WINDOW - .05):
            return False
        samples = read_window(self.directory, info, self.cursor, end)
        bounds = speech_bounds(samples)
        self.last_end = end
        if bounds is None:
            self.cursor = end
            self.state.update(partial=None, processed_until=end, status='listening', message='Listening for speech')
            self.publish()
            return True
        first, last, silence = bounds
        final = stopping or silence >= .75 or end - self.cursor >= MAX_WINDOW - .05
        start = self.cursor + first / RATE
        speech_end = self.cursor + last / RATE
        self.state.update(status='transcribing', message='Transcribing current speech')
        self.publish()
        text = clean_text(self.decode(samples[first:last]))
        if text:
            segment = dict(start=start, end=speech_end, text=text, speaker=None)
            if final:
                self.state['segments'].append(segment)
                self.state['partial'] = None
                self.save_draft()
            else:
                self.state['partial'] = segment
        elif final:
            self.state['partial'] = None
        if final:
            self.cursor = end
        self.state.update(processed_until=end, status='listening', message='Listening for speech')
        self.publish()
        return True

    def save_draft(self):
        from .transcripts import meeting_title, transcript_markdown
        atomic_json(self.directory / 'live-transcript.json', self.state['segments'])
        atomic_text(self.directory / 'live-transcript.md',
                    transcript_markdown(self.state['segments'], meeting_title(self.directory)))

    def finish(self):
        if self.state['partial']:
            self.state['segments'].append(self.state['partial'])
            self.state['partial'] = None
        self.save_draft()
        self.state.update(status='stopped', message='Live draft saved')
        self.publish()


def run_worker(directory: Path, models_dir: Path, model_name: str, prompt: str = ''):
    state = dict(status='loading', message='Loading live caption model (first use downloads it)',
                 segments=[], partial=None, processed_until=0, error=None)
    atomic_json(directory / 'live.json', state)
    try:
        from pywhispercpp.model import Model
        def progress(message):
            state.update(message=message)
            atomic_json(directory / 'live.json', state)
        model_path = ensure_model(model_name, models_dir, progress)
        model = Model(model_path, models_dir=str(models_dir), language='bg', translate=False,
            print_progress=False, print_realtime=False, print_timestamps=False,
            single_segment=True, no_context=True, suppress_blank=True,
            suppress_non_speech_tokens=True, temperature=0, n_threads=4, initial_prompt=prompt)
        def decode(samples):
            raw = model.transcribe(samples, language='bg', single_segment=True, no_context=True)
            text = ' '.join(s.text for s in raw)
            return '' if repeats_prompt(text, prompt) else text
        engine = CaptionEngine(directory, decode)
        stop_file = directory / '.live-stop'
        while True:
            info = read_json(directory / 'capture.json', None)
            stopping = stop_file.exists()
            meeting = read_json(directory / 'meeting.json', {})
            if info:
                # A checkpoint is synced with the capture timeline once per second.
                end = float(info.get('duration', 0))
                paused = meeting.get('status') == 'paused'
                engine.step(info, end, stopping=stopping or paused)
            if stopping:
                # Do not hold final processing behind an unlimited live backlog.
                engine.finish()
                return
            time.sleep(.2)
    except Exception as exc:
        state = read_json(directory / 'live.json', state)
        state.update(status='error', error=str(exc),
                     message='Live captions stopped. Audio recording continues; transcribe after stopping.')
        atomic_json(directory / 'live.json', state)
        raise


class LiveSession:
    """Own the child process and share the app's model-memory slot with final jobs."""
    def __init__(self, directory: Path, project: Path, settings: dict, slot, prompt: str = ''):
        self.directory, self.project = directory, project
        self.prompt = prompt
        self.settings, self.slot = settings, slot
        self.stopping = threading.Event()
        self.thread = None
        self.stop_reason = None

    def start(self):
        atomic_json(self.directory / 'live.json', dict(status='waiting',
            message='Waiting for the previous processing job', segments=[], partial=None,
            processed_until=0, error=None))
        self.thread = threading.Thread(target=self._run, name='live-caption-session', daemon=True)
        self.thread.start()

    def snapshot(self):
        return read_json(self.directory / 'live.json', {})

    def request_stop(self, reason=None):
        if reason:
            self.stop_reason = reason
        self.stopping.set()
        atomic_text(self.directory / '.live-stop', '')

    def close(self):
        self.request_stop()
        if self.thread:
            self.thread.join(timeout=22)

    def _run(self):
        acquired = False
        process = None
        try:
            while not self.stopping.is_set():
                if self.slot.acquire(timeout=.2):
                    acquired = True
                    break
            if not acquired or self.stopping.is_set():
                state = self.snapshot()
                state.update(status='stopped', message='No live draft was produced. Transcribe the saved recording.')
                atomic_json(self.directory / 'live.json', state)
                return
            with (self.directory / 'live-caption.log').open('w') as log:
                command = [sys.executable, '--live-worker'] if getattr(sys, 'frozen', False) else [sys.executable, '-m', 'app.live']
                process = subprocess.Popen(command + [
                    '--directory', str(self.directory), '--models-dir', self.settings['models_dir'],
                    '--model', self.settings['local_model'], '--prompt=' + self.prompt], cwd=self.project,
                    stdout=log, stderr=log)
                deadline = None
                while process.poll() is None:
                    if self.stopping.wait(.2):
                        deadline = deadline or time.monotonic() + 15
                        if time.monotonic() >= deadline:
                            process.terminate()
                            try:
                                process.wait(timeout=3)
                            except subprocess.TimeoutExpired:
                                process.kill()
                                process.wait()
                            state = self.snapshot()
                            state.update(status='stopped',
                                message='Live captions ended; saved recording is available for final transcription')
                            atomic_json(self.directory / 'live.json', state)
                            break
                        time.sleep(.1)
                if process.returncode and self.snapshot().get('status') not in {'error', 'stopped'}:
                    raise RuntimeError('Live caption process exited unexpectedly. See live-caption.log.')
        except Exception as exc:
            state = self.snapshot()
            state.update(status='error', error=str(exc), message='Live captions unavailable; audio recording is preserved')
            atomic_json(self.directory / 'live.json', state)
        finally:
            if process and process.poll() is None:
                process.kill()
                process.wait()
            if acquired:
                self.slot.release()
            if self.stop_reason:
                state = self.snapshot()
                state.update(status='stopped', message=self.stop_reason)
                atomic_json(self.directory / 'live.json', state)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--models-dir', type=Path, required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--prompt', default='')
    args = parser.parse_args()
    run_worker(args.directory, args.models_dir, args.model, args.prompt)


if __name__ == '__main__':
    main()
