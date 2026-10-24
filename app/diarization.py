"""Optional, offline speaker diarization using pyannote.audio."""
from __future__ import annotations

import math
import os
from pathlib import Path

from .storage import atomic_json

MODEL_ID = 'pyannote/speaker-diarization-community-1'
_pipeline = None


def diarize(directory: Path, progress=lambda message: None) -> list[dict]:
    """Create a speaker timeline without sending audio to a network service."""
    global _pipeline
    audio = directory / 'recording.wav'
    if not audio.is_file():
        raise ValueError('A saved recording is required for speaker diarization')
    try:
        import torch
        from pyannote.audio import Pipeline
    except ImportError as exc:
        raise RuntimeError(
            'Speaker diarization is optional. Install requirements-diarization.txt '
            'in the app environment, then retry Analytics.'
        ) from exc
    try:
        if _pipeline is None:
            progress('Loading offline speaker-diarization model')
            # The token is read from the environment and is never persisted.
            _pipeline = Pipeline.from_pretrained(MODEL_ID, token=os.environ.get('HF_TOKEN') or None)
            if torch.backends.mps.is_available():
                _pipeline.to(torch.device('mps'))
        progress('Identifying speakers locally')
        output = _pipeline(str(audio))
        annotation = getattr(output, 'speaker_diarization', output)
        timeline = []
        for turn, _, speaker in annotation.itertracks(yield_label=True):
            start, end = float(turn.start), float(turn.end)
            if math.isfinite(start) and math.isfinite(end) and 0 <= start < end:
                timeline.append({'start': round(start, 3), 'end': round(end, 3), 'speaker': str(speaker)})
        if not timeline:
            raise RuntimeError('The diarization model returned no speaker intervals')
        timeline.sort(key=lambda item: (item['start'], item['end'], item['speaker']))
        atomic_json(directory / 'speaker-timeline.json', timeline)
        return timeline
    except Exception as exc:
        if isinstance(exc, (ValueError, RuntimeError)) and str(exc).startswith('Speaker diarization'):
            raise
        message = str(exc)
        token = os.environ.get('HF_TOKEN')
        if token:
            message = message.replace(token, '[redacted]')
        raise RuntimeError(
            'Offline diarization could not finish. Check the pyannote installation, '
            'model access and HF_TOKEN. Transcription is preserved. ' + message
        ) from exc
