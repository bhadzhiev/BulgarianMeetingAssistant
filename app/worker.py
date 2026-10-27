"""Run a single heavy step in an owned, cancellable child process.

The API key crosses a private stdin pipe, never command arguments or files.
Only structured progress/results use stdout; native diagnostics go to a log.
"""
import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import sys
import threading

from .jobs import JobCancelled


def execute(action, directory, settings, progress, key='', speakers=(), trackers=()):
    if action == 'repo_report':
        from .repo_reports import analyze
        return analyze(settings['repo_evidence'],settings,progress,key)
    if action == 'gmail_extract':
        from .gmail_ai import extract
        return extract(settings['gmail_ai_input'],settings,progress)
    from . import processing, correction, diarization, capture, analytics
    if action == 'transcribe':
        return processing.transcribe(directory, settings, progress, key, speakers)
    if action == 'summarize':
        return processing.summarize(directory, settings, progress, key, speakers)
    if action == 'correct':
        return correction.correct(directory, settings, progress, key, speakers)
    if action == 'diarize':
        return diarization.diarize(directory, progress)
    if action == 'recover':
        return capture.render_recording(directory)
    if action == 'analytics':
        return analytics.analyze(directory, settings, trackers, progress)
    raise ValueError('Unknown processing step')


class ProcessingWorker:
    def __init__(self, project):
        self.project = project

    def run(self, action, directory, settings, progress, key='', speakers=(), trackers=(), cancel=None):
        if cancel and cancel.is_set():
            raise JobCancelled()
        command = [sys.executable, '--processing-worker'] if getattr(sys, 'frozen', False) else [sys.executable, '-m', 'app.worker']
        log_path = directory / 'processing.log'
        if log_path.exists() and log_path.stat().st_size > 5_000_000:
            os.replace(log_path, directory / 'processing.previous.log')
        with log_path.open('ab') as log:
            child = subprocess.Popen(command, cwd=self.project, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=log, text=True, process_group=0)
            # A separate OS process can observe parent death even while native
            # inference holds Python's GIL. It survives the launcher's group kill.
            try:
                guardian = subprocess.Popen(['/bin/sh', '-c',
                    'if ! read -r done; then kill -KILL -"$1"; fi', 'processing-parent', str(child.pid)],
                    stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, process_group=0)
            except OSError:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()
                child.stdin.close()
                child.stdout.close()
                raise
            messages = queue.Queue()
            def read():
                try:
                    for line in child.stdout:
                        try:
                            messages.put(json.loads(line))
                        except ValueError:
                            continue
                finally:
                    messages.put(None)
            reader = threading.Thread(target=read, name='processing-output', daemon=True)
            reader.start()
            try:
                child.stdin.write(json.dumps(dict(action=action, directory=str(directory), settings=settings,
                    key=key, speakers=list(speakers), trackers=list(trackers))) + '\n')
                child.stdin.flush()
                while True:
                    if cancel and cancel.is_set():
                        raise JobCancelled('Processing cancelled. Completed checkpoints are preserved.')
                    try:
                        message = messages.get(timeout=.1)
                    except queue.Empty:
                        continue
                    if message is None:
                        raise RuntimeError('The processing worker stopped unexpectedly. Check processing.log; saved audio is preserved.')
                    if not isinstance(message, dict):
                        continue
                    if message.get('event') == 'progress':
                        progress(message['message'])
                    elif message.get('event') == 'result':
                        return message.get('result')
                    elif message.get('event') == 'error':
                        raise RuntimeError(message.get('message', 'Processing failed'))
            finally:
                # Only this child's process group, including its ffmpeg children.
                try:
                    if child.poll() is None:
                        os.killpg(child.pid, signal.SIGTERM)
                        try:
                            child.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            os.killpg(child.pid, signal.SIGKILL)
                    child.wait()
                except ProcessLookupError:
                    child.wait()
                child.stdin.close()
                try:
                    guardian.stdin.write(b'done\n')
                    guardian.stdin.flush()
                except BrokenPipeError:
                    pass
                guardian.stdin.close()
                guardian.wait(timeout=3)
                reader.join(timeout=2)
                child.stdout.close()
                for path in directory.glob('.transcription-*.wav'):
                    path.unlink(missing_ok=True)


def configure_speaker_runtime(directory):
    # PyInstaller gives matplotlib a fresh temp directory on every launch. That
    # rescans all macOS fonts for every speaker worker, even though we never plot.
    import hashlib
    bundle = str(getattr(sys, '_MEIPASS', sys.prefix))
    key = hashlib.sha256(bundle.encode()).hexdigest()[:12]
    cache = Path(directory).parent / '.speaker-runtime-cache' / key
    cache.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.environ['MPLCONFIGDIR'] = str(cache)
    os.environ['MPLBACKEND'] = 'Agg'


def main():
    from .desktop import control_output
    output = control_output()
    request = json.loads(sys.stdin.readline())
    if request.get('action') == 'diarize':
        configure_speaker_runtime(request['directory'])
    def parent():
        # The parent keeps stdin open. EOF means it died; do not orphan inference.
        sys.stdin.read()
        if os.getpgrp() == os.getpid():
            os.killpg(os.getpid(), signal.SIGTERM)
        os._exit(125)
    threading.Thread(target=parent, name='processing-parent', daemon=True).start()
    def send(event, **values):
        print(json.dumps(dict(event=event, **values)), file=output, flush=True)
    key = request.get('key', '')
    try:
        result = execute(request['action'], Path(request['directory']), request['settings'],
            lambda message: send('progress', message=message), key, request.get('speakers', []), request.get('trackers', []))
        send('result', result=result)
    except Exception as exc:
        message = str(exc).replace(key, '[redacted]') if key else str(exc)
        send('error', message=message)


if __name__ == '__main__':
    main()
