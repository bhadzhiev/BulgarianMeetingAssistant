#!/usr/bin/env python3
"""Loopback-only meeting app. Run directly or double-click Open Meeting Assistant.command."""
from __future__ import annotations

import argparse
import http.cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import html
import mimetypes
from pathlib import Path
import re
import secrets
import signal
import sys
import threading
from urllib.parse import urlsplit, parse_qs, quote, unquote
import webbrowser

from app.service import MeetingService
from app.work_items import WorkItemConflict
from app.google_calendar import CalendarError

PROJECT = Path(__file__).resolve().parent
if getattr(sys, 'frozen', False):
    import os
    os.environ['PATH'] = str(PROJECT / 'bin') + os.pathsep + os.environ.get('PATH', '')
EXPORTS = {'transcript.before-speakers.json', 'transcript.alignment.json', 'speaker-turns.json', 'recording.wav', 'transcription.wav', 'transcript.md', 'transcript.json', 'transcript.srt', 'transcript.raw.json', 'minutes.md', 'minutes.json', 'analytics.json', 'speaker-timeline.json', 'live-transcript.md', 'live-transcript.json', 'markers.json'}


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, service):
        super().__init__(address, Handler)
        self.service = service
        self.token = secrets.token_urlsafe(32)
        self.origin = f'http://127.0.0.1:{self.server_port}'
        self.service.base_url = self.origin


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Request URLs may contain the one-time launch token.
        pass

    def headers_common(self):
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; media-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")

    def respond(self, status, body, mime='application/json', cookie=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(status)
        self.headers_common()
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        if cookie:
            self.send_header('Set-Cookie', cookie)
        self.end_headers()
        self.wfile.write(body)

    def authorized(self):
        if self.headers.get('Host') != f'127.0.0.1:{self.server.server_port}':
            return False
        cookie = http.cookies.SimpleCookie()
        try:
            cookie.load(self.headers.get('Cookie', ''))
        except http.cookies.CookieError:
            return False
        value = cookie.get('meeting_session')
        return value is not None and secrets.compare_digest(value.value, self.server.token)

    def do_GET(self):
        try:
            self.get()
        except WorkItemConflict as exc:
            self.respond(409, {'error': str(exc)})
        except (ValueError, KeyError, TypeError) as exc:
            self.respond(400, {'error': str(exc)})
        except CalendarError as exc:
            self.respond(400, {'error': str(exc)})
        except FileNotFoundError:
            self.respond(404, {'error': 'Not found'})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            self.respond(500, {'error': 'Cannot read this meeting. Check the app terminal.'})

    def get(self):
        url = urlsplit(self.path)
        token = parse_qs(url.query).get('token', [''])[0]
        valid_token = (token and self.headers.get('Host') == f'127.0.0.1:{self.server.server_port}'
                       and secrets.compare_digest(token, self.server.token))
        if url.path == '/' and valid_token:
            # A native window (Tauri) opens this URL from its own origin, and WebKit then drops a
            # SameSite=Strict cookie. A refresh from this page makes the next step same-origin.
            target = '/session?token=' + quote(token)
            return self.respond(200, f'<!doctype html><meta http-equiv="refresh" content="0;url={target}">'
                                     f'<title>Meeting Assistant</title><a href="{target}">Open Meeting Assistant</a>',
                                'text/html; charset=utf-8')
        if url.path == '/session' and valid_token:
            self.send_response(303)
            self.headers_common()
            self.send_header('Set-Cookie', f'meeting_session={self.server.token}; HttpOnly; SameSite=Strict; Path=/')
            self.send_header('Location', '/')
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        callback_params = parse_qs(url.query)
        if url.path == '/oauth/google/callback' or url.path == '/' and 'state' in callback_params and ('code' in callback_params or 'error' in callback_params):
            if self.headers.get('Host') != f'127.0.0.1:{self.server.server_port}':
                return self.respond(403, 'Invalid callback host', 'text/plain')
            try:
                self.server.service.google.complete({k:v[0] for k,v in parse_qs(url.query).items()})
                self.server.service.google_connected()
                message = 'You are signed in with Google. Return to Meeting Assistant to use the permissions you approved.'
                code = 200
            except Exception as exc:
                message, code = str(exc), 400
            return self.respond(code, '<!doctype html><html><head><title>Meeting Assistant · Google Calendar</title></head><body><h1>Meeting Assistant</h1><p>'+html.escape(message)+'</p><p><a href="/">Return to Meeting Assistant</a> or close this tab.</p></body></html>', 'text/html; charset=utf-8')
        if not self.authorized():
            self.respond(403, 'Open the app using its launcher.', 'text/plain; charset=utf-8')
            return
        if url.path == '/api/search':
            return self.respond(200, self.server.service.library.list(parse_qs(url.query).get('q', [''])[0]))
        if url.path == '/api/backups':
            return self.respond(200, self.server.service.backups())
        if url.path == '/api/events':
            return self.stream_events()
        if url.path == '/api/devices':
            return self.respond(200, self.server.service.input_devices())
        if url.path == '/api/find':
            query = parse_qs(url.query)
            value = lambda name: query.get(name, [''])[0]
            return self.respond(200, self.server.service.find(value('q'), value('kind'), value('project')))
        if url.path == '/api/prepare':
            query = parse_qs(url.query)
            return self.respond(200, self.server.service.prepare(query.get('project', [None])[0], query.get('series', [None])[0]))
        if url.path == '/api/github':
            return self.respond(200, self.server.service.github.status())
        if url.path == '/api/github/repos':
            return self.respond(200, self.server.service.github.repos())
        if url.path == '/api/github/items':
            query = parse_qs(url.query)
            return self.respond(200, self.server.service.github.listing(int(query.get('repo',['0'])[0]),query.get('filter',['all'])[0],query.get('kind',['all'])[0]))
        if url.path == '/api/github/item':
            return self.respond(200, self.server.service.github.detail(int(parse_qs(url.query).get('id',['0'])[0])))
        if url.path == '/api/chat':
            return self.respond(200, self.server.service.chat.status())
        if url.path == '/api/chat/spaces':
            return self.respond(200, self.server.service.chat.spaces())
        if url.path == '/api/chat/messages':
            return self.respond(200, self.server.service.chat.messages(parse_qs(url.query).get('space',[''])[0]))
        if url.path == '/api/chat/message':
            return self.respond(200, self.server.service.chat.detail(parse_qs(url.query).get('name',[''])[0]))
        if url.path == '/api/gmail/ai':
            return self.respond(200, self.server.service.gmail_ai.status())
        if url.path == '/api/gmail':
            return self.respond(200, self.server.service.gmail.status())
        if url.path == '/api/gmail/threads':
            return self.respond(200, self.server.service.gmail.listing(parse_qs(url.query).get('view',['needs_reply'])[0]))
        if url.path == '/api/gmail/thread':
            return self.respond(200, self.server.service.gmail.detail(parse_qs(url.query).get('id',[''])[0]))
        if url.path == '/api/items':
            return self.respond(200, self.server.service.item_list())
        if url.path == '/api/tasks':
            return self.respond(200, self.server.service.tasks())
        if url.path == '/api/trackers':
            return self.respond(200, {'trackers': self.server.service.library.trackers()})
        if url.path == '/api/analytics':
            query = parse_qs(url.query)
            value = lambda name: query.get(name, [''])[0]
            return self.respond(200, self.server.service.analytics_overview(
                value('from'), value('to'), value('speaker'), value('topic')))
        if url.path == '/api/state':
            return self.respond(200, self.server.service.snapshot())
        if url.path == '/api/calendar/calendars':
            return self.respond(200, self.server.service.google.list_calendars())
        match = re.fullmatch(r'/api/meetings/([a-f0-9]{32})', url.path)
        if match:
            return self.respond(200, self.server.service.detail(match[1]))
        match = re.fullmatch(r'/api/meetings/([a-f0-9]{32})/analytics', url.path)
        if match:
            return self.respond(200, {'analytics': self.server.service.detail(match[1])['analytics']})
        match = re.fullmatch(r'/files/([a-f0-9]{32})/([a-z.-]+)', url.path)
        if match and match[2] in EXPORTS:
            path = self.server.service.library.directory(match[1]) / match[2]
            return self.serve_file(path, download=match[2] not in {'recording.wav', 'transcription.wav'})
        assets = {'/': 'index.html', '/app.js': 'app.js', '/style.css': 'style.css'}
        if url.path in assets:
            return self.serve_file(PROJECT / 'web' / assets[url.path])
        self.respond(404, {'error': 'Not found'})

    def stream_events(self):
        """Server-sent events: the tab keeps one connection and reloads only after a change."""
        self.send_response(200)
        self.headers_common()
        self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
        self.end_headers()
        try:
            for event, data in self.server.service.watcher.events():
                self.wfile.write(f'event: {event}\ndata: {json.dumps(data)}\n\n'.encode())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass  # the tab closed or hid itself

    def serve_file(self, path, download=False):
        if not path.is_file() or path.is_symlink():
            raise FileNotFoundError()
        total = path.stat().st_size
        start, end, status = 0, total - 1, 200
        range_header = self.headers.get('Range')
        if range_header:
            match = re.fullmatch(r'bytes=(\d+)-(\d*)', range_header)
            if not match or int(match[1]) >= total:
                self.send_response(416)
                self.send_header('Content-Range', f'bytes */{total}')
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
            start = int(match[1])
            end = min(total - 1, int(match[2]) if match[2] else total - 1)
            if end < start:
                raise ValueError('Invalid range')
            status = 206
        self.send_response(status)
        self.headers_common()
        self.send_header('Content-Type', mimetypes.guess_type(path.name)[0] or 'application/octet-stream')
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Content-Length', str(max(0, end - start + 1)))
        if status == 206:
            self.send_header('Content-Range', f'bytes {start}-{end}/{total}')
        if download:
            self.send_header('Content-Disposition', f'attachment; filename="{path.name}"')
        self.end_headers()
        with path.open('rb') as source:
            source.seek(start)
            left = end - start + 1
            while left > 0:
                data = source.read(min(left, 65536))
                if not data:
                    break
                self.wfile.write(data)
                left -= len(data)

    def do_POST(self):
        if not self.authorized() or self.headers.get('Origin') != self.server.origin:
            return self.respond(403, {'error': 'Invalid app session or origin'})
        try:
            if urlsplit(self.path).path == '/api/import-audio':
                # Audio is too large for JSON; the body streams to disk.
                modified = self.headers.get('X-Last-Modified', '')
                try:
                    result = self.server.service.import_audio(self.rfile, int(self.headers.get('Content-Length', '0')),
                        unquote(self.headers.get('X-Filename', '')), int(modified) if modified.isdigit() else None)
                except Exception:
                    self.close_connection = True  # the rest of a refused upload is never read
                    raise
                return self.respond(200, result)
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                raise ValueError('Expected JSON')
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 8_000_000:
                raise ValueError('Invalid request size')
            body = json.loads(self.rfile.read(size))
            if not isinstance(body, dict):
                raise ValueError('Expected an object')
            service = self.server.service
            path = urlsplit(self.path).path
            if path == '/api/local-ai/models':
                from app.local_ai import list_models
                result = {'models': list_models(body.get('base_url', service.settings['local_ai_base_url']))}
            elif path == '/api/calendar/credentials':
                result = service.google.configure(body['credentials'])
            elif path == '/api/calendar/connect':
                url = service.google.begin(self.server.origin, body.get('capability','calendar')) if body.get('capability') else service.google.begin(self.server.origin)
                opened = webbrowser.open(url)
                result = {'authorization_url':url,'browser_opened':opened}
            elif path == '/api/calendar/disconnect':
                result = service.google.disconnect()
            elif path == '/api/calendar/sync-all':
                result = service.sync_saved_meetings()
            elif path == '/api/import':
                result = service.import_transcript(body['text'], body.get('filename', ''))
            elif path in {'/api/work/ingest', '/api/work/review', '/api/work/question', '/api/work/relate', '/api/work/availability'}:
                result = service.work_graph_action(path.rsplit('/', 1)[-1], body)
            elif path == '/api/github/connect':
                result = service.github.connection.connect(body['token'])
            elif path == '/api/github/disconnect':
                service.github.stop()
                result = service.github.connection.disconnect()
            elif path == '/api/github/sync':
                result = service.github.start(body['repository'],body.get('filter','all'),body.get('restart',False))
            elif path == '/api/github/refresh':
                result = service.github.start(key=body['id'])
            elif path == '/api/github/cancel':
                result = service.github.stop()
            elif path == '/api/github/clear':
                result = service.github.clear(body['account'])
            elif path == '/api/github/propose':
                result = service.github_proposal(body['id'],body['revision'],body['title'])
            elif path == '/api/chat/discover':
                result = service.chat.start('spaces',restart=body.get('restart',False))
            elif path == '/api/chat/sync':
                result = service.chat.start('messages',body['space'],body.get('restart',False))
            elif path == '/api/chat/refresh':
                result = service.chat.start('refresh',body['name'])
            elif path == '/api/chat/cancel':
                result = service.chat.stop()
            elif path == '/api/chat/clear':
                result = service.chat.clear(body['account'])
            elif path == '/api/chat/propose':
                result = service.chat_proposal(body['name'],body['revision'],body['title'])
            elif path == '/api/gmail/sync':
                result = service.gmail.start()
            elif path == '/api/gmail/cancel':
                result = service.gmail.stop()
            elif path == '/api/gmail/ai/preview':
                result = service.gmail_ai.preview(body['id'],body['revision'],body['message_id'])
            elif path == '/api/gmail/ai/start':
                result = service.gmail_ai.start(body['id'],body['revision'],body['message_id'],body.get('preview_token'),body.get('approved'))
            elif path == '/api/gmail/ai/cancel':
                result = service.gmail_ai.stop()
            elif path == '/api/gmail/clear':
                service.gmail_ai.stop()
                result = service.gmail.clear(body.get('account'))
            elif path == '/api/gmail/propose':
                result = service.gmail_proposal(body['id'],body['revision'],body['message_id'],body['title'])
            elif path == '/api/speakers':
                result = service.save_speakers(body['speakers'])
            elif path == '/api/trackers':
                result = service.save_trackers(body['trackers'])
            elif path == '/api/settings':
                result = service.save_settings(body)
            elif path == '/api/check-mic':
                result = service.check_microphone(body['device'], body.get('device_name'))
            elif path == '/api/start':
                result = service.start(body.get('title', ''), body['mode'], body['device'], body.get('project_id'), body.get('series_id'), body.get('device_name'), body.get('fallback_device_name', ''), transcription_timing=body.get('transcription_timing'))
            elif path == '/api/pause':
                if type(body['paused']) is not bool:
                    raise ValueError('Invalid pause state')
                result = service.pause(body['paused'])
            elif path == '/api/backups/create':
                result = service.create_backup()
            elif path == '/api/backups/restore':
                result = service.restore_backup(body['name'])
            elif path == '/api/backups/reveal':
                result = service.reveal_backup(body['name'])
            elif path == '/api/ask':
                result = service.ask(body['question'], body.get('project', ''), body.get('ai', True) is not False)
            elif path == '/api/projects/change':
                result = service.change_scope(body['kind'], body['id'], body['action'], body.get('name'))
            elif path == '/api/marker':
                result = service.add_marker(body['kind'], body.get('note', ''))
            elif path == '/api/stop':
                result = service.stop()
            elif re.fullmatch(r'/api/items/[a-f0-9]{1,64}(/delete|/merge)?', path):
                item_id, _, action = path[len('/api/items/'):].partition('/')
                if type(body.get('revision')) is not int:
                    raise ValueError('Reload the item list before making changes')
                if action == 'delete': result = service.delete_item(item_id, body['text'], body['revision'])
                elif action == 'merge':
                    if type(body.get('into_revision')) is not int:
                        raise ValueError('Reload both items before merging')
                    result = service.merge_items(item_id, body['into'], body['revision'], body['into_revision'])
                else: result = service.update_item(item_id, body['text'], body['changes'], body['revision'])
            else:
                match = re.fullmatch(r'/api/meetings/([a-f0-9]{32})/(process|cancel|edit|title|calendar|delete|task|delete-task|reanalyze|question|notes-review|marker-delete|link|scope)', path)
                if not match:
                    raise FileNotFoundError()
                if match[2] == 'process': result = service.process(match[1], body['action'])
                elif match[2] == 'cancel': result = service.cancel_processing(match[1])
                elif match[2] == 'reanalyze': result = service.process(match[1], 'reanalyze')
                elif match[2] == 'question': result = service.update_question(match[1], body['id'], body['answered'], body.get('text'))
                elif match[2] == 'scope': result = service.set_scope(match[1], body.get('project'), body.get('series'))
                elif match[2] == 'link': result = service.resolve_link(match[1], body['field'], body['index'], body['text'], body['action'], body.get('item_id'))
                elif match[2] == 'marker-delete': result = service.delete_marker(match[1], body['id'])
                elif match[2] == 'notes-review': result = service.review_notes(match[1], body['action'], body.get('accept', []), body.get('revision', ''))
                elif match[2] == 'title': result = service.generate_meeting_title(match[1])
                elif match[2] == 'calendar': result = service.sync_calendar(match[1])
                elif match[2] == 'delete': result = service.delete(match[1], body.get('calendar_event', False))
                elif match[2] == 'task': result = service.update_task(match[1], body['index'], body['task'], body['changes'])
                elif match[2] == 'delete-task': result = service.delete_task(match[1], body['index'], body['task'])
                else: result = service.edit(match[1], body)
            self.respond(200, result)
        except FileNotFoundError:
            self.respond(404, {'error': 'Meeting not found'})
        except WorkItemConflict as exc:
            self.respond(409, {'error': str(exc)})
        except (ValueError, KeyError, TypeError) as exc:
            self.respond(400, {'error': str(exc)})
        except Exception as exc:
            # Audio setup errors should be visible without disclosing secrets.
            message = str(exc)
            if self.server.service.api_key:
                message = message.replace(self.server.service.api_key, '[redacted]')
            self.respond(500, {'error': message})


def stop_running_copy(lock_path, timeout=60):
    """Stop the other process that holds the library lock, then wait for its lock to free."""
    import fcntl, os, subprocess, time
    # Only a process that holds this lock file is stopped, never an unrelated reused PID.
    found = subprocess.run(['/usr/sbin/lsof', '-t', str(lock_path)], capture_output=True, text=True).stdout
    pids = {int(pid) for pid in found.split()} - {os.getpid()}
    print('Stopping the running Meeting Assistant…', flush=True)
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)  # the normal shutdown saves an active recording
        except ProcessLookupError:
            pass
    with open(lock_path, 'a') as probe:
        deadline, sent = time.monotonic() + timeout, set()
        while True:
            try:
                fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(probe, fcntl.LOCK_UN)
                return
            except BlockingIOError:
                if time.monotonic() > deadline:
                    if signal.SIGKILL in sent:
                        raise SystemExit('Meeting Assistant is still running and could not be stopped.')
                    for pid in pids:
                        try:
                            os.kill(pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    sent.add(signal.SIGKILL)
                    deadline = time.monotonic() + 5
                time.sleep(0.2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--library', type=Path, default=PROJECT / 'meetings')
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--desktop-control', action='store_true', help='Private stdin/stdout channel for the native window')
    parser.add_argument('--models', type=Path, help='Writable model cache outside the application bundle')
    parser.add_argument('--backups', type=Path, help='Folder for library archives (default: ~/Documents/Meeting Assistant Backups)')
    args = parser.parse_args()
    control = None
    if args.desktop_control:
        from app.desktop import control_output
        control = control_output()
    # One process per library, including when an alternate port is requested.
    import fcntl
    args.library.mkdir(parents=True, exist_ok=True)
    lockfile = (args.library / '.app.lock').open('a')
    try:
        fcntl.flock(lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        if args.desktop_control:
            raise SystemExit('This meeting library is already open. Quit the other copy first.')
        # A new start replaces the old copy so that code changes take effect.
        stop_running_copy(args.library / '.app.lock')
        fcntl.flock(lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
    from app.worker import ProcessingWorker
    service = MeetingService(args.library, PROJECT, backup_dir=args.backups, step_runner=ProcessingWorker(PROJECT))
    service.desktop_mode = args.desktop_control
    if control is not None:
        from app.desktop import activity, microphone_health
        service.activity_changed = lambda active: activity(active, control)
        service.health_changed = lambda missing: microphone_health(missing, control)
    if args.models:
        service.models_dir = args.models
    server = Server(('127.0.0.1', args.port), service)
    url = f'{server.origin}/?token={server.token}'
    from app.storage import atomic_json
    atomic_json(args.library / '.running.json', {'url': url})
    def stop(signum, frame):
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    if args.desktop_control:
        from app.desktop import ready, watch_parent
        watch_parent(sys.stdin, lambda: stop(None, None))
        ready(url, control)
    else:
        print(f'Meeting Assistant: {url}', flush=True)
    if not args.no_browser and not args.desktop_control:
        webbrowser.open(url)
    try:
        server.serve_forever()
    finally:
        service.close(finalize_recording=args.desktop_control)
        server.server_close()
        (args.library / '.running.json').unlink(missing_ok=True)
        lockfile.close()
        if control is not None:
            control.close()


if __name__ == '__main__':
    if sys.argv[1:2] == ['--live-worker']:
        from app.live import main as live_main
        sys.argv.pop(1)
        live_main()
    elif sys.argv[1:2] == ['--processing-worker']:
        from app.worker import main as worker_main
        worker_main()
    else:
        main()
