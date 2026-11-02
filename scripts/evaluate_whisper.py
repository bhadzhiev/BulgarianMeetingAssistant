#!/usr/bin/env python3
"""Compare local Whisper models on one short clip and a human reference. No text AI."""
import argparse
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import time


def word_error_rate(reference, prediction):
    def words(text):
        return re.findall(r"\w+(?:[-']\w+)*", text.casefold())
    expected, actual = words(reference), words(prediction)
    if not expected:
        raise ValueError('The reference must contain words')
    previous = list(range(len(actual) + 1))
    for i, word in enumerate(expected, 1):
        current = [i]
        for j, other in enumerate(actual, 1):
            current.append(min(previous[j] + 1, current[-1] + 1, previous[j-1] + (word != other)))
        previous = current
    return previous[-1] / len(expected)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audio', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True, help='Human transcript of exactly the selected clip')
    parser.add_argument('--output', type=Path, required=True, help='New private directory; never an existing library')
    parser.add_argument('--models-dir', type=Path, required=True)
    parser.add_argument('--models', nargs='+', choices=['large-v3-turbo','large-v3','medium','small'], default=['large-v3-turbo','large-v3'])
    parser.add_argument('--start', type=float, default=0)
    parser.add_argument('--seconds', type=float, default=120)
    args = parser.parse_args()
    if not math.isfinite(args.start) or not 0 <= args.start or not 0 < args.seconds <= 600:
        parser.error('Choose a finite start and a clip of at most 600 seconds')
    if not args.audio.is_file() or not args.reference.is_file() or args.reference.stat().st_size > 100000:
        parser.error('Choose audio and a reference text file of at most 100 KB')
    reference = args.reference.read_text()
    if len(reference.split()) > 5000:
        parser.error('Use a short reference of at most 5000 words')
    word_error_rate(reference, '')
    args.output.mkdir(mode=0o700, parents=True, exist_ok=False)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.capture import ffmpeg_path
    from app.processing import transcribe
    from app.service import DEFAULTS
    clip = args.output/'clip.wav'
    subprocess.run([ffmpeg_path(),'-v','error','-nostdin','-ss',str(args.start),'-i',str(args.audio),'-t',str(args.seconds),'-ac','1','-ar','16000','-c:a','pcm_s16le',str(clip)], check=True)
    import shutil
    import wave
    with wave.open(str(clip)) as audio:
        duration = audio.getnframes()/audio.getframerate()
    results = []
    for model in dict.fromkeys(args.models):
        directory = args.output/model;directory.mkdir(mode=0o700)
        shutil.copyfile(clip, directory/'recording.wav')
        started = time.monotonic()
        transcribe(directory, dict(DEFAULTS, transcription='local', local_model=model,
            models_dir=str(args.models_dir), diarization_enabled=False, audio_preparation='off'), lambda _:None)
        elapsed = time.monotonic() - started
        prediction = ' '.join(s['text'] for s in json.loads((directory/'transcript.json').read_text()))
        row = dict(model=model, seconds=round(elapsed,2), audio_seconds=round(duration,2),
                   wer=word_error_rate(reference,prediction), wall_seconds_per_audio_second=elapsed/max(duration,.001))
        results.append(row)
        (args.output/'metrics.json').write_text(json.dumps(dict(normalization='casefold, words, punctuation ignored', results=results),indent=2))
        print(json.dumps(row), flush=True)


if __name__ == '__main__':
    main()
