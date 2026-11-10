from __future__ import annotations

from dataclasses import asdict
import gc
import hashlib
from importlib.metadata import PackageNotFoundError, version
import io
import json
import math
import os
from pathlib import Path
from types import SimpleNamespace
import urllib.request
import uuid
import wave
import time

from .storage import atomic_json
from .model_cache import ensure_model, ensure_vad_model
from . import whisper
from . import audio_preparation


def upload_audio(audio: bytes, key: str, model: str) -> dict:
    boundary = 'meeting-' + uuid.uuid4().hex
    fields = [('model', model), ('languages[]', 'bg'), ('languages[]', 'en')]
    parts = []
    for name, value in fields:
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="chunk.wav"\r\nContent-Type: audio/wav\r\n\r\n'.encode() + audio + b'\r\n')
    parts.append(f'--{boundary}--\r\n'.encode())
    request = urllib.request.Request('https://api.openai.com/v1/audio/transcriptions',
        data=b''.join(parts), headers={'Authorization': 'Bearer ' + key,
        'Content-Type': 'multipart/form-data; boundary=' + boundary}, method='POST')
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.load(response)


def archive(directory: Path, names) -> Path | None:
    """Copy the files that exist into a new versions/<time> folder before they change."""
    import shutil
    from datetime import datetime
    existing = [directory / name for name in names if (directory / name).exists()]
    if not existing:
        return None
    previous = directory / 'versions' / datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    previous.mkdir(parents=True)
    for path in existing:
        shutil.copy2(path, previous / path.name)
    return previous


