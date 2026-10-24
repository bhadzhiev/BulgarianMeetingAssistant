from __future__ import annotations

import json
import datetime as dt
import math
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time
import os

import numpy as np
import sounddevice as sd

from .storage import atomic_json


def ffmpeg_path() -> str:
    result = shutil.which('ffmpeg')
    if not result and Path('/opt/homebrew/bin/ffmpeg').exists():
        result = '/opt/homebrew/bin/ffmpeg'
    if not result:
        raise RuntimeError('Install ffmpeg first: brew install ffmpeg')
    return result


def devices() -> list[dict]:
    return [dict(id=i, name=d['name'], rate=int(d['default_samplerate']))
            for i, d in enumerate(sd.query_devices()) if d['max_input_channels'] > 0]


class Clock:
    def __init__(self):
        self.origin = time.monotonic()
        self.paused_at = None
        self.paused_total = 0.0
        self.lock = threading.Lock()

    def elapsed(self) -> float:
        with self.lock:
            return max(0, (self.paused_at or time.monotonic()) - self.origin - self.paused_total)

    def pause(self, paused: bool) -> float:
        with self.lock:
            now = time.monotonic()
            if paused and self.paused_at is None:
                self.paused_at = now
            elif not paused and self.paused_at is not None:
                self.paused_total += now - self.paused_at
                self.paused_at = None
            return now


class PCMWriter:
    """Bounded callback queue; fsync every second; raw PCM survives process failure."""
    def __init__(self, path: Path, rate: int):
        self.path, self.rate = path, rate
        self.queue = queue.Queue(maxsize=200)
        self.error = None
        self.samples = 0
        self.done = threading.Event()
        self.thread = threading.Thread(target=self._run, name='audio-disk-writer', daemon=True)
        self.thread.start()

    def append(self, position: int, data: bytes):
        if self.error:
            return
        try:
            self.queue.put_nowait((max(0, position), data))
        except queue.Full:
            self.error = 'Audio disk writer fell behind. Recording stopped; saved audio is preserved.'

    def _run(self):
        try:
            with self.path.open('wb', buffering=0) as out:
                synced = time.monotonic()
                while True:
                    item = self.queue.get()
                    if item is None:
                        break
                    position, data = item
                    # Preserve capture timing through initial delays and callback gaps.
                    gap = position - self.samples
                    while gap > 0:
                        count = min(gap, self.rate)
                        out.write(b'\0' * count * 2)
                        self.samples += count
                        gap -= count
                    overlap = max(0, self.samples - position)
                    data = data[overlap * 2:]
                    out.write(data)
                    self.samples += len(data) // 2
                    if time.monotonic() - synced >= 1:
                        os.fsync(out.fileno())
                        synced = time.monotonic()
                os.fsync(out.fileno())
        except Exception as exc:
            self.error = f'Cannot save microphone audio: {exc}'
        finally:
            self.done.set()

    def close(self):
        while not self.done.is_set():
            try:
                self.queue.put(None, timeout=0.2)
                break
            except queue.Full:
                continue
        self.thread.join(timeout=10)
        if self.thread.is_alive():
            raise RuntimeError('Audio writer did not finish. Raw audio is preserved.')


