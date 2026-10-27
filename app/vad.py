"""Silero voice activity detection (ONNX) for live captions and Parakeet.

The final Whisper pass uses the same detector inside whisper.cpp. pywhispercpp cannot call that
detector directly, so live captions and Parakeet run the ONNX release of the same model version.
Without onnxruntime or the model, callers keep their previous behavior.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

RATE = 16000
WINDOW = 512   # samples per decision at 16 kHz (32 ms)
CONTEXT = 64   # samples that each window repeats from the previous one, as the v5 model expects
MODEL = 'silero-vad-v5.1.2.onnx'
URL = 'https://raw.githubusercontent.com/snakers4/silero-vad/v5.1.2/src/silero_vad/data/silero_vad.onnx'
SHA256 = '2623a2953f6ff3d2c1e61740c6cdb7168133479b267dfef114a4a3cc5bdd788f'
LABEL = 'silero v5.1.2 onnx'


class SileroVAD:
    def __init__(self, path):
        import onnxruntime
        options = onnxruntime.SessionOptions()
        options.inter_op_num_threads = options.intra_op_num_threads = 1
        self.session = onnxruntime.InferenceSession(str(path), sess_options=options, providers=['CPUExecutionProvider'])

    def probabilities(self, samples: np.ndarray) -> np.ndarray:
        """The speech probability of each 32 ms window of float samples in [-1, 1]."""
        samples = np.asarray(samples, dtype=np.float32)
        count = -(-len(samples) // WINDOW)
        padded = np.zeros(count * WINDOW, dtype=np.float32)
        padded[:len(samples)] = samples
        state = np.zeros((2, 1, 128), dtype=np.float32)
        context = np.zeros((1, CONTEXT), dtype=np.float32)
        rate = np.array(RATE, dtype=np.int64)
        result = np.empty(count, dtype=np.float32)
        for index in range(count):
            window = np.concatenate([context, padded[index * WINDOW:(index + 1) * WINDOW][None]], axis=1)
            output, state = self.session.run(None, {'input': window, 'state': state, 'sr': rate})
            context = window[:, -CONTEXT:]
            result[index] = output[0][0]
        return result


def speech_spans(probabilities, threshold=.5, release=.35, min_speech=.25, min_silence=.1):
    """Sample ranges of speech. Speech starts above the threshold and ends after a short pause below release."""
    spans, start, quiet = [], None, 0
    windows_speech, windows_silence = int(min_speech * RATE / WINDOW), max(1, int(min_silence * RATE / WINDOW))
    for index, probability in enumerate(probabilities):
        if start is None:
            if probability >= threshold:
                start, quiet = index, 0
        elif probability < release:
            quiet += 1
            if quiet >= windows_silence:
                end = index - quiet + 1
                if end - start >= windows_speech:
                    spans.append((start * WINDOW, end * WINDOW))
                start = None
        else:
            quiet = 0
    if start is not None and len(probabilities) - start >= windows_speech:
        spans.append((start * WINDOW, len(probabilities) * WINDOW))
    return spans


def load(models_dir, progress=lambda _: None):
    """(detector, None) or (None, reason). A missing runtime or model never stops transcription."""
    try:
        from .model_cache import download
        destination = Path(models_dir) / MODEL
        if not destination.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            download(URL, destination, 'voice detection model', progress, SHA256)
        return SileroVAD(destination), None
    except Exception as exc:
        return None, f'unavailable: {exc}'
