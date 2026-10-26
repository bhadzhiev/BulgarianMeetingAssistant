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
    segments = []
    audio_path = directory / 'recording.wav'
    try:
        audio_path, preparation = audio_preparation.prepare(directory, settings.get('audio_preparation', 'off'), progress)
        progress('Checking saved transcription progress')
        model_stat = None
        if model_path and Path(model_path).is_file():
            stat = Path(model_path).stat()
            model_stat = [str(model_path), stat.st_size, stat.st_mtime_ns]
        try:
            backend_version = version('pywhispercpp') if provider == 'local' else None
        except PackageNotFoundError:
            backend_version = 'unknown'
        signature = hashlib.sha256(json.dumps(dict(version=1, backend_version=backend_version, audio=audio_digest(audio_path),
            provider=provider, model=settings['local_model'] if provider == 'local' else settings['cloud_model'],
            model_file=model_stat, vad=vad, prompt=prompt, preparation=preparation), sort_keys=True).encode()).hexdigest()
        checkpoint = directory / '.transcription-progress.json'
        with wave.open(str(audio_path), 'rb') as source:
            rate = source.getframerate()
            total = source.getnframes()
            if (rate, source.getnchannels(), source.getsampwidth()) != (16000, 1, 2):
                raise ValueError('Processing requires a 16 kHz mono PCM recording')
            cursor, segments = transcription_checkpoint(checkpoint, signature, total, rate)
            resumed_from = cursor / rate
            if cursor:
                source.setpos(cursor)
                progress(f'Resuming transcription from {int(cursor / rate)} seconds')
            first_cursor, inference_started = cursor, time.monotonic()
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
                    timed = merge_segments(model.transcribe(audio, language='bg', no_context=True, initial_prompt=''), start)
                    if prompt and timed:
                        prompted = model.transcribe(audio, language='bg', no_context=True, initial_prompt=prompt)
                        timed = whisper.apply_prompted_text(timed, ' '.join(clean_text(s.text) for s in prompted))
                    segments.extend(timed)
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
        progress('Publishing transcript')
        # transcription.wav is not archived: about 115 MB per hour, and recording.wav plus the profile in the
        # archived metadata can produce it again.
        if archive(directory, ['transcript.json', 'transcript.raw.json', 'transcript.md', 'transcript.srt', 'minutes.json',
                               'minutes.md', 'minutes.proposed.json', 'analytics.json', 'speaker-timeline.json',
                               'transcript.metadata.json']):
            # Previous notes and analytics no longer refer to the current transcription.
            # The kept Whisper text belongs to the old transcription.
            for name in ['minutes.json', 'minutes.md', 'minutes.proposed.json', 'transcript.raw.json', 'analytics.json', 'speaker-timeline.json']:
                (directory / name).unlink(missing_ok=True)
        save_transcript(directory, segments)
        if preparation['profile'] == 'light':
            os.replace(audio_path, directory / 'transcription.wav')
        else:
            (directory / 'transcription.wav').unlink(missing_ok=True)
        metadata = dict(provider=provider,
            model=settings['local_model'] if provider == 'local' else settings['cloud_model'],
            timestamps='segment' if provider == 'local' else 'approximate chunk boundaries',
            audio_preparation=preparation, resumed_from_seconds=resumed_from)
        if provider == 'local':
            metadata.update(vad=vad is True, prompt=prompt or None)
            if isinstance(vad, str):
                metadata['vad_error'] = vad
        atomic_json(directory / 'transcript.metadata.json', metadata)
        checkpoint.unlink(missing_ok=True)
    finally:
        if audio_path != directory / 'recording.wav':
            audio_path.unlink(missing_ok=True)
        del model
        gc.collect()


def summarize(directory: Path, settings: dict, progress, api_key: str = '', speakers=()) -> None:
    from meeting_assistant import ITEM_FIELDS, TranscriptSegment, generate_minutes, save_minutes, timestamp, validate_minutes
    segments = [TranscriptSegment(**s) for s in json.loads((directory / 'transcript.json').read_text())]
    if not segments:
        raise ValueError('Transcribe the recording before generating notes')
    groups, group, length = [], [], 0
    for segment in segments:
        if group and length + len(segment.text) > 4000:
            groups.append(group)
            group, length = [], 0
        group.append(segment)
        length += len(segment.text) + 15
    if group:
        groups.append(group)
    args = SimpleNamespace(summarizer=settings['summarizer'], llm_model=settings['llm_model'],
        local_ai_base_url=settings.get('local_ai_base_url', 'http://localhost:1235/v1'),
        local_ai_model=settings.get('local_ai_model', 'qwen3.5-9b'),
        local_ai_format=settings.get('local_ai_format', 'json_schema'),
        local_ai_max_tokens=settings.get('local_ai_max_tokens', 4096),
        local_ai_reasoning=settings.get('local_ai_reasoning', 'default'))
    if args.summarizer == 'openai' and not api_key:
        raise ValueError('Add an OpenAI API key in Settings before generating cloud notes.')
    # Pass credentials explicitly; never alter the process environment across jobs.
    args.api_key = api_key
    args.speakers = list(speakers)
    meeting = json.loads((directory / 'meeting.json').read_text()) if (directory / 'meeting.json').exists() else {}
    from datetime import date
    args.meeting_date = (meeting.get('started_at') or meeting.get('created') or '')[:10] or date.today().isoformat()
    from .live import read_json
    args.markers = [m for m in read_json(directory / 'markers.json', []) if isinstance(m, dict) and isinstance(m.get('time'), (int, float))]
    # Cache only validated parts of an unfinished run. Settings, sources and
    # prompts must match exactly before a retry can reuse them. No API key is saved.
    identity = dict(version=1, segments=[asdict(s) for s in segments],
                    args={k: v for k, v in vars(args).items() if k != 'api_key'})
    signature = hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    checkpoint = directory / '.notes-progress.json'
    saved = read_json(checkpoint, {})
    parts = saved.get('parts', {}) if isinstance(saved, dict) and saved.get('signature') == signature else {}
    if not isinstance(parts, dict):
        parts = {}
    saved_splits = saved.get('splits', []) if isinstance(saved, dict) and saved.get('signature') == signature else []
    splits = {key for key in saved_splits if isinstance(key, str)} if isinstance(saved_splits, list) else set()
    split_attempts = 0
    result = dict(summary=[], decisions=[], next_steps=[], needs_decision=[], tasks=[], open_questions=[], observations=[])

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
        validate_minutes(minutes, group)
        parts[key] = minutes
        atomic_json(checkpoint, dict(signature=signature, parts=parts, splits=sorted(splits)))
        return [minutes]

    for index, group in enumerate(groups):
        for minutes in generate_part(group, f'{index + 1} of {len(groups)}'):
            for field in result:
                result[field].extend(minutes[field])
    validate_minutes(result, segments)
    if (directory / 'minutes.json').exists():
        # Saved notes may hold checked statements and manual edits; the new run waits for review.
        atomic_json(directory / 'minutes.proposed.json', result)
    else:
        save_minutes(directory, result)
    checkpoint.unlink(missing_ok=True)