class Recorder:
    def __init__(self, directory: Path, device: int, mode: str, helper: Path):
        self.directory, self.device, self.mode, self.helper = directory, device, mode, helper
        self.clock = Clock()
        self.level = 0.0
        self.warnings = []
        self.stream = None
        self.writer = None
        self.system = None
        self.system_log = None
        self.stop_lock = threading.Lock()
        self.on_frame = None
        self.stopped = False
        self.last_frame = time.monotonic()
        self.rate = int(sd.query_devices(device)['default_samplerate'])
        self.info = dict(microphone_rate=self.rate, system_rate=48000, mode=mode,
                         duration=0, origin=self.clock.origin)
        atomic_json(directory / 'capture.json', self.info)

    def _callback(self, data, frames, timing, status):
        self.last_frame = time.monotonic()
        if status:
            # Do not perform console or disk IO in the PortAudio callback.
            self.fatal = f'Microphone reported lost audio: {status}'
        if self.clock.paused_at is not None:
            self.level = 0
            return
        samples = np.frombuffer(data, dtype=np.int16)
        self.level = min(1.0, float(np.sqrt(np.mean((samples.astype(np.float32) / 32768)**2))) * 5)
        # PortAudio provides ADC and callback times in its own shared clock.
        latency = max(0, timing.currentTime - timing.inputBufferAdcTime)
        position = round((self.clock.elapsed() - latency) * self.rate)
        saved = bytes(data)
        self.writer.append(position, saved)
        if self.on_frame:
            self.on_frame(saved, max(0, position))

    def start(self):
        self.fatal = None
        self.writer = PCMWriter(self.directory / 'microphone.pcm', self.rate)
        try:
            if self.mode == 'online':
                if not self.helper.is_file():
                    raise RuntimeError('System audio helper is missing. Run build_native.sh first.')
                self.system_log = (self.directory / 'system-audio.log').open('w')
                self.system = subprocess.Popen(
                    [str(self.helper), str(self.directory / 'system.pcm'), str(self.clock.origin)],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.system_log, text=True,
                )
                ready = queue.Queue()
                threading.Thread(target=lambda: ready.put(self.system.stdout.readline()), daemon=True).start()
                try:
                    line = ready.get(timeout=30)
                except queue.Empty:
                    raise RuntimeError('System audio permission timed out. Allow Screen & System Audio Recording in System Settings, then retry.')
                if line.strip() != 'READY':
                    raise RuntimeError('System audio could not start. See system-audio.log and allow Screen & System Audio Recording in System Settings.')
            self.stream = sd.RawInputStream(device=self.device, samplerate=self.rate,
                blocksize=round(self.rate * .03), channels=1, dtype='int16', callback=self._callback)
            self.clock.origin = time.monotonic()
            self.info['origin'] = self.clock.origin
            self.info['started_at'] = dt.datetime.now().astimezone().isoformat()
            if self.system:
                self.system.stdin.write(f'begin {self.clock.origin}\n')
                self.system.stdin.flush()
            self.stream.start()
            self.last_frame = time.monotonic()
        except Exception:
            self.stop()
            raise

    def error(self):
        if self.fatal:
            return self.fatal
        if self.writer and self.writer.error:
            return self.writer.error
        if self.system and self.system.poll() is not None and not self.stopped:
            return 'System audio capture stopped unexpectedly. Saved audio is preserved.'
        if self.stream and (not self.stream.active or time.monotonic() - self.last_frame > 5):
            return 'Microphone disconnected or stopped delivering audio. Saved audio is preserved.'
        return None

    def pause(self, paused: bool):
        when = self.clock.pause(paused)
        if self.system:
            self.system.stdin.write(f'{"pause" if paused else "resume"} {when}\n')
            self.system.stdin.flush()
        self.level = 0
        self.checkpoint()

    def checkpoint(self):
        self.info['duration'] = self.clock.elapsed()
        self.info['checkpoint_at'] = dt.datetime.now().astimezone().isoformat()
        atomic_json(self.directory / 'capture.json', self.info)

    def stop(self):
        with self.stop_lock:
            self._stop()

    def _stop(self):
        if self.stopped:
            return
        self.stopped = True
        self.clock.pause(True)
        try:
            if self.stream:
                self.stream.stop()
                self.stream.close()
        finally:
            if self.system:
                try:
                    if self.system.poll() is None:
                        self.system.stdin.write('stop\n')
                        self.system.stdin.flush()
                        self.system.wait(timeout=10)
                except (BrokenPipeError, subprocess.TimeoutExpired):
                    self.system.kill()
                    self.system.wait()
                finally:
                    self.system.stdin.close()
                    self.system.stdout.close()
            if self.system_log:
                self.system_log.close()
            if self.writer:
                self.writer.close()
            self.checkpoint()


def render_recording(directory: Path) -> float:
    info = json.loads((directory / 'capture.json').read_text())
    tracks = [('microphone.pcm', info['microphone_rate'])]
    if info['mode'] == 'online':
        tracks.append(('system.pcm', info['system_rate']))
    available = [(directory / name, rate) for name, rate in tracks
                 if (directory / name).exists() and (directory / name).stat().st_size >= 2]
    if not available:
        raise ValueError('No saved audio is available yet. Check microphone access and record again.')
    # Raw data is authoritative after a crash; a checkpoint may be up to one second old.
    duration = max(info.get('duration', 0), max(p.stat().st_size / (2 * r) for p, r in available))
    command = [ffmpeg_path(), '-hide_banner', '-loglevel', 'error', '-y']
    for path, rate in available:
        command += ['-f', 's16le', '-ar', str(rate), '-ac', '1', '-i', str(path)]
    filters = ';'.join(f'[{i}:a]apad,atrim=duration={duration}[a{i}]' for i in range(len(available)))
    if len(available) > 1:
        filters += ';' + ''.join(f'[a{i}]' for i in range(len(available))) + f'amix=inputs={len(available)}:normalize=0,alimiter=limit=0.95:latency=1[out]'
        mapped = '[out]'
    else:
        mapped = '[a0]'
    temp = directory / '.recording.wav'
    command += ['-filter_complex', filters, '-map', mapped, '-ar', '16000', '-ac', '1', '-c:a', 'pcm_s16le', str(temp)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=600)
    if result.returncode:
        raise RuntimeError('Audio conversion failed: ' + result.stderr[-1500:])
    os.replace(temp, directory / 'recording.wav')
    return duration
