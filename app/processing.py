from __future__ import annotations

from dataclasses import asdict
import gc
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
import urllib.request
import uuid
import wave

from .storage import atomic_json
from .model_cache import ensure_model


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


def transcribe(directory: Path, settings: dict, progress, api_key: str = '') -> None:
    import numpy as np
    from meeting_assistant import TranscriptSegment, merge_segments, save_transcript
    provider = settings['transcription']
    model = None
    if provider == 'openai' and not api_key:
        raise ValueError('Add an OpenAI API key in Settings before processing with cloud transcription.')
    if provider == 'local':
        from pywhispercpp.model import Model
        progress('Loading local Whisper model (first use may download it)')
        model_path = ensure_model(settings['local_model'], Path(settings['models_dir']), progress)
        model = Model(model_path, models_dir=str(Path(settings['models_dir'])),
            language='bg', translate=False, print_progress=False, print_realtime=False,
            print_timestamps=False, no_context=True, suppress_blank=True,
            suppress_non_speech_tokens=True, temperature=0, n_threads=6)
    segments = []
    try:
        with wave.open(str(directory / 'recording.wav'), 'rb') as source:
            rate = source.getframerate()
            total = source.getnframes()
            if (rate, source.getnchannels(), source.getsampwidth()) != (16000, 1, 2):
                raise ValueError('Processing requires a 16 kHz mono PCM recording')
            cursor = 0
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
                    raw_segments = model.transcribe(samples.astype(np.float32) / 32768, language='bg', no_context=True)
                    segments.extend(merge_segments(raw_segments, start))
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
        if not segments:
            raise ValueError('No speech was recognized. The recording is saved; try another model or provider.')
        if any((directory / name).exists() for name in ['transcript.json', 'transcript.raw.json', 'transcript.md', 'transcript.srt', 'minutes.json', 'minutes.md', 'analytics.json', 'speaker-timeline.json']):
            archive = directory / 'versions'
            archive.mkdir(exist_ok=True)
            from datetime import datetime
            previous = archive / datetime.now().strftime('%Y%m%d-%H%M%S-%f')
            previous.mkdir()
            import shutil
            for name in ['transcript.json', 'transcript.raw.json', 'transcript.md', 'transcript.srt', 'minutes.json', 'minutes.md', 'analytics.json', 'speaker-timeline.json']:
                path = directory / name
                if path.exists():
                    shutil.copy2(path, previous / name)
            # Previous notes and analytics no longer refer to the current transcription.
            # The kept Whisper text belongs to the old transcription.
            for name in ['minutes.json', 'minutes.md', 'transcript.raw.json', 'analytics.json', 'speaker-timeline.json']:
                (directory / name).unlink(missing_ok=True)
        save_transcript(directory, segments)
        atomic_json(directory / 'transcript.metadata.json', dict(provider=provider,
            model=settings['local_model'] if provider == 'local' else settings['cloud_model'],
            timestamps='segment' if provider == 'local' else 'approximate chunk boundaries'))
    finally:
        del model
        gc.collect()


def summarize(directory: Path, settings: dict, progress, api_key: str = '', speakers=()) -> None:
    from meeting_assistant import TranscriptSegment, generate_minutes, save_minutes, validate_minutes
    segments = [TranscriptSegment(**s) for s in json.loads((directory / 'transcript.json').read_text())]
    if not segments:
        raise ValueError('Transcribe the recording before generating notes')
    groups, group, length = [], [], 0
    for segment in segments:
        if group and length + len(segment.text) > 10000:
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
    args.meeting_date = (meeting.get('started_at') or meeting.get('created') or '')[:10] or None
    result = dict(summary=[], decisions=[], next_steps=[], needs_decision=[], tasks=[], open_questions=[], observations=[])
    for index, group in enumerate(groups):
        progress(f'Generating notes · part {index + 1} of {len(groups)}')
        minutes = generate_minutes(args, group)
        validate_minutes(minutes, group)
        for field in result:
            result[field].extend(minutes[field])
    validate_minutes(result, segments)
    save_minutes(directory, result)
