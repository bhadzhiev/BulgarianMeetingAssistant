from __future__ import annotations

from dataclasses import asdict
import json
import datetime as dt
import os
from pathlib import Path
import threading
import time
import uuid
import wave

import numpy as np
import sounddevice as sd

from .capture import Recorder, audio_created, convert_audio, devices, ffmpeg_path, render_recording
from .storage import Library, atomic_json, atomic_text
from . import processing
from . import correction
from . import analytics as conversation
from . import diarization
from . import backup
from . import items
from . import whisper
from .live import LiveSession, read_json
from .google_calendar import GoogleCalendar, bundled_client
from .meeting_automation import MeetingAutomation
from .local_ai import DEFAULT_BASE_URL, DEFAULT_MODEL, migrate_settings, validate_base_url

DEFAULTS = dict(transcription='local', local_model='large-v3-turbo', cloud_model='gpt-transcribe',
                summarizer='none', llm_model='gpt-4.1-mini', transcript_correction='local',
                local_ai_base_url=DEFAULT_BASE_URL, local_ai_model=DEFAULT_MODEL, local_ai_format='json_schema', local_ai_max_tokens=4096, local_ai_reasoning='default', auto_process=True, live_transcription=True,
                whisper_vad=True, whisper_vocabulary='',
                diarization_enabled=True, auto_title=True, title_provider='local', title_model='gpt-4.1-mini',
                calendar_enabled=False, calendar_id='', calendar_name='', calendar_account='')


MARKER_KINDS = ('important', 'decision', 'check')
AUDIO_TYPES = {'.m4a', '.mp3', '.wav', '.aac', '.ogg', '.opus', '.flac', '.webm', '.mp4', '.mov', '.caf', '.aiff', '.aif', '.amr', '.3gp'}
MAX_AUDIO_BYTES = 4_000_000_000


