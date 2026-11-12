from __future__ import annotations

from contextlib import contextmanager
from .work_graph import WorkGraph, validate_graph
from .work_items import COLLECTIONS, normalize
import copy
import json
import re
import secrets
import shutil
import hashlib
import datetime as dt
import os
from pathlib import Path
import threading
import time
import uuid

import numpy as np
import sounddevice as sd

from .capture import Recorder, audio_created, convert_audio, devices, ffmpeg_path, render_recording
from .storage import Library, atomic_json
from .transcripts import segment_at, stamp_seconds, time_stamp
from .meeting_review import review_state
from . import voices
from .jobs import Job, JobCancelled
from . import processing
from . import correction
from . import analytics as conversation
from . import diarization
from . import parakeet, parakeet_sherpa
from .repo_reports import RepoReports, read_store as read_report_store
from . import backup
from . import items
from . import briefing
from . import meeting_types
from . import search
from .events import Watcher
from .projects import Projects
from .meeting_templates import Templates
from .conversations import Conversations
from .people import People
from . import identity_channels
from .github_links import GitHubLinks, parse as parse_github_reference
from . import whisper
from .live import LiveSession, read_json
from .google_calendar import GoogleCalendar, bundled_client, CalendarError
from .gmail import GmailSync
from .gmail_ai import GmailAI
from .google_chat import ChatSync
from .github_source import GitHubConnection,GitHubSync,GitHubError
from .meeting_automation import MeetingAutomation
from .local_ai import DEFAULT_BASE_URL, DEFAULT_CONTEXT, DEFAULT_MODEL, migrate_settings, validate_base_url

DEFAULTS = dict(transcription='local', local_model='large-v3-turbo', cloud_model='gpt-transcribe',
                summarizer='none', llm_model='gpt-4.1-mini', transcript_correction='local',
                local_ai_base_url=DEFAULT_BASE_URL, local_ai_model=DEFAULT_MODEL, local_ai_format='json_schema', local_ai_max_tokens=4096, local_ai_reasoning='default', local_ai_context=DEFAULT_CONTEXT, local_ai_temperature='zero', task_matching_target='', auto_process=True, live_transcription=True,
                whisper_vad=True, whisper_vocabulary='', audio_preparation='off',
                diarization_enabled=True, auto_title=True, meeting_task_ai=False, title_provider='local', title_model='gpt-4.1-mini',
                calendar_enabled=False, calendar_id='', calendar_name='', calendar_account='',
                # The name of the person who runs Atlanta, as a speaker: the team analysis coaches this person (2026-11-13).
                self_name='')


MARKER_KINDS = ('important', 'decision', 'check')
AUDIO_TYPES = {'.m4a', '.mp3', '.wav', '.aac', '.ogg', '.opus', '.flac', '.webm', '.mp4', '.mov', '.caf', '.aiff', '.aif', '.amr', '.3gp'}
MAX_AUDIO_BYTES = 4_000_000_000


