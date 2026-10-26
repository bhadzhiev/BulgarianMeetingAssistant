"""Optional Apple Silicon ASR. No audio leaves the Mac; only model files download."""
from importlib import util
import math
from pathlib import Path
import platform
import sys

MODEL_NAME = 'parakeet-tdt-0.6b-v3'
MODEL_ID = 'mlx-community/' + MODEL_NAME
MODEL_REVISION = 'ed2b7e8c15f9aaa0b5772e2efb986255eaef7e15'
ALIGNMENT_METHOD = 'Parakeet TDT token boundaries grouped into words'


def availability():
    supported = sys.platform == 'darwin' and platform.machine() == 'arm64'
    try:
        installed = supported and all(util.find_spec(name) is not None for name in ('parakeet_mlx', 'mlx'))
    except (ImportError, ValueError):
        installed = False
    return dict(available=bool(installed), model=MODEL_NAME, message=(
        'Parakeet v3 runs locally. Its model downloads on first use. Live captions use Whisper; the Whisper vocabulary does not apply to Parakeet.' if installed else
        'Parakeet requires Apple Silicon.' if not supported else
        'Parakeet is not included in this build. Rebuild with --with-parakeet and requirements-parakeet.txt.'))


def word_units(result, offset, duration):
    """Join subword tokens using their whitespace and real boundaries, never interpolated times."""
    units = []
    previous = 0.0
    separated = True
    for token in result.tokens:
        text = token.text
        start, end = float(token.start), float(token.end)
        if (not isinstance(text, str) or not math.isfinite(start) or not math.isfinite(end)
                or not 0 <= start <= end <= duration + 1 or start < previous):
            raise ValueError('Parakeet returned invalid token boundaries')
        previous = start
        if not text.strip():
            separated = separated or bool(text)
            continue
        new_word = separated or text[0].isspace() or not units
        if new_word:
            units.append(dict(start=offset + min(start, duration), end=offset + min(end, duration), text=text.strip(), speaker=None))
        else:
            units[-1]['text'] += text.strip()
            units[-1]['end'] = offset + min(end, duration)
        separated = text[-1].isspace()
    # Reject malformed decoder output rather than silently losing or inventing words.
    if ' '.join(' '.join(u['text'] for u in units).split()) != ' '.join(result.text.split()):
        raise ValueError('Parakeet token text does not match its transcript')
    return units


class Decoder:
    def __init__(self, models_dir, progress):
        if not availability()['available']:
            raise RuntimeError(availability()['message'])
        progress('Loading Parakeet v3 (first use downloads the local model)')
        from huggingface_hub import snapshot_download
        from parakeet_mlx import from_pretrained
        path = snapshot_download(MODEL_ID, revision=MODEL_REVISION,
            cache_dir=str(Path(models_dir) / 'parakeet'), allow_patterns=['config.json', 'model.safetensors'])
        self.model = from_pretrained(path)

    def transcribe(self, samples, offset, rate=16000):
        # The shared pipeline already provides mono PCM; avoid another ffmpeg round trip.
        import mlx.core as mx
        import numpy as np
        from parakeet_mlx.audio import get_logmel
        config = self.model.preprocessor_config
        if rate != config.sample_rate:
            raise ValueError('Parakeet input sample rate does not match its model')
        audio = samples.astype(np.float32) / 32768
        if len(audio) < config.hop_length:
            audio = np.pad(audio, (0, config.hop_length - len(audio)))
        result = self.model.generate(get_logmel(mx.array(audio), config))[0]
        return word_units(result, offset, len(samples) / rate)
