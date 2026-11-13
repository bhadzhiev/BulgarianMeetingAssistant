"""ElevenLabs Scribe batch transcription. Credentials stay in the worker pipe."""
import json
import math
import re
import urllib.error
import urllib.request
import uuid

from .credentials import CredentialStore

MODEL = 'scribe_v3'
ALIGNMENT_METHOD = 'ElevenLabs Scribe word timestamps'
ENDPOINT = 'https://api.elevenlabs.io/v1/speech-to-text'


class KeyStore(CredentialStore):
    """The ElevenLabs API key in the shared Atlanta Keychain item. One key for all libraries."""
    def __init__(self):
        super().__init__('default', 'elevenlabs')


def keyterms(vocabulary):
    from .vocabulary import terms as preferred_terms
    terms = preferred_terms(vocabulary)
    if len(terms) > 1000 or any(len(t) > 50 or len(t.split()) > 5 or any(c in t for c in '<>{}[]\\') for t in terms):
        raise ValueError('Scribe vocabulary: use up to 1000 terms, each at most 50 characters and 5 words; avoid < > { } [ ] and backslash.')
    return terms


EDIT_LIMIT = 2000
EDIT_RULES = ('Fix only speech recognition errors in this Bulgarian transcript: spelling, punctuation, capitalization, '
              'merged or split words. Keep English technical terms in English; do not translate them. Do not rephrase, '
              'summarize, translate, add or drop content. Keep every name, number, date and negation exactly.')


def edit_instruction(vocabulary, speakers=()):
    """The transcript_edit instruction: the correction rules plus the preferred spellings and names that fit."""
    from .vocabulary import terms as preferred_terms
    base = EDIT_RULES
    names = ', '.join(str(n) for n in list(speakers)[:100])
    if names:
        base += '\nParticipant names: ' + names + '.'
    prefix = 'Preferred spellings where the audio supports them: '
    chosen, length = [], len(base) + 1 + len(prefix)
    for term in preferred_terms(vocabulary):
        if length + len(term) + 2 > EDIT_LIMIT:
            break
        chosen.append(term)
        length += len(term) + 2
    if chosen:
        base += '\n' + prefix + ', '.join(chosen) + '.'
    return base[:EDIT_LIMIT]


def transcribe(audio, key, terms, offset, end, timeout=180, edit=''):
    boundary = 'scribe-' + uuid.uuid4().hex
    # The local speaker model separates speakers: Scribe merges voices that share one system audio stream.
    # Bulgarian is the main language; Scribe v3 declares English as secondary instead of guessing (2026-11-13).
    fields = [('model_id', MODEL), ('timestamps_granularity', 'word'), ('language_code', 'bg'),
              ('secondary_language_codes', 'en'), ('tag_audio_events', 'false'), ('diarize', 'false')]
    if edit:
        fields.append(('transcript_edit', edit))
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
    edited = data.get('edited_transcript')
    return word_units(data, offset, end), edited if isinstance(edited, str) and edited.strip() else None


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