class MeetingService:
    def __init__(self, root: Path, project: Path, google=None, backup_dir: Path | None = None, step_runner=None):
        self.project = project
        self.models_dir = project / 'models'
        self.backup_dir = backup_dir or Path.home() / 'Documents' / 'Meeting Assistant Backups'
        self.library = Library(root)
        self.library.recover()
        self.settings_path = root / 'settings.json'
        self.settings = dict(DEFAULTS)
        self.settings_error = None
        if self.settings_path.exists():
            try:
                saved = json.loads(self.settings_path.read_text())
                if not isinstance(saved, dict):
                    raise ValueError('not an object')
                self.settings.update(migrate_settings(saved))
            except (ValueError, OSError, UnicodeDecodeError):
                # A damaged settings file must not lock the person out of the library. The app starts with safe
                # defaults: no automatic processing, no calendar, no cloud AI. The original bytes stay in a copy.
                copy_path = None
                try:
                    copy_path = self.settings_path.with_name('settings.corrupt-' + secrets.token_hex(8) + '.json')
                    copy_path.write_bytes(self.settings_path.read_bytes())
                except OSError:
                    copy_path = None
                self.settings = dict(DEFAULTS, auto_process=False, calendar_enabled=False)
                self.settings_error = ('Settings could not be read, so the app uses safe defaults: no automatic processing, '
                                       'no calendar and no cloud AI.' + (f' The damaged file is kept as {copy_path.name}.' if copy_path else '')
                                       + ' Check Settings and save them to replace the damaged file.')
        self.google = google or GoogleCalendar(root, builtin=bundled_client(project))
        self.base_url = 'http://127.0.0.1:8765'
        self.api_key = os.environ.get('OPENAI_API_KEY', '')
        self.elevenlabs_api_key = os.environ.get('ELEVENLABS_API_KEY', '')
        self.elevenlabs_key_error = None
        # The key of the configured (OpenAI-compatible) API, for example a cloud endpoint. A local server needs none.
        self.local_ai_api_key = os.environ.get('LOCAL_AI_API_KEY', '')
        self.local_ai_key_error = None
        self.local_ai_marker = root / 'local-ai-key.json'
        from .local_ai import KeyStore as LocalAIKeyStore
        self.local_ai_store = LocalAIKeyStore()
        if not self.local_ai_api_key and self.local_ai_marker.exists():
            try:
                saved = self.local_ai_store.get()
                self.local_ai_api_key = saved.get('api_key', '') if isinstance(saved, dict) else ''
            except Exception:
                self.local_ai_key_error = 'The API key could not be read from Keychain. Unlock Keychain or enter the key again.'
        # This file holds no secret. It says that Keychain has a key, so tests and new libraries never open Keychain.
        self.elevenlabs_marker = root / 'elevenlabs.json'
        from .scribe import KeyStore
        self.elevenlabs_store = KeyStore()
        if not self.elevenlabs_api_key and self.elevenlabs_marker.exists():
            try:
                saved = self.elevenlabs_store.get()
                self.elevenlabs_api_key = saved.get('api_key', '') if isinstance(saved, dict) else ''
            except Exception:
                self.elevenlabs_key_error = 'The ElevenLabs key could not be read from Keychain. Unlock Keychain or enter the key again.'
        self.lock = threading.RLock()
        self.active = None
        self.start_thread = None
        self.finish_thread = None
        self.recorder = None
        self.live_sessions = {}
        self.busy = set()
        self.processing_slot = threading.Semaphore(1)
        self.voice_job = dict(running=False, done=0, total=0, failed=0)
        self.voice_thread = None
        self.step_runner = step_runner
        self.cancel_events = {}
        self.processing_threads = {}
        self.desktop_mode = False
        self.activity_changed = lambda active: None
        self.health_changed = lambda missing: None
        self.editor_changed = lambda dirty: None
        self.review_notify = None
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
        self.items.meeting_date = lambda meeting_id: items.meeting_time(self.library.get(meeting_id))
        from .commit_journal import CommitJournal
        CommitJournal(self.items.store.path).recover()
        self.projects = Projects(root / 'projects.json')
        self.people = self.library.people
        from .team_reviews import TeamReviews
        self.team_reviews = TeamReviews(self.library.root)
        self.github_links = GitHubLinks(root / 'github-links.json')
        self.templates = Templates(root / 'meeting-templates.json')
        from .capture_setup import CaptureSetup
        self.capture_setup=CaptureSetup(root/'capture-setup.json')
        from .prompts import Prompts
        self.prompts = Prompts(root / 'ai-prompts.json')
        from .prompt_lab import PromptLab
        self.prompt_lab = PromptLab(self)
        self.conversations = Conversations(self)
        self.search_index = search.SearchIndex(root / 'search.db')
        self._sync_all_items()
        self.gmail = GmailSync(root, self.google, lambda: self.closed.is_set() or bool(self.active or self.busy), self._refresh_gmail_source)
        self.gmail_ai = GmailAI(self)
        self.chat = ChatSync(root,self.google,lambda:self.closed.is_set() or bool(self.active or self.busy),
                             self._refresh_chat_message,self._chat_unavailable)
        self.github = GitHubSync(root,GitHubConnection(root),lambda:self.closed.is_set() or bool(self.active or self.busy),
                                 self._refresh_github_source,self._github_unavailable)
        self.repo_reports = RepoReports(self)
        from .task_draft import DraftJobs
        self.task_drafts = DraftJobs(self)
        from .task_titles import TitleJobs
        self.task_titles = TitleJobs(self)
        from .team_ai import ReviewAI
        self.team_ai = ReviewAI(self)
        from .team_github import TeamGitHub
        self.team_github = TeamGitHub(self)
        from .job_registry import Jobs
        self.jobs = Jobs(self)
        self.automation = MeetingAutomation(self)
        self.monitor = threading.Thread(target=self._monitor, daemon=True)
        self.monitor.start()
        self.watcher = Watcher(self)

    def validate_settings(self, settings):
        if set(settings) - set(DEFAULTS):
            raise ValueError('Unknown setting')
        values = migrate_settings(dict(self.settings, **settings))
        if values['audio_preparation'] not in {'off', 'light', 'strong'}:
            raise ValueError('Audio preparation must be Off, Light or Strong')
        values['local_ai_base_url'] = validate_base_url(values['local_ai_base_url'])
        if type(values['local_ai_max_tokens']) is not int or not 128 <= values['local_ai_max_tokens'] <= 32768:
            raise ValueError('API output limit must be between 128 and 32768 tokens')
        if values['local_ai_reasoning'] not in {'default', 'server', 'none', 'low', 'medium', 'high'}:
            raise ValueError('Invalid API reasoning effort')
        if values['local_ai_temperature'] not in {'zero', 'server'}:
            raise ValueError('Invalid temperature setting')
        # The permission to send task context goes with one API address. Another address needs a new permission.
        if not isinstance(values['task_matching_target'], str):
            raise ValueError('Invalid task matching permission')
        if values['task_matching_target'] and values['task_matching_target'] != values['local_ai_base_url']:
            values['task_matching_target'] = ''
        if type(values['local_ai_context']) is not int or not 4096 <= values['local_ai_context'] <= 2_000_000:
            raise ValueError('The model context must be between 4096 and 2000000 tokens')
        from .processing import CHARS_PER_TOKEN, MIN_PART_CHARS, PROMPT_TOKENS
        # The output limit and the notes instructions must leave room for some transcript in the context.
        if values['local_ai_context'] - values['local_ai_max_tokens'] < PROMPT_TOKENS + MIN_PART_CHARS / CHARS_PER_TOKEN:
            raise ValueError(f"The output limit leaves no room for the transcript: keep it at least "
                             f"{int(PROMPT_TOKENS + MIN_PART_CHARS / CHARS_PER_TOKEN)} tokens below the model context.")
        if values['local_ai_format'] not in {'json_schema', 'json_object', 'text'}:
            raise ValueError('Invalid API response format')
        if (values['transcription'] not in {'local', 'parakeet', 'parakeet_sherpa', 'openai', 'elevenlabs'} or values['summarizer'] not in {'none', 'local', 'openai'}
                or values['transcript_correction'] not in {'none', 'local', 'openai'}):
            raise ValueError('Invalid processing provider')
        vocabulary = values['whisper_vocabulary']
        if not isinstance(vocabulary, str) or len(vocabulary) > 2000 or any(ord(c) < 32 and c != '\n' for c in vocabulary):
            raise ValueError('The transcription vocabulary must be text of at most 2000 characters')
        from .vocabulary import entries
        entries(vocabulary)
        if values['transcription'] == 'elevenlabs':
            from .scribe import keyterms
            keyterms(vocabulary)
        for field in ['auto_process', 'live_transcription', 'whisper_vad', 'diarization_enabled', 'auto_title', 'meeting_task_ai', 'calendar_enabled']:
            if type(values[field]) is not bool:
                raise ValueError(f'{field} must be true or false')
        if values['title_provider'] not in {'local','openai'}:
            raise ValueError('Invalid title provider')
        for field in ['calendar_id','calendar_name','calendar_account']:
            if not isinstance(values[field],str) or len(values[field])>512 or any(ord(c)<32 for c in values[field]):
                raise ValueError('Invalid calendar setting')
        if not isinstance(values['self_name'],str) or len(values['self_name'])>100 or any(ord(c)<32 for c in values['self_name']):
            raise ValueError('Your name must be one line of at most 100 characters')
        values['self_name']=values['self_name'].strip()
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
            elevenlabs_key = values.pop('elevenlabs_api_key', None)
            if elevenlabs_key is not None and (not isinstance(elevenlabs_key, str) or len(elevenlabs_key) > 1000 or any(ord(c) < 32 for c in elevenlabs_key)):
                raise ValueError('Invalid ElevenLabs API key')
            key = values.pop('api_key', None)
            if key is not None and (not isinstance(key, str) or len(key) > 1000 or '\n' in key):
                raise ValueError('Invalid API key')
            local_key = values.pop('local_ai_api_key', None)
            if local_key is not None and (not isinstance(local_key, str) or len(local_key) > 1000 or any(ord(c) < 32 for c in local_key)):
                raise ValueError('Invalid API key for the configured API')
            settings = self.validate_settings(values)
            previous = dict(self.settings)
            # Choose Parakeet only where it can run, so a meeting does not fail after the recording.
            if settings['transcription'] == 'parakeet_sherpa':
                parakeet_sherpa.vocabulary_terms(settings['whisper_vocabulary'], self.library.speakers())
                runtime = parakeet_sherpa.availability()
                if not runtime['available']:
                    raise ValueError(runtime['message'])
            if settings['transcription'] == 'parakeet' and previous.get('transcription') != 'parakeet':
                runtime = parakeet.availability()
                if not runtime['available']:
                    raise ValueError(runtime['message'])
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
            # Valid settings replace a damaged file; its copy stays.
            self.settings_error = None
            if key is not None:
                self.api_key = key.strip()
            if elevenlabs_key is not None:
                self._save_elevenlabs_key(elevenlabs_key.strip())
            if local_key is not None:
                self._save_local_ai_key(local_key.strip())
            return dict(elevenlabs_api_key_configured=bool(self.elevenlabs_api_key), elevenlabs_key_error=self.elevenlabs_key_error, settings=self.settings, api_key_configured=bool(self.api_key), google=self.google.status(),
                        **self.local_ai_key_status())

    def local_ai_key_status(self):
        from .local_ai import is_remote
        return dict(local_ai_api_key_configured=bool(self.local_ai_api_key), local_ai_key_error=self.local_ai_key_error,
                    local_ai_remote=is_remote(self.settings.get('local_ai_base_url')))

    def ai_key(self, provider):
        """The key for one AI provider. A key never goes to another provider."""
        return self.api_key if provider == 'openai' else self.local_ai_api_key if provider == 'local' else ''

    def redact(self, message):
        for secret in (self.api_key, self.local_ai_api_key, self.elevenlabs_api_key):
            if secret:
                message = message.replace(secret, '[redacted]')
        return message

    def _save_local_ai_key(self, key):
        """Keep the key in Keychain; an empty key forgets it. Settings stay saved if Keychain refuses."""
        try:
            if key:
                self.local_ai_store.set(dict(api_key=key))
                atomic_json(self.local_ai_marker, dict(saved=True))
            else:
                self.local_ai_store.delete()
                self.local_ai_marker.unlink(missing_ok=True)
            self.local_ai_key_error = None
        except Exception:
            self.local_ai_key_error = ('The API key is kept only until the app closes: Keychain refused it.' if key else
                                       'The API key could not be removed from Keychain.')
        self.local_ai_api_key = key

    def _save_elevenlabs_key(self, key):
        """Keep the key in Keychain; an empty key forgets it. Settings stay saved if Keychain refuses."""
        try:
            if key:
                self.elevenlabs_store.set(dict(api_key=key))
                atomic_json(self.elevenlabs_marker, dict(saved=True))
            else:
                self.elevenlabs_store.delete()
                self.elevenlabs_marker.unlink(missing_ok=True)
            self.elevenlabs_key_error = None
        except Exception:
            self.elevenlabs_key_error = ('The ElevenLabs key is kept only until the app closes: Keychain refused it.' if key else
                                         'The ElevenLabs key could not be removed from Keychain.')
        self.elevenlabs_api_key = key

    def readiness(self):
        """What the next recording needs, checked without downloading or opening devices."""
        provider = self.settings['transcription']
        if provider == 'elevenlabs':
            model = dict(ready=bool(self.elevenlabs_api_key), label='Scribe v3 key set' if self.elevenlabs_api_key else 'Add an ElevenLabs key in Settings')
        elif provider == 'openai':
            model = dict(ready=bool(self.api_key), label='OpenAI key set' if self.api_key else 'Add an OpenAI key in Settings')
        elif provider == 'parakeet_sherpa':
            cached = parakeet_sherpa.cached(self.models_dir)
            runtime = parakeet_sherpa.availability()
            model = dict(ready=runtime['available'] and cached, label=('Parakeet + vocabulary ready' if cached else 'Parakeet + vocabulary downloads about 670 MB') if runtime['available'] else runtime['message'])
        elif provider == 'parakeet':
            cached = (self.models_dir / 'parakeet' / ('models--' + parakeet.MODEL_ID.replace('/', '--')) / 'snapshots'
                      / parakeet.MODEL_REVISION / 'model.safetensors').is_file()
            model = dict(ready=parakeet.availability()['available'] and cached,
                         label=parakeet.MODEL_NAME + (' ready' if cached else ' downloads on first use'))
        else:
            name = self.settings['local_model']
            cached = any((self.models_dir / candidate).is_file() for candidate in (name, name + '.bin', f'ggml-{name}.bin'))
            model = dict(ready=cached, label='Whisper ' + name + (' ready' if cached else ' downloads on first use'))
        free = shutil.disk_usage(self.library.root).free
        # Online meetings keep both raw tracks and the mix: about 0.5 GB per hour.
        return dict(model=model, system_audio=(self.project / 'bin/SystemAudio').is_file(),
                    disk_free=free, disk_hours=round(free / 500_000_000, 1))

    def snapshot(self):
        with self.lock:
            try:
                inputs = devices()
                device_error = None
            except Exception as exc:
                inputs, device_error = [], str(exc)
            active = self.library.get(self.active) if self.active else None
            if active and self.recorder:
                active.update(duration=self.recorder.clock.elapsed(), level=self.recorder.level,
                              microphone_status=getattr(self.recorder, 'input_status', 'connected'),
                              microphone_name=getattr(self.recorder, 'input_name', ''))
                live = self.live_sessions.get(self.active)
                active['live'] = live.snapshot() if live else None
                active['markers'] = read_json(self.library.directory(self.active) / 'markers.json', [])
            return dict(meetings=[dict(m, has_audio=self._has_audio(m['id'])) for m in self.library.list()], active=active, google=self.google.status(),
                capture_setup=self.capture_setup.public(), storage_errors=self.metadata_errors(), settings_error=self.settings_error, desktop_mode=self.desktop_mode, diarization=diarization.availability(), parakeet=parakeet.availability(), parakeet_sherpa=parakeet_sherpa.availability(),
                speakers=self.library.speakers(), people_migration=self.library.people_migration, voices=dict(self.voice_job), people=self.people.list(), meeting_types=meeting_types.public(self.templates.list()), trackers=self.library.trackers(), task_summary=self.task_summary(), projects=self.projects.data,
                settings=self.settings, elevenlabs_api_key_configured=bool(self.elevenlabs_api_key), elevenlabs_key_error=self.elevenlabs_key_error, api_key_configured=bool(self.api_key), **self.local_ai_key_status(), devices=inputs, readiness=self.readiness(),
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
            meeting['transcript_revision'] = self._transcript_revision(meeting['transcript'])
            from . import team_analysis
            meeting['team_analysis'] = team_analysis.read(self, meeting_id)
            meeting['voice_suggestions'] = self._voice_suggestions(meeting_id, directory, meeting['transcript'])
            meeting['minutes_revision'] = self._minutes_revision(directory)
            from .notes_consolidation import audit_for
            meeting['notes_consolidation'] = audit_for(directory, meeting['minutes'], meeting['transcript']) if notes_valid else None
            meeting['minutes_proposal'] = None
            if notes_valid and (directory / 'minutes.proposed.json').exists():
                from meeting_assistant import validate_minutes
                from . import notes
                try:
                    proposed = json.loads((directory / 'minutes.proposed.json').read_text())
                    validate_minutes(proposed)
                    meeting['minutes_proposal'] = dict(revision=self._notes_revision(directory),
                                                       changes=notes.changes(meeting['minutes'], proposed),
                                                       consolidation=audit_for(directory, proposed, meeting['transcript'], proposed=True))
                except (OSError, ValueError):
                    pass
            ids = set()
            for field in items.FIELD.values():
                for mention in (meeting['minutes'] or {}).get(field, []) if notes_valid else []:
                    ids.add(mention.get('item_id'))
                    ids.update(c.get('item_id') for c in (mention.get('link') or {}).get('candidates', []))
            with self.items.lock:
                ids.update(i['id'] for i in self.items.items.values() if any(l['meeting_id']==meeting_id and l.get('manual_task') for l in i['links']))
                meeting['items'] = {i: self.items.items[i] for i in ids if i in self.items.items}
            meeting['item_meetings'] = self._meeting_refs() if meeting['items'] else {}
            review_sources=self.review_sources() if meeting['items'] else {}
            meeting['items']={key:dict(item,review_state=review_state(item,review_sources)) for key,item in meeting['items'].items()}
            meeting['github_links'] = [link for i in meeting['items'] for link in self.github_links.for_resource('item', i)]
            meeting['live'] = read_json(directory / 'live.json', None)
            meeting['input_gaps'] = read_json(directory / 'capture.json', {}).get('input_gaps', [])
            matching = read_json(directory / 'task-matching.json', None)
            meeting['task_matching'] = (dict(status=matching.get('status'), reason=matching.get('reason'))
                                        if isinstance(matching, dict) and matching.get('status') == 'needs_permission' else None)
            meeting['markers'] = read_json(directory / 'markers.json', [])
            meeting['files'] = [name for name in ['recording.wav', 'transcript.md', 'transcript.json',
                               'transcript.srt', 'transcript.raw.json', 'minutes.md', 'minutes.json',
                               'analytics.json', 'speaker-timeline.json', 'live-transcript.md', 'live-transcript.json', 'markers.json',
                               'transcription.wav', 'transcript.before-speakers.json', 'transcript.alignment.json', 'speaker-turns.json'] if (directory / name).exists()]
            return meeting

    def _stop_preview(self):
        if self.preview:
            self.preview.stop()
            self.preview.close()
            self.preview = None
        self.preview_level = 0

    def _release_live(self, meeting_id, reason=None):
        """Stop a finished recording's caption session; drop it once its worker exits."""
        live = self.live_sessions.get(meeting_id)
        if not live:
            return
        if reason is None:
            live.request_stop()
        else:
            live.request_stop(reason)
        thread = getattr(live, 'thread', None)
        if thread:
            thread.join(timeout=10)
        if not thread or not thread.is_alive():
            with self.lock:
                self.live_sessions.pop(meeting_id, None)

    def input_devices(self):
        """The microphone list, scanned again. The new-meeting form asks for it while it is open."""
        with self.lock:
            try:
                # Rescan only when no audio stream is open; a rescan would break a running stream.
                return dict(devices=devices(rescan=not self.active and not self.recorder and self.preview is None), device_error=None)
            except Exception as exc:
                return dict(devices=[], device_error=str(exc))

    def live_values(self):
        """What changes many times a second: the timer and the levels."""
        with self.lock:
            if self.active and self.recorder:
                return dict(meeting_id=self.active, duration=round(self.recorder.clock.elapsed(), 1), level=round(self.recorder.level, 3))
            if self.preview is not None:
                return dict(preview_level=round(self.preview_level, 3))
            return None

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

    def start(self, title, mode, device, project_id=None, series_id=None, device_name=None, fallback_device_name='', transcription_timing=None,
              meeting_type=None):
        if self.closed.is_set():
            raise ValueError('The app is closing')
        if mode not in {'in_person', 'online'}:
            raise ValueError('Choose an in-person or online meeting')
        if not isinstance(title, str):
            raise ValueError('Meeting title must be text')
        if transcription_timing is not None and transcription_timing not in ('live', 'after'):
            raise ValueError('Choose live captions or transcription after recording')
        if meeting_type is not None:
            self._meeting_type(meeting_type)
        ffmpeg_path()
        device = self._input_device(device, device_name)
        if not isinstance(fallback_device_name, str) or len(fallback_device_name) > 300:
            raise ValueError('Choose an available fallback microphone')
        if fallback_device_name and not any(d['name'] == fallback_device_name and d['id'] != device for d in devices()):
            raise ValueError('Choose another available microphone as fallback')
        with self.lock:
            if self.active:
                raise ValueError('A meeting is already recording')
            self._stop_preview()
            settings = self._with_known_terms(dict(self.settings, models_dir=str(self.models_dir)))
            settings['fallback_microphone'] = fallback_device_name
            settings['_capture_microphone']=next((d.get('name',device_name or '') for d in devices() if d['id']==device),device_name or '')
            if transcription_timing is not None:
                settings['live_transcription'] = transcription_timing == 'live'
            with self.projects.lock:
                project_id = self.projects.ensure_project({'id': project_id} if project_id else None)
                series_id = self.projects.ensure_series({'id': series_id} if series_id else None, project_id)
            # Missing credentials never prevent saving a recording.
            meeting = self.library.create(title, mode, settings)
            # A new meeting of a series starts with the type of the series; a different choice is the person's own.
            inherited = self._series_type(series_id)
            meeting = self.library.update(meeting['id'], project_id=project_id, series_id=series_id,
                                          **self._type_changes(meeting_type or inherited, 'series' if (meeting_type or inherited) == inherited else 'manual'))
            if not self.prompts.error:
                settings['_prompt_snapshot']=self.prompts.snapshot(meeting_types.of(meeting)['id'],meeting['id'])
            meeting=self.library.update(meeting['id'],settings=settings)
            self.active = meeting['id']
            self.activity_changed(True)
            self.start_thread = threading.Thread(target=self._start, args=(meeting['id'], int(device), mode), daemon=True)
            self.start_thread.start()
            return meeting

    def import_transcript(self, text, filename='', modified_ms=None):
        from meeting_assistant import TranscriptSegment, save_transcript
        from .transcripts import parse_transcript
        if not isinstance(text, str) or not text.strip() or len(text) > 5_000_000:
            raise ValueError('Choose a transcript file of at most 5 MB')
        parsed = parse_transcript(text, self.library.speakers())
        segments = [TranscriptSegment(**s) for s in parsed['segments']]
        name = parsed['title'] or (Path(filename).stem if isinstance(filename, str) else '')
        with self.lock:
            settings = dict(self.settings, models_dir=str(self.models_dir))
            meeting = self.library.create(name or '', 'imported', settings)
            changes = dict(status='ready', progress='Imported', duration=max(s.end for s in segments))
            if parsed['date']:
                # Noon keeps the date the same in every time zone of the user.
                when = dt.datetime.combine(parsed['date'], dt.time(12)).astimezone().isoformat()
                changes.update(created=when, started_at=when)
            elif type(modified_ms) is int and 0 < modified_ms < 4102444800000:
                # Like imported audio: without a date in the text, the file's date is the meeting date.
                start = dt.datetime.fromtimestamp(modified_ms / 1000).astimezone() - dt.timedelta(seconds=changes['duration'])
                changes.update(created=start.isoformat(), started_at=start.isoformat(),
                               ended_at=(start + dt.timedelta(seconds=changes['duration'])).isoformat())
            self.library.update(meeting['id'], **changes)
            save_transcript(self.library.directory(meeting['id']), segments)
            self.library.add_speakers(s.speaker for s in segments if s.speaker)
            self.busy.add(meeting['id'])
        self._analyze_unlocked(meeting['id'], settings)
        if settings.get('auto_process') and (settings['summarizer'] != 'none' or settings.get('transcript_correction', 'none') != 'none'):
            try:
                self.process(meeting['id'], 'all')
            except ValueError as exc:
                # For example, a missing API key. The imported transcript is kept and ready; the notes wait.
                self.library.update(meeting['id'], notes_refresh_error='Notes were not made automatically: ' + self.redact(str(exc))
                                    + ' Fix this in Settings, then choose Update notes & tasks.')
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
                settings = dict(self.settings, models_dir=str(self.models_dir))
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
            recorder.fallback_name = self.library.get(meeting_id)['settings'].get('fallback_microphone', '')
            with self.lock:
                self.recorder = recorder
            recorder.start()
            if self.closed.is_set():
                recorder.stop()
                with self.lock:
                    self.library.update(meeting_id, status='interrupted', progress='App closed — saved audio can be recovered')
                    self.active, self.recorder = None, None
                    self.activity_changed(False)
                return
            with self.lock:
                self.library.update(meeting_id, status='recording', progress='Recording',started_at=dt.datetime.now().astimezone().isoformat())
                try:self.capture_setup.remember(self.library.get(meeting_id))
                except (ValueError,OSError):pass  # Metadata failure must never stop durable audio capture.
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
            self._release_live(meeting_id)
            with self.lock:
                self.library.update(meeting_id, status='error', error=str(exc), progress='Recording could not start')
                self.active, self.recorder = None, None
                self.activity_changed(False)

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
            self._release_live(meeting_id)
            duration = render_recording(self.library.directory(meeting_id))
            with self.lock:
                meeting = self.library.update(meeting_id, status='recorded', duration=duration,
                    warnings=list(getattr(recorder, 'warnings', [])),
                    error=failure, progress='Recording saved' if not failure else 'Stopped after an audio error; recording saved')
                self.active, self.recorder = None, None
                self.activity_changed(False)
                if meeting['settings']['auto_process'] and not failure and not self.closed.is_set():
                    try:
                        self.process(meeting_id, 'all', use_saved=True)
                        processing_started = True
                    except Exception as exc:
                        self.library.update(meeting_id, status='recorded', error=str(exc),
                                            progress='Recording saved — update settings and retry processing')
        except Exception as exc:
            self._release_live(meeting_id)
            with self.lock:
                self.library.update(meeting_id, status='interrupted', error=str(exc),
                                    progress='Raw audio saved — open More → Recover audio')
                self.active, self.recorder = None, None
                self.activity_changed(False)
        finally:
            self._queue_metadata(meeting_id,enrich=not processing_started)


    def process(self, meeting_id, action, use_saved=False, preserve_notes=False):
        if self.closed.is_set():
            raise ValueError('The app is closing')
        if action not in {'all', 'transcribe', 'summarize', 'recover', 'correct', 'correct_summarize', 'reanalyze', 'speakers'}:
            raise ValueError('Unknown processing action')
        with self.lock:
            meeting = self.library.get(meeting_id)
            if meeting_id == self.active or meeting_id in self.busy:
                raise ValueError('This meeting is already busy')
            if meeting['mode'] == 'audio' and action == 'recover':
                raise ValueError('An imported audio file has no raw tracks to recover')
            # A full run of an imported transcript corrects the text like a transcription would, then makes notes.
            imported_all = meeting['mode'] == 'imported' and action == 'all'
            if meeting['mode'] == 'imported' and action in {'transcribe', 'recover', 'speakers'}:
                raise ValueError('An imported transcript has no audio to transcribe')
            settings = meeting['settings'] if use_saved else dict(self.settings, models_dir=str(self.models_dir))
            # Migrate once, after the per-meeting fields below are pinned.
            if preserve_notes:
                if action!='all':raise ValueError('Preserve notes applies to full reprocessing')
                settings['_reprocess_preserve_notes']=True
            # Processing retries do not opt old meetings into a different calendar or AI provider.
            for field in ['calendar_enabled','calendar_id','calendar_name','calendar_account','auto_title','title_provider','title_model']:
                settings[field] = meeting['settings'].get(field, DEFAULTS[field] if field != 'auto_title' else False)
            settings = self._with_known_terms(migrate_settings(settings))
            if imported_all:
                correction_on = settings.get('transcript_correction', 'none') != 'none'
                if settings['summarizer'] != 'none':
                    action = 'summarize'
                elif correction_on:
                    action = 'correct'
                else:
                    raise ValueError('Choose Local API or OpenAI for notes or transcript correction in Settings first')
            if action in {'summarize','correct_summarize'} and settings['summarizer'] == 'none':
                raise ValueError('Choose Local API or OpenAI for notes in Settings first')
            settings.setdefault('transcript_correction', 'none')
            settings.setdefault('diarization_enabled', True)
            if action in {'correct','correct_summarize'}:
                if settings['transcript_correction'] == 'none':
                    raise ValueError('Choose Local API or OpenAI for transcript correction in Settings first')
                if not (self.library.directory(meeting_id) / 'transcript.json').exists():
                    raise ValueError('Transcribe the recording before AI correction')
            if action == 'speakers' and (not (self.library.directory(meeting_id) / 'transcript.json').exists()
                    or not (self.library.directory(meeting_id) / 'recording.wav').exists()):
                raise ValueError('A saved recording and final transcript are required for speaker separation')
            if action == 'reanalyze' and not (self.library.directory(meeting_id) / 'transcript.json').exists():
                raise ValueError('Transcribe or import a meeting before running analytics')
            # Capture the keys for this job; they are never persisted in metadata.
            key = self.api_key
            elevenlabs_key = self.elevenlabs_api_key
            local_key = self.local_ai_api_key
            from .local_ai import is_remote
            uses_local = (action in {'all', 'summarize', 'correct_summarize'} and settings['summarizer'] == 'local'
                          or action in {'correct', 'correct_summarize'} and settings['transcript_correction'] == 'local')
            if uses_local and is_remote(settings.get('local_ai_base_url')) and not local_key:
                raise ValueError('Add the API key of the configured API in Settings first. Your recording is saved.')
            if action in {'all', 'transcribe'} and settings['transcription'] == 'elevenlabs' and not elevenlabs_key:
                raise ValueError('Add an ElevenLabs API key in Settings first. Your recording is saved.')
            if (action in {'all', 'transcribe'} and settings['transcription'] == 'openai' or
                action in {'all', 'summarize','correct_summarize'} and settings['summarizer'] == 'openai' or
                (action in {'correct','correct_summarize'} or imported_all or action in {'all', 'transcribe'} and settings['transcription'] != 'elevenlabs')
                and settings['transcript_correction'] == 'openai') and not key:
                raise ValueError('Add an OpenAI API key in Settings first. Your recording is saved.')
            if action in {'all','summarize','correct','correct_summarize','reanalyze'} and '_prompt_snapshot' not in settings:
                settings['_prompt_snapshot']=self.prompts.snapshot(meeting_types.of(meeting)['id'],meeting_id)
            self.busy.add(meeting_id)
            self.library.update(meeting_id, status='processing', error=None, settings=settings, progress='Queued for processing')
            self.cancel_events[meeting_id] = threading.Event()
            self.library.update(meeting_id, processing_cancel_requested=False, processing_stage='Queued',
                                processing_started_at=time.time(), processing_stage_started_at=time.time(),
                                processing_timings={}, processing_elapsed=0)
            if self.active and self.active in self.live_sessions:
                self.live_sessions[self.active].request_stop('Live captions paused to process a saved meeting. Audio recording continues.')
            thread = threading.Thread(target=self._process, args=(meeting_id, action, settings, key, elevenlabs_key, imported_all, local_key), daemon=True)
            self.processing_threads[meeting_id] = thread
            thread.start()
            return {'id': meeting_id, 'status': 'processing'}

    def cancel_processing(self, meeting_id):
        with self.lock:
            self.library.get(meeting_id)
            cancel = self.cancel_events.get(meeting_id)
            if cancel is None or meeting_id not in self.busy:
                raise ValueError('No processing job is running for this meeting')
            cancel.set()
            self.library.update(meeting_id, processing_cancel_requested=True, progress='Cancelling processing…')
            return {'id': meeting_id, 'cancel_requested': True}

    def _execute(self, action, directory, settings, progress, key='', speakers=(), trackers=()):
        if action in {'summarize','correct','analytics','task_matching'} and '_prompt_snapshot' not in settings:
            meeting=read_json(directory/'meeting.json',{})
            settings=dict(settings,_prompt_snapshot=self.prompts.snapshot(meeting_types.of(meeting)['id'],meeting.get('id')))
        if action in {'summarize','correct','analytics','task_matching'}:
            from .prompts import record_usage
            record_usage(directory,action,settings['_prompt_snapshot'])
        if self.step_runner:
            return self.step_runner.run(action, directory, settings, progress, key, speakers, trackers,
                                        cancel=self.cancel_events.get(directory.name))
        # In-process embedding uses the same dispatcher; progress checks cancel
        # between chunks. The desktop launcher supplies an isolated worker.
        from .worker import execute
        return execute(action, directory, settings, progress, key, speakers, trackers)

    def _process(self, meeting_id, action, settings, key, elevenlabs_key='', auto_correct=False, local_key=''):
        # Each AI step gets the key of its own provider: OpenAI or the configured API.
        step_key = lambda provider: key if provider == 'openai' else local_key if provider == 'local' else ''
        cancel = self.cancel_events.setdefault(meeting_id, threading.Event())
        job = Job(cancel, lambda **changes: self.library.update(meeting_id, **changes))
        acquired = False
        completed = False
        try:
            with job.step('Queued'):
                while not self.processing_slot.acquire(timeout=.1):
                    job.check()
                acquired = True
                job.check()
            directory = self.library.directory(meeting_id)
            progress = job.update
            imported = self.library.get(meeting_id)['mode'] == 'imported'
            if action in {'all','transcribe','recover'} and not imported and (not (directory / 'recording.wav').exists() or action == 'recover'):
                with job.step('Recovering audio'):
                    duration = self._execute('recover', directory, settings, progress)
                    self.library.update(meeting_id, duration=duration)
            if action in {'all', 'transcribe'}:
                with job.step('Transcription'):
                    self._execute('transcribe', directory, settings, progress, elevenlabs_key if settings['transcription'] == 'elevenlabs' else key, self.library.speakers())
                    if settings.get('_reprocess_preserve_notes'):
                        self.library.update(meeting_id,notes_need_refresh=(directory/'minutes.json').exists(),notes_refresh_error=None)
            should_diarize = action in {'all', 'transcribe', 'speakers'}
            if should_diarize and (action == 'speakers' or settings.get('diarization_enabled', True)) and (directory / 'recording.wav').exists():
                with job.step('Speaker identification'):
                    self._run_diarization(meeting_id, directory, progress)
            # Scribe text is final; AI correction runs after it only on explicit request.
            # An imported transcript is corrected like a new transcription; its failure does not stop the notes.
            automatic_correction = action in {'all', 'transcribe'} and settings['transcription'] != 'elevenlabs' or auto_correct
            if (automatic_correction or action in {'correct','correct_summarize'}) and settings.get('transcript_correction', 'none') != 'none':
                try:
                    with job.step('Transcript correction'):
                        before_correction=(directory/'transcript.json').read_bytes()
                        self._execute('correct', directory, settings, progress, step_key(settings.get('transcript_correction')), self.library.speakers())
                        if (directory/'transcript.json').read_bytes()!=before_correction:
                            processing.archive(directory,['minutes.proposed.json'])
                            (directory/'minutes.proposed.json').unlink(missing_ok=True)
                            self.library.update(meeting_id,notes_need_refresh=(directory/'minutes.json').exists(),notes_refresh_error=None)
                        self.library.update(meeting_id, correction_error=None)
                except JobCancelled:
                    raise
                except Exception as exc:
                    if action in {'correct','correct_summarize'} and not auto_correct:
                        raise
                    message = self.redact(str(exc))
                    self.library.update(meeting_id, correction_error=message)
            if action in {'summarize','correct_summarize'} or action == 'all' and settings['summarizer'] != 'none':
                with job.step('Meeting notes'):
                    self._execute('summarize', directory, settings, progress, step_key(settings.get('summarizer')), self.note_names())
                    self.library.update(meeting_id, notes_need_refresh=(directory / 'minutes.proposed.json').exists(), notes_refresh_error=None)
                # Matching the notes to existing tasks is a step of the same job. Its failure never stops the notes.
                # Without AI meeting tasks the job ends with the notes: the person makes and updates the tasks.
                if self.meeting_task_ai():
                    try:
                        with job.step('Task matching'):
                            self._match_tasks(meeting_id, directory, settings, progress, step_key('local'))
                    except JobCancelled:
                        raise
                    except Exception as exc:
                        self._save_matching(directory, dict(status='failed', error=self.redact(str(exc))))
            if action != 'recover' and (directory / 'transcript.json').exists():
                with job.step('Analytics'):
                    self._run_analytics(meeting_id, settings, progress)
            job.check()
            self.library.update(meeting_id, status='ready' if (directory / 'transcript.json').exists() else 'recorded',
                                error=None, progress='Ready', processing_stage='Complete')
            completed = True
        except JobCancelled:
            directory = self.library.directory(meeting_id)
            self.library.update(meeting_id, status='ready' if (directory / 'transcript.json').exists() else 'recorded',
                error=None, progress='Processing cancelled — saved audio and completed checkpoints are preserved', processing_stage='Cancelled')
        except Exception as exc:
            message = self.redact(str(exc))
            self.library.update(meeting_id, status='error', error=message, processing_stage='Failed',
                                progress='Processing failed — recording preserved')
        finally:
            if acquired:
                self.processing_slot.release()
            try:
                self._sync_items(meeting_id)
            except Exception as exc:
                print(f'Task registry: {exc}', flush=True)
            with self.lock:
                self.busy.discard(meeting_id)
                self.cancel_events.pop(meeting_id, None)
                self.processing_threads.pop(meeting_id, None)
            self._queue_metadata(meeting_id, enrich=not cancel.is_set())
        if completed and self.review_notify:
            try:
                meeting = self.library.get(meeting_id)
                if meeting.get('status') == 'ready' and self._review_pending(meeting_id, meeting):
                    self.review_notify(meeting_id, meeting['title'])
            except Exception:
                pass

    def _save_matching(self, directory, record):
        atomic_json(directory / 'task-matching.json', dict(version=1, at=items.now(), **record))

    def meeting_task_ai(self) -> bool:
        """Whether AI makes task and decision proposals and matches from meeting notes. Off by default since 2026-11-12:
        the AI stops at the notes, tasks and decisions are text there, and the person creates tasks by hand."""
        return bool(self.settings.get('meeting_task_ai'))

    def allow_task_matching(self, meeting_id):
        """Grant the one-address task matching permission and match this meeting's notes in the background."""
        from .local_ai import is_remote
        if not self.meeting_task_ai():
            raise ValueError('AI tasks from meetings are off. Turn them on in Settings → AI to match tasks.')
        directory = self.library.directory(meeting_id)
        if not (directory / 'minutes.json').exists():
            raise ValueError('Generate the notes first; matching compares them with the existing tasks.')
        settings = copy.deepcopy(self.settings)
        if settings.get('summarizer') != 'local':
            raise ValueError('Task matching uses the configured API. Choose that API for notes first.')
        base_url = settings.get('local_ai_base_url')
        if not is_remote(base_url):
            raise ValueError('This API runs on this Mac or your network; it needs no matching permission.')
        with self.lock:
            if self.closed.is_set() or self.active or self.busy:
                raise ValueError('Wait until recording or processing finishes.')
            self.save_settings(dict(task_matching_target=base_url))
            threading.Thread(target=self._run_task_matching, args=(meeting_id,), name='task-matching', daemon=True).start()
        return {'id': meeting_id, 'status': 'matching'}

    def _run_task_matching(self, meeting_id):
        try:
            directory = self.library.directory(meeting_id)
            self._match_tasks(meeting_id, directory, copy.deepcopy(self.settings), lambda message: None, self.ai_key('local'))
            self._queue_metadata(meeting_id)
        except Exception as exc:
            print(f'Task matching: {exc}', flush=True)

    def _review_pending(self, meeting_id, meeting):
        # What the Review banner counts: unnamed speakers, notes to check, proposed items.
        directory = self.library.directory(meeting_id)
        try:
            speakers = {row.get('speaker') for row in json.loads((directory / 'transcript.json').read_text())}
        except (OSError, ValueError):
            speakers = set()
        unnamed = any(name and re.fullmatch(r'SPEAKER[ _-]?\d+', name, re.I) for name in speakers)
        with self.items.lock:
            proposed = self.meeting_task_ai() and any(item.get('acceptance_state') == 'proposed'
                           and any(link['meeting_id'] == meeting_id for link in item.get('links', []))
                           for item in self.items.items.values())
        return bool(unnamed or proposed or (directory / 'minutes.proposed.json').exists()
                    or meeting.get('notes_need_refresh') or meeting.get('notes_refresh_error'))

    def _match_tasks(self, meeting_id, directory, settings, progress, key):
        """Suggest which existing task each task or update of the notes belongs to. Nothing changes a task here."""
        from . import task_matching
        from .local_ai import is_remote
        path = directory / ('minutes.proposed.json' if (directory / 'minutes.proposed.json').exists() else 'minutes.json')
        minutes = read_json(path, None)
        if not minutes:
            return
        if settings.get('summarizer') != 'local':
            return self._save_matching(directory, dict(status='skipped', reason='Task matching uses the configured API.', notes=path.name))
        base_url = settings.get('local_ai_base_url')
        if is_remote(base_url) and settings.get('task_matching_target') != base_url:
            return self._save_matching(directory, dict(status='needs_permission', notes=path.name,
                reason='Allow task context for this API in Settings → AI to match tasks.'))
        from .transcripts import segment_at
        rows = read_json(directory / 'transcript.json', [])

        def speaker_at(stamp):
            # The speaker of the cited words, and the person in People with exactly that name.
            segment = segment_at(rows, stamp) if stamp and rows else None
            name = (segment or {}).get('speaker')
            person = self.people.match(name) if name else None
            return (person['name'] if person else name), (person['id'] if person else None)
        with self.lock, self.items.lock:
            try:
                self._link_confirmed_owners()
            except items.WorkItemConflict:
                pass
            meeting = self.library.get(meeting_id)
            meetings = self._meeting_refs()
            tasks = [dict(item, effective_project_ids=self.effective_project_ids(item, meetings)) for item in self.items.items.values() if item['kind'] == 'task']
            names = {p['id']: p['name'] for p in self.projects.data['projects']}
            data = task_matching.select(tasks, minutes, meeting, names, self.people.list(), speaker_at)
        if not data:
            return self._save_matching(directory, dict(status='no_candidates', notes=path.name))
        sign = task_matching.signature(data, settings)
        previous = read_json(directory / 'task-matching.json', {})
        if previous.get('signature') == sign and previous.get('status') == 'complete':
            return self._add_meeting_updates(meeting_id, directory, previous)  # a retry: the saved answer stands
        progress(f"Matching tasks with existing work · {len(data['existing_tasks'])} candidates")
        result = self._execute('task_matching', directory, dict(settings, task_matching_input=data), progress, key)
        self._save_matching(directory, dict(status='complete', signature=sign, notes=path.name,
            target=dict(base_url=base_url, model=settings.get('local_ai_model')),
            candidates={c['id']: c['revision'] for c in data['existing_tasks']},
            mentions=data['mentions'], speaker_ids=data.get('speaker_ids', {}), matches=result['matches'], rejected=result['rejected']))
        self._add_meeting_updates(meeting_id, directory, read_json(directory / 'task-matching.json', {}))

    def _add_meeting_updates(self, meeting_id, directory, record):
        """Add what a speaker said about their own open task to that task. Running it again adds nothing new.
        The added mentions are kept in the record, so For review does not show them again."""
        from . import task_matching
        with self.lock, self.items.lock:
            # The update has the time of the meeting, not of the check: an old meeting never hides a newer update.
            when = task_matching.cutoff(self.library.get(meeting_id)).astimezone().isoformat(timespec='seconds')
            rows = task_matching.automatic(record, self.items.items)
            applied, added = list(record.get('applied') or []), 0
            for row in rows:
                task = self.items.items[row['task_id']]
                same = any(e.get('event') == 'progress_update' and e.get('meeting_id') == meeting_id
                           and e.get('evidence_timestamp') == row['evidence_timestamp'] and e.get('text') == row['text']
                           for e in task.get('history', []))
                if not same:
                    task['history'].append(dict(at=when, event='progress_update', by='ai', changes={}, text=row['text'],
                                                meeting_id=meeting_id, evidence_timestamp=row['evidence_timestamp'],
                                                quote=(row['quote'] or '')[:500] or None, mention_id=row['mention_id']))
                    added += 1
                if row['mention_id'] not in applied:
                    applied.append(row['mention_id'])
            if added:
                self.items.save()
            if applied != list(record.get('applied') or []):
                self._save_matching(directory, {**{k: v for k, v in record.items() if k not in ('version', 'at')}, 'applied': applied})
            return added

    def remove_meeting_update(self, item_id, body):
        """Remove one update that a meeting added by itself. The history keeps a record of the removal."""
        if not isinstance(body, dict):
            raise ValueError('Choose the update to remove')
        with self.lock, self.items.lock:
            task = self.items.items.get(item_id)
            if not task or task['kind'] != 'task':
                raise ValueError('Choose an existing task')
            history = task['history']
            index = next((i for i, e in enumerate(history) if e.get('event') == 'progress_update' and e.get('by') == 'ai'
                          and e.get('meeting_id') == body.get('meeting_id') and e.get('text') == body.get('text')
                          and e.get('evidence_timestamp') == body.get('evidence_timestamp')), None)
            if index is None:
                raise items.WorkItemConflict('This update is no longer in the task. Reload the task.')
            removed = history.pop(index)
            history.append(dict(at=items.now(), event='meeting_update_removed', by='user', changes={}, meeting_id=removed.get('meeting_id'),
                                text=removed['text']))
            try:
                self.items.save()
            except items.WorkItemConflict:
                raise
            except Exception:
                history.pop();history.insert(index, removed)
                raise
            return dict(self.items.items[item_id])

    def _run_diarization(self, meeting_id, directory, progress):
        from meeting_assistant import TranscriptSegment, save_transcript
        try:
            from .speaker_alignment import align
            source = json.loads((directory / 'transcript.json').read_text())
            if any(s.get('speaker') and not conversation.is_generic_speaker(s['speaker']) for s in source):
                raise ValueError('Existing speaker names were kept. Review them before running speaker separation again.')
            timeline = self._execute('diarize', directory, self.settings, progress)
            turns = read_json(directory / 'speaker-turns.json', timeline)
            alignment = read_json(directory / 'transcript.alignment.json', None)
            method = 'segment overlap'
            try:
                assigned = align(source, alignment, turns)
                method = 'Parakeet word boundaries and speaker turns' if alignment.get('method') in {parakeet.ALIGNMENT_METHOD, parakeet_sherpa.ALIGNMENT_METHOD} else 'Scribe word boundaries and speaker turns' if alignment.get('method') == 'ElevenLabs Scribe word timestamps' else 'Whisper word boundaries and speaker turns'
            except (ValueError, KeyError, TypeError):
                # Old, cloud or edited transcripts have no trustworthy word alignment.
                assigned = conversation.assign_speakers(source, turns)
            if not (directory / 'transcript.before-speakers.json').exists():
                atomic_json(directory / 'transcript.before-speakers.json', source)
            # A correction snapshot may have a different segment layout; do not present it as row-aligned.
            raw = directory / 'transcript.raw.json'
            if raw.exists() and len(read_json(raw, [])) != len(assigned):
                processing.archive(directory, ['transcript.raw.json'])
                raw.unlink()
            metadata = read_json(directory / 'transcript.metadata.json', {})
            metadata['speaker_alignment'] = dict(method=method, experimental=True, names_confirmed=False)
            atomic_json(directory / 'transcript.metadata.json', metadata)
            save_transcript(directory, [TranscriptSegment(**segment) for segment in assigned])
            self.library.update(meeting_id, diarization_error=None)
        except JobCancelled:
            raise
        except Exception as exc:
            # Diarization is optional; transcription and notes must still succeed.
            self.library.update(meeting_id, diarization_error=str(exc))

    def _voice_identity(self, name):
        person, how = self.people.owner_of(dict(owner=name))
        return (('person', person['id']), person['name']) if person else (('name', ' '.join(name.split()).casefold()), name)

    def _voice_suggestions(self, meeting_id, directory, transcript):
        prints = voices.read(directory)
        labels = {s['speaker'] for s in transcript if s.get('speaker') and voices.GENERIC.match(s['speaker'])}
        if not prints or not labels or not voices.current(directory):
            return {}
        present = {self._voice_identity(s['speaker'])[0] for s in transcript if s.get('speaker') and not voices.GENERIC.match(s['speaker'])}
        groups = voices.bank(self.library, meeting_id, self._voice_identity, prints.get('model'))
        groups = {key: group for key, group in groups.items() if key[0] == 'person'}
        return {label: row for label, row in voices.suggest(prints, groups, present).items() if label in labels}

    def learn_voices(self):
        """Make voice prints for saved meetings whose speakers have turns but no current prints."""
        from . import diarization
        if not diarization.availability()['available']:
            raise ValueError('Speaker separation is not installed in this build')
        with self.lock:
            if self.closed.is_set():
                raise ValueError('The app is closing')
            if self.voice_job['running']:
                return dict(self.voice_job)
            pending = [m['id'] for m in self.library.list() if m.get('status') == 'ready' and m['id'] != self.active
                       and m['id'] not in self.busy and (self.library.directory(m['id']) / 'recording.wav').exists()
                       and voices.turns_file(self.library.directory(m['id'])) and not voices.current(self.library.directory(m['id']))]
            self.voice_job = dict(running=bool(pending), done=0, total=len(pending), failed=0)
            if pending:
                self.voice_thread = threading.Thread(target=self._learn_voices, args=(pending,), name='voice-learning', daemon=True)
                self.voice_thread.start()
            return dict(self.voice_job)

    def _learn_voices(self, pending):
        try:
            for meeting_id in pending:
                while not self.processing_slot.acquire(timeout=.5):
                    if self.closed.is_set():
                        return
                reserved = False
                try:
                    # Reserve under the same lock used by edits, deletion and processing.
                    with self.lock:
                        if self.closed.is_set():
                            return
                        if meeting_id in self.busy or meeting_id == self.active:
                            continue
                        directory = self.library.directory(meeting_id)
                        self.busy.add(meeting_id)
                        cancel = threading.Event()
                        self.cancel_events[meeting_id] = cancel
                        settings = copy.deepcopy(self.settings)
                        reserved = True
                    def progress(message):
                        if cancel.is_set() or self.closed.is_set():
                            raise JobCancelled()
                    self._execute('voices', directory, settings, progress)
                except JobCancelled:
                    return
                except Exception as exc:
                    with self.lock:
                        self.voice_job['failed'] += 1
                    print(f'Voice prints: {exc}', flush=True)
                finally:
                    with self.lock:
                        if reserved:
                            self.busy.discard(meeting_id)
                            self.cancel_events.pop(meeting_id, None)
                        self.voice_job['done'] += 1
                    self.processing_slot.release()
        finally:
            with self.lock:
                self.voice_job['running'] = False

    def _run_analytics(self, meeting_id, settings, progress=lambda message: None):
        try:
            progress('Building conversation analytics')
            result = self._execute('analytics', self.library.directory(meeting_id), settings, progress, self.ai_key('local'), trackers=self.library.trackers())
            self.library.update(meeting_id, analytics_error=result.get('semantic_error'),analytics_need_refresh=bool(result.get('semantic_error')))
            return result
        except JobCancelled:
            raise
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
            if 'defer_analysis' in body and (type(body['defer_analysis']) is not bool or 'transcript' not in body):raise ValueError('Deferred analysis applies to a saved transcript')
            local_assignment=False
            if 'speaker_assignment' in body:
                if set(body)!={'speaker_assignment'}:raise ValueError('Save other edits before assigning this speaker')
                value=body['speaker_assignment']
                if not isinstance(value,dict):raise ValueError('Choose a speaker for this turn')
                current=read_json(directory/'transcript.json',[])
                revision=self._transcript_revision(current)
                if value.get('revision')!=revision:raise items.WorkItemConflict('The transcript changed. Reload before changing this speaker.')
                indices=value.get('indices');name=value.get('name')
                if not isinstance(indices,list) or not indices or len(indices)>100000 or any(type(index) is not int or not 0<=index<len(current) for index in indices) or len(set(indices))!=len(indices):raise ValueError('Choose existing transcript segments')
                if name is not None and (not isinstance(name,str) or not name.strip() or len(name)>120 or any(ord(c)<32 for c in name)):raise ValueError('Enter a participant name, or choose Unidentified speaker')
                selected=set(indices);name=name.strip() if name is not None else None
                body=dict(transcript=[dict(segment,speaker=name) if index in selected else segment for index,segment in enumerate(current)],transcript_revision=revision,defer_analysis=value.get('defer_analysis') is True)
                local_assignment=True
            if 'refresh_notes' in body and (type(body['refresh_notes']) is not bool or 'transcript' not in body):
                raise ValueError('Choose whether to refresh notes after saving a transcript')
            if 'transcript' in body:
                # Like the notes: a copy without the current revision must not replace a newer transcript.
                current = read_json(directory / 'transcript.json', [])
                revision = self._transcript_revision(current)
                if current and body.get('transcript_revision') != revision:
                    raise items.WorkItemConflict('The transcript changed. Reload before saving your corrections.')
            if 'speaker_name' in body and set(body) != {'speaker_name'}:
                raise ValueError('Save other edits before naming speakers')
            if 'title' in body:
                if not isinstance(body['title'], str) or not body['title'].strip():
                    raise ValueError('Meeting title is required')
                current = self.library.get(meeting_id)
                self.library.update(meeting_id, title=body['title'].strip()[:160],title_source='manual',
                    title_revision=current.get('title_revision',0)+1,title_status='manual',title_error=None)
                self._queue_metadata(meeting_id)
            requested_rename = None
            if 'speaker_name' in body:
                value = body['speaker_name']
                if not isinstance(value, dict):
                    raise ValueError('Choose a speaker and name')
                path = directory / 'transcript.json'
                current = read_json(path, [])
                revision = self._transcript_revision(current)
                if value.get('revision') != revision:
                    raise items.WorkItemConflict('The transcript changed. Reload before naming speakers.')
                old, name = value.get('speaker'), value.get('name')
                if (not isinstance(old, str) or not any(s.get('speaker') == old for s in current)
                        or not isinstance(name, str) or not name.strip() or len(name) > 120
                        or any(ord(c) < 32 for c in name) or conversation.is_generic_speaker(name)):
                    raise ValueError('Enter a participant name for an existing speaker')
                requested_rename = (old, name.strip())
                body = dict(body, transcript=[dict(s, speaker=name.strip()) if s.get('speaker') == old else s for s in current])
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
                renames = dict([requested_rename]) if requested_rename else {}
                for old, new in zip(old_segments, segments):
                    if (not local_assignment and conversation.is_generic_speaker(old.speaker) and new.speaker
                            and not conversation.is_generic_speaker(new.speaker)
                            and new.speaker.strip() != old.speaker):
                        renames[old.speaker] = new.speaker.strip()
                # A real name corrected on one segment moves only that segment's time, so talk time
                # and questions keep the same speaker.
                corrections = [(new.start, new.end, old.speaker, new.speaker.strip()) for old, new in zip(old_segments, segments)
                               if old.speaker and new.speaker and old.speaker not in renames
                               and not conversation.is_generic_speaker(old.speaker)
                               and not conversation.is_generic_speaker(new.speaker) and new.speaker.strip() != old.speaker]
                if local_assignment:
                    corrections=[(new.start,new.end,old.speaker,new.speaker) for old,new in zip(old_segments,segments) if old.speaker!=new.speaker]
                for segment in segments:
                    if segment.speaker in renames:
                        segment.speaker = renames[segment.speaker]
                prints_current = voices.current(directory) if renames else False
                if renames or corrections:
                    for filename in ('speaker-timeline.json', 'speaker-turns.json'):
                        timeline_path = directory / filename
                        if timeline_path.exists():
                            timeline = json.loads(timeline_path.read_text())
                            for turn in timeline:
                                if turn.get('speaker') in renames:
                                    turn['speaker'] = renames[turn['speaker']]
                            for start, end, old_name, new_name in corrections:
                                timeline = conversation.relabel_range(timeline, start, end, old_name, new_name)
                            atomic_json(timeline_path, timeline)
                    if renames and prints_current and not corrections:
                        # Only a complete relabel of a current profile preserves its audio evidence.
                        turns = voices.turns_file(directory)
                        voices.rename(directory, renames, hashlib.sha256(turns.read_bytes()).hexdigest())
                changed = [vars(segment) for segment in old_segments] != [vars(segment) for segment in segments]
                if changed:
                    processing.archive(directory, ['transcript.json', 'transcript.md', 'transcript.srt', 'minutes.proposed.json'])
                save_transcript(directory, segments)
                if changed:
                    # A draft derived from the previous transcript is no longer safe to apply.
                    (directory / 'minutes.proposed.json').unlink(missing_ok=True)
                    self.library.update(meeting_id, notes_need_refresh=(directory / 'minutes.json').exists(), notes_refresh_error=None)
                # A named speaker gets the name in the saved notes too, without AI: "SPEAKER_00 да провери" becomes
                # "Мария да провери". The tasks and decisions of the meeting follow the notes.
                if renames and (directory / 'minutes.json').exists():
                    self._name_speakers_in_notes(meeting_id, directory, renames)
                # Human labels become known speakers; diarization IDs stay meeting-local.
                old_names = {s.speaker for s in old_segments}
                self.library.add_speakers(s.speaker for s in segments if s.speaker and s.speaker not in old_names and not conversation.is_generic_speaker(s.speaker))
                analytics_settings = dict(self.settings, models_dir=str(self.models_dir), reuse_semantic_topics=True)
            if 'minutes' in body or 'minutes_fields' in body:
                self._refresh_items()
                source = json.loads((directory / 'transcript.json').read_text())
                minutes = self._edited_minutes(directory, body)
                validate_minutes(minutes, [TranscriptSegment(**s) for s in source])
                from .meeting_review import minutes_evidence, fingerprint, source_matches
                before=read_json(directory/'minutes.json',None)
                if minutes_evidence(before)==minutes_evidence(minutes):
                    context=self.review_sources().get(meeting_id)
                    if isinstance(context,dict):
                        with self.items.lock:
                            previous=copy.deepcopy(self.items.data);upgraded=False
                            for item in self.items.items.values():
                                receipt=item.get('meeting_reviews',{}).get(meeting_id)
                                if receipt and not receipt.get('evidence') and receipt.get('content')==fingerprint(item) and source_matches(receipt,context):
                                    receipt['evidence']=context['evidence'];upgraded=True
                            if upgraded:
                                try:self.items.save()
                                except items.WorkItemConflict:raise
                                except Exception:self.items.data=previous;raise
                save_minutes(directory, minutes)
                self._sync_items(meeting_id)
            if analytics_settings is None:
                return self.detail(meeting_id)
            if body.get('refresh_notes'):
                # Queue one job for the saved text; its analytics run after the new notes.
                # A queue failure must not hide the fact that the transcript was saved.
                try:
                    self.process(meeting_id, 'summarize')
                except ValueError as exc:
                    self.library.update(meeting_id, notes_refresh_error=str(exc))
                return self.detail(meeting_id)
            if body.get('defer_analysis'):
                self.library.update(meeting_id,analytics_need_refresh=True)
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
    def _transcript_revision(transcript):
        """The version of a transcript; an edit must start from it."""
        return hashlib.sha256(json.dumps(transcript, sort_keys=True).encode()).hexdigest()

    @staticmethod
    def _minutes_revision(directory):
        """The version of the saved notes; an edit must start from it."""
        import hashlib
        path = directory / 'minutes.json'
        return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None

    @staticmethod
    def _notes_revision(directory):
        import hashlib
        digest = hashlib.sha256()
        for name in ['minutes.json', 'minutes.proposed.json', 'transcript.json']:
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
                processing.archive(directory, ['minutes.json', 'minutes.md', 'minutes.consolidation.json'])
                from .notes_consolidation import promote_audit
                promote_audit(directory, result, source)
                save_minutes(directory, result)
                proposal.unlink()
                (directory / 'minutes.consolidation.proposed.json').unlink(missing_ok=True)
                self._sync_items(meeting_id)
                self.library.update(meeting_id, notes_need_refresh=False, notes_refresh_error=None)
                return self.detail(meeting_id)
            # Dismissing a matching draft also confirms that the saved notes are current.
            current = read_json(directory / 'minutes.json', None)
            proposed = read_json(proposal, {})
            if not notes.changes(current, proposed):
                self.library.update(meeting_id, notes_need_refresh=False, notes_refresh_error=None)
            proposal.unlink()
            (directory / 'minutes.consolidation.proposed.json').unlink(missing_ok=True)
            return self.detail(meeting_id)

    def set_scope(self, meeting_id, project=None, series=None):
        """Put a meeting into a project and, if it repeats, into a series. Names create new entries."""
        with self.lock, self.projects.lock:
            self.library.get(meeting_id)
            project_id = self.projects.ensure_project(project)
            series_id = self.projects.ensure_series(series, project_id)
            self.projects.save()
            meeting = self.library.get(meeting_id)
            changes = dict(project_id=project_id, series_id=series_id)
            # A type that the person chose stays; otherwise the meeting follows its series.
            if meeting.get('meeting_type_source') != 'manual':
                changes.update(self._type_changes(self._series_type(series_id), 'series'))
            self.library.update(meeting_id, **changes)
            return self.detail(meeting_id)

    def set_meeting_type(self, meeting_id, kind):
        """Change the type of one meeting. Saved notes stay; new notes for the type wait for review."""
        changes = self._type_changes(kind, 'manual')
        with self.lock:
            meeting = self.library.get(meeting_id)
            # An AI title carries the code of the type; it follows the new type. A title that a person wrote stays.
            if meeting.get('title_source') == 'ai':
                title = meeting_types.with_code(meeting['title'], dict(meeting, **changes), meeting)
                if title != meeting['title']:
                    changes.update(title=title, title_revision=meeting.get('title_revision', 0) + 1)
            self.library.update(meeting_id, **changes)
            return self.detail(meeting_id)

    def type_export(self, meeting_id):
        """The result of the meeting in the format of its type, for example a postmortem document."""
        from meeting_assistant import validate_minutes
        from . import type_exports
        with self.lock:
            meeting = self.library.get(meeting_id)
            minutes = read_json(self.library.directory(meeting_id) / 'minutes.json', None)
            if not minutes:
                raise ValueError('Generate meeting notes first')
            validate_minutes(minutes)
            ids = [task['item_id'] for task in minutes.get('tasks', []) if task.get('item_id')]
            with self.items.lock:
                items = {i: copy.deepcopy(self.items.items[i]) for i in ids if i in self.items.items}
            links = {i: self.github_links.for_resource('item', i) for i in ids}
            return type_exports.render(meeting, minutes, items, links)

    def _meeting_type(self, kind):
        """(type ID, copy of the own template or None). An unknown type raises."""
        if kind in meeting_types.TYPES:
            return kind, None
        template = self.templates.get(kind) if isinstance(kind, str) else None
        if not template:
            raise ValueError('Choose a meeting type')
        return kind, {key: template[key] for key in ('label', 'description', 'prepare', 'sections')}

    def _type_changes(self, kind, source):
        # A meeting keeps a copy of its template, so a later edit of the template never changes its notes.
        kind, template = self._meeting_type(kind)
        return dict(meeting_type=kind, meeting_template=template, meeting_type_source=source)

    def _series_type(self, series_id):
        """The default type of a series. A deleted template falls back to the general type."""
        kind = self.projects.series_type(series_id)
        return kind if kind in meeting_types.TYPES or self.templates.get(kind) else meeting_types.DEFAULT

    def save_template(self, body):
        with self.lock:
            template = self.templates.save(body)
            return dict(template=template, meeting_types=meeting_types.public(self.templates.list()))

    def delete_template(self, template_id, revision):
        """Delete an own template. Saved meetings keep their copy; series that used it become general."""
        with self.lock, self.projects.lock:
            self.projects.guard_write()
            self.templates.delete(template_id, revision)
            for series in self.projects.data['series']:
                if series.get('type') == template_id:
                    series['type'] = meeting_types.DEFAULT
            self.projects.save()
            return dict(meeting_types=meeting_types.public(self.templates.list()), projects=self.projects.data)

    def change_scope(self, kind, entry_id, action, name=None, value=None):
        """Rename, recolor or delete a project or series, or set the default meeting type of a series. Deleting never deletes meetings."""
        if kind not in {'projects', 'series'} or action not in {'rename', 'delete', 'type', 'color'} or action == 'type' and kind != 'series' or action == 'color' and kind != 'projects':
            raise ValueError('Invalid change')
        with self.lock, self.projects.lock:
            if action == 'type':
                # Only new meetings use the new default; saved meetings keep their type.
                self.projects.set_series_type(entry_id, self._meeting_type(name)[0])
            elif action == 'color':
                self.projects.set_color(entry_id, value)
            elif action == 'rename':
                self.projects.rename(kind, entry_id, name)
            else:
                removed = self.projects.delete(kind, entry_id)
                for meeting in self.library.list():
                    if kind == 'projects' and meeting.get('project_id') == entry_id:
                        self.library.update(meeting['id'], project_id=None, series_id=None)
                    elif meeting.get('series_id') in removed:
                        self.library.update(meeting['id'], series_id=None)
            self.projects.save()
            return dict(projects=self.projects.data)

    def set_project_repositories(self, project_id, repositories, expected_repositories=None):
        with self.lock, self.projects.lock:
            project=self.projects.get('projects',project_id)
            if expected_repositories is not None:
                if not isinstance(expected_repositories,list) or len(expected_repositories)>30 or any(not isinstance(value,str) for value in expected_repositories):raise ValueError('Invalid repository revision')
                if not project or project.get('repositories',[])!=expected_repositories:raise items.WorkItemConflict('Project repositories changed. Reload before saving your changes.')
            previous=copy.deepcopy(self.projects.data)
            try:
                result = self.projects.set_repositories(project_id, repositories)
                if result != (next(p for p in previous['projects'] if p['id']==project_id).get('repositories', [])):
                    project['repository_revision']=uuid.uuid4().hex
                self.projects.save()
            except Exception:
                self.projects.data=previous
                raise
            return dict(repositories=result, projects=self.projects.data)

    # People ------------------------------------------------------------------------------------------
    def note_names(self):
        """The people for the notes prompt, with the other names (aliases) that people use for them in speech."""
        return [dict(name=p['name'], aliases=[a for a in p.get('aliases') or [] if a.casefold() != p['name'].casefold()])
                for p in self.people.list() if not re.fullmatch(r'SPEAKER[ _-]?\d+', p['name'], re.I)]

    def save_person(self, body):
        return dict(person=self.people.save(body), people=self.people.list(), speakers=self.library.speakers())

    def team_change(self, body):
        """Join or leave my team. A change only records the period; it starts no analysis."""
        if not isinstance(body, dict):
            raise ValueError('Invalid team change')
        person = self.people.team_change(body.get('id'), body.get('revision'), body.get('action'), body.get('date'))
        return dict(person=person, people=self.people.list(), team=self.team_overview())

    def team_overview(self):
        """The people with a team period: whether they are in the team today, and their projects.

        A project comes from a meeting where the person speaks under a confirmed name, or from a task that they own.
        """
        from .people import in_team
        members = [p for p in self.people.list() if p.get('team')]
        if not members:
            return dict(members=[])
        names = {p['id']: {n for n in self._person_names(p) if len(self.people.matching(n)) == 1} for p in members}
        projects = {p['id']: set() for p in members}
        for meeting in self.library.list():
            if not meeting.get('project_id'):
                continue
            try:
                speakers = {name.casefold() for name in self.conversations._text(meeting)['participants']}
            except (OSError, ValueError):
                continue
            for person_id, known in names.items():
                if known & speakers:
                    projects[person_id].add(meeting['project_id'])
        for item in self.item_list()['items']:
            if item['kind'] != 'task':
                continue
            owner, _how = self.people.owner_of(item)
            for person_id in {owner['id'] if owner else None, *(item.get('assignee_person_ids') or [])}:
                if person_id in projects:
                    projects[person_id].update(item.get('effective_project_ids') or [])
        return dict(members=[dict(id=p['id'], active=in_team(p), periods=p['team'], project_ids=sorted(projects[p['id']]), **self.team_reviews.summary(p['id'])) for p in members])

    def _team_person(self, person_id):
        person = self.people.get(person_id)
        if not person:
            raise ValueError('This person no longer exists. Reload and try again.')
        return person

    def team_reviews_list(self, person_id=''):
        """Every review, newest period first, with its person and status. No review text."""
        return dict(reviews=self.team_reviews.list(person_id or None))

    def team_review_prepare(self, person_id):
        """The default period of the next review. Nothing is saved."""
        person = self._team_person(person_id)
        return dict(person_id=person['id'], person_name=person['name'], **self.team_reviews.next_period(person['id']))

    def _team_collector(self, person):
        from .team_facts import collect
        return lambda start, end, previous: collect(self, person, start, end, previous)

    def team_review(self, review_id):
        """One review, and the sources that changed after it was collected: a finalized review suggests a new version."""
        review = self.team_reviews.get(review_id)
        items = {i['id']: i for i in self.item_list()['items']}
        changed, seen = [], set()
        for record in review.get('evidence', []):
            ref = record.get('source_ref') or {}
            key, revision = ref.get('item_id'), ref.get('revision')
            if not key or revision is None or key in seen:
                continue
            seen.add(key)
            item = items.get(key)
            if not item or item.get('revision') != revision:
                changed.append(dict(item_id=key, text=(record.get('facts') or {}).get('text', ''), removed=not item))
        person = self.people.get(review['person_id'])
        # The agreements of the last 1:1 stay editable here, so the manager marks them done or dropped.
        last = self.team_reviews.previous(review['person_id'], review['period']['start'], review.get('supersedes')) if review['status'] == 'draft' else None
        previous = last and dict(review_id=last['id'], revision=last['revision'], period=last['period'], agreements=last['agreements'])
        return dict(review, source_changes=changed, person_current_name=person['name'] if person else None, previous_agreements=previous)

    def team_review_action(self, action, body):
        result = self._team_review_action(action, body)
        # A changed review comes back with its source changes and the current name, like a read.
        return self.team_review(result['id']) if isinstance(result, dict) and 'review_md' in result else result

    def _team_review_action(self, action, body):
        if not isinstance(body, dict):
            raise ValueError('Invalid review change')
        reviews = self.team_reviews
        if action == 'create':
            person = self._team_person(body.get('person_id'))
            return reviews.create(person, body.get('start'), body.get('end'), collect=self._team_collector(person))
        if action == 'collect':
            old = reviews.get(body.get('id'))
            return reviews.recollect(old['id'], body.get('revision'), self._team_collector(self._team_person(old['person_id'])))
        if action == 'version':
            old = reviews.get(body.get('id'))
            person = self._team_person(old['person_id'])
            return reviews.create(person, old['period']['start'], old['period']['end'], supersedes=old['id'])
        if action == 'save':
            return reviews.save_review(body.get('id'), body.get('revision'), body.get('review_md'))
        if action == 'notes':
            return reviews.save_notes(body.get('id'), body.get('revision'), body.get('notes_md'))
        if action == 'finalize':
            return reviews.finalize(body.get('id'), body.get('revision'))
        if action == 'agreements':
            return reviews.save_agreements(body.get('id'), body.get('revision'), body.get('agreements'))
        if action == 'delete':
            return reviews.delete(body.get('id'), body.get('revision'))
        if action == 'discard':
            return reviews.discard(body.get('id'), body.get('revision'))
        raise ValueError('Unknown review action')

    def delete_person(self, person_id, revision):
        if isinstance(person_id, str) and re.fullmatch(r'[a-f0-9]{12}', person_id) and self.team_reviews.list(person_id):
            raise ValueError('This person has 1:1 reviews. Delete them in Team → Reviews first, or keep the person.')
        self.people.delete(person_id, revision)
        return dict(people=self.people.list(), speakers=self.library.speakers())

    def github_user(self, login):
        """The stable GitHub ID of a username, so a later rename keeps the same person."""
        from .people import LOGIN
        if not isinstance(login, str) or not LOGIN.fullmatch(login.strip().lstrip('@')):
            raise ValueError('Enter a GitHub username')
        user = self.github.connection.get('/users/' + login.strip().lstrip('@'))['data']
        if type(user.get('id')) is not int or not isinstance(user.get('login'), str):
            raise ValueError('GitHub returned an invalid user')
        return dict(login=user['login'], id=user['id'])

    def _person_names(self, person):
        return {name.casefold() for name in [person['name'], *person['aliases']] if not re.fullmatch(r'SPEAKER[ _-]?\d+',name,re.I)}

    def person_profile(self, person_id):
        """What a person said (their confirmed names in transcripts) and what they took on.

        Only a task whose owner a person confirmed is a commitment. An owner from the AI is shown apart,
        as a suggestion, so taking part in a conversation never becomes a responsibility by itself.
        """
        person = self.people.get(person_id)
        if not person:
            raise ValueError('This person no longer exists. Reload and try again.')
        names = {name for name in self._person_names(person) if len(self.people.matching(name)) == 1}
        said, meetings, voice_samples = [], {}, []
        for meeting in self.library.list():
            directory = self.library.directory(meeting['id'])
            prints = voices.read(directory) if voices.current(directory) else None
            if prints:
                seconds = sum(row['seconds'] for name, row in prints['speakers'].items() if name.casefold() in names)
                if seconds: voice_samples.append(dict(meeting_id=meeting['id'], seconds=seconds))
            path = directory / 'transcript.json'
            rows = read_json(path, []) if path.exists() else []
            mine = [row for row in rows if isinstance(row, dict) and isinstance(row.get('speaker'), str) and row['speaker'].casefold() in names]
            if mine:
                meetings[meeting['id']] = len(mine)
                said += [dict(meeting_id=meeting['id'], meeting_title=meeting['title'], date=meeting.get('started_at') or meeting['created'],
                              start=row['start'], text=row.get('text', '')) for row in mine]
        said.sort(key=lambda r: (r['date'], r['start']), reverse=True)
        with self.items.lock:
            owned = [(i, self.people.owner_of(i)) for i in self.items.items.values() if i['kind'] == 'task']
            tasks = [(i, how) for i, (owner, how) in owned if owner and owner['id'] == person_id]
        row = lambda i: dict(id=i['id'], text=i['text'], status=i['status'], due_date=i.get('due_date'), links=i.get('links', []))
        confirmed = [row(i) for i, how in tasks if how == 'linked' or 'owner' in i.get('manual', [])]
        # A shared task: the person works on it, and another person is accountable.
        with self.items.lock:
            shared = [row(i) for i in self.items.items.values() if i['kind'] == 'task' and person_id in (i.get('assignee_person_ids') or [])[1:]]
        suggested = [row(i) for i, how in tasks if how != 'linked' and 'owner' not in i.get('manual', [])]
        github = []
        if person['github'] and person['github'].get('id'):
            try:
                github = self.github.assigned_to(person['github']['id'])
            except (ValueError, GitHubError):
                github = []
        return dict(person=person, voice_samples=voice_samples, statements=len(said), meetings=len(meetings), said=said[:50],
                    commitments=confirmed, shared=shared, suggested=suggested, github=github, channels=identity_channels.profile(self,person))

    # GitHub drafts and local links -------------------------------------------------------------------
    def _resource(self, value):
        """The text, moment and projects of a task, decision, question or saved excerpt."""
        from .github_links import resource
        target = resource(value)
        if target['kind'] == 'attachment':
            row = self.conversations.attachment(target['id'])
            moment = None
            if row['kind'] == 'excerpt':
                meeting = self.library.get(row['locator']['meeting_id'])
                moment = dict(meeting_id=meeting['id'], title=meeting['title'], date=meeting.get('started_at') or meeting['created'],
                              seconds=row['locator']['start'])
            quote = '\n'.join(re.sub(r'^\[[0-9.]+–[0-9.]+\] ', '', line) for line in row['text'].splitlines() if line.strip())[:4000]
            return dict(target=target, kind='excerpt' if row['kind'] == 'excerpt' else 'conversation', text=row['title'], quote=quote,
                        speaker=None, moment=moment, project_ids=row['project_ids'], owner=None, owner_confirmed=False, due_date=None,
                        source_label=None if moment else ('Gmail' if row['kind'] == 'gmail' else 'Google Chat'),repository_bindings=self.repository_bindings(row['project_ids']))
        item = next((i for i in self.item_list()['items'] if i['id'] == target['id']), None)
        if not item:
            raise ValueError('This item no longer exists. Reload and try again.')
        moment = quote = speaker = source = None
        meetings = {m['id']: m for m in self.library.list()}
        links = sorted((l for l in item['links'] if l['meeting_id'] in meetings),
                       key=lambda l: meetings[l['meeting_id']].get('started_at') or meetings[l['meeting_id']]['created'])
        for link in links:
            stamp = link.get('evidence_timestamp')
            if not stamp:
                continue
            seconds = stamp_seconds(stamp)
            meeting = meetings[link['meeting_id']]
            moment = dict(meeting_id=meeting['id'], title=meeting['title'], date=meeting.get('started_at') or meeting['created'], seconds=seconds)
            rows = read_json(self.library.directory(meeting['id']) / 'transcript.json', [])
            segment = segment_at(rows, stamp)
            if segment:
                quote, speaker = segment['text'], segment['speaker']
            break
        if not quote:
            graph = WorkGraph(self.items).snapshot()
            evidence = next((e for e in graph['source_evidence'] if e['id'] in set(item.get('source_evidence', []))), None)
            if evidence:
                quote = evidence['quote']
                found = next((x for x in graph['sources'] if x['id'] == evidence['source_id']), {})
                remote = found.get('remote', {})
                source = {'gmail': 'Gmail', 'google_chat': 'Google Chat'}.get(found.get('provider')) or (
                    f"GitHub {remote.get('repository', '')}#{remote.get('number', '')}" if found.get('provider') == 'github' else None)
        if source is None and item.get('created_by')=='user':source='Manually added task'
        return dict(target=target, kind=item['kind'], text=item['text'], quote=quote, speaker=speaker, moment=moment,
                    project_ids=item['effective_project_ids'], owner=item.get('owner'), owner_person_id=item.get('owner_person_id'),
                    owner_confirmed='owner' in item.get('manual', []) or bool(item.get('owner_person_id')),
                    due_date=item.get('due_date'), status=item['status'], source_label=source,
                    details=item.get('details',''),completion_criteria=item.get('completion_criteria',''),
                    destination_repository=item.get('destination_repository'),repository_bindings=self.repository_bindings(item['effective_project_ids']),
                    revision=item.get('revision'))

    def github_draft(self, body):
        """Markdown for a GitHub issue or comment. The person copies it, or publishes it after a preview."""
        from .github_source import repo_name
        from .github_publish import ATLANTA_LABEL
        fmt = body.get('format')
        if fmt not in {'issue', 'comment'}:
            raise ValueError('Choose an issue or a comment')
        data = self._resource(body.get('resource'))
        projects = [self.projects.get('projects', key) for key in data['project_ids']]
        projects = [p for p in projects if p]
        choices = list({r.casefold():r for p in projects for r in p.get('repositories', [])}.values())
        chosen = data.get('destination_repository')
        allowed={r.casefold():r for r in choices}
        explicit=body.get('repository')
        if explicit and (not isinstance(explicit,str) or explicit.casefold() not in allowed):
            raise items.WorkItemConflict('Repository is no longer linked to this project. Choose a linked repository and preview again.')
        stale_destination=bool(chosen and chosen.casefold() not in allowed)
        repository = allowed.get(explicit.casefold()) if explicit else (allowed.get(chosen.casefold(),'') if chosen else choices[0] if len(choices)==1 else '')
        if repository:
            repository = repo_name(repository)
        with_meeting, with_speaker = body.get('include_meeting', True) is not False, body.get('include_speaker') is True
        notes, kind = [], {'task': 'Task', 'decision': 'Decision', 'question': 'Question', 'excerpt': 'Meeting excerpt', 'conversation': 'Conversation'}[data['kind']]
        if stale_destination:notes.append('The previous task destination is no longer linked to its projects. Choose a repository explicitly; no replacement was selected.')
        moment = data['moment']
        when = ''
        if moment:
            day = dt.datetime.fromisoformat(moment['date']).strftime('%-d %B %Y')
            stamp = time_stamp(moment['seconds'])
            when = (f"{moment['title']}, {day} · {stamp}" if with_meeting else f'A meeting on {day} · {stamp}')
            if not with_meeting:
                notes.append('The meeting title is hidden.')
        elif data.get('source_label'):
            when = data['source_label']
        quote = data['quote']
        if quote and data['speaker'] and not with_speaker and data['kind'] != 'excerpt':
            notes.append('The speaker name is hidden.')
        if data['kind'] == 'excerpt' and not with_speaker:
            # Excerpt lines start with the speaker; keep only the words.
            quote = '\n'.join(re.sub(r'^[^:\n]{1,80}: ', '', line) for line in quote.splitlines())
            notes.append('Speaker names are hidden.')
        quoted = '\n'.join('> ' + line for line in quote.splitlines()) if quote else ''
        if quoted and data['speaker'] and with_speaker and data['kind'] != 'excerpt':
            quoted += '\n> — ' + data['speaker']
        owner = ''
        if data['owner'] and data['owner_confirmed']:
            person, _ = self.people.owner_of(data)
            owner = '@' + person['github']['login'] if person and person['github'] else data['owner']
            if person and person['github'] and not person['github'].get('id'):
                notes.append(f"@{person['github']['login']} is not checked on GitHub yet; check it in Settings → People.")
        elif data['owner']:
            notes.append('The AI-suggested owner is not included; confirm the owner in Atlanta first.')
        reference = data['target']['kind'] + ':' + data['target']['id']
        footer = f"<sub>Atlanta reference: {reference}</sub>\n<!-- atlanta:resource={reference} -->"
        details = ' · '.join(x for x in [owner and 'Owner: ' + owner, data.get('due_date') and 'Due: ' + data['due_date']] if x)
        if fmt == 'comment':
            parts = [f"**{kind}{' · ' + when if when else ''}**", quoted, data['text'] if data['text'] != quote and data['kind'] not in {'excerpt', 'conversation'} else '', details, footer]
            title = ''
        else:
            context = ' · '.join(x for x in ['Project: ' + ', '.join(p['name'] for p in projects) if projects else '', 'From: ' + when if when else ''] if x)
            title = (data['text'] if data['kind'] not in {'excerpt', 'conversation'} else (data['text'] or 'Follow up from a meeting'))[:120]
            parts = [f'## {kind}\n\n' + data['text'] if data['kind'] not in {'excerpt', 'conversation'} else '',
                     '## Context\n\n' + context if context else '', '## Evidence\n\n' + quoted if quoted else '',
                     '## Details\n\n' + details if details else '', footer]
        if data.get('details'):parts.insert(-1,'## Details\n\n'+data['details'])
        if data.get('completion_criteria'):parts.insert(-1,'## Expected result\n\n'+data['completion_criteria'])
        markdown = '\n\n'.join(p for p in parts if p)
        # The dialog shows where the draft can go, so a person can fix the project or its repositories there.
        routing = [dict(id=p['id'], name=p['name'], repositories=list(p.get('repositories', []))) for p in projects]
        return dict(format=fmt, title=title, body=markdown, repository=repository, repositories=choices,
                    assignee=owner if owner.startswith('@') else None, notes=notes, resource=data['target'],
                    projects=routing, revision=data.get('revision'), people=self.github_assignees(),
                    labels=[ATLANTA_LABEL] if fmt == 'issue' else [])

    def github_assignees(self):
        """People in Atlanta with a GitHub username: the choices for an issue assignee."""
        return [dict(id=p['id'], name=p['name'], login=p['github']['login'], checked=bool(p['github'].get('id')))
                for p in self.people.list() if p.get('github') and p['github'].get('login')]

    def github_link(self, body):
        """Link a resource to an existing issue or pull request. Checks the local cache, then GitHub (read only)."""
        data = self._resource(body.get('resource'))
        repository, number = parse_github_reference(body.get('reference'), body.get('repository') or '')
        details = dict(kind='unknown')
        try:
            cached = self.github.find(repository, number)
        except (ValueError, GitHubError):
            cached = None
        force=body.get('verify_live',False)
        if type(force) is not bool:raise ValueError('Invalid GitHub check option')
        if cached and not force:
            details = dict(kind=cached['kind'], title=cached['title'], state=cached['state'], issue_id=cached['issue_id'], verified=True,
                           verification='cached', cached_at=cached.get('fetched_at'))
        else:
            try:
                issue = self.github.connection.get(f'/repos/{repository}/issues/{number}')['data']
                details = dict(kind='pull_request' if 'pull_request' in issue else 'issue', title=issue.get('title'), state=issue.get('state'),
                               issue_id=issue.get('id'), verified=True, verification='github', checked_at=dt.datetime.now(dt.timezone.utc).isoformat())
            except (ValueError, GitHubError):
                details.update(verification='offline')
        row = self.github_links.link(data['target'], repository, number, details)
        return dict(link=row, links=self.github_links.for_resource(data['target']['kind'], data['target']['id']))

    def github_unlink(self, body):
        self.github_links.unlink(body.get('id'), body.get('revision'))
        return dict(ok=True)

    def github_links_for(self, kind=None, key=None, repository=None, number=None):
        if repository:
            rows = self.github_links.for_issue(repository, int(number))
            for row in rows:
                try:
                    data = self._resource(row['resource'])
                    row['resource_text'], row['resource_kind'] = data['text'], data['kind']
                except ValueError:
                    row['resource_text'], row['resource_kind'] = 'A deleted resource', 'deleted'
            return rows
        return self.github_links.for_resource(kind, key)

    def create_project(self, name, color=None):
        with self.lock, self.projects.lock:
            key = self.projects.ensure_project({'name': name, **({'color': color} if color else {})})
            self.projects.save()
            return dict(id=key, projects=self.projects.data)

    def project_workspace(self, project_id=''):
        with self.lock, self.items.lock, self.projects.lock:
            data = self.item_list()
            projects = self.projects.data['projects']
            if project_id not in ('', '__none__') and not self.projects.get('projects', project_id):
                raise ValueError('This project no longer exists. Reload and try again.')
            def includes(ids, key):
                return not key or (not ids if key == '__none__' else key in ids)
            all_meetings = self.library.list()
            meetings = [m for m in all_meetings if includes([m['project_id']] if m.get('project_id') else [], project_id)]
            rows = [i for i in data['items'] if includes(i['effective_project_ids'], project_id)]
            cards = []
            for p in [dict(id='__none__', name='Unassigned'), *projects]:
                items_here = [i for i in data['items'] if includes(i['effective_project_ids'], p['id'])]
                cards.append(dict(p, linked_conversations=len(self.conversations.attachments(p['id'])), meetings=sum(includes([m['project_id']] if m.get('project_id') else [], p['id']) for m in all_meetings),
                    repository_usage={r:sum(i['kind']=='task' and (i.get('destination_repository') or '').casefold()==r.casefold() for i in items_here) for r in p.get('repositories',[])},
                    repository_projects={r:[q['name'] for q in projects if any(v.casefold()==r.casefold() for v in q.get('repositories',[]))] for r in p.get('repositories',[])},
                    open_tasks=sum(i['kind']=='task' and i['status']=='open' and i.get('workflow_state')!='cancelled' and i.get('acceptance_state')!='proposed' and not i.get('dismissed') for i in items_here),
                    open_questions=sum(i['kind']=='question' and i['status']=='open' for i in items_here)))
            return dict(project_id=project_id, projects=cards, meetings=meetings, items=rows, graph=data['graph'], conversations=self.conversations.attachments(project_id), timeline=self.conversations.timeline(project_id, rows, meetings))

    def prepare(self, project_id=None, series_id=None, meeting_type=None):
        """Open tasks, questions, decisions and an agenda for the next meeting of a project or series."""
        with self.lock, self.projects.lock:
            series = self.projects.get('series', series_id) if series_id else None
            project = self.projects.get('projects', series['project_id'] if series else project_id)
            if not project or series_id and not series:
                raise ValueError('Choose a project or a series')
            meetings = [m for m in self.library.list() if (m.get('series_id') == series_id if series else m.get('project_id') == project['id'])]
            self._refresh_items()
            with self.items.lock:
                registry = [item for item in self.item_list()['items'] if project['id'] in item['effective_project_ids']]
            existing_types={meeting_types.of(m)['id'] for m in meetings}
            requires_type=not series and meeting_type is None and len(existing_types)>1
            kind = (self._meeting_type(meeting_type)[0] if meeting_type is not None else
                    self._series_type(series_id) if series else next(iter(existing_types)) if len(existing_types)==1 else meeting_types.DEFAULT)
            kind = meeting_types.definition(kind, self.templates.get(kind))
            result = briefing.build(meetings, {m['id']: self._minutes(m['id']) for m in meetings}, registry,
                                    {m['id']: read_json(self.library.directory(m['id']) / 'markers.json', []) for m in meetings},
                                    dt.date.today(), project['name'] + (' · ' + series['name'] if series else ''), kind, project_id=None if series else project['id'])
            from .followup import build as build_followup
            result.update(project_id=project['id'],series_id=series_id,requires_type=requires_type)
            result['followup']=build_followup(self,result,registry,meetings,{m['id']:self._minutes(m['id']) for m in meetings})
            return result

    SEARCH_GROUPS = {'decisions': {'decision'}, 'tasks': {'task'}, 'notes': {'summary', 'next_step', 'question', 'observation', 'marker'},
                     'transcript': {'transcript', 'draft'}}

    def find(self, query, kind='', project='', limit=40):
        """Passages that match, best first, each with its meeting and moment."""
        if not isinstance(query, str) or len(query) > 500 or kind not in {'', *self.SEARCH_GROUPS} or not isinstance(project, str):
            raise ValueError('Invalid search')
        meetings = self.library.list()
        with self.items.lock:
            registry = [dict(item) for item in self.items.items.values()]
        registry_path = self.library.root / 'items.json'
        self.search_index.refresh(meetings, self.library.directory, registry,
                                  str(registry_path.stat().st_mtime_ns) if registry_path.exists() else '')
        by_id = {m['id']: m for m in meetings}
        scope = {m['id'] for m in meetings if m.get('project_id') == project} if project else None
        results = self.search_index.search(query, self.SEARCH_GROUPS.get(kind), scope, limit)
        for result in results:
            meeting = by_id.get(result['meeting_id'], {})
            result.update(meeting_title=meeting.get('title', 'Deleted meeting'), meeting_date=meeting.get('started_at') or meeting.get('created', ''), project_id=meeting.get('project_id'),
                          timestamp=None if result['start'] is None else time_stamp(result['start']))
        return results

    def ask(self, question, project='', ai=True):
        """An answer only from the passages that search finds, with a separate check for confirmed decisions."""
        if not isinstance(question, str) or not question.strip():
            raise ValueError('Type a question')
        results = self.find(question, project=project)
        order = {'decision': 0, 'task': 1, 'transcript': 3, 'draft': 3}
        # A replaced decision is no longer in force: it is not proposed and it is not an answer source.
        current = [r for r in results if not (r['kind'] == 'decision' and r['status'] == 'superseded')]
        sources = sorted(current, key=lambda r: order.get(r['kind'], 2))[:12]
        decisions = [r for r in current if r['kind'] == 'decision']
        result = dict(question=question.strip(), sources=sources, decision_question=bool(search.DECISION_QUESTION.search(question)),
                      confirmed=[r for r in decisions if r['status'] == 'accepted'][:5],
                      proposed=[r for r in decisions if r['status'] != 'accepted'][:5], ai=None, ai_error=None,
                      provider=self.settings.get('summarizer', 'none'))
        if sources and ai:
            try:
                result['ai'] = search.ai_answer(dict(self.settings,_prompt_snapshot=self.prompts.snapshot()), self.ai_key(self.settings.get('summarizer')), question.strip(), sources)
            except Exception as exc:
                message = str(exc)
                result['ai_error'] = self.redact(message)
        return result

    def metadata_stores(self):
        return (('people.json',self.people),('projects.json',self.projects),
                ('github-links.json',self.github_links),('meeting-templates.json',self.templates),('capture-setup.json',self.capture_setup))

    def metadata_errors(self):
        errors={}
        for name,store in self.metadata_stores():
            with store.lock:
                try:store.guard_write()
                except ValueError:errors[name]=store.error
        if self.prompts.error:errors['ai-prompts.json']=self.prompts.error
        return errors

    def backups(self):
        return dict(folder=str(self.backup_dir), archives=backup.archives(self.backup_dir) if self.backup_dir.exists() else [])

    def create_backup(self):
        def skip():
            live = {meeting_id for meeting_id, session in self.live_sessions.items()
                    if session.thread and session.thread.is_alive()}
            return set(self.busy) | live | ({self.active} if self.active else set())
        @contextmanager
        def archive_guard():
            with self._snapshot_guard():
                errors=self.metadata_errors()
                if errors:raise ValueError('Cannot create an archive while local metadata needs recovery. '+next(iter(errors.values())))
                yield
        result = backup.create(self.library.root, self.backup_dir, skip, guard=archive_guard)
        return dict(self.backups(), created=result, skipped_active=bool(result['skipped_meetings']))

    @contextmanager
    def _snapshot_guard(self):
        with self.lock, self.items.lock, self.items.store.serialized(), self.projects.lock, self.library.lock, self.people.lock, self.github_links.lock, self.templates.lock, self.capture_setup.lock, self.prompts.lock, self.team_reviews.lock:
            self.library._finish_scope_batch()
            # Recover a projection interrupted after SQLite committed before pinning it.
            self.items.data, self.items.revision = self.items.store.load()
            from .commit_journal import CommitJournal
            atomic_json(self.library.root/'commit-journal.json',CommitJournal(self.items.store.path).export())
            yield

    def restore_backup(self, name):
        restored_reports={}
        recovered_metadata=[]
        archived_metadata={}
        archive_staging=[]
        def require_recovery_files(staging):
            for name in self.metadata_errors():
                if not (staging/name).exists():raise ValueError(f"This archive has no {name}; choose an archive containing that metadata before restoring.")
        def validate(staging):
            archive_staging.append(staging)
            require_recovery_files(staging)
            for name,store in self.metadata_stores():
                if (staging/name).exists():
                    try:archived_metadata[name]=store.validate_archive(staging/name)
                    except (ValueError,TypeError,KeyError,AttributeError) as exc:raise ValueError(f"Invalid {name} in archive; nothing was restored.") from exc
            from .commit_journal import CommitJournal
            if (staging/'commit-journal.json').exists():CommitJournal.validate_archive(json.loads((staging/'commit-journal.json').read_text()))
            self.prompts.read(staging/'ai-prompts.json')
            restored_reports.update(read_report_store(staging / 'repo-reports.json')['reports'])
            path = staging / 'items.json'
            if path.exists():
                portable = json.loads(path.read_text())
                validate_graph({key: portable.get(key, {}) for key in COLLECTIONS}, portable['items'])
                for item in portable['items'].values():
                    normalize(item)
        def merge(staging, restored):
            from .commit_journal import CommitJournal
            if (staging/'commit-journal.json').exists():CommitJournal(self.items.store.path).restore(json.loads((staging/'commit-journal.json').read_text()))
            self.repo_reports.restore(staging)
            if (staging/'ai-prompts.json').exists():
                damaged=bool(self.prompts.error)
                self.prompts.merge(staging/'ai-prompts.json')
                if damaged:recovered_metadata.append('ai-prompts.json')
            for name,store in self.metadata_stores():
                if name in archived_metadata and store.error:
                    store.recover_file(staging/name);recovered_metadata.append(name)
                elif name in archived_metadata and name!='projects.json':store.merge(archived_metadata[name])
            with self.projects.lock:
                mapping=dict(projects={},series={})
                if 'projects.json' in archived_metadata:
                    mapping=self.projects.merge(archived_metadata['projects.json'])
                    self.projects.save()
                # A restored meeting follows its project by name, not only by ID.
                for meeting_id in restored:
                    meeting = self.library.get(meeting_id)
                    project_id = mapping['projects'].get(meeting.get('project_id'), meeting.get('project_id'))
                    series_id = mapping['series'].get(meeting.get('series_id'), meeting.get('series_id'))
                    if not self.projects.get('projects', project_id):
                        project_id = series_id = None
                    series = self.projects.get('series', series_id)
                    if not series or series['project_id'] != project_id:
                        series_id = None
                    if (project_id, series_id) != (meeting.get('project_id'), meeting.get('series_id')):
                        self.library.update(meeting_id, project_id=project_id, series_id=series_id)
            try:
                if not (staging / 'items.json').exists():
                    return
                portable = json.loads((staging / 'items.json').read_text())
                archived = portable['items']
                graph_ids = {key for edge in portable.get('relationships', {}).values() for key in (edge['from_id'], edge['to_id'])}
                with self.items.lock:
                    # Only items of the meetings that this restore added come back, with only those links.
                    # Items this library already has stay as they are.
                    for item_id, item in archived.items():
                        links = [link for link in item.get('links', []) if link.get('meeting_id') in restored]
                        if (links or item.get('created_by') == 'user' or item.get('managed_by') == 'work_graph' or item.get('source_evidence') or item_id in graph_ids) and item_id not in self.items.items:
                            restored_item = dict(item, links=links)
                            if 'project_ids' in restored_item:
                                restored_item['project_ids'] = sorted({mapping['projects'].get(key, key) for key in restored_item['project_ids']
                                    if self.projects.get('projects', mapping['projects'].get(key, key))})
                            self.items.items[item_id] = restored_item
                    for collection in COLLECTIONS:
                        for key, record in portable.get(collection, {}).items():
                            if collection == 'conversation_links':
                                record = dict(record, project_ids=sorted({mapping['projects'].get(p,p) for p in record['project_ids'] if self.projects.get('projects',mapping['projects'].get(p,p))}))
                            self.items.data[collection].setdefault(key, record)
                    self.items.prune({m['id'] for m in self.library.list()})
                    self.items.save()
            except (OSError, ValueError, KeyError, AttributeError):
                self.items.data, self.items.revision = self.items.store.load(repair_export=False)
                raise
        @contextmanager
        def restore_guard():
            with self._snapshot_guard(), self.repo_reports.lock:
                require_recovery_files(archive_staging[0])
                if self.repo_reports.thread and self.repo_reports.thread.is_alive():
                    raise ValueError('Stop repository report jobs before restoring')
                if len(set(self.repo_reports.data['reports']) | set(restored_reports)) > 24:
                    raise ValueError('Restoring would exceed the 24-report limit')
                yield
        result = backup.restore(backup.archive_path(self.backup_dir, name), self.library, merge, guard=restore_guard, validate=validate)
        with self.lock:
            for meeting_id in result['restored']:
                # A meeting archived during a job comes back as interrupted, like after a crash.
                if self.library.get(meeting_id)['status'] in {'starting', 'recording', 'paused', 'stopping', 'processing'}:
                    self.library.update(meeting_id, status='interrupted', progress='Restored from an archive',
                                        error='This meeting was busy when it was archived. Use More → Recover audio.')
            self._refresh_items()
        return dict(self.backups(), recovered_metadata=recovered_metadata, **result)

    def reveal_backup(self, name):
        import subprocess
        subprocess.run(['/usr/bin/open', '-R', str(backup.archive_path(self.backup_dir, name))], check=False, timeout=10)
        return {'ok': True}

    NOTE_FIELDS = ('summary', 'decisions', 'updates', 'next_steps', 'needs_decision', 'tasks', 'open_questions', 'observations', 'discussion', *meeting_types.SECTION_FIELDS)

    def _edited_minutes(self, directory, body):
        """The notes after an edit. A copy that is older than the saved notes must not undo newer changes:
        only the sections that the person changed are applied, and only if nobody changed them meanwhile."""
        from meeting_assistant import validate_minutes
        revision, current_revision = body.get('minutes_revision'), self._minutes_revision(directory)
        if 'minutes_fields' not in body:
            if current_revision is not None and revision != current_revision:
                raise ValueError('These notes changed after you opened them. Reload the meeting and try again.')
            return body['minutes']
        fields, base = body['minutes_fields'], body.get('minutes_base')
        if not isinstance(fields, dict) or not fields or set(fields) - set(self.NOTE_FIELDS) or not isinstance(base, dict):
            raise ValueError('Invalid notes change')
        if current_revision is None:
            raise ValueError('These notes no longer exist. Reload the meeting.')
        current = json.loads((directory / 'minutes.json').read_text())
        validate_minutes(current)
        canonical = lambda value: json.dumps(value, sort_keys=True, ensure_ascii=False)
        if revision != current_revision:
            changed = [field for field in fields if canonical(current.get(field, [])) != canonical(base.get(field, []))]
            if changed:
                raise ValueError('These sections changed after you opened the notes: ' + ', '.join(changed).replace('_', ' ')
                                 + '. Reload the meeting; your edits stay on the screen so that you can copy them.')
        current.update(fields)
        return current

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
            # With a speaker filter, a topic counts only the matches of that speaker.
            hits = {id(row): [hit for hit in row.get('matches', [])
                              if not wanted_speaker or (hit.get('speaker') or '').casefold() == wanted_speaker] for row in topic_rows}
            if wanted_speaker:
                topic_rows = [row for row in topic_rows if hits[id(row)]]
            speaker_in_topics = bool(wanted_speaker and topic_rows)
            if wanted_speaker and not speaker_rows and not questions and not speaker_in_topics or topic_key and not topic_rows:
                continue
            unanswered = sum(not item.get('answered', False) for item in questions)
            meetings.append(dict(id=meeting['id'], title=meeting['title'], date=meeting.get('started_at') or meeting['created'],
                                 talk_seconds=round(sum(row['talk_seconds'] for row in speaker_rows), 3),
                                 questions=len(questions), unanswered_questions=unanswered,
                                 topic_matches=sum(len(hits[id(row)]) for row in topic_rows)))
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
                aggregate['matches'] += len(hits[id(row)])
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

    def _name_speakers_in_notes(self, meeting_id, directory, renames):
        """Put the names of named speakers in the saved notes and in the items that still have the label.

        A text that a person changed in the item stays: only an item text equal to the old notes text follows.
        A placeholder is not wording, so the reviews that held before still hold."""
        from meeting_assistant import save_minutes
        from .notes import name_speakers
        from .meeting_review import fingerprint
        minutes = read_json(directory / 'minutes.json', None)
        named = name_speakers(minutes, renames)
        if not named:
            return
        with self.items.lock:
            previous = copy.deepcopy(self.items.data)
            try:
                for kind, field in items.FIELD.items():
                    for old, new in zip(minutes.get(field) or [], named.get(field) or []):
                        item = self.items.items.get(new.get('item_id')) if new.get('item_id') else None
                        link = next((l for l in item['links'] if l['meeting_id'] == meeting_id), None) if item else None
                        if not link or old == new:
                            continue
                        before, applied = fingerprint(item), {}
                        for name, source in items.MENTION[kind].items():
                            if old.get(source) != new.get(source) and item.get(name) == old.get(source) and not (name == 'owner' and item.get('owner_person_id')):
                                applied[name] = [item.get(name), new.get(source)]
                                item[name] = new.get(source)
                        # The notes changed by a name, not by a person: the item does not take it as an edit.
                        link['seen'] = items.seen(kind, new)
                        if applied:
                            self.items._event(item, 'speaker_named', meeting_id, applied, by='system')
                            after = fingerprint(item)
                            for receipt in item.get('meeting_reviews', {}).values():
                                if receipt.get('state') == 'confirmed' and receipt.get('content') == before:
                                    receipt['content'] = after
                self.items.save()
            except Exception:
                self.items.data = previous
                raise
        save_minutes(directory, named)
        self._sync_items(meeting_id)

    def _sync_items(self, meeting_id, follow=True):
        """Run after every change to a meeting's notes. A status change reaches every linked meeting."""
        from meeting_assistant import save_minutes, validate_minutes
        with self.items.lock:
            directory = self.library.directory(meeting_id)
            self.items.status_changed = set()
            if (directory / 'minutes.json').exists():
                minutes = json.loads((directory / 'minutes.json').read_text())
                validate_minutes(minutes)
                if self.items.sync(meeting_id, minutes, create_items=self.meeting_task_ai()):
                    save_minutes(directory, minutes)
            else:
                # Processing again removes the notes; the items wait for the new notes, which replace them.
                self.items.detach(meeting_id)
            changed = set(self.items.status_changed)
            self.items.save()
            path = directory / 'minutes.json'
            self.items_synced[meeting_id] = path.stat().st_mtime_ns if path.exists() else None
            # Mentions that may be existing tasks wait in For review as proposals, unless the person makes tasks by hand.
            if path.exists() and meeting_id != self.active and meeting_id not in self.busy and self.meeting_task_ai():
                try:
                    from . import meeting_proposals
                    meeting_proposals.build(self, meeting_id)
                except (OSError, ValueError, items.WorkItemConflict) as exc:
                    print(f'Meeting proposals: {meeting_id}: {exc}', flush=True)
            if follow:
                self._sync_linked(changed, except_meeting=meeting_id)

    def _sync_linked(self, item_ids, except_meeting=None):
        """Write the current state of these items into the notes of every meeting that mentions them.
        A busy meeting follows at its next sync, when its job ends."""
        meetings = {link['meeting_id'] for item_id in item_ids if item_id in self.items.items
                    for link in self.items.items[item_id]['links']} - {except_meeting}
        for meeting_id in sorted(meetings):
            if meeting_id != self.active and meeting_id not in self.busy:
                try:
                    self._sync_items(meeting_id, follow=False)
                except (OSError, ValueError) as exc:
                    print(f'Task registry: {meeting_id}: {exc}', flush=True)

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

    def _has_audio(self, meeting_id):
        """A finished recording can play from any moment; a meeting that is still recording has none yet."""
        return meeting_id != self.active and (self.library.directory(meeting_id) / 'recording.wav').is_file()

    def effective_project_ids(self, item, meetings=None):
        """A person's project choice, or else the projects of the meetings that discussed the item."""
        meetings = self._meeting_refs() if meetings is None else meetings
        known = {p['id'] for p in self.projects.data['projects']}
        assigned = item.get('project_ids')
        effective = assigned if assigned is not None else [meetings.get(link['meeting_id'], {}).get('project_id') for link in item['links']]
        return sorted({key for key in effective if key in known})

    def repository_bindings(self, project_ids):
        """Explicit project/repository routing, included in publication approvals."""
        return [dict(project_id=p['id'],revision=p.get('repository_revision'),repositories=sorted(r.casefold() for r in p.get('repositories',[])))
                for key in sorted(project_ids) if (p:=self.projects.get('projects',key))]

    def project_repositories(self, project_ids):
        """The GitHub repositories that the projects name: the only places a task can go."""
        return sorted({r for key in project_ids for r in (self.projects.get('projects', key) or {}).get('repositories', [])})

    def _meeting_refs(self):
        return {m['id']: dict(title=m['title'], date=m.get('started_at') or m['created'], project_id=m.get('project_id'), has_audio=self._has_audio(m['id']))
                for m in self.library.list()}

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

    def review_sources(self):
        from .meeting_review import source_digest, minutes_evidence, legacy_minutes_evidence, evidence_variants
        sources={}
        cache=getattr(self,'_review_source_cache',{})
        fresh={}
        for meeting in self.library.list():
            directory=self.library.directory(meeting['id'])
            try:
                stamps=tuple((p.stat().st_mtime_ns,p.stat().st_ctime_ns,p.stat().st_size) if p.exists() else None for p in [directory/'transcript.json',directory/'minutes.json'])
                previous=cache.get(meeting['id'])
                if previous and previous[0]==stamps:
                    sources[meeting['id']]=previous[1];fresh[meeting['id']]=previous;continue
                transcript=json.loads((directory/'transcript.json').read_text()) if (directory/'transcript.json').exists() else []
                revision=self._transcript_revision(transcript)
                minutes=json.loads((directory/'minutes.json').read_text()) if (directory/'minutes.json').exists() else None
                sources[meeting['id']]=dict(source=source_digest(revision,self._minutes_revision(directory)),evidence=source_digest(revision,minutes_evidence(minutes)),
                                            legacy_evidence=source_digest(revision,legacy_minutes_evidence(minutes)),
                                            compatible=[source_digest(revision,value) for value in evidence_variants(minutes)])
                fresh[meeting['id']]=(stamps,sources[meeting['id']])
            except (OSError,ValueError):pass
        self._review_source_cache=fresh
        return sources

    def _migrate_link_reviews(self):
        """Once: the mentions that waited in the old link review become proposals in For review."""
        if getattr(self, '_links_migrated', False) or not self.meeting_task_ai():
            return
        self._links_migrated = True
        from . import meeting_proposals
        for meeting_id in sorted({entry['meeting_id'] for entry in self.pending_links()}):
            if meeting_id == self.active or meeting_id in self.busy:
                self._links_migrated = False
                continue
            try:
                meeting_proposals.build(self, meeting_id)
            except (OSError, ValueError, items.WorkItemConflict) as exc:
                print(f'Meeting proposals: {meeting_id}: {exc}', flush=True)

    def known_terms(self):
        """Names that Atlanta already knows: people and their aliases, projects and repositories."""
        found = []
        for person in self.people.list():
            found += [person.get('name'), *(person.get('aliases') or [])]
        for project in self.projects.data.get('projects', []):
            found.append(project.get('name'))
            found += [str(repo).rsplit('/', 1)[-1] for repo in project.get('repositories') or []]
        return [name for name in found if isinstance(name, str) and name.strip()]

    def _with_known_terms(self, settings):
        """Transcription, correction and notes also get the names that Atlanta knows."""
        from .vocabulary import with_terms
        try:
            settings['whisper_vocabulary'] = with_terms(settings.get('whisper_vocabulary', ''), self.known_terms())
        except ValueError:
            pass  # an invalid saved vocabulary stays as it is; Settings shows its error
        return settings

    def _link_confirmed_owners(self):
        """A confirmed owner name that belongs to exactly one person links the task to that person.

        Only a name that a person confirmed (accepted the task or chose Confirm owner) links. A shared name links
        nobody, and an owner that a person chose stays. Returns the number of linked tasks."""
        linked = 0
        for item in self.items.items.values():
            if (item.get('kind') != 'task' or item.get('owner_person_id') or 'owner' not in (item.get('manual') or [])
                    or item.get('acceptance_state') == 'proposed'):
                continue
            person, how = self.people.owner_of(item)
            if not person or how != 'name':
                continue
            from .meeting_review import fingerprint, keep_confirmed
            before = fingerprint(item)
            item['owner_person_id'] = person['id']
            # The link is the confirmed owner itself: the reviews that held before it still hold.
            keep_confirmed(item, before, {'owner_person_id': person['id']})
            if 'owner_person_id' not in item['manual']:
                item['manual'].append('owner_person_id')
            self.items._event(item, 'owner_linked', None, {'owner_person_id': [None, person['id']]}, by='system')
            linked += 1
        if linked:
            self.items.save()
        return linked

    def item_list(self):
        with self.lock, self.items.lock:
            self._refresh_items()
            self._migrate_link_reviews()
            try:
                self._link_confirmed_owners()
            except items.WorkItemConflict:
                pass  # another writer won; the next refresh links again
            meetings = self._meeting_refs()
            sources=self.review_sources()
            # Without AI meeting items, the task proposals and the decisions that the AI made from meetings stay hidden,
            # not deleted: decisions are text in the notes. Turning the setting on shows them again.
            manual = not self.meeting_task_ai()
            rows = [dict(item, effective_project_ids=self.effective_project_ids(item, meetings), review_state=review_state(item,sources))
                    for item in self.items.items.values()
                    if not (manual and (item.get('acceptance_state') == 'proposed' or item['kind'] == 'decision'))]
            graph = WorkGraph(self.items).snapshot()
            if manual:
                graph['proposals'] = [p for p in graph['proposals'] if p.get('origin') != 'meeting_match']
            conversations = {source['id'] for source in graph['sources'] if source.get('remote',{}).get('authority')=='conversation'}
            # Pinned conversation bodies are fetched on demand, not with every My Work refresh.
            for revision in graph['source_revisions']:
                if revision['source_id'] in conversations:revision.pop('text',None)
            # The list needs state, not every cached remote comment; cards load activity on demand.
            github_rows=self.github_links.all()
            for link in github_rows:
                link.pop('observations',None)
                if link.get('progress'):link['progress']={k:v for k,v in link['progress'].items() if k!='events'}
            # Tasks wait in For review as proposals; decisions keep the link review until they have proposals too.
            return dict(items=rows, pending=[entry for entry in self.pending_links() if entry['kind'] == 'decision' and not manual], meetings=meetings, graph=graph, github_links=github_rows,
                        meeting_questions=self.meeting_questions(meetings))

    def meeting_questions(self, meetings):
        """The questions in the notes of every meeting, newest first. A question asked again shows once, with its
        newest source. A question that a person tracks in My Work shows there instead."""
        tracked = [item['text'] for item in self.items.items.values() if item['kind'] == 'question']
        result = []
        for meeting_id in sorted(meetings, key=lambda key: meetings[key]['date'] or '', reverse=True):
            for field, kind in (('needs_decision', 'decide'), ('open_questions', 'discuss')):
                for entry in (self._minutes(meeting_id) or {}).get(field, []):
                    text = ((entry.get('text') if isinstance(entry, dict) else str(entry)) or '').strip()
                    if not text or any(items.similarity(text, known) >= items.MATCH for known in tracked + [q['text'] for q in result]):
                        continue
                    result.append(dict(text=text, kind=kind, meeting_id=meeting_id,
                                       evidence_timestamp=entry.get('evidence_timestamp') if isinstance(entry, dict) else None))
        return result

    def _github_publish(self,account,record,suggestions,after=None):
        graph=WorkGraph(self.items)
        def metadata(data,result):
            data['sources'][result['source_id']]['remote']=dict(state=record['state'],kind=record['kind'],
                repository_id=record['repository_id'],repository=record['repository'],number=record['number'],
                authority='github',fetched_at=record['fetched_at'])
            if after:after(data,result)
        return graph.ingest(dict(provider='github',account='github.com:'+account,external_id='issue:'+str(record['issue_id']),
            revision=record['revision'],text=record['text']),suggestions,after=metadata)

    def _refresh_github_source(self,account,record):
        with self.lock,self.items.lock:
            if self.closed.is_set() or self.active or self.busy:raise InterruptedError('paused for recording or processing')
            if self.github.connection.status()['account_id']!=account:raise GitHubError('GitHub account changed. Sync again.')
            source=next((s for s in self.items.data['sources'].values() if s['provider']=='github' and
                         s['account']=='github.com:'+account and s['external_id']=='issue:'+str(record['issue_id'])),None)
            if source:
                if record['available']:
                    known=self.items.data['source_revisions'][source['current_revision']]
                    if source['available'] and known['external_revision']==record['revision']:
                        return
                    self._github_publish(account,record,[])
                else:WorkGraph(self.items).availability(source['id'],source['current_revision'],False)

    def _github_unavailable(self,account,repo):
        with self.lock,self.items.lock:
            if self.github.connection.status()['account_id']!=account:raise GitHubError('GitHub account changed. Sync again.')
            graph=WorkGraph(self.items)
            def apply(data):
                for source in data['sources'].values():
                    if source['provider']=='github' and source['account']=='github.com:'+account and source.get('remote',{}).get('repository_id')==repo:
                        source.update(available=False,ai_export_allowed=False);source.pop('ai_consent',None)
                graph._activity(data,'github_repository_unavailable',account=account,repository_id=repo)
            graph._write(apply)

    def github_proposal(self,key,revision,title,after=None):
        with self.github.lock,self.lock,self.items.lock:
            account=self.github._account();record=self.github.detail(key,expected_account=account)
            if not record['available']:raise ValueError('This GitHub source is unavailable. Refresh repository access first.')
            if record['revision']!=revision or self.github.connection.status()['account_id']!=account:
                raise items.WorkItemConflict('GitHub source/account changed. Reopen the object before proposing a task.')
            quote=(record['body'] or record['title'])[:10000]
            return self._github_publish(account,record,[dict(kind='task',text=title,quote=quote,
                locator=dict(repository_id=record['repository_id'],repository=record['repository'],issue_id=key,
                             number=record['number'],kind=record['kind'],url=record['url'],head_sha=record.get('head_sha')))],after=after)

    def _refresh_chat_message(self, account, record):
        with self.lock,self.items.lock:
            if self.closed.is_set() or self.active or self.busy:
                raise InterruptedError('paused for recording or processing')
            if self.google.status().get('chat_account_id')!=account:
                raise CalendarError('The Chat account changed. Sync again.')
            source=next((s for s in self.items.data['sources'].values()
                if s['provider']=='google_chat' and s['account']==account and s['external_id']==record['name']),None)
            if source:
                graph=WorkGraph(self.items)
                if record['available'] and record['body']:
                    graph.ingest(dict(provider='google_chat',account=account,external_id=record['name'],
                                      revision=record['revision'],text=record['body']),[])
                else:graph.availability(source['id'],source['current_revision'],False)

    def _chat_unavailable(self,account,resource):
        with self.lock,self.items.lock:
            if self.google.status().get('chat_account_id')!=account:
                raise CalendarError('The Chat account changed. Sync again.')
            graph=WorkGraph(self.items)
            def apply(data):
                for source in data['sources'].values():
                    if (source['provider']=='google_chat' and source['account']==account and
                        (source['external_id'].startswith(resource) if resource.endswith('/') else source['external_id']==resource)):
                        source.update(available=False,ai_export_allowed=False);source.pop('ai_consent',None)
                graph._activity(data,'chat_source_unavailable',account=account,resource=resource)
            graph._write(apply)

    def chat_proposal(self,name,revision,title,after=None):
        # Match the cache writer lock order: cache -> service -> registry.
        with self.chat.lock,self.lock,self.items.lock:
            account=self.chat._account()
            record=self.chat.detail(name,expected_account=account)
            if not record['available'] or not record['body']:
                raise ValueError('This Chat message has no available text to quote')
            if record['revision']!=revision or self.google.status().get('chat_account_id')!=account:
                raise items.WorkItemConflict('The Chat message/account changed. Reopen it before proposing a task.')
            return WorkGraph(self.items).ingest(dict(provider='google_chat',account=account,external_id=name,
                revision=revision,text=record['body']),[dict(kind='task',text=title,quote=record['body'][:10000],
                locator=dict(space=record['space'],thread=record['thread'],message=name,sender_id=record['sender_id'],created=record['date']))],after=after)

    def _refresh_gmail_source(self, account, key, record):
        with self.lock, self.items.lock:
            if self.closed.is_set() or self.active or self.busy:
                raise InterruptedError('paused for recording or processing')
            status = self.google.status()
            if status.get('account') != account or not status.get('capabilities', {}).get('gmail'):
                raise CalendarError('The Google connection changed. Start sync again.')
            graph = WorkGraph(self.items)
            source = next((s for s in self.items.data.get('sources', {}).values()
                if s['provider']=='gmail' and s['account']==account and s['external_id']==key), None)
            if source:
                if record:
                    graph.ingest(dict(provider='gmail',account=account,external_id=key,
                        revision=record['revision'],text=record['text']), [])
                else:
                    graph.availability(source['id'],source['current_revision'],False)

    def gmail_proposal(self, key, revision, message_id, title, after=None):
        with self.lock, self.items.lock:
            account = self.gmail._account()
            record = self.gmail.detail(key,expected_account=account)
            if record['revision'] != revision:
                raise items.WorkItemConflict('This email thread changed. Reopen it before proposing a task.')
            message = next((m for m in record['messages'] if m['id']==message_id), None)
            if not message or not message['body']:
                raise ValueError('This message has no available text body')
            if self.google.status().get('account') != account:
                raise items.WorkItemConflict('The Google account changed. Reopen the email thread.')
            return WorkGraph(self.items).ingest(dict(provider='gmail',account=account,external_id=key,
                revision=record['revision'],text=record['text']),
                [dict(kind='task',text=title,quote=message['body'][:10000],locator=dict(thread_id=key,message_id=message_id))],after=after)

    def work_graph_action(self, action, body):
        # The same service/registry lock order as meeting edits and backup snapshots.
        with self.lock, self.items.lock:
            graph = WorkGraph(self.items)
            if action == 'project':
                ids = body.get('project_ids')
                if ids is not None and (not isinstance(ids, list) or len(ids)>50 or any(not isinstance(key, str) or not self.projects.get('projects', key) for key in ids)):
                    raise ValueError('Choose existing projects')
                def assign(data):
                    item = data['items'].get(body.get('id'))
                    if not item or type(body.get('revision')) is not int or item.get('revision') != body.get('revision'):
                        raise items.WorkItemConflict('Work item changed. Reload and try again.')
                    previous = item.get('project_ids')
                    if ids is None: item.pop('project_ids', None)
                    else: item['project_ids'] = sorted(set(ids))
                    item['history'].append(dict(at=items.now(), event='projects_changed', by='user', meeting_id=None, changes={'project_ids': [previous, ids]}))
                    graph._activity(data, 'item_projects_changed', item_id=item['id'], project_ids=ids)
                    return item
                return graph._write(assign)
            if action == 'ingest':
                return graph.ingest(body['source'], body['suggestions'])
            if action == 'availability':
                return graph.availability(body['source_id'], body['source_revision'], body['available'])
            if action == 'review':
                # A meeting match has its own decisions (link, update, change); the generic review would make a new item.
                if (self.items.data.get('proposals', {}).get(body.get('id')) or {}).get('origin') == 'meeting_match':
                    raise ValueError('Review this meeting suggestion with its own buttons.')
                return graph.review(body['id'], body['revision'], body['action'],
                    target_id=body.get('target_id'), target_revision=body.get('target_revision'),
                    snoozed_until=body.get('snoozed_until'),edited_text=body.get('text'))
            if action == 'question':
                return graph.question(body.get('text'), item_id=body.get('id'), revision=body.get('revision'), answer=body.get('answer'), source=body.get('source'))
            if action == 'relate':
                return graph.relate(body['from_id'], body['to_id'], body['kind'], body['from_revision'], body['to_revision'])
            raise ValueError('Unknown work graph action')

    def tasks(self):
        """Every persistent task, each once, however many meetings discussed it."""
        with self.lock, self.items.lock:
            self._refresh_items()
            return [dict(item) for item in self.items.items.values() if item['kind'] == 'task']

    def task_summary(self):
        today = dt.date.today().isoformat()
        open_tasks = [t for t in self.tasks() if t['status'] == 'open' and t.get('workflow_state')!='cancelled' and t.get('acceptance_state')!='proposed' and not t.get('dismissed')
                      and (not t.get('snoozed_until') or t['snoozed_until'] <= today)]
        return dict(open=len(open_tasks), overdue=sum(1 for t in open_tasks if t['due_date'] and t['due_date'] < today),
                    today=today, review=sum(1 for p in self.items.data.get('proposals', {}).values()
                                            if p.get('origin') == 'meeting_match' and p.get('state') == 'pending') if self.meeting_task_ai() else 0,
                    suggested=sum(1 for p in self.items.data.get('proposals', {}).values()
                                  if p.get('origin') != 'meeting_match' and (p.get('state') == 'stale' or (
                                      p.get('state') == 'pending' and (not p.get('snoozed_until') or p['snoozed_until'] <= today)))))

    def _linked_minutes(self, item):
        """Each meeting that mentions the item, with its notes; busy meetings must wait."""
        from meeting_assistant import validate_minutes
        for link in item['links']:
            meeting_id = link['meeting_id']
            if meeting_id == self.active or meeting_id in self.busy:
                raise ValueError('A meeting with this item is busy. Try again when processing finishes.')
            directory = self.library.directory(meeting_id)
            if link.get('manual_task') and not (directory / 'minutes.json').exists():continue
            minutes = json.loads((directory / 'minutes.json').read_text())
            validate_minutes(minutes)
            yield link, directory, minutes

    def create_task(self, body):
        """A user-authored WorkItem; no invented transcript evidence or AI execution."""
        if not isinstance(body, dict):raise ValueError('Task fields are required')
        text=body.get('text');owner=body.get('owner');due=body.get('due_date');details=body.get('details')
        request_id=body.get('request_id');meeting_id=body.get('meeting_id');project_id=body.get('project_id')
        # mention_index: the task line of the meeting notes that the person makes into a task.
        mention_index=body.get('mention_index')
        if not isinstance(text,str) or not text.strip() or len(text.strip())>1000:raise ValueError('Enter task text up to 1000 characters')
        if details is not None and (not isinstance(details,str) or len(details)>5000):raise ValueError('Description must be up to 5000 characters')
        if mention_index is not None and (meeting_id is None or type(mention_index) is not int):raise ValueError('Choose the meeting task line to create')
        if owner is not None and (not isinstance(owner,str) or len(owner)>160):raise ValueError('Owner must be text up to 160 characters')
        if not isinstance(request_id,str) or not re.fullmatch(r'[a-f0-9]{32}',request_id):raise ValueError('A task request ID is required')
        if due is not None:
            try:
                if not isinstance(due,str) or dt.date.fromisoformat(due).isoformat()!=due:raise ValueError()
            except (TypeError,ValueError):raise ValueError('Due date must use YYYY-MM-DD') from None
        payload=dict(text=text.strip(),owner=(owner or '').strip() or None,due_date=due,meeting_id=meeting_id,project_id=project_id)
        if (details or '').strip():payload['details']=details.strip()
        if mention_index is not None:payload['mention_index']=mention_index
        with self.lock,self.items.lock,self.items.store.serialized():
            self.items.data,self.items.revision=self.items.store.load()
            existing=next((i for i in self.items.items.values() if i.get('creation_request')==request_id),None)
            if existing:
                if existing.get('creation_payload')!=payload:raise items.WorkItemConflict('This request already created a different task. Reload the task list.')
                return copy.deepcopy(existing)
            if meeting_id is not None:
                self.library.get(meeting_id)
                if meeting_id==self.active or meeting_id in self.busy:raise ValueError('Wait for recording or processing to finish before adding a task')
            if project_id is not None and not self.projects.get('projects',project_id):raise ValueError('This project no longer exists')
            minutes=mention=own=None
            if mention_index is not None:
                directory=self.library.directory(meeting_id)
                minutes=read_json(directory/'minutes.json',None)
                lines=(minutes or {}).get('tasks') or []
                if not 0<=mention_index<len(lines):raise items.WorkItemConflict('This task line is no longer in the meeting notes. Reload the meeting.')
                mention=lines[mention_index]
                own=self.items.items.get(mention.get('item_id')) if mention.get('item_id') else None
                # A hidden AI proposal of the same line gives way to the person's task; any other task stays.
                if own and own.get('acceptance_state')!='proposed':raise items.WorkItemConflict('This task line is already a task. Reload the meeting.')
            key=uuid.uuid4().hex[:16]
            item=dict(id=key,kind='task',text=payload['text'],owner=payload['owner'],due_date=due,deadline=None,status='open',
                created=self.items.created_at(meeting_id),created_by='user',manual=['text','owner','deadline','due_date','status'],links=[],history=[],
                supersedes=[],superseded_by=None,creation_request=request_id,creation_payload=payload)
            if payload.get('details'):item['details']=payload['details'];item['manual'].append('details')
            if project_id is not None:item['project_ids']=[project_id]
            if mention is not None:
                # The task keeps the line of the notes as its evidence; what the notes said stays as said.
                item['links'].append(dict(meeting_id=meeting_id,manual_task=True,evidence_timestamp=mention.get('evidence_timestamp'),seen=items.seen('task',mention)))
            elif meeting_id is not None:
                item['links'].append(dict(meeting_id=meeting_id,manual_task=True,evidence_timestamp=None,
                    seen=dict(task=item['text'],owner=item['owner'],deadline=None,due_date=due,status='open')))
            self.items.items[key]=item
            self.items._event(item,'created',meeting_id,by='user');self.items._date_creation(item)
            if own:
                if self.items.has_graph_links(own['id']):
                    own['dismissed']=True;own['links']=[l for l in own['links'] if l['meeting_id']!=meeting_id]
                    self.items._event(own,'removed',meeting_id,by='user')
                else:self.items.remove(own['id'])
            self.items.save()
            if mention is not None:
                from meeting_assistant import save_minutes
                mention['item_id']=key;mention.pop('link',None)
                save_minutes(self.library.directory(meeting_id),minutes)
            if meeting_id is not None:self._sync_items(meeting_id)
            return copy.deepcopy(self.items.items[key])

    def _clean_item_changes(self, item, changes):
        allowed = {'text', 'owner', 'owner_person_id', 'assignee_person_ids', 'destination_repository', 'deadline', 'due_date', 'status'} if item['kind'] == 'task' else {'text', 'status'}
        allowed |= {'dismissed', 'snoozed_until'}
        if item['kind']=='task':allowed |= {'project_ids','details','completion_criteria','workflow_state','acceptance_state','requester_person_id','assigned_by_person_id','follower_person_id','follow_up_date','update_note','update_evidence_id'}
        if set(changes) - allowed:
            raise ValueError('These fields cannot change here')
        clean = {}
        for name, value in changes.items():
            if name=='update_evidence_id':
                if value is not None and value not in item.get('source_evidence',[]):raise ValueError('Choose evidence already linked to this task')
                clean[name]=value
            elif name=='project_ids':
                if value is not None and (not isinstance(value,list) or len(value)>50 or any(not isinstance(p,str) or not self.projects.get('projects',p) for p in value)):raise ValueError('Choose existing projects')
                clean[name]=None if value is None else sorted(set(value))
            elif name in {'requester_person_id','assigned_by_person_id','follower_person_id'}:
                if value is not None and not self.people.get(value):raise ValueError('Choose an existing person')
                clean[name]=value
            elif name in {'details','completion_criteria','update_note'}:
                if not isinstance(value,str) or len(value)>5000:raise ValueError('Text must be up to 5000 characters')
                clean[name]=value.strip()
            elif name=='workflow_state':
                if value not in {'todo','in_progress','waiting','done','cancelled'}:raise ValueError('Choose a task state')
                clean[name]=value
            elif name=='acceptance_state':
                if value!='accepted':raise ValueError('Use Skip to hide a proposal')
                clean[name]=value
            elif name == 'dismissed':
                if type(value) is not bool:
                    raise ValueError('Dismissed must be true or false')
                clean[name] = value
            elif name == 'snoozed_until':
                if value is not None:
                    try:
                        if dt.date.fromisoformat(value).isoformat() != value:
                            raise ValueError()
                    except (ValueError, TypeError):
                        raise ValueError('Snooze date must use YYYY-MM-DD') from None
                clean[name] = value
            elif name == 'text':
                if not isinstance(value, str) or not value.strip():
                    raise ValueError('The text cannot be empty')
                clean[name] = value.strip()[:1000]
            elif name == 'status':
                if value not in (items.TASK_STATES if item['kind'] == 'task' else items.DECISION_STATES):
                    raise ValueError('Invalid status')
                clean[name] = value
            elif name == 'assignee_person_ids':
                from .work_items import MAX_ASSIGNEES
                if not isinstance(value, list) or len(value) > MAX_ASSIGNEES or len(set(value)) != len(value) or any(not isinstance(v, str) or not self.people.get(v) for v in value):
                    raise ValueError(f'Choose up to {MAX_ASSIGNEES} different people from People')
                clean[name] = list(value)
            elif name == 'owner_person_id':
                # A person chooses who owns the task. That also confirms the owner.
                person = self.people.get(value) if value is not None else None
                if value is not None and not person:
                    raise ValueError('This person no longer exists. Reload and try again.')
                clean[name] = value
                if person and 'owner' not in changes:
                    clean['owner'] = item.get('owner') if item.get('owner') and item['owner'].casefold() in self._person_names(person) else person['name']
            elif name == 'destination_repository':
                # Where the task goes when a person publishes it: a repository of its projects, or this Mac only.
                if value is not None:
                    from .github_source import repo_name
                    value = repo_name(value)
                    candidate=dict(item,**({'project_ids':clean.get('project_ids',changes['project_ids'])} if 'project_ids' in changes else {}))
                    if value.casefold() not in {r.casefold() for r in self.project_repositories(self.effective_project_ids(candidate))}:
                        raise ValueError('Choose a repository of the task project')
                clean[name] = value
            elif name in {'due_date','follow_up_date'}:
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
        # A new owner name that the linked person does not have ends the link.
        linked = self.people.get(item.get('owner_person_id')) if item.get('owner_person_id') else None
        if 'owner' in clean and 'owner_person_id' not in clean and item.get('owner_person_id') and (
                not linked or not clean['owner'] or clean['owner'].casefold() not in self._person_names(linked)):
            clean['owner_person_id'] = None
        return self._clean_assignees(item, changes, clean)

    def _clean_assignees(self, item, changes, clean):
        """Keep the assignee list and the owner link together: the first assignee is the accountable owner.

        A person sets the whole list, or changes the accountable owner. Without linked people the text owner stays.
        """
        if item['kind'] != 'task':
            return clean
        current = list(item.get('assignee_person_ids') or ([item['owner_person_id']] if item.get('owner_person_id') else []))
        if 'assignee_person_ids' in clean:
            ids = clean['assignee_person_ids']
            if 'owner_person_id' in clean and clean['owner_person_id'] != (ids[0] if ids else None):
                raise ValueError('The first assignee is the owner. Choose one of them.')
            clean['owner_person_id'] = ids[0] if ids else None
            if ids and 'owner' not in changes:
                person = self.people.get(ids[0])
                clean['owner'] = item.get('owner') if item.get('owner') and item['owner'].casefold() in self._person_names(person) else person['name']
        elif 'owner_person_id' in clean:
            owner, others = clean['owner_person_id'], current[1:]
            if owner:
                # The new owner replaces the old one; the other assignees stay.
                ids = [owner, *[i for i in current[1:] if i != owner]]
            elif others and 'owner_person_id' in changes:
                # Removing the accountable person makes the next assignee accountable.
                ids, person = others, self.people.get(others[0])
                clean['owner_person_id'], clean['owner'] = others[0], person['name'] if person else item.get('owner')
            elif others:
                raise ValueError('This task is shared. Choose the owner from People, or remove the other assignees first.')
            else:
                ids = []
            clean['assignee_person_ids'] = ids
        return clean

    def update_item(self, item_id, text, changes, revision=None):
        if not isinstance(changes, dict) or not changes:
            raise ValueError('Nothing to change')
        with self.lock, self.items.lock:
            item = self.items.items.get(item_id)
            if item and item['kind'] == 'question' and set(changes) - {'text', 'dismissed', 'snoozed_until'}:
                raise ValueError('Use question controls to answer or reopen this question')
            if not item or item['text'] != text:
                raise items.WorkItemConflict('This item changed. Reload the list and try again.')
            if revision is not None and (type(revision) is not int or revision != item.get('revision')):
                raise items.WorkItemConflict('This item changed. Reload the list and try again.')
            clean=self._clean_item_changes(item,changes)
            note=clean.pop('update_note',None);evidence_id=clean.pop('update_evidence_id',None)
            if evidence_id and not note:raise ValueError('Add an update before choosing its evidence')
            previous=copy.deepcopy(self.items.data)
            from .meeting_review import fingerprint, keep_confirmed
            before=fingerprint(item)
            try:
                self.items.update(item_id, clean)
                keep_confirmed(self.items.items[item_id],before,clean)
                if clean.get('acceptance_state')=='accepted' or item['kind']=='decision' and clean.get('status')=='accepted':
                    from .meeting_review import accept_content, confirm_linked
                    confirmed=accept_content(self.items.items[item_id])
                    if 'owner' in confirmed:self.items._event(self.items.items[item_id],'confirmed',changes={'owner':confirmed['owner']},by='user')
                    confirm_linked(self,self.items.items[item_id])
                if note:self.items.items[item_id]['history'].append(dict(at=items.now(),event='progress_update',by='user',meeting_id=None,changes={},text=note,**({'evidence_id':evidence_id} if evidence_id else {})))
                self.items.save()
            except items.WorkItemConflict:raise  # Registry.save already reloaded the winning revision
            except Exception:
                self.items.data=previous
                raise
            # The notes of each meeting show the same state, so exports and searches agree.
            self._sync_linked({item_id})
            result = dict(self.items.items[item_id])
            if 'text' in clean and clean['text'] != text:
                result['vocabulary_suggestions'] = self.vocabulary_suggestions(text, clean['text'])
            return result

    def vocabulary_suggestions(self, old, new):
        """Terms that a text correction teaches, which the vocabulary and the known names do not have yet."""
        from .vocabulary import suggestions
        known = {name.casefold() for name in self.known_terms()}
        return [row for row in suggestions(old, new, self.settings.get('whisper_vocabulary', ''))
                if row['variant'] or row['term'].casefold() not in known]

    def add_vocabulary(self, body):
        """Add one term, or one variant of a term, to the saved vocabulary."""
        from .vocabulary import add
        if not isinstance(body, dict) or not isinstance(body.get('term'), str) or not isinstance(body.get('variant') or '', str):
            raise ValueError('Choose a term to add')
        self.save_settings(dict(whisper_vocabulary=add(self.settings.get('whisper_vocabulary', ''), body['term'], body.get('variant'))))
        return dict(vocabulary=self.settings['whisper_vocabulary'])

    def bulk_update_tasks(self, body):
        """One explicit selection, one revision-checked commit; never writes externally."""
        selected=body.get('items');changes=body.get('changes');operation=body.get('request_id')
        if not isinstance(selected,list) or not 1<=len(selected)<=100:raise ValueError('Select 1–100 tasks')
        if not isinstance(changes,dict) or not changes or set(changes)-{'owner','owner_person_id','workflow_state','due_date','follow_up_date'}:raise ValueError('Choose owner, state or dates')
        if not isinstance(operation,str) or not re.fullmatch('[a-f0-9]{32}',operation):raise ValueError('A bulk request ID is required')
        ids=[]
        for row in selected:
            if not isinstance(row,dict) or not isinstance(row.get('id'),str) or type(row.get('revision')) is not int:raise ValueError('Reload the task selection')
            ids.append(row['id'])
        if len(set(ids))!=len(ids):raise ValueError('Select each task once')
        from .work_items import canonical
        payload=hashlib.sha256(canonical(dict(items=selected,changes=changes)).encode()).hexdigest()
        with self.lock,self.items.lock,self.items.store.serialized():
            self.items.data,self.items.revision=self.items.store.load()
            old=next((e for e in self.items.data['activity'].values() if e.get('event')=='tasks_bulk_updated' and e.get('request_id')==operation),None)
            if old:
                if old['payload']!=payload:raise items.WorkItemConflict('This operation already changed a different selection')
                return dict(updated=old['item_ids'],count=len(old['item_ids']))
            validated=[]
            for row in selected:
                item=self.items.items.get(row['id'])
                if not item or item['kind']!='task' or item.get('revision')!=row['revision']:raise items.WorkItemConflict('A selected task changed. Reload and select again; no tasks changed.')
                if item.get('acceptance_state')=='proposed' or item.get('dismissed'):raise ValueError('Select accepted, visible tasks only')
                validated.append((item['id'],self._clean_item_changes(item,changes)))
            previous=copy.deepcopy(self.items.data)
            try:
                from .meeting_review import fingerprint, keep_confirmed
                for key,clean in validated:
                    before=fingerprint(self.items.items[key]);self.items.update(key,clean);keep_confirmed(self.items.items[key],before,clean)
                WorkGraph._activity(self.items.data,'tasks_bulk_updated',request_id=operation,payload=payload,item_ids=ids)
                self.items.save()
            except items.WorkItemConflict:raise
            except Exception:
                self.items.data=previous
                raise
            self._sync_linked(set(ids))
            return dict(updated=ids,count=len(ids))

    def delete_item(self, item_id, text, revision=None):
        """Remove a task, decision or question and its mentions from every meeting.

        A person can delete anything that the AI suggested. Links to other items go too;
        saved source quotes stay in the work graph."""
        from meeting_assistant import save_minutes
        with self.lock, self.items.lock:
            item = self.items.items.get(item_id)
            if not item or item['text'] != text:
                raise items.WorkItemConflict('This item changed. Reload the list and try again.')
            if revision is not None and (type(revision) is not int or revision != item.get('revision')):
                raise items.WorkItemConflict('This item changed. Reload the list and try again.')
            field = items.FIELD.get(item['kind'])
            if field is not None:
                for _, directory, minutes in list(self._linked_minutes(item)):
                    minutes[field] = [mention for mention in minutes[field] if mention.get('item_id') != item_id]
                    save_minutes(directory, minutes)
            self.items.forget_graph_links(item_id)
            self.items.remove(item_id)
            self.items.save()
            return dict(deleted=item_id)

    def merge_items(self, item_id, into_id, revision=None, into_revision=None):
        from meeting_assistant import save_minutes
        with self.lock, self.items.lock:
            item, into = self.items.items.get(item_id), self.items.items.get(into_id)
            if not item or not into or item_id == into_id or item['kind'] != into['kind']:
                raise ValueError('Choose another item of the same kind')
            if (revision is not None and (type(revision) is not int or revision != item.get('revision'))
                    or into_revision is not None and (type(into_revision) is not int or into_revision != into.get('revision'))):
                raise items.WorkItemConflict('These items changed. Reload the list and try again.')
            if self.items.replaces(item_id, into_id):
                raise ValueError('One of these decisions replaces the other. They cannot be merged.')
            if self.items.has_graph_links(item_id):
                raise ValueError('Dismiss this source-linked item to preserve its history')
            if self.items.has_graph_links(into_id):
                raise ValueError('Use proposal Link for source-linked items')
            field = items.FIELD.get(item['kind'])
            if field is None:
                raise ValueError('Use question controls for this item')
            for _, directory, minutes in list(self._linked_minutes(item)):
                if any(mention.get('item_id') == into_id for mention in minutes[field]):
                    # This meeting already mentions the item that stays; the other mention is the same thing.
                    minutes[field] = [mention for mention in minutes[field] if mention.get('item_id') != item_id]
                else:
                    for mention in minutes[field]:
                        if mention.get('item_id') == item_id:
                            mention['item_id'] = into_id
                save_minutes(directory, minutes)
            self.items.merge(item_id, into_id)
            self.items.save()
            self._sync_linked({into_id})
            return dict(into)

    def resolve_link(self, meeting_id, field, index, text, action, item_id=None, fields=None, revision=None):
        """A person's answer to the question: is this mention an existing task or decision?

        Same links the meeting as evidence. Of the owner, deadline and due date that the meeting said,
        only the fields in `fields` change the task: a person chose them, after seeing both values.
        `revision` is the item revision that the person saw; a changed item is a conflict."""
        from meeting_assistant import save_minutes, validate_minutes
        kind = {'tasks': 'task', 'decisions': 'decision'}.get(field)
        if not kind or action not in ({'same', 'duplicate', 'new'} if kind == 'task' else {'same', 'replaces', 'new'}):
            raise ValueError('Invalid choice')
        fields = list(fields or [])
        if any(name not in items.AI_UPDATES for name in fields) or (fields and (kind != 'task' or action != 'same')):
            raise ValueError('Only the owner, deadline and due date of a task can change here')
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
                if revision is not None and target.get('revision') != revision:
                    raise items.WorkItemConflict('This item changed after you opened the review. Check the current values and choose again.')
                manual = [name for name in fields if name in target['manual']]
                if manual:
                    raise ValueError('You edited the ' + ', '.join(manual).replace('_', ' ') + ' of this task. It does not change from a meeting.')
            if action == 'new':
                mention['item_id'] = self.items.create(kind, mention, meeting_id)
            elif action == 'replaces':
                mention['item_id'] = self.items.replace(item_id, mention, meeting_id)
            else:
                self.items.link(item_id, kind, mention, meeting_id, fields=fields, duplicate=action == 'duplicate')
                mention['item_id'] = item_id
                if kind == 'task':
                    mention['status'] = target['status']
            mention.pop('link')
            self.items.sync(meeting_id, minutes, create_items=self.meeting_task_ai())
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
        sweeps = 0
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
                                warnings = getattr(self.recorder, 'warnings', [])
                                changes = dict(warnings=list(warnings),
                                    microphone_status=getattr(self.recorder, 'input_status', 'connected'),
                                    microphone_name=getattr(self.recorder, 'input_name', ''))
                                meeting = self.library.get(self.active)
                                if any(meeting.get(k) != v for k, v in changes.items()):
                                    self.library.update(self.active, **changes)
                                    if meeting.get('microphone_status', 'connected') != changes['microphone_status']:
                                        self.health_changed(changes['microphone_status'] != 'connected')
                # The title/calendar sweeper tolerates half-minute granularity.
                sweeps += 1
                if sweeps >= 30:
                    sweeps = 0
                    self.automation.retry_pending()
            except Exception as exc:
                print(f'Monitor: {exc}', flush=True)

    def close(self, finalize_recording=False):
        self.closed.set()
        self.prompt_lab.close()
        self.task_drafts.close()
        self.task_titles.close()
        self.team_ai.close()
        self.team_github.close()
        self.repo_reports.close()
        self.github.close()
        self.chat.close()
        self.gmail_ai.close()
        self.gmail.close()
        for cancel in list(self.cancel_events.values()):
            cancel.set()
        self.automation.close()
        if self.start_thread and self.start_thread.is_alive():
            self.start_thread.join(timeout=35)
        if self.finish_thread and self.finish_thread.is_alive():
            self.finish_thread.join(timeout=None if finalize_recording else 20)
        with self.lock:
            self._stop_preview()
            if self.active and self.recorder:
                # Signal handlers let the normal durability path finish before exit.
                self.recorder.stop()
                self.library.update(self.active, status='interrupted', progress='Saved raw audio — recover on next launch',
                    ended_at=dt.datetime.now().astimezone().isoformat(),duration=self.recorder.clock.elapsed())
                if finalize_recording:
                    try:
                        duration = render_recording(self.library.directory(self.active))
                        self.library.update(self.active, status='recorded', duration=duration,
                                            progress='Recording saved on exit', error=None)
                    except Exception as exc:
                        self.library.update(self.active, error=str(exc))
                self.active, self.recorder = None, None
        for live in self.live_sessions.values():
            live.request_stop()
        for live in self.live_sessions.values():
            live.close()
        for thread in list(self.processing_threads.values()):
            thread.join(timeout=3)
        if self.voice_thread and self.voice_thread is not threading.current_thread():
            self.voice_thread.join(timeout=3)
        self.search_index.close()
