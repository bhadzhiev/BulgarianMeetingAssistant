"""Experimental local Parakeet v3 ONNX with decoder-time vocabulary boosting."""
from importlib import util
from importlib.metadata import version, PackageNotFoundError
import math
from pathlib import Path
import re
from types import SimpleNamespace

from .parakeet import MODEL_NAME, word_units
from .storage import atomic_text

MODEL_ID = 'csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8'
MODEL_REVISION = '2bda32ec70b097a55adaa07d9a7173915b43cc78'
RUNTIME_VERSION = '2.0.1'  # Includes upstream #4084 (TDT speech dropping / hotword scoring).
FILES = ('encoder.int8.onnx', 'decoder.int8.onnx', 'joiner.int8.onnx', 'tokens.txt')
ALIGNMENT_METHOD = 'Parakeet Sherpa TDT token boundaries grouped into words'
HOTWORDS_SCORE = 1.5
LENGTH_REWARD = 0.5


def availability():
    try:
        installed = util.find_spec('sherpa_onnx') is not None and version('sherpa-onnx') == RUNTIME_VERSION
    except (ImportError, ValueError, PackageNotFoundError):
        installed = False
    return dict(available=installed, model=MODEL_NAME, message=(
        'Experimental Parakeet + vocabulary runs locally on CPU. Uses terms and participant names during recognition. '
        'First use downloads a separate ONNX model (about 670 MB). Speed and Bulgarian accuracy may differ from MLX.' if installed else
        'Parakeet + vocabulary is not included in this build. Install requirements-parakeet-sherpa.txt and rebuild with --with-parakeet-sherpa.'))


def cached(models_dir):
    path = Path(models_dir) / 'parakeet-sherpa' / ('models--' + MODEL_ID.replace('/', '--')) / 'snapshots' / MODEL_REVISION
    return all((path / name).is_file() for name in FILES)


def vocabulary_terms(vocabulary, speakers=()):
    # Commas, semicolons and newlines separate phrases; spaces inside names are retained.
    terms = []
    for value in [*re.split(r'[,;\n]', vocabulary), *speakers]:
        term = ' '.join(value.split())
        if term and term not in terms:
            # These characters control Sherpa's phrase/score parser, not literal text.
            if any(c in term for c in '/:') or any(ord(c) < 32 for c in term):
                raise ValueError('Parakeet vocabulary phrases cannot contain /, : or control characters. Separate terms with commas or newlines.')
            terms.append(term)
    if len(terms) > 200 or sum(map(len, terms)) > 8000:
        raise ValueError('Parakeet vocabulary is too large (maximum 200 phrases / 8000 characters including participant names).')
    return terms


def prepare_vocabulary(tokens_path, target, terms):
    """Official Sherpa Parakeet recipe: tokens.txt -> equal-score longest-match BPE vocab.

    Fail visibly for unknown characters instead of allowing Sherpa to silently skip a phrase.
    This is a hotword tokenizer, not a replacement for the speech model tokenizer.
    """
    symbols = [line.rsplit(' ', 1)[0] for line in Path(tokens_path).read_text().splitlines() if line.strip()]
    alphabet = {c for symbol in symbols if not symbol.startswith('<') for c in symbol}
    unsupported = [term for term in terms if any(c not in alphabet for c in term.replace(' ', '▁'))]
    if unsupported:
        raise ValueError('Parakeet vocabulary contains unsupported characters: ' + ', '.join(unsupported[:5]))
    Path(target).parent.mkdir(parents=True, exist_ok=True)
    atomic_text(Path(target), ''.join(symbol + '\t-1.0\n' for symbol in symbols))


def result_units(result, offset, duration):
    tokens, starts, lengths = result.tokens, result.timestamps, result.durations
    if len(tokens) != len(starts) or len(tokens) != len(lengths):
        raise ValueError('Parakeet Sherpa returned missing token boundaries')
    timed = []
    for text, start, length in zip(tokens, starts, lengths):
        if not isinstance(text, str) or not math.isfinite(length) or length < 0:
            raise ValueError('Parakeet Sherpa returned invalid token boundaries')
        timed.append(SimpleNamespace(text=text.replace('▁', ' '), start=start, end=start + length))
    return word_units(SimpleNamespace(text=result.text, tokens=timed), offset, duration)


class Decoder:
    def __init__(self, models_dir, progress, vocabulary='', speakers=()):
        runtime = availability()
        if not runtime['available']:
            raise RuntimeError(runtime['message'])
        from huggingface_hub import snapshot_download
        import sherpa_onnx
        self.terms = vocabulary_terms(vocabulary, speakers)
        progress('Loading experimental Parakeet + vocabulary (first use downloads about 670 MB)')
        cache = Path(models_dir) / 'parakeet-sherpa'
        path = Path(snapshot_download(MODEL_ID, revision=MODEL_REVISION, cache_dir=str(cache), allow_patterns=list(FILES)))
        # A fixed derived vocabulary has no user terms and is safe to share across meetings.
        vocab = cache / 'hotword-bpe.vocab'
        prepare_vocabulary(path / 'tokens.txt', vocab, self.terms)
        self.model = sherpa_onnx.OfflineRecognizer.from_transducer(
            encoder=str(path / FILES[0]), decoder=str(path / FILES[1]), joiner=str(path / FILES[2]),
            tokens=str(path / 'tokens.txt'), num_threads=4, provider='cpu', model_type='nemo_transducer',
            decoding_method='modified_beam_search', max_active_paths=4,
            hotwords_score=HOTWORDS_SCORE, modeling_unit='bpe', bpe_vocab=str(vocab))
        self.hotwords = '/'.join(self.terms)

    def transcribe(self, samples, offset, rate=16000):
        import numpy as np
        if rate != 16000:
            raise ValueError('Parakeet input must be 16 kHz mono PCM')
        if not len(samples):
            return []
        stream = self.model.create_stream(self.hotwords) if self.hotwords else self.model.create_stream()
        # See upstream #4084: avoids rewarding paths that skip speech after a pause.
        stream.set_option('length_reward', str(LENGTH_REWARD))
        stream.accept_waveform(rate, samples.astype(np.float32) / 32768)
        self.model.decode_stream(stream)
        return result_units(stream.result, offset, len(samples) / rate)