class MeetingService:
    def __init__(self, root: Path, project: Path, google=None, backup_dir: Path | None = None):
        self.project = project
        self.backup_dir = backup_dir or Path.home() / 'Documents' / 'Meeting Assistant Backups'
        self.library = Library(root)
        self.library.recover()
        self.settings_path = root / 'settings.json'
        self.settings = dict(DEFAULTS)
        if self.settings_path.exists():
            self.settings.update(migrate_settings(json.loads(self.settings_path.read_text())))
        self.google = google or GoogleCalendar(root, builtin=bundled_client(project))
        self.base_url = 'http://127.0.0.1:8765'
        self.api_key = os.environ.get('OPENAI_API_KEY', '')
        self.lock = threading.RLock()
        self.active = None
        self.start_thread = None
        self.finish_thread = None
        self.recorder = None
        self.live_sessions = {}
        self.busy = set()
        self.processing_slot = threading.Semaphore(1)
        self.task_cache = {}
        self.analytics_cache = {}
        self.preview = None
        self.preview_level = 0
        self.preview_deadline = 0
        self.closed = threading.Event()
        for meeting in self.library.list():
            if meeting.get('title_status') == 'generating':
                self.library.update(meeting['id'],title_status='pending')
        self.items = items.Registry(root / 'items.json')
        self._sync_all_items()
        self.automation = MeetingAutomation(self)
        self.monitor = threading.Thread(target=self._monitor, daemon=True)
        self.monitor.start()

    def validate_settings(self, settings):
        if set(settings) - set(DEFAULTS):
            raise ValueError('Unknown setting')
        values = migrate_settings(dict(self.settings, **settings))
        values['local_ai_base_url'] = validate_base_url(values['local_ai_base_url'])
        if type(values['local_ai_max_tokens']) is not int or not 128 <= values['local_ai_max_tokens'] <= 32768:
            raise ValueError('Local AI output limit must be between 128 and 32768 tokens')
        if values['local_ai_reasoning'] not in {'default', 'none', 'low', 'medium', 'high'}:
            raise ValueError('Invalid local AI reasoning effort')
        if values['local_ai_format'] not in {'json_schema', 'json_object', 'text'}:
            raise ValueError('Invalid local AI response format')
        if (values['transcription'] not in {'local', 'openai'} or values['summarizer'] not in {'none', 'local', 'openai'}
                or values['transcript_correction'] not in {'none', 'local', 'openai'}):
            raise ValueError('Invalid processing provider')
        vocabulary = values['whisper_vocabulary']
        if not isinstance(vocabulary, str) or len(vocabulary) > 2000 or any(ord(c) < 32 and c != '\n' for c in vocabulary):
            raise ValueError('The transcription vocabulary must be text of at most 2000 characters')
        for field in ['auto_process', 'live_transcription', 'whisper_vad', 'diarization_enabled', 'auto_title', 'calendar_enabled']:
            if type(values[field]) is not bool:
                raise ValueError(f'{field} must be true or false')
        if values['title_provider'] not in {'local','openai'}:
            raise ValueError('Invalid title provider')
        for field in ['calendar_id','calendar_name','calendar_account']:
            if not isinstance(values[field],str) or len(values[field])>512 or any(ord(c)<32 for c in values[field]):
                raise ValueError('Invalid calendar setting')
        for key in ['local_model', 'cloud_model', 'llm_model', 'title_model', 'local_ai_model']:
            if not isinstance(values[key], str) or not values[key].strip() or len(values[key]) > 150:
                raise ValueError('Invalid model name')
            if key == 'local_model' and ('/' in values[key] or '\\' in values[key] or '..' in values[key]):
                raise ValueError('Choose a model name, not a filesystem path')
        return values

    def save_settings(self, values):
        with self.lock:
            values = dict(values)
            if 'calendar_account' in values:
                raise ValueError('The calendar account is set by Google sign-in, not by settings input.')
            key = values.pop('api_key', None)
            if key is not None and (not isinstance(key, str) or len(key) > 1000 or '\n' in key):
                raise ValueError('Invalid API key')
            settings = self.validate_settings(values)
            previous = dict(self.settings)
        status = self.google.status()
        changed = settings['calendar_id'] != previous['calendar_id'] or not previous['calendar_enabled']
        account_changed = status['connected'] and status['account'] != previous.get('calendar_account')
        if settings['calendar_enabled'] and (changed or account_changed):
            if not status['connected']:
                raise ValueError('Sign in with Google before enabling automatic sync.')
            calendars = self.google.list_calendars()
            destination = next((c for c in calendars if c['id'] == settings['calendar_id']), None)
            if not destination:
                raise ValueError('Choose a calendar you can write to.')
            settings.update(calendar_name=destination['name'], calendar_account=status['account'])
        with self.lock:
            atomic_json(self.settings_path, settings)
            self.settings = settings
            if key is not None:
                self.api_key = key.strip()
            return dict(settings=self.settings, api_key_configured=bool(self.api_key), google=self.google.status())

    def snapshot(self):
        with self.lock:
            try:
                # Rescan only when no audio stream is open; a rescan would break a running stream.
                inputs = devices(rescan=not self.active and not self.recorder and self.preview is None)
                device_error = None
            except Exception as exc:
                inputs, device_error = [], str(exc)
            active = self.library.get(self.active) if self.active else None
            if active and self.recorder:
                active.update(duration=self.recorder.clock.elapsed(), level=self.recorder.level)
                live = self.live_sessions.get(self.active)
                active['live'] = live.snapshot() if live else None
                active['markers'] = read_json(self.library.directory(self.active) / 'markers.json', [])
            return dict(meetings=self.library.list(), active=active, google=self.google.status(),
                speakers=self.library.speakers(), trackers=self.library.trackers(), task_summary=self.task_summary(),
                settings=self.settings, api_key_configured=bool(self.api_key), devices=inputs,
                device_error=device_error, preview_level=self.preview_level,
                preview_active=self.preview is not None,
                system_audio_available=(self.project / 'bin/SystemAudio').exists())

    def detail(self, meeting_id):
        with self.lock:
            meeting = self.library.get(meeting_id)
            directory = self.library.directory(meeting_id)
            for key, name, fallback in [('transcript', 'transcript.json', []), ('minutes', 'minutes.json', None),
                                        ('transcript_metadata', 'transcript.metadata.json', None),
                                        ('transcript_raw', 'transcript.raw.json', None),
                                        ('analytics', 'analytics.json', None)]:
                path = directory / name
                meeting[key] = json.loads(path.read_text()) if path.exists() else fallback
            notes_valid = True
            if meeting['minutes']:
                from meeting_assistant import validate_minutes
                try:
                    validate_minutes(meeting['minutes'])  # adds fields that older notes lack
                except ValueError:
                    notes_valid = False
            meeting['minutes_proposal'] = None
            if notes_valid and (directory / 'minutes.proposed.json').exists():
                from meeting_assistant import validate_minutes
                from . import notes
                try:
                    proposed = json.loads((directory / 'minutes.proposed.json').read_text())
                    validate_minutes(proposed)
                    meeting['minutes_proposal'] = dict(revision=self._notes_revision(directory),
                                                       changes=notes.changes(meeting['minutes'], proposed))
                except (OSError, ValueError):
                    pass
            ids = set()
            for field in items.FIELD.values():
                for mention in (meeting['minutes'] or {}).get(field, []) if notes_valid else []:
                    ids.add(mention.get('item_id'))
                    ids.update(c.get('item_id') for c in (mention.get('link') or {}).get('candidates', []))
            with self.items.lock:
                meeting['items'] = {i: self.items.items[i] for i in ids if i in self.items.items}
            meeting['item_meetings'] = self._meeting_refs() if meeting['items'] else {}
            meeting['live'] = read_json(directory / 'live.json', None)
            meeting['markers'] = read_json(directory / 'markers.json', [])
            meeting['files'] = [name for name in ['recording.wav', 'transcript.md', 'transcript.json',
                               'transcript.srt', 'transcript.raw.json', 'minutes.md', 'minutes.json',
                               'analytics.json', 'speaker-timeline.json', 'live-transcript.md', 'live-transcript.json', 'markers.json'] if (directory / name).exists()]
            return meeting

    def _stop_preview(self):
        if self.preview:
            self.preview.stop()
            self.preview.close()
            self.preview = None
        self.preview_level = 0

    @staticmethod
    def _input_device(device, name=None):
        """A rescan can renumber devices, so the name that the person chose decides."""
        inputs = {d['id']: d for d in devices()}
        chosen = inputs.get(int(device))
        if name and (not chosen or chosen['name'] != name):
            chosen = next((d for d in inputs.values() if d['name'] == name), None)
        if not chosen:
            raise ValueError('Select an available microphone')
        return chosen['id']

    def check_microphone(self, device, device_name=None):
        with self.lock:
            if self.active:
                raise ValueError('A meeting is already recording')
            self._stop_preview()
            device = self._input_device(device, device_name)
            self.preview_deadline = time.monotonic() + 10
            def callback(data, frames, timing, status):
                samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768
                self.preview_level = min(1, float(np.sqrt(np.mean(samples ** 2))) * 5)
            self.preview = sd.RawInputStream(device=int(device), channels=1, dtype='int16', callback=callback)
            try:
                self.preview.start()
            except Exception:
                self.preview.close()
                self.preview = None
                raise
            return {'ok': True}

    def start(self, title, mode, device, device_name=None):
        if mode not in {'in_person', 'online'}:
            raise ValueError('Choose an in-person or online meeting')
        if not isinstance(title, str):
            raise ValueError('Meeting title must be text')
        ffmpeg_path()
        device = self._input_device(device, device_name)
        with self.lock:
            if self.active:
                raise ValueError('A meeting is already recording')
            self._stop_preview()
            settings = dict(self.settings, models_dir=str(self.project / 'models'))
            # Missing credentials never prevent saving a recording.
            meeting = self.library.create(title, mode, settings)
            self.active = meeting['id']
            self.start_thread = threading.Thread(target=self._start, args=(meeting['id'], int(device), mode), daemon=True)
            self.start_thread.start()
            return meeting

    def import_transcript(self, text, filename=''):
        from meeting_assistant import TranscriptSegment, save_transcript
        from .transcripts import parse_transcript
        if not isinstance(text, str) or not text.strip() or len(text) > 5_000_000:
            raise ValueError('Choose a transcript file of at most 5 MB')
        parsed = parse_transcript(text, self.library.speakers())
        segments = [TranscriptSegment(**s) for s in parsed['segments']]
        name = parsed['title'] or (Path(filename).stem if isinstance(filename, str) else '')
        with self.lock:
            settings = dict(self.settings, models_dir=str(self.project / 'models'))
            meeting = self.library.create(name or '', 'imported', settings)
            changes = dict(status='ready', progress='Imported', duration=max(s.end for s in segments))
            if parsed['date']:
                # Noon keeps the date the same in every time zone of the user.
                when = dt.datetime.combine(parsed['date'], dt.time(12)).astimezone().isoformat()
                changes.update(created=when, started_at=when)
            self.library.update(meeting['id'], **changes)
            save_transcript(self.library.directory(meeting['id']), segments)
            self.library.add_speakers(s.speaker for s in segments if s.speaker)
            self.busy.add(meeting['id'])
        self._analyze_unlocked(meeting['id'], settings)
        if settings.get('auto_process') and settings['summarizer'] != 'none':
            try:
                self.process(meeting['id'], 'summarize')
            except ValueError:
                pass  # For example, a missing API key. The user can generate notes later.
        else:
            self._queue_metadata(meeting['id'], enrich=True)
        return self.detail(meeting['id'])

    def import_audio(self, source, size, filename, modified_ms=None):
        """A recording from a phone or another app becomes a meeting that is processed like a new recording."""
        import shutil
        import tempfile
        name = Path(filename).name if isinstance(filename, str) else ''
        if Path(name).suffix.lower() not in AUDIO_TYPES:
            raise ValueError('Choose an audio file: ' + ', '.join(sorted(AUDIO_TYPES)))
        if not 0 < size <= MAX_AUDIO_BYTES:
            raise ValueError('Choose an audio file of at most 4 GB')
        # The upload and conversion happen outside the library; only a complete recording becomes a meeting.
        staging = Path(tempfile.mkdtemp(prefix='.upload-', dir=self.library.root))
        try:
            upload = staging / ('source' + Path(name).suffix.lower())
            with upload.open('wb') as output:
                left = size
                while left:
                    chunk = source.read(min(1 << 20, left))
                    if not chunk:
                        raise ValueError('The upload stopped before the file was complete. Try again.')
                    output.write(chunk)
                    left -= len(chunk)
            created = audio_created(upload)
            duration = convert_audio(upload, staging / 'recording.wav')
            upload.unlink()
            if not created and isinstance(modified_ms, int) and modified_ms > 0:
                created = dt.datetime.fromtimestamp(modified_ms / 1000).astimezone()
            created = created or dt.datetime.now().astimezone()
            with self.lock:
                settings = dict(self.settings, models_dir=str(self.project / 'models'))
                # A blank name lets an AI title replace the file name; the file name is the fallback.
                meeting = self.library.create('', 'audio', settings)
                os.replace(staging / 'recording.wav', self.library.directory(meeting['id']) / 'recording.wav')
                self.library.update(meeting['id'], title=Path(name).stem.strip()[:160] or 'Imported audio', status='recorded',
                                    progress='Audio imported', duration=duration, created=created.isoformat(),
                                    started_at=created.isoformat(), ended_at=(created + dt.timedelta(seconds=duration)).isoformat())
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        if settings.get('auto_process'):
            try:
                self.process(meeting['id'], 'all')
            except ValueError as exc:
                self.library.update(meeting['id'], error=str(exc), progress='Audio imported — update settings and transcribe')
                self._queue_metadata(meeting['id'])
        else:
            self._queue_metadata(meeting['id'])
        return self.detail(meeting['id'])

    def _start(self, meeting_id, device, mode):
        recorder = None
        try:
            recorder = Recorder(self.library.directory(meeting_id), device, mode, self.project / 'bin/SystemAudio')
            with self.lock:
                self.recorder = recorder
            recorder.start()
            if self.closed.is_set():
                recorder.stop()
                with self.lock:
                    self.library.update(meeting_id, status='interrupted', progress='App closed — saved audio can be recovered')
                    self.active, self.recorder = None, None
                return
            with self.lock:
                self.library.update(meeting_id, status='recording', progress='Recording',started_at=dt.datetime.now().astimezone().isoformat())
                settings = self.library.get(meeting_id)['settings']
                if settings.get('live_transcription', True):
                    # Caption failures must not take down the durable recorder.
                    prompt = whisper.build_prompt(settings.get('whisper_vocabulary', ''), self.library.speakers())
                    live = LiveSession(self.library.directory(meeting_id), self.project, settings, self.processing_slot, prompt)
                    self.live_sessions[meeting_id] = live
                    try:
                        live.start()
                    except Exception as exc:
                        atomic_json(self.library.directory(meeting_id) / 'live.json',
                            dict(status='error', error=str(exc), message='Live captions unavailable; recording continues',
                                 segments=[], partial=None, processed_until=0))
        except Exception as exc:
            if recorder:
                try:
                    recorder.stop()
                except Exception:
                    pass
            with self.lock:
                self.library.update(meeting_id, status='error', error=str(exc), progress='Recording could not start')
                self.active, self.recorder = None, None

    def add_marker(self, kind, note=''):
        """Mark this moment of the recording, so that the review after the meeting starts here."""
        if kind not in MARKER_KINDS:
            raise ValueError('Choose important, decision or check')
        if not isinstance(note, str) or len(note) > 300:
            raise ValueError('A marker note must be text of at most 300 characters')
        with self.lock:
            if not self.active or not self.recorder or self.library.get(self.active)['status'] not in {'recording', 'paused'}:
                raise ValueError('Markers can be added only during a recording')
            path = self.library.directory(self.active) / 'markers.json'
            markers = read_json(path, [])
            # The clock excludes pauses, like the saved audio, so the time matches the transcript.
            markers.append(dict(id=uuid.uuid4().hex[:12], time=round(self.recorder.clock.elapsed(), 2), kind=kind,
                                note=' '.join(note.split())))
            atomic_json(path, markers)
            return dict(markers=markers)

    def delete_marker(self, meeting_id, marker_id):
        with self.lock:
            path = self.library.directory(meeting_id) / 'markers.json'
            markers = read_json(path, [])
            if not any(marker.get('id') == marker_id for marker in markers):
                raise ValueError('This marker no longer exists. Reload the meeting.')
            atomic_json(path, [marker for marker in markers if marker.get('id') != marker_id])
            return self.detail(meeting_id)

    def pause(self, paused):
        with self.lock:
            if not self.active or self.library.get(self.active)['status'] not in {'recording', 'paused'}:
                raise ValueError('No active recording')
            self.recorder.pause(paused)
            return self.library.update(self.active, status='paused' if paused else 'recording',
                                       progress='Paused' if paused else 'Recording')

    def stop(self, failure=None):
        with self.lock:
            if not self.active or self.library.get(self.active)['status'] not in {'recording', 'paused'}:
                raise ValueError('No active recording to stop')
            meeting_id, recorder = self.active, self.recorder
            failure = failure or recorder.error()
            self.library.update(meeting_id, status='stopping', progress='Saving recording')
            self.finish_thread = threading.Thread(target=self._finish, args=(meeting_id, recorder, failure), daemon=True)
            self.finish_thread.start()
            return {'id': meeting_id, 'status': 'stopping'}

    def _finish(self, meeting_id, recorder, failure):
        processing_started = False
        try:
            recorder.stop()
            self.library.update(meeting_id,ended_at=dt.datetime.now().astimezone().isoformat())
            live = self.live_sessions.get(meeting_id)
            if live:
                live.request_stop()
            duration = render_recording(self.library.directory(meeting_id))
            with self.lock:
                meeting = self.library.update(meeting_id, status='recorded', duration=duration,
                    error=failure, progress='Recording saved' if not failure else 'Stopped after an audio error; recording saved')
                self.active, self.recorder = None, None
                if meeting['settings']['auto_process'] and not failure:
                    try:
                        self.process(meeting_id, 'all', use_saved=True)
                        processing_started = True
                    except Exception as exc:
                        self.library.update(meeting_id, status='recorded', error=str(exc),
                                            progress='Recording saved — update settings and retry processing')
        except Exception as exc:
            live = self.live_sessions.get(meeting_id)
            if live:
                live.request_stop()
            with self.lock:
                self.library.update(meeting_id, status='interrupted', error=str(exc),
                                    progress='Raw audio saved — use Recover / Retry')
                self.active, self.recorder = None, None
        finally:
            self._queue_metadata(meeting_id,enrich=not processing_started)


    def process(self, meeting_id, action, use_saved=False):
        if action not in {'all', 'transcribe', 'summarize', 'recover', 'correct', 'reanalyze'}:
            raise ValueError('Unknown processing action')
        with self.lock:
            meeting = self.library.get(meeting_id)
            if meeting_id == self.active or meeting_id in self.busy:
                raise ValueError('This meeting is already busy')
            if meeting['mode'] == 'audio' and action == 'recover':
                raise ValueError('An imported audio file has no raw tracks to recover')
            if meeting['mode'] == 'imported':
                if action in {'transcribe', 'recover'}:
                    raise ValueError('An imported transcript has no audio to transcribe')
                if action == 'all':
                    action = 'summarize'
            settings = meeting['settings'] if use_saved else dict(self.settings, models_dir=str(self.project / 'models'))
            settings = migrate_settings(settings)
            # Processing retries do not opt old meetings into a different calendar or AI provider.
            for field in ['calendar_enabled','calendar_id','calendar_name','calendar_account','auto_title','title_provider','title_model']:
                settings[field] = meeting['settings'].get(field, DEFAULTS[field] if field != 'auto_title' else False)
            settings = migrate_settings(settings)
            if action == 'summarize' and settings['summarizer'] == 'none':
                raise ValueError('Choose Local API or OpenAI for notes in Settings first')
            settings.setdefault('transcript_correction', 'none')
            settings.setdefault('diarization_enabled', True)
            if action == 'correct':
                if settings['transcript_correction'] == 'none':
                    raise ValueError('Choose Local API or OpenAI for transcript correction in Settings first')
                if not (self.library.directory(meeting_id) / 'transcript.json').exists():
                    raise ValueError('Transcribe the recording before AI correction')
            if action == 'reanalyze' and not (self.library.directory(meeting_id) / 'transcript.json').exists():
                raise ValueError('Transcribe or import a meeting before running analytics')
            # Capture the key for this job; it is never persisted in metadata.
            key = self.api_key
            if (action in {'all', 'transcribe'} and settings['transcription'] == 'openai' or
                action in {'all', 'summarize'} and settings['summarizer'] == 'openai' or
                action in {'all', 'transcribe', 'correct'} and settings['transcript_correction'] == 'openai') and not key:
                raise ValueError('Add an OpenAI API key in Settings first. Your recording is saved.')
            self.busy.add(meeting_id)
            self.library.update(meeting_id, status='processing', error=None, settings=settings, progress='Queued for processing')
            threading.Thread(target=self._process, args=(meeting_id, action, settings, key), daemon=True).start()
            return {'id': meeting_id, 'status': 'processing'}

    def _process(self, meeting_id, action, settings, key):
        try:
            with self.processing_slot:
                directory = self.library.directory(meeting_id)
                progress = lambda message: self.library.update(meeting_id, progress=message)
                imported = self.library.get(meeting_id)['mode'] == 'imported'
                if action != 'reanalyze' and not imported and (not (directory / 'recording.wav').exists() or action == 'recover'):
                    progress('Recovering saved audio')
                    duration = render_recording(directory)
                    self.library.update(meeting_id, duration=duration)
                if action in {'all', 'transcribe'}:
                    processing.transcribe(directory, settings, progress, key, self.library.speakers())
                should_diarize = action in {'all', 'transcribe'} or (action == 'reanalyze' and not (directory / 'speaker-timeline.json').exists())
                if should_diarize and settings.get('diarization_enabled', True) and (directory / 'recording.wav').exists():
                    self._run_diarization(meeting_id, directory, progress)
                if action in {'all', 'transcribe', 'correct'} and settings.get('transcript_correction', 'none') != 'none':
                    try:
                        correction.correct(directory, settings, progress, key, speakers=self.library.speakers())
                        self.library.update(meeting_id, correction_error=None)
                    except Exception as exc:
                        if action == 'correct':
                            raise
                        # A failed clean-up must not block notes; the Whisper transcript stays.
                        message = str(exc).replace(key, '[redacted]') if key else str(exc)
                        self.library.update(meeting_id, correction_error=message)
                if action == 'summarize' or action == 'all' and settings['summarizer'] != 'none':
                    processing.summarize(directory, settings, progress, key, speakers=self.library.speakers())
                if action != 'recover' and (directory / 'transcript.json').exists():
                    self._run_analytics(meeting_id, settings, progress)
                self.library.update(meeting_id, status='ready' if (directory / 'transcript.json').exists() else 'recorded',
                                    error=None, progress='Ready')
        except Exception as exc:
            # Never include request objects, headers, or keys in persisted errors.
            message = str(exc)
            if key:
                message = message.replace(key, '[redacted]')
            self.library.update(meeting_id, status='error', error=message, progress='Processing failed — recording preserved')
        finally:
            try:
                self._sync_items(meeting_id)
            except Exception as exc:
                print(f'Task registry: {exc}', flush=True)
            with self.lock:
                self.busy.discard(meeting_id)
            self._queue_metadata(meeting_id,enrich=True)

    def _run_diarization(self, meeting_id, directory, progress):
        from meeting_assistant import TranscriptSegment, save_transcript
        try:
            timeline = diarization.diarize(directory, progress)
            source = json.loads((directory / 'transcript.json').read_text())
            assigned = conversation.assign_speakers(source, timeline)
            save_transcript(directory, [TranscriptSegment(**segment) for segment in assigned])
            self.library.update(meeting_id, diarization_error=None)
        except Exception as exc:
            # Diarization is optional; transcription and notes must still succeed.
            self.library.update(meeting_id, diarization_error=str(exc))

    def _run_analytics(self, meeting_id, settings, progress=lambda message: None):
        try:
            progress('Building conversation analytics')
            result = conversation.analyze(self.library.directory(meeting_id), settings,
                                          self.library.trackers(), progress)
            self.library.update(meeting_id, analytics_error=result.get('semantic_error'))
            return result
        except Exception as exc:
            # Keep an earlier valid analytics file and never fail the transcript job.
            self.library.update(meeting_id, analytics_error=str(exc))
            return None

    def edit(self, meeting_id, body):
        from meeting_assistant import TranscriptSegment, save_transcript, save_minutes, validate_minutes
        analytics_settings = None
        with self.lock:
            if meeting_id == self.active or meeting_id in self.busy:
                raise ValueError('Wait until processing finishes before editing')
            directory = self.library.directory(meeting_id)
            if 'title' in body:
                if not isinstance(body['title'], str) or not body['title'].strip():
                    raise ValueError('Meeting title is required')
                current = self.library.get(meeting_id)
                self.library.update(meeting_id, title=body['title'].strip()[:160],title_source='manual',
                    title_revision=current.get('title_revision',0)+1,title_status='manual',title_error=None)
                self._queue_metadata(meeting_id)
            if 'transcript' in body:
                if not isinstance(body['transcript'], list) or len(body['transcript']) > 100000:
                    raise ValueError('Invalid transcript')
                transcript_path = directory / 'transcript.json'
                old_segments = [TranscriptSegment(**item) for item in json.loads(transcript_path.read_text())] if transcript_path.exists() else []
                segments = []
                duration = self.library.get(meeting_id)['duration']
                previous = 0
                for item in body['transcript']:
                    s = TranscriptSegment(**item)
                    if (type(s.start) not in {int, float} or type(s.end) not in {int, float}
                        or not np.isfinite(s.start) or not np.isfinite(s.end)
                        or not 0 <= s.start <= s.end <= duration + 1 or s.start < previous
                        or not isinstance(s.text, str) or len(s.text) > 100000
                        or s.speaker is not None and not isinstance(s.speaker, str)):
                        raise ValueError('Invalid transcript segment')
                    previous = s.start
                    segments.append(s)
                renames = {}
                for old, new in zip(old_segments, segments):
                    if (conversation.is_generic_speaker(old.speaker) and new.speaker
                            and not conversation.is_generic_speaker(new.speaker)
                            and new.speaker.strip() != old.speaker):
                        renames[old.speaker] = new.speaker.strip()
                if renames:
                    for segment in segments:
                        if segment.speaker in renames:
                            segment.speaker = renames[segment.speaker]
                    timeline_path = directory / 'speaker-timeline.json'
                    if timeline_path.exists():
                        timeline = json.loads(timeline_path.read_text())
                        for turn in timeline:
                            if turn.get('speaker') in renames:
                                turn['speaker'] = renames[turn['speaker']]
                        atomic_json(timeline_path, timeline)
                save_transcript(directory, segments)
                # Human labels become known speakers; diarization IDs stay meeting-local.
                self.library.add_speakers(s.speaker for s in segments if s.speaker and not conversation.is_generic_speaker(s.speaker))
                analytics_settings = dict(self.settings, models_dir=str(self.project / 'models'))
            if 'minutes' in body:
                self._refresh_items()
                source = json.loads((directory / 'transcript.json').read_text())
                validate_minutes(body['minutes'], [TranscriptSegment(**s) for s in source])
                save_minutes(directory, body['minutes'])
                self._sync_items(meeting_id)
            if analytics_settings is None:
                return self.detail(meeting_id)
            self.busy.add(meeting_id)
        self._analyze_unlocked(meeting_id, analytics_settings)
        return self.detail(meeting_id)

    def _analyze_unlocked(self, meeting_id, settings):
        # Semantic topics can wait minutes for the AI endpoint; recording controls must not wait.
        # The busy mark keeps other edits and jobs away from this meeting until analytics finish.
        try:
            self._run_analytics(meeting_id, settings)
        finally:
            with self.lock:
                self.busy.discard(meeting_id)

    @staticmethod
    def _notes_revision(directory):
        import hashlib
        digest = hashlib.sha256()
        for name in ['minutes.json', 'minutes.proposed.json']:
            path = directory / name
            digest.update(path.read_bytes() if path.exists() else b'')
            digest.update(b'\0')
        return digest.hexdigest()

    def review_notes(self, meeting_id, action, accept=(), revision=''):
        """Apply the accepted changes of a new AI draft to the saved notes, or discard the draft."""
        from meeting_assistant import TranscriptSegment, save_minutes, validate_minutes
        from . import notes
        if action not in {'apply', 'discard'} or not isinstance(accept, list) or not all(isinstance(item, str) for item in accept):
            raise ValueError('Invalid notes review')
        with self.lock:
            if meeting_id == self.active or meeting_id in self.busy:
                raise ValueError('Wait until processing finishes before changing the notes')
            directory = self.library.directory(meeting_id)
            proposal = directory / 'minutes.proposed.json'
            if not proposal.exists() or revision != self._notes_revision(directory):
                raise ValueError('These notes changed. Reload the meeting and review the new notes again.')
            if action == 'apply':
                self._refresh_items()
                current = json.loads((directory / 'minutes.json').read_text()) if (directory / 'minutes.json').exists() else None
                if current is not None:
                    validate_minutes(current)
                proposed = json.loads(proposal.read_text())
                validate_minutes(proposed)
                result = notes.apply(current, proposed, set(accept))
                source = json.loads((directory / 'transcript.json').read_text())
                validate_minutes(result, [TranscriptSegment(**s) for s in source])
                processing.archive(directory, ['minutes.json', 'minutes.md'])
                save_minutes(directory, result)
                proposal.unlink()
                self._sync_items(meeting_id)
                return self.detail(meeting_id)
            proposal.unlink()
            return self.detail(meeting_id)

    def backups(self):
        return dict(folder=str(self.backup_dir), archives=backup.archives(self.backup_dir) if self.backup_dir.exists() else [])

    def create_backup(self):
        # Archiving can take minutes; recording controls must not wait for it.
        with self.lock:
            skip = {self.active} if self.active else set()
        result = backup.create(self.library.root, self.backup_dir, skip)
        return dict(self.backups(), created=result, skipped_active=bool(skip))

    def restore_backup(self, name):
        result = backup.restore(backup.archive_path(self.backup_dir, name), self.library)
        with self.lock:
            for meeting_id in result['restored']:
                # A meeting archived during a job comes back as interrupted, like after a crash.
                if self.library.get(meeting_id)['status'] in {'starting', 'recording', 'paused', 'stopping', 'processing'}:
                    self.library.update(meeting_id, status='interrupted', progress='Restored from an archive',
                                        error='This meeting was busy when it was archived. Use Recover / Retry.')
        return dict(self.backups(), **result)

    def reveal_backup(self, name):
        import subprocess
        subprocess.run(['/usr/bin/open', '-R', str(backup.archive_path(self.backup_dir, name))], check=False, timeout=10)
        return {'ok': True}

    def save_trackers(self, trackers):
        return dict(trackers=self.library.save_trackers(trackers))

    def update_question(self, meeting_id, question_id, answered, text=None):
        if not isinstance(question_id, str) or type(answered) is not bool:
            raise ValueError('Invalid question update')
        with self.lock:
            if meeting_id == self.active or meeting_id in self.busy:
                raise ValueError('Wait until processing finishes before changing analytics')
            path = self.library.directory(meeting_id) / 'analytics.json'
            result = json.loads(path.read_text())
            question = next((item for item in result.get('questions', []) if item.get('id') == question_id), None)
            if question is None or text is not None and question.get('text') != text:
                raise ValueError('These analytics changed. Reload the meeting and try again.')
            question['answered'] = answered
            result['unanswered_questions'] = sum(not item['answered'] for item in result['questions'])
            atomic_json(path, result)
            return result

    def _meeting_analytics(self, meeting_id):
        path = self.library.directory(meeting_id) / 'analytics.json'
        try:
            stamp = path.stat().st_mtime_ns
        except FileNotFoundError:
            self.analytics_cache.pop(meeting_id, None)
            return None
        cached = self.analytics_cache.get(meeting_id)
        if not cached or cached[0] != stamp:
            try:
                value = json.loads(path.read_text())
                if not isinstance(value, dict) or value.get('version') != conversation.VERSION:
                    raise ValueError('Unsupported analytics file')
                cached = (stamp, value)
            except (OSError, ValueError):
                cached = (stamp, None)
            self.analytics_cache[meeting_id] = cached
        return cached[1]

    def analytics_overview(self, from_date='', to_date='', speaker='', topic=''):
        for value in [from_date, to_date, speaker, topic]:
            if not isinstance(value, str) or len(value) > 200:
                raise ValueError('Invalid analytics filter')
        try:
            first = dt.date.fromisoformat(from_date) if from_date else None
            last = dt.date.fromisoformat(to_date) if to_date else None
        except ValueError:
            raise ValueError('Analytics dates must use YYYY-MM-DD') from None
        if first and last and first > last:
            raise ValueError('The start date must not be after the end date')
        wanted_speaker, topic_key = speaker.casefold(), topic.casefold()

        def speaker_key(name, meeting):
            # Diarization labels such as SPEAKER_00 are local to one meeting; only real names join meetings.
            return (meeting['id'], name.casefold()) if conversation.is_generic_speaker(name) else name.casefold()

        def new_speaker(name, meeting):
            row = dict(speaker=name, talk_seconds=0.0, turns=0, questions=0, unanswered_questions=0,
                       longest_monologue_seconds=0.0, meetings=set())
            if conversation.is_generic_speaker(name):
                row.update(meeting_id=meeting['id'], meeting_title=meeting['title'])
            return row
        with self.lock:
            records = [(meeting, self._meeting_analytics(meeting['id'])) for meeting in self.library.list()]
        records = [(meeting, data) for meeting, data in records if data]
        available_speakers = sorted({name for _, data in records for name in
            [row.get('speaker') for row in data.get('speakers', [])]
            + [row.get('speaker') for row in data.get('questions', [])]
            + [hit.get('speaker') for topic in data.get('topics', []) for hit in topic.get('matches', [])] if name}, key=str.casefold)
        available_topics = sorted({row['name'] for _, data in records for row in data.get('topics', [])}, key=str.casefold)
        speakers, topics, meetings = {}, {}, []
        for meeting, data in records:
            meeting_date = (meeting.get('started_at') or meeting['created'])[:10]
            if first and meeting_date < first.isoformat() or last and meeting_date > last.isoformat():
                continue
            speaker_rows = [row for row in data.get('speakers', [])
                            if not wanted_speaker or row.get('speaker', '').casefold() == wanted_speaker]
            topic_rows = [row for row in data.get('topics', [])
                          if not topic_key or str(row.get('id', '')).casefold() == topic_key or row.get('name', '').casefold() == topic_key]
            questions = [item for item in data.get('questions', [])
                         if not wanted_speaker or (item.get('speaker') or '').casefold() == wanted_speaker]
            speaker_in_topics = any((hit.get('speaker') or '').casefold() == wanted_speaker
                                    for row in topic_rows for hit in row.get('matches', []))
            if wanted_speaker and not speaker_rows and not questions and not speaker_in_topics or topic_key and not topic_rows:
                continue
            unanswered = sum(not item.get('answered', False) for item in questions)
            meetings.append(dict(id=meeting['id'], title=meeting['title'], date=meeting.get('started_at') or meeting['created'],
                                 talk_seconds=round(sum(row['talk_seconds'] for row in speaker_rows), 3),
                                 questions=len(questions), unanswered_questions=unanswered,
                                 topic_matches=sum(len(row.get('matches', [])) for row in topic_rows)))
            for row in speaker_rows:
                name = row['speaker']
                aggregate = speakers.setdefault(speaker_key(name, meeting), new_speaker(name, meeting))
                aggregate['talk_seconds'] += row.get('talk_seconds', 0)
                aggregate['turns'] += row.get('turns', 0)
                aggregate['longest_monologue_seconds'] = max(aggregate['longest_monologue_seconds'], row.get('longest_monologue_seconds', 0))
                aggregate['meetings'].add(meeting['id'])
            for item in questions:
                name = item.get('speaker')
                if not name:
                    continue
                aggregate = speakers.setdefault(speaker_key(name, meeting), new_speaker(name, meeting))
                aggregate['questions'] += 1
                aggregate['unanswered_questions'] += not item.get('answered', False)
                aggregate['meetings'].add(meeting['id'])
            for row in topic_rows:
                key = row.get('name', '').casefold()
                aggregate = topics.setdefault(key, dict(id=row.get('id'), name=row.get('name'), matches=0, meetings=set()))
                aggregate['matches'] += len(row.get('matches', []))
                aggregate['meetings'].add(meeting['id'])
        total_speech = round(sum(row['talk_seconds'] for row in speakers.values()), 3)
        speaker_rows = []
        for row in speakers.values():
            row['meetings'] = len(row['meetings'])
            row['talk_seconds'] = round(row['talk_seconds'], 3)
            row['talk_percent'] = round(100 * row['talk_seconds'] / total_speech, 1) if total_speech else 0.0
            row['average_turn_seconds'] = round(row['talk_seconds'] / row['turns'], 3) if row['turns'] else 0.0
            row['longest_monologue_seconds'] = round(row['longest_monologue_seconds'], 3)
            speaker_rows.append(row)
        topic_rows = []
        for row in topics.values():
            row['meetings'] = len(row['meetings'])
            topic_rows.append(row)
        speaker_rows.sort(key=lambda row: (-row['talk_seconds'], row['speaker'].casefold()))
        topic_rows.sort(key=lambda row: (-row['matches'], row['name'].casefold()))
        return dict(meetings=meetings, meeting_count=len(meetings), speakers=speaker_rows, topics=topic_rows,
                    total_speech_seconds=total_speech, questions=sum(row['questions'] for row in meetings),
                    unanswered_questions=sum(row['unanswered_questions'] for row in meetings),
                    available_speakers=available_speakers, available_topics=available_topics,
                    filters=dict(**{'from': from_date, 'to': to_date}, speaker=speaker, topic=topic))

    def _minutes(self, meeting_id):
        """Validated notes of a meeting, cached until the file changes."""
        from meeting_assistant import validate_minutes
        path = self.library.directory(meeting_id) / 'minutes.json'
        try:
            stamp = path.stat().st_mtime_ns
        except FileNotFoundError:
            self.task_cache.pop(meeting_id, None)
            return None
        cached = self.task_cache.get(meeting_id)
        if not cached or cached[0] != stamp:
            try:
                minutes = json.loads(path.read_text())
                validate_minutes(minutes)
            except (OSError, ValueError):
                minutes = None
            cached = self.task_cache[meeting_id] = (stamp, minutes)
        return cached[1]

    def _sync_items(self, meeting_id):
        """Run after every change to a meeting's notes."""
        from meeting_assistant import save_minutes, validate_minutes
        with self.items.lock:
            directory = self.library.directory(meeting_id)
            minutes = None
            if (directory / 'minutes.json').exists():
                minutes = json.loads((directory / 'minutes.json').read_text())
                validate_minutes(minutes)
            if self.items.sync(meeting_id, minutes) and minutes is not None:
                save_minutes(directory, minutes)
            self.items.save()
            path = directory / 'minutes.json'
            self.items_synced[meeting_id] = path.stat().st_mtime_ns if path.exists() else None

    def _refresh_items(self):
        """Notes that changed outside the app (or before this version) reach the registry on the next read."""
        meetings = self.library.list()
        for meeting in sorted(meetings, key=lambda m: m.get('started_at') or m['created']):
            if meeting['id'] in self.busy or meeting['id'] == self.active:
                continue
            path = self.library.directory(meeting['id']) / 'minutes.json'
            stamp = path.stat().st_mtime_ns if path.exists() else None
            if self.items_synced.get(meeting['id'], 'never') != stamp:
                try:
                    self._sync_items(meeting['id'])
                except (OSError, ValueError) as exc:
                    self.items_synced[meeting['id']] = stamp
                    print(f'Task registry: {meeting["id"]}: {exc}', flush=True)
        for meeting_id in set(self.items_synced) - {m['id'] for m in meetings}:
            with self.items.lock:
                self.items.sync(meeting_id, None)
                self.items.save()
            del self.items_synced[meeting_id]

    def _sync_all_items(self):
        # Oldest meetings first, so that a later mention links to the item that an earlier meeting created.
        self.items_synced = {}
        self._refresh_items()

    def _meeting_refs(self):
        return {m['id']: dict(title=m['title'], date=m.get('started_at') or m['created']) for m in self.library.list()}

    def pending_links(self, meetings=None):
        """Mentions that may be an existing task or decision and wait for a person to choose."""
        result = []
        for meeting_id in meetings or [m['id'] for m in self.library.list()]:
            minutes = self._minutes(meeting_id)
            for kind, field in items.FIELD.items():
                for index, mention in enumerate((minutes or {}).get(field, [])):
                    if mention.get('link') and not mention.get('item_id'):
                        candidates = [c for c in mention['link'].get('candidates', []) if c.get('item_id') in self.items.items]
                        result.append(dict(meeting_id=meeting_id, kind=kind, field=field, index=index, mention=mention,
                                           text=mention[items.MENTION[kind]['text']], candidates=candidates))
        return result

    def item_list(self):
        with self.lock, self.items.lock:
            self._refresh_items()
            return dict(items=list(self.items.items.values()), pending=self.pending_links(), meetings=self._meeting_refs())

    def tasks(self):
        """Every persistent task, each once, however many meetings discussed it."""
        with self.lock, self.items.lock:
            self._refresh_items()
            return [dict(item) for item in self.items.items.values() if item['kind'] == 'task']

    def task_summary(self):
        today = dt.date.today().isoformat()
        open_tasks = [t for t in self.tasks() if t['status'] == 'open']
        return dict(open=len(open_tasks), overdue=sum(1 for t in open_tasks if t['due_date'] and t['due_date'] < today),
                    today=today, review=len(self.pending_links()))

    def _linked_minutes(self, item):
        """Each meeting that mentions the item, with its notes; busy meetings must wait."""
        from meeting_assistant import validate_minutes
        for link in item['links']:
            meeting_id = link['meeting_id']
            if meeting_id == self.active or meeting_id in self.busy:
                raise ValueError('A meeting with this item is busy. Try again when processing finishes.')
            directory = self.library.directory(meeting_id)
            minutes = json.loads((directory / 'minutes.json').read_text())
            validate_minutes(minutes)
            yield link, directory, minutes

    def update_item(self, item_id, text, changes):
        from meeting_assistant import save_minutes
        if not isinstance(changes, dict) or not changes:
            raise ValueError('Nothing to change')
        with self.lock, self.items.lock:
            item = self.items.items.get(item_id)
            if not item or item['text'] != text:
                raise ValueError('This item changed. Reload the list and try again.')
            allowed = {'text', 'owner', 'deadline', 'due_date', 'status'} if item['kind'] == 'task' else {'text', 'status'}
            if set(changes) - allowed:
                raise ValueError('These fields cannot change here')
            clean = {}
            for name, value in changes.items():
                if name == 'text':
                    if not isinstance(value, str) or not value.strip():
                        raise ValueError('The text cannot be empty')
                    clean[name] = value.strip()[:1000]
                elif name == 'status':
                    if value not in (items.TASK_STATES if item['kind'] == 'task' else items.DECISION_STATES):
                        raise ValueError('Invalid status')
                    clean[name] = value
                elif name == 'due_date':
                    if value is not None:
                        try:
                            dt.date.fromisoformat(value)
                        except (TypeError, ValueError):
                            raise ValueError('Due date must be a date in YYYY-MM-DD format') from None
                    clean[name] = value
                else:
                    if value is not None and not isinstance(value, str):
                        raise ValueError(f'{name} must be text')
                    clean[name] = (value or '').strip()[:160] or None
            if item['kind'] == 'task' and 'status' in clean:
                # The notes of each meeting show the same status, so exports stay correct.
                for link, directory, minutes in list(self._linked_minutes(item)):
                    for mention in minutes['tasks']:
                        if mention.get('item_id') == item_id:
                            mention['status'] = clean['status']
                    save_minutes(directory, minutes)
                    link['seen']['status'] = clean['status']
            self.items.update(item_id, clean)
            self.items.save()
            return dict(self.items.items[item_id])

    def delete_item(self, item_id, text):
        """Remove a task or decision and its mentions from every meeting."""
        from meeting_assistant import save_minutes
        with self.lock, self.items.lock:
            item = self.items.items.get(item_id)
            if not item or item['text'] != text:
                raise ValueError('This item changed. Reload the list and try again.')
            field = items.FIELD[item['kind']]
            for _, directory, minutes in list(self._linked_minutes(item)):
                minutes[field] = [mention for mention in minutes[field] if mention.get('item_id') != item_id]
                save_minutes(directory, minutes)
            self.items.remove(item_id)
            self.items.save()
            return dict(deleted=item_id)

    def merge_items(self, item_id, into_id):
        from meeting_assistant import save_minutes
        with self.lock, self.items.lock:
            item, into = self.items.items.get(item_id), self.items.items.get(into_id)
            if not item or not into or item_id == into_id or item['kind'] != into['kind']:
                raise ValueError('Choose another item of the same kind')
            field = items.FIELD[item['kind']]
            for _, directory, minutes in list(self._linked_minutes(item)):
                for mention in minutes[field]:
                    if mention.get('item_id') == item_id:
                        mention['item_id'] = into_id
                        if item['kind'] == 'task':
                            mention['status'] = into['status']
                save_minutes(directory, minutes)
            self.items.merge(item_id, into_id)
            for link in into['links']:
                if item['kind'] == 'task':
                    link['seen']['status'] = into['status']
            self.items.save()
            return dict(into)

    def resolve_link(self, meeting_id, field, index, text, action, item_id=None):
        """A person's answer to the question: is this mention an existing task or decision?"""
        from meeting_assistant import save_minutes, validate_minutes
        kind = {'tasks': 'task', 'decisions': 'decision'}.get(field)
        if not kind or action not in ({'same', 'duplicate', 'new'} if kind == 'task' else {'same', 'replaces', 'new'}):
            raise ValueError('Invalid choice')
        with self.lock, self.items.lock:
            if meeting_id == self.active or meeting_id in self.busy:
                raise ValueError('Wait until processing finishes before changing the notes')
            directory = self.library.directory(meeting_id)
            minutes = json.loads((directory / 'minutes.json').read_text())
            validate_minutes(minutes)
            mentions = minutes[field]
            if (type(index) is not int or not 0 <= index < len(mentions) or mentions[index][items.MENTION[kind]['text']] != text
                    or not mentions[index].get('link')):
                raise ValueError('These notes changed. Reload and try again.')
            mention = mentions[index]
            if action != 'new':
                target = self.items.items.get(item_id)
                if not target or target['kind'] != kind:
                    raise ValueError('That item no longer exists. Reload and try again.')
            if action == 'new':
                mention['item_id'] = self.items.create(kind, mention, meeting_id)
            elif action == 'replaces':
                mention['item_id'] = self.items.replace(item_id, mention, meeting_id)
            else:
                self.items.link(item_id, kind, mention, meeting_id, ai_updates=action == 'same', duplicate=action == 'duplicate')
                mention['item_id'] = item_id
                if kind == 'task':
                    mention['status'] = target['status']
            mention.pop('link')
            self.items.sync(meeting_id, minutes)
            save_minutes(directory, minutes)
            self.items.save()
            return self.detail(meeting_id)

    def update_task(self, meeting_id, index, text, changes):
        if not isinstance(changes, dict) or not changes or set(changes) - {'task', 'status', 'due_date', 'owner'}:
            raise ValueError('Only text, status, due date and owner can change here')
        if 'task' in changes:
            if not isinstance(changes['task'], str) or not changes['task'].strip():
                raise ValueError('Task text cannot be empty')
            changes['task'] = changes['task'].strip()[:1000]
        if 'owner' in changes and changes['owner'] is not None:
            if not isinstance(changes['owner'], str):
                raise ValueError('Owner must be text')
            changes['owner'] = changes['owner'].strip()[:160] or None
        def change(tasks):
            tasks[index].update(changes)
            return dict(tasks[index], index=index, meeting_id=meeting_id)
        return self._change_tasks(meeting_id, index, text, change)

    def delete_task(self, meeting_id, index, text):
        def remove(tasks):
            tasks.pop(index)
            return dict(deleted=True, meeting_id=meeting_id)
        return self._change_tasks(meeting_id, index, text, remove)

    def _change_tasks(self, meeting_id, index, text, change):
        from meeting_assistant import TranscriptSegment, save_minutes, validate_minutes
        with self.lock:
            if meeting_id == self.active or meeting_id in self.busy:
                raise ValueError('Wait until processing finishes before changing tasks')
            self._refresh_items()  # the registry must know the notes before this edit
            directory = self.library.directory(meeting_id)
            minutes = json.loads((directory / 'minutes.json').read_text())
            validate_minutes(minutes)
            # The index alone is not enough: notes can be regenerated after the page loaded.
            if type(index) is not int or not 0 <= index < len(minutes['tasks']) or minutes['tasks'][index]['task'] != text:
                raise ValueError('These notes changed. Reload the task list and try again.')
            result = change(minutes['tasks'])
            source = json.loads((directory / 'transcript.json').read_text())
            validate_minutes(minutes, [TranscriptSegment(**s) for s in source])
            save_minutes(directory, minutes)
            self._sync_items(meeting_id)
            return result

    def save_speakers(self, names):
        return dict(speakers=self.library.save_speakers(names))

    def delete(self, meeting_id, calendar_event=False):
        if type(calendar_event) is not bool:
            raise ValueError('Invalid calendar event choice')
        with self.lock:
            meeting = self.library.get(meeting_id)
            live = self.live_sessions.get(meeting_id)
            if meeting_id == self.active or meeting_id in self.busy or live and live.thread and live.thread.is_alive():
                raise ValueError('Wait until recording and processing finish before deleting this meeting.')
            if not self.automation.forget(meeting_id):
                raise ValueError('A title or calendar update is running for this meeting. Try again in a moment.')
            self.busy.add(meeting_id)
        try:
            binding = meeting.get('calendar_sync') or {}
            event_deleted = False
            if calendar_event and binding.get('calendar_id') and binding.get('event_id'):
                # Google first: a failure keeps the meeting so nothing is lost silently.
                event_deleted = self.google.delete_event(binding['calendar_id'], binding['event_id'], meeting_id,
                                                         expected_account=binding.get('account_id'))
            with self.lock:
                self.library.delete(meeting_id)
                with self.items.lock:
                    self.items.sync(meeting_id, None)
                    self.items.save()
                self.live_sessions.pop(meeting_id, None)
        except Exception:
            self.automation.restore(meeting_id)
            raise
        finally:
            with self.lock:
                self.busy.discard(meeting_id)
        return dict(deleted=meeting_id, calendar_event_deleted=event_deleted)

    def _queue_metadata(self, meeting_id, enrich=False, force_title=False):
        if self.closed.is_set():return
        meeting = self.library.get(meeting_id)
        settings = meeting['settings']
        needs_title = enrich and settings.get('auto_title',False) and meeting.get('title_source') != 'manual'
        if force_title or needs_title or settings.get('calendar_enabled',False) or meeting.get('calendar_sync'):
            self.automation.enqueue(meeting_id,enrich=enrich,force_title=force_title)

    def generate_meeting_title(self, meeting_id):
        with self.lock:
            meeting = self.library.get(meeting_id)
            if meeting_id == self.active or meeting_id in self.busy:
                raise ValueError('Wait until this meeting finishes processing.')
            directory = self.library.directory(meeting_id)
            if not any((directory/name).exists() for name in ['transcript.json','live-transcript.json']):
                raise ValueError('A transcript or saved live draft is needed to generate a title.')
            self.library.update(meeting_id,title_status='pending',title_error=None)
            self._queue_metadata(meeting_id,enrich=True,force_title=True)
            return self.detail(meeting_id)

    def sync_calendar(self, meeting_id):
        with self.lock:
            meeting = self.library.get(meeting_id)
            if meeting_id == self.active:
                raise ValueError('Stop recording before adding this meeting to the calendar.')
            if not meeting.get('calendar_sync'):
                if not self.settings['calendar_enabled'] or not self.settings['calendar_id']:
                    raise ValueError('Choose and enable a destination Google Calendar in Settings first.')
                settings = dict(meeting['settings'])
                settings.update({k:self.settings[k] for k in ['calendar_enabled','calendar_id','calendar_name','calendar_account']})
                self.library.update(meeting_id,settings=settings)
            else:
                binding = dict(meeting['calendar_sync'],status='pending',attempts=0,next_retry=0)
                self.library.update(meeting_id,calendar_sync=binding)
            self._queue_metadata(meeting_id)
            return self.detail(meeting_id)

    def sync_saved_meetings(self):
        count = 0
        for meeting in self.library.list():
            directory = self.library.directory(meeting['id'])
            if meeting['id'] != self.active and (directory/'recording.wav').exists():
                self.sync_calendar(meeting['id'])
                count += 1
        return dict(queued=count)

    def google_connected(self):
        for meeting in self.library.list():
            binding = meeting.get('calendar_sync')
            if binding and binding.get('status') != 'synced':
                self.library.update(meeting['id'],calendar_sync=dict(binding,status='pending',attempts=0,next_retry=0))
        self.automation.retry_pending()

    def _monitor(self):
        while not self.closed.wait(1):
            try:
                with self.lock:
                    if self.preview and time.monotonic() > self.preview_deadline:
                        self._stop_preview()
                    if self.recorder and self.active:
                        status = self.library.get(self.active)['status']
                        if status in {'recording', 'paused'}:
                            error = self.recorder.error()
                            if error:
                                self.stop(error)
                            else:
                                self.recorder.checkpoint()
                self.automation.retry_pending()
            except Exception as exc:
                print(f'Monitor: {exc}', flush=True)

    def close(self):
        self.closed.set()
        self.automation.close()
        if self.start_thread and self.start_thread.is_alive():
            self.start_thread.join(timeout=35)
        if self.finish_thread and self.finish_thread.is_alive():
            self.finish_thread.join(timeout=20)
        with self.lock:
            self._stop_preview()
            if self.active and self.recorder:
                # Signal handlers let the normal durability path finish before exit.
                self.recorder.stop()
                self.library.update(self.active, status='interrupted', progress='Saved raw audio — recover on next launch',
                    ended_at=dt.datetime.now().astimezone().isoformat(),duration=self.recorder.clock.elapsed())
        for live in self.live_sessions.values():
            live.request_stop()
        for live in self.live_sessions.values():
            live.close()
