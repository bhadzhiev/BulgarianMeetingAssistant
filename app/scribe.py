"""ElevenLabs Scribe batch transcription. Credentials stay in the worker pipe."""
import json
import math
import re
import urllib.error
import urllib.request
import uuid

from .credentials import CredentialStore

MODEL = 'scribe_v2'
ALIGNMENT_METHOD = 'ElevenLabs Scribe word timestamps'
ENDPOINT = 'https://api.elevenlabs.io/v1/speech-to-text'


class KeyStore(CredentialStore):
    """The ElevenLabs API key in the shared Atlanta Keychain item. One key for all libraries."""
    def __init__(self):
        super().__init__('default', 'elevenlabs')


def keyterms(vocabulary):
    terms = list(dict.fromkeys(term.strip() for term in re.split(r'[,\n]', vocabulary) if term.strip()))
    if len(terms) > 1000 or any(len(t) > 50 or len(t.split()) > 5 or any(c in t for c in '<>{}[]\\') for t in terms):
        raise ValueError('Scribe vocabulary: use up to 1000 terms, each at most 50 characters and 5 words; avoid < > { } [ ] and backslash.')
    return terms


def transcribe(audio, key, terms, offset, end, timeout=180):
    boundary = 'scribe-' + uuid.uuid4().hex
    fields = [('model_id', MODEL), ('timestamps_granularity', 'word'),
              ('tag_audio_events', 'false'), ('diarize', 'false')]
    # The local speaker model separates speakers: Scribe merges voices that share one system audio stream.
    # Omit language_code so Bulgarian and English can both be detected.
    fields.extend(('keyterms', term) for term in terms)
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode() for name, value in fields]
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="recording.wav"\r\nContent-Type: audio/wav\r\n\r\n'.encode() + audio + b'\r\n')
    parts.append(f'--{boundary}--\r\n'.encode())
    request = urllib.request.Request(ENDPOINT, data=b''.join(parts),
        headers={'xi-api-key': key, 'Content-Type': 'multipart/form-data; boundary=' + boundary}, method='POST')
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.load(response)
    except urllib.error.HTTPError as exc:
        hints = {401: 'Check the ElevenLabs API key.', 403: 'Check key permissions and plan access.',
                 402: 'Check your ElevenLabs credits.', 413: 'The recording is larger than ElevenLabs accepts.',
                 429: 'ElevenLabs quota or concurrency limit reached; retry later.'}
        raise ValueError(f'Scribe request failed (HTTP {exc.code}). ' + hints.get(exc.code, 'Retry later or check your ElevenLabs account.')) from None
    except (urllib.error.URLError, TimeoutError):
        raise ValueError('Could not reach ElevenLabs. Check the connection and retry; the recording is saved.') from None
    return word_units(data, offset, end)


def word_units(data, offset, end):
    if not isinstance(data, dict) or not isinstance(data.get('text'), str) or not isinstance(data.get('words'), list):
        raise ValueError('Scribe returned an invalid transcript')
    units, previous = [], 0
    for word in data['words']:
        if not isinstance(word, dict):
            raise ValueError('Scribe returned an invalid word')
        if word.get('type') in {'spacing', 'audio_event'}:
            continue
        start, stop, text = word.get('start'), word.get('end'), word.get('text')
        if (word.get('type') != 'word' or type(start) not in (int, float) or type(stop) not in (int, float)
                or not math.isfinite(start) or not math.isfinite(stop) or start > end - offset or not previous <= start <= stop <= end - offset + .05
                or not isinstance(text, str) or not text.strip()):
            raise ValueError('Scribe returned invalid word timestamps')
        units.append(dict(start=offset + start, end=min(end, offset + stop), text=text.strip(), speaker=None))
        previous = start
    if data['text'].strip() and not units:
        raise ValueError('Scribe returned text without word timestamps')
    return units
