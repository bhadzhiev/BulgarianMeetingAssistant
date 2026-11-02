"""Optional, bounded-memory audio preparation for the final transcription pass.

Capture and playback keep the original audio. This module never removes silence or changes speed.
The caller publishes the prepared WAV only after transcription succeeds.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import wave

from .capture import ffmpeg_path

# afftdn at 16 kHz delays output by two 12.5 ms hops. Pad through its last partial
# hop, discard the 400-sample startup delay, then rebase timestamps before mixing.
# See FFmpeg libavfilter/af_afftdn.c (window_length = 3 * sample_advance).
DENOISE_DELAY = 400
# Deliberately mild: remove rumble, reduce steady noise by at most 6 dB, cap gain at 2x.
# The threshold keeps the normalizer from amplifying near-silence. Limiter auto-level is disabled.
LIGHT_FILTER = ('highpass=f=75,apad=pad_len=600,afftdn=nr=6:nf=-50:tn=1,'
                'atrim=start_sample=400,asetpts=PTS-STARTPTS,dynaudnorm=f=250:g=7:p=0.9:m=2:t=0.01')
LIMITER = 'alimiter=limit=0.95:level=0:latency=1'
# Strong: RNNoise (FFmpeg arnndn) with a model for voice in a noisy room. RNNoise works on 10 ms
# frames at 48 kHz and delays output by one frame (160 samples at 16 kHz, measured). Pad through the
# last frame, discard that delay, then balance the voices like Light. The model is read from the
# working directory, so a path with spaces needs no filter escaping.
RNNOISE_MODEL = 'rnnoise-leavened-quisling.rnnn'
RNNOISE_URL = ('https://raw.githubusercontent.com/GregorR/rnnoise-models/3eee541a283fd3b8f81b85b1748e3b9ccbefa04d/'
               'leavened-quisling-2018-08-31/lq.rnnn')
RNNOISE_SHA256 = '1957528b752799fddf06270bc5469af7cf54c3badc358544ae2abed730943ff9'
RNNOISE_DELAY = 160
STRONG_FILTER = ('highpass=f=75,aresample=48000,apad=pad_len=960,arnndn=m=' + RNNOISE_MODEL + ',aresample=16000,'
                 'atrim=start_sample=160,asetpts=PTS-STARTPTS,dynaudnorm=f=250:g=7:p=0.9:m=2:t=0.01')
FILTERS = {'light': (LIGHT_FILTER, DENOISE_DELAY), 'strong': (STRONG_FILTER, RNNOISE_DELAY)}


def rnnoise_model(models_dir: Path, progress) -> Path:
    from .model_cache import download
    destination = Path(models_dir) / RNNOISE_MODEL
    if not destination.is_file():
        destination.parent.mkdir(parents=True, exist_ok=True)
        download(RNNOISE_URL, destination, 'RNNoise model', progress, RNNOISE_SHA256)
    return destination


def pcm_frames(path: Path) -> int:
    with wave.open(str(path), 'rb') as source:
        if (source.getframerate(), source.getnchannels(), source.getsampwidth(), source.getcomptype()) != (16000, 1, 2, 'NONE'):
            raise ValueError('Processing requires a 16 kHz mono PCM recording')
        return source.getnframes()


def prepare(directory: Path, profile: str, progress, models_dir: Path | None = None) -> tuple[Path, dict]:
    original = directory / 'recording.wav'
    if profile not in {'off', 'light', 'strong'}:
        raise ValueError('Invalid audio preparation profile')
    if profile == 'off':
        return original, dict(profile='off', source='recording.wav')
    frames = pcm_frames(original)
    if not frames:
        raise ValueError('The recording contains no audio')
    cwd = None
    if profile == 'strong':
        try:
            cwd = rnnoise_model(models_dir or directory, progress).parent
        except Exception as exc:
            # Like any preparation failure, this stops the attempt; the chosen profile never changes silently.
            raise RuntimeError(f'The RNNoise model for Strong preparation is unavailable ({exc}). '
                               'Retry when online, or choose Light or Off.') from exc
    microphone_filter, delay = FILTERS[profile]
    progress('Preparing audio for transcription · ' + profile.capitalize())
    command = [ffmpeg_path(), '-hide_banner', '-loglevel', 'error', '-nostdin', '-y']
    split = False
    # With both original online tracks available, keep already-processed remote voices out of denoise.
    capture = directory / 'capture.json'
    if capture.exists():
        try:
            info = json.loads(capture.read_text())
            rates = [info.get('microphone_rate'), info.get('system_rate')]
            split = (info.get('mode') == 'online' and all(type(r) is int and 8000 <= r <= 192000 for r in rates)
                     and all((directory / name).is_file() and (directory / name).stat().st_size >= 2
                             for name in ('microphone.pcm', 'system.pcm')))
        except (OSError, ValueError, AttributeError):
            split = False
    if split:
        for name, rate in zip(('microphone.pcm', 'system.pcm'), rates):
            command += ['-f', 's16le', '-ar', str(rate), '-ac', '1', '-i', str(directory / name)]
        filters = (f'[0:a]aresample=16000,{microphone_filter},apad,atrim=end_sample={frames}[mic];'
                   f'[1:a]aresample=16000,apad,atrim=end_sample={frames}[system];'
                   '[mic][system]amix=inputs=2:normalize=0:dropout_transition=0,')
        source = 'separate microphone and system tracks'
    else:
        command += ['-i', str(original)]
        filters = f'[0:a]{microphone_filter},'
        source = 'recording.wav'
    filters += f'{LIMITER},apad,atrim=end_sample={frames}[out]'
    fd, name = tempfile.mkstemp(prefix='.transcription-', suffix='.wav', dir=directory)
    os.close(fd)
    output = Path(name)
    try:
        result = subprocess.run(command + ['-filter_complex', filters, '-map', '[out]', '-ar', '16000',
                                '-ac', '1', '-c:a', 'pcm_s16le', str(output)],
                                capture_output=True, text=True, timeout=600, cwd=cwd)
        if result.returncode:
            raise RuntimeError('Audio preparation failed: ' + result.stderr[-1200:])
        if pcm_frames(output) != frames:
            raise RuntimeError('Prepared audio changed the recording timeline')
        result = dict(profile=profile, source=source, sample_rate=16000, frames=frames,
                      microphone_filter=microphone_filter, limiter=LIMITER, latency_compensation_samples=delay)
        if profile == 'strong':
            result.update(model=RNNOISE_MODEL, model_sha256=RNNOISE_SHA256)
        return output, result
    except Exception:
        output.unlink(missing_ok=True)
        raise