def audio_digest(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def transcription_checkpoint(path, signature, total, rate):
    from meeting_assistant import TranscriptSegment
    try:
        saved = json.loads(path.read_text())
        cursor = saved['cursor']
        if saved['signature'] != signature or type(cursor) is not int or not 0 <= cursor <= total:
            return 0, []
        segments = [TranscriptSegment(**s) for s in saved['segments']]
        previous = 0
        for segment in segments:
            if (type(segment.start) not in {int, float} or type(segment.end) not in {int, float}
                or not math.isfinite(segment.start) or not math.isfinite(segment.end)
                or not previous <= segment.start <= segment.end <= cursor / rate + 1
                or not isinstance(segment.text, str) or not segment.text.strip()
                or segment.speaker is not None and not isinstance(segment.speaker, str)):
                return 0, []
            previous = segment.start
        return cursor, segments
    except (OSError, ValueError, KeyError, TypeError):
        return 0, []


def transcribe(directory: Path, settings: dict, progress, api_key: str = '', speakers=()) -> None:
    import numpy as np
    from meeting_assistant import TranscriptSegment, clean_text, merge_segments, save_transcript
    provider = settings['transcription']
    model = None
    model_path = None
    vad = prompt = None
    if provider == 'elevenlabs':
        from . import scribe
        if not api_key:
            raise ValueError('Add an ElevenLabs API key in Settings before transcription.')
        prompt = scribe.keyterms(settings.get('whisper_vocabulary', ''))
    if provider == 'openai' and not api_key:
        raise ValueError('Add an OpenAI API key in Settings before processing with cloud transcription.')
    if provider == 'local':
        from pywhispercpp.model import Model
        progress('Loading local Whisper model (first use may download it)')
        model_path = ensure_model(settings['local_model'], Path(settings['models_dir']), progress)
        options = {}
        if settings.get('whisper_vad', True):
            try:
                options = dict(vad=True, vad_model_path=ensure_vad_model(Path(settings['models_dir']), progress))
                vad = True
            except Exception as exc:
                # Voice detection only improves quality; transcription continues without it.
                vad = f'unavailable: {exc}'
        prompt = whisper.build_prompt(settings.get('whisper_vocabulary', ''), speakers)
        progress('Loading local Whisper model into memory')
        model = Model(model_path, models_dir=str(Path(settings['models_dir'])),
            language='bg', translate=False, print_progress=False, print_realtime=False,
            print_timestamps=False, no_context=True, suppress_blank=True,
            suppress_non_speech_tokens=True, temperature=0, n_threads=6, **options)
    detector = None
    if provider in {'parakeet', 'parakeet_sherpa'}:
        if provider == 'parakeet_sherpa':
            from . import parakeet_sherpa as parakeet
            model = parakeet.Decoder(settings['models_dir'], progress, settings.get('whisper_vocabulary', ''), speakers)
            prompt = model.terms
        else:
            from . import parakeet
            model = parakeet.Decoder(settings['models_dir'], progress)
        if settings.get('whisper_vad', True):
            # Silero skips silent chunks and trims each chunk to its speech; it only improves quality.
            from . import vad as voice
            detector, reason = voice.load(Path(settings['models_dir']), progress)
            vad = voice.LABEL if detector else reason
    word_alignment = provider == 'elevenlabs' or provider in {'local', 'parakeet', 'parakeet_sherpa'} and settings.get('diarization_enabled', True)
    model_name = parakeet.MODEL_NAME if provider in {'parakeet', 'parakeet_sherpa'} else settings['local_model'] if provider == 'local' else scribe.MODEL if provider == 'elevenlabs' else settings['cloud_model']
    segments = []
    audio_path = directory / 'recording.wav'
    try:
        audio_path, preparation = audio_preparation.prepare(directory, settings.get('audio_preparation', 'off'), progress,
            Path(settings['models_dir']) if settings.get('models_dir') else None)
        progress('Checking saved transcription progress')
        model_stat = None
        if model_path and Path(model_path).is_file():
            stat = Path(model_path).stat()
            model_stat = [str(model_path), stat.st_size, stat.st_mtime_ns]
        try:
            backend_version = version('sherpa-onnx') if provider == 'parakeet_sherpa' else version('parakeet-mlx') if provider == 'parakeet' else version('pywhispercpp') if provider == 'local' else None
        except PackageNotFoundError:
            backend_version = 'unknown'
        # Stable facts only: a varying VAD error message must not invalidate checkpoints.
        vad_state = bool(detector) if provider in {'parakeet', 'parakeet_sherpa'} else vad is True
        signature = hashlib.sha256(json.dumps(dict(version=2, word_alignment=word_alignment, backend_version=backend_version, audio=audio_digest(audio_path),
            provider=provider, model=model_name,
            model_file=model_stat, vad=vad_state, prompt=prompt, preparation=preparation,
            **({'request': 'whole recording'} if provider == 'elevenlabs' else {}),
            **({'hotwords_score': parakeet.HOTWORDS_SCORE, 'length_reward': parakeet.LENGTH_REWARD} if provider == 'parakeet_sherpa' else {}),
            **({'model_revision': parakeet.MODEL_REVISION} if provider in {'parakeet', 'parakeet_sherpa'} else {})), sort_keys=True).encode()).hexdigest()
        checkpoint = directory / '.transcription-progress.json'
        with wave.open(str(audio_path), 'rb') as source:
            rate = source.getframerate()
            total = source.getnframes()
            if (rate, source.getnchannels(), source.getsampwidth()) != (16000, 1, 2):
                raise ValueError('Processing requires a 16 kHz mono PCM recording')
            cursor, segments = transcription_checkpoint(checkpoint, signature, total, rate)
            resumed_from = cursor / rate
            if provider == 'elevenlabs':
                # One request covers the whole recording; a chunk cursor cannot resume it.
                cursor, segments, resumed_from = 0, [], 0
            if cursor:
                source.setpos(cursor)
                progress(f'Resuming transcription from {int(cursor / rate)} seconds')
            first_cursor, inference_started = cursor, time.monotonic()
            if provider == 'elevenlabs':
                # One request gives Scribe the context of the whole meeting.
                progress('Sending the whole recording to ElevenLabs Scribe')
                segments = [TranscriptSegment(**unit) for unit in scribe.transcribe(audio_path.read_bytes(), api_key, prompt, 0, total / rate,
                                                                                    timeout=300 + total / rate)]
                cursor = total
            while cursor < total:
                # Bound memory and cloud request size. Prefer a quiet boundary in the last 5s.
                raw = source.readframes(min(rate * 60, total - cursor))
                samples = np.frombuffer(raw, dtype=np.int16)
                count = len(samples)
                if count == 0:
                    break
                if count == rate * 60 and cursor + count < total:
                    tail = samples[-rate * 5:].astype(np.float32).reshape(-1, 1600)
                    energies = np.mean(tail ** 2, axis=1)
                    count = count - rate * 5 + (int(np.argmin(energies)) + 1) * 1600
                    samples = samples[:count]
                    source.setpos(cursor + count)
                start, end = cursor / rate, (cursor + count) / rate
                progress(f'Transcribing {int(100 * cursor / max(1, total))}% · {provider}')
                if provider == 'local':
                    audio = samples.astype(np.float32) / 32768
                    # The model keeps call parameters, so every call sets the prompt explicitly.
                    raw = model.transcribe(audio, language='bg', no_context=True, initial_prompt='',
                        token_timestamps=word_alignment, max_len=1 if word_alignment else 0, split_on_word=word_alignment)
                    timed = whisper.word_units(raw, start) if word_alignment else merge_segments(raw, start)
                    if prompt and timed:
                        prompted = model.transcribe(audio, language='bg', no_context=True, initial_prompt=prompt,
                            token_timestamps=False, max_len=0, split_on_word=False)
                        timed = whisper.apply_prompted_text(timed, ' '.join(clean_text(s.text) for s in prompted))
                    segments.extend(timed)
                elif provider in {'parakeet', 'parakeet_sherpa'}:
                    from .speaker_alignment import group_units
                    part, offset = samples, start
                    if detector:
                        from . import vad as voice
                        spans = voice.speech_spans(detector.probabilities(samples.astype(np.float32) / 32768))
                        first, last = (max(0, spans[0][0] - 4800), min(count, spans[-1][1] + 4800)) if spans else (0, 0)
                        part, offset = samples[first:last], start + first / rate
                    decoded = model.transcribe(part, offset, rate) if len(part) else []
                    segments.extend(TranscriptSegment(**unit) for unit in (decoded if word_alignment else group_units(decoded)))
                else:
                    buffer = io.BytesIO()
                    with wave.open(buffer, 'wb') as chunk:
                        chunk.setnchannels(1)
                        chunk.setsampwidth(2)
                        chunk.setframerate(rate)
                        chunk.writeframes(samples.tobytes())
                    response = upload_audio(buffer.getvalue(), api_key, settings['cloud_model'])
                    text = response.get('text')
                    if not isinstance(text, str):
                        raise ValueError('Cloud transcription returned no text')
                    if text.strip():
                        # Cloud text has chunk timestamps, not fabricated word alignment.
                        segments.append(TranscriptSegment(start, end, text.strip()))
                cursor += count
                atomic_json(directory / 'transcript.partial.json', [asdict(s) for s in segments])
                atomic_json(checkpoint, dict(signature=signature, cursor=cursor, segments=[asdict(s) for s in segments]))
                processed = cursor - first_cursor
                eta = (total - cursor) * (time.monotonic() - inference_started) / max(1, processed)
                progress(f'Transcribing {int(100 * cursor / max(1, total))}% · {provider} · about {int(eta)}s left')
        if not segments:
            checkpoint.unlink(missing_ok=True)
            raise ValueError('No speech was recognized. The recording is saved; try another model or provider.')
        from .speaker_alignment import group_units, revision
        units = [asdict(s) for s in segments] if word_alignment else None
        if units:
            segments = [TranscriptSegment(**s) for s in group_units(units)]
        progress('Publishing transcript')
        # transcription.wav is not archived: about 115 MB per hour, and recording.wav plus the profile in the
        # archived metadata can produce it again.
        if archive(directory, ['transcript.json', 'transcript.raw.json', 'transcript.md', 'transcript.srt', 'minutes.json',
                               'minutes.md', 'minutes.proposed.json', 'analytics.json', 'speaker-timeline.json',
                               'transcript.metadata.json', 'transcript.alignment.json', 'speaker-turns.json', 'speaker-diarization.json', 'transcript.before-speakers.json']):
            # Previous notes and analytics no longer refer to the current transcription.
            # The kept Whisper text belongs to the old transcription.
            for name in ['minutes.json', 'minutes.md', 'minutes.proposed.json', 'transcript.raw.json', 'analytics.json', 'speaker-timeline.json', 'transcript.alignment.json', 'speaker-turns.json', 'speaker-diarization.json', 'transcript.before-speakers.json']:
                if settings.get('_reprocess_preserve_notes') and name in {'minutes.json','minutes.md'}:continue
                (directory / name).unlink(missing_ok=True)
        save_transcript(directory, segments)
        if units:
            atomic_json(directory / 'transcript.alignment.json', dict(version=1, source_revision=revision([asdict(s) for s in segments]),
                method=parakeet.ALIGNMENT_METHOD if provider in {'parakeet', 'parakeet_sherpa'} else scribe.ALIGNMENT_METHOD if provider == 'elevenlabs' else 'whisper.cpp experimental word boundaries', units=units))
        if preparation['profile'] == 'light':
            os.replace(audio_path, directory / 'transcription.wav')
        else:
            (directory / 'transcription.wav').unlink(missing_ok=True)
        metadata = dict(provider=provider,
            model=model_name,
            timestamps='word' if provider == 'elevenlabs' else 'segment' if provider in {'local', 'parakeet', 'parakeet_sherpa'} else 'approximate chunk boundaries',
            audio_preparation=preparation, resumed_from_seconds=resumed_from)
        if provider == 'elevenlabs':
            metadata.update(language='auto', vocabulary_applied=bool(prompt), word_boundaries=True, speaker_recognition='local')
        if provider == 'local':
            metadata.update(vad=vad is True, prompt=prompt or None, word_boundaries=bool(units))
            if isinstance(vad, str):
                metadata['vad_error'] = vad
        if provider in {'parakeet', 'parakeet_sherpa'}:
            metadata.update(model_repository=parakeet.MODEL_ID, model_revision=parakeet.MODEL_REVISION, word_boundaries=bool(units), language='auto', vocabulary_applied=bool(prompt) if provider == 'parakeet_sherpa' else False,
                vad=bool(detector))
            if isinstance(vad, str) and vad.startswith('unavailable'):
                metadata['vad_error'] = vad
        if provider == 'parakeet_sherpa':
            metadata.update(backend='sherpa-onnx', backend_version=backend_version, experimental=True,
                hotwords_score=parakeet.HOTWORDS_SCORE, length_reward=parakeet.LENGTH_REWARD, vocabulary_terms=prompt, execution_provider='cpu')
        atomic_json(directory / 'transcript.metadata.json', metadata)
        checkpoint.unlink(missing_ok=True)
    finally:
        if audio_path != directory / 'recording.wav':
            audio_path.unlink(missing_ok=True)
        del model
        gc.collect()


NOTES_PART_CHARS = 10000
# Measured with Qwen on Bulgarian: about 2.4 characters per token and 2,500 tokens of instructions.
CHARS_PER_TOKEN = 2.0
PROMPT_TOKENS = 3000
MAX_PART_CHARS = 400000


def notes_part_chars(settings: dict) -> int:
    """Characters of transcript per notes part. A 16k local model keeps the measured 10,000; a larger
    context, for example a cloud model, takes a long meeting in one part and needs no consolidation."""
    if settings.get('summarizer') != 'local':
        return NOTES_PART_CHARS
    context = settings.get('local_ai_context') or 16384
    if context <= 16384:
        return NOTES_PART_CHARS
    free = context - (settings.get('local_ai_max_tokens') or 4096) - PROMPT_TOKENS
    return max(NOTES_PART_CHARS, min(MAX_PART_CHARS, int(free * CHARS_PER_TOKEN)))


def canonical_notes(minutes: dict, vocabulary: str, people=()) -> dict:
    """The preferred spellings in the generated notes. The transcript stays as it was.

    A vocabulary variant becomes its term in statement and task text. Another name of a person in People
    (an alias, for example a short name) becomes the People name there and in the task owner too: the prompt
    asks for this, but a model does not always do it, and then one person has two names in one set of notes.
    """
    from .vocabulary import canonicalize, entries
    rows = entries(vocabulary or '')
    names = [dict(term=p['name'], aliases=[a for a in p.get('aliases') or [] if isinstance(a, str) and a.strip()])
             for p in people or () if isinstance(p, dict) and isinstance(p.get('name'), str) and p['name'].strip()]
    # The name itself is in the list too: the longest match wins, so "Мария Петрова" stays as it is and does not
    # become "Мария Петрова Петрова" through the alias "Мария".
    names = [dict(row, aliases=[row['term'], *row['aliases']]) for row in names if row['aliases']]
    if not any(row['aliases'] for row in rows) and not names:
        return minutes
    for items in minutes.values():
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            for key in ('text', 'task', 'owner'):
                value = item.get(key)
                if not isinstance(value, str):
                    continue
                # An owner is a person, not a vocabulary term.
                if key != 'owner':
                    value = canonicalize(value, rows)
                item[key] = canonicalize(value, names)
    return minutes


def clear_unstated_due_dates(minutes: dict) -> dict:
    """A task without a deadline in the words of the meeting has no due date. A model sometimes picks one."""
    for task in minutes.get('tasks') or []:
        if isinstance(task, dict) and not (task.get('deadline') or '').strip():
            task['due_date'] = None
    return minutes


def summarize(directory: Path, settings: dict, progress, api_key: str = '', speakers=()) -> None:
    from meeting_assistant import ITEM_FIELDS, TranscriptSegment, generate_minutes, save_minutes, timestamp, validate_minutes
    segments = [TranscriptSegment(**s) for s in json.loads((directory / 'transcript.json').read_text())]
    if not segments:
        raise ValueError('Transcribe the recording before generating notes')
    from .transcripts import group_by_length
    # About 4,000 tokens of Bulgarian per part. With the prompt and a 4,096-token answer it fits a
    # 16k context. Smaller parts split one meeting into many partial summaries.
    groups = group_by_length(segments, lambda segment: segment.text, notes_part_chars(settings), overhead=15)
    args = SimpleNamespace(summarizer=settings['summarizer'], llm_model=settings['llm_model'],
        local_ai_base_url=settings.get('local_ai_base_url', 'http://localhost:1235/v1'),
        local_ai_model=settings.get('local_ai_model', 'qwen3.5-9b'),
        local_ai_format=settings.get('local_ai_format', 'json_schema'),
        local_ai_max_tokens=settings.get('local_ai_max_tokens', 4096),
        local_ai_reasoning=settings.get('local_ai_reasoning', 'default'),
        local_ai_temperature=settings.get('local_ai_temperature', 'zero'))
    if args.summarizer == 'openai' and not api_key:
        raise ValueError('Add an OpenAI API key in Settings before generating cloud notes.')
    # Pass credentials explicitly; never alter the process environment across jobs.
    args.api_key = api_key
    if settings.get('_prompt_snapshot'):args._prompt_snapshot=settings['_prompt_snapshot']
    args.speakers = list(speakers)
    args.whisper_vocabulary = settings.get('whisper_vocabulary', '')
    meeting = json.loads((directory / 'meeting.json').read_text()) if (directory / 'meeting.json').exists() else {}
    from datetime import date
    args.meeting_date = (meeting.get('started_at') or meeting.get('created') or '')[:10] or date.today().isoformat()
    # The summary limit of a part follows the part; the whole meeting length is context for the model.
    args.meeting_duration = meeting.get('duration') if isinstance(meeting.get('duration'), (int, float)) else None
    from . import meeting_types
    args.meeting_type = meeting_types.of(meeting)
    from .live import read_json
    args.markers = [m for m in read_json(directory / 'markers.json', []) if isinstance(m, dict) and isinstance(m.get('time'), (int, float))]
    # Cache only validated parts of an unfinished run. Settings, sources and
    # prompts must match exactly before a retry can reuse them. No API key is saved.
    from .prompts import select_stages
    map_args = {k: v for k, v in vars(args).items() if k != 'api_key'}
    if map_args.get('_prompt_snapshot'):
        map_args['_prompt_snapshot'] = select_stages(map_args['_prompt_snapshot'], ('meeting_minutes',))
    identity = dict(version=3, segments=[asdict(s) for s in segments], args=map_args)
    signature = hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    checkpoint = directory / '.notes-progress.json'
    saved = read_json(checkpoint, {})
    parts = saved.get('parts', {}) if isinstance(saved, dict) and saved.get('signature') == signature else {}
    if not isinstance(parts, dict):
        parts = {}
    saved_splits = saved.get('splits', []) if isinstance(saved, dict) and saved.get('signature') == signature else []
    splits = {key for key in saved_splits if isinstance(key, str)} if isinstance(saved_splits, list) else set()
    split_attempts = 0
    result = dict(summary=[], decisions=[], updates=[], next_steps=[], needs_decision=[], tasks=[], open_questions=[], observations=[],
                  **{field: [] for field in meeting_types.sections(args.meeting_type)})

    def generate_part(group, label, depth=0):
        nonlocal split_attempts
        from .local_ai import OutputTruncatedError
        key = hashlib.sha256(json.dumps([asdict(s) for s in group], sort_keys=True).encode()).hexdigest()
        cached = parts.get(key)
        if cached is not None:
            try:
                validate_minutes(cached, group)
                progress(f'Reusing completed notes · part {label}')
                return [cached]
            except (ValueError, TypeError, KeyError):
                parts.pop(key, None)
        def split_part():
            middle = len(group) // 2
            return (generate_part(group[:middle], label + '.1', depth + 1)
                    + generate_part(group[middle:], label + '.2', depth + 1))

        if key in splits and len(group) > 1:
            return split_part()
        progress(f'Generating notes · part {label}')
        try:
            minutes = generate_minutes(args, group)
        except OutputTruncatedError as exc:
            # Keep the configured provider and reasoning preference. Bound retries
            # even when the model spends its whole budget on internal reasoning.
            if not exc.can_split or len(group) < 2 or depth >= 2 or split_attempts >= 2:
                raise
            split_attempts += 1
            splits.add(key)
            atomic_json(checkpoint, dict(signature=signature, parts=parts, splits=sorted(splits)))
            progress(f'Output limit reached · splitting notes part {label}')
            return split_part()
        stamps = {timestamp(s.start) for s in group}
        for field in ITEM_FIELDS:
            # A wrong source on a statement is dropped, not fatal: the statement then shows no source.
            for item in minutes.get(field, []) if isinstance(minutes, dict) else []:
                if isinstance(item, dict) and item.get('evidence_timestamp') not in stamps:
                    item['evidence_timestamp'] = None
        # A quote must be the words of this part of the transcript; a rewritten quote goes, the statement stays.
        from meeting_assistant import verify_quotes
        verify_quotes(minutes, group)
        validate_minutes(minutes, group)
        parts[key] = minutes
        atomic_json(checkpoint, dict(signature=signature, parts=parts, splits=sorted(splits)))
        return [minutes]

    completed = []
    for index, group in enumerate(groups):
        for minutes in generate_part(group, f'{index + 1} of {len(groups)}'):
            completed.append(minutes)
            for field in result:
                result[field].extend(minutes.get(field, []))
    audit = None
    if len(completed) > 1:
        from .notes_consolidation import consolidate
        try:
            consolidation_settings = dict(vars(args))
            if consolidation_settings.get('_prompt_snapshot'):
                consolidation_settings['_prompt_snapshot'] = select_stages(consolidation_settings['_prompt_snapshot'], ('meeting_consolidation',))
            result, audit = consolidate(completed, segments, consolidation_settings, directory, progress, api_key)
        except Exception as error:
            from .jobs import JobCancelled
            if isinstance(error, JobCancelled):
                raise
            # Notes with repeated statements beat no notes. Keep both checkpoints so a retry resumes.
            from .notes_consolidation import failed_audit
            audit = failed_audit(completed, segments, error)
            progress('Notes saved without merging repeated statements · ' + audit['error'])
    result = clear_unstated_due_dates(canonical_notes(result, args.whisper_vocabulary, args.speakers))
    validate_minutes(result, segments)
    proposed = (directory / 'minutes.json').exists()
    audit_path = directory / ('minutes.consolidation.proposed.json' if proposed else 'minutes.consolidation.json')
    if audit is not None:
        atomic_json(audit_path, audit)
    elif audit_path.exists():
        audit_path.unlink()
    if (directory / 'minutes.json').exists():
        # Saved notes may hold checked statements and manual edits; the new run waits for review.
        atomic_json(directory / 'minutes.proposed.json', result)
    else:
        save_minutes(directory, result)
    if audit is None or audit.get('status') != 'failed':
        checkpoint.unlink(missing_ok=True)
        (directory / '.consolidation-progress.json').unlink(missing_ok=True)
