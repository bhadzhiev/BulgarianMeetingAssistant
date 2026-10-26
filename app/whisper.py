"""Whisper output clean-up, the vocabulary prompt, and the merge of a prompted pass into timed segments."""
from __future__ import annotations

import dataclasses
import difflib
import re

_SENTENCE = r'[^.!?\n]*[.!?…]*'
# Whisper learned these subtitle credits and video endings from its training data.
# It writes them over silence or noise; nobody says them in a meeting.
HALLUCINATIONS = re.compile('|'.join(pattern + _SENTENCE for pattern in [
    r'(?:превод|редакция|редактор)\s+(?:и\s+)?(?:на\s+)?субтитри(?:те)?',
    r'субтитри(?:те)?\s*(?:от|на|:|-|бяха)',
    r'субтитр(?:ы|ов)\s+(?:сделал|делал|создавал|подготовил|от)',
    r'редактор\s+субтитров',
    r'(?:не\s+)?забравяйте\s+да\s+се\s+абонирате',
    r'абонирайте\s+се',
    r'подпишитесь\s+на',
    r'благодаря\s+(?:ви\s+)?за\s+гледането',
    r'спасибо\s+за\s+просмотр',
    r'продолжение\s+следует',
    r'thanks?\s+(?:you\s+)?for\s+watching',
    r'subtitles?\s+by',
]), re.IGNORECASE)
# Short endings that are hallucinations only when they are the whole segment.
WHOLE_SEGMENT = {'продължава', 'следва продължение', 'продолжение следует', 'край'}
MIN_REPEATS = 4
PROMPT_CHARS = 400


def _key(word: str) -> str:
    return re.sub(r'[^\w]', '', word).casefold()


def collapse_repeats(text: str, max_words: int = 6) -> str:
    """Keep one copy of a phrase that Whisper repeats in a loop (four or more times in a row)."""
    words = text.split()
    keys = [_key(word) for word in words]
    result, i = [], 0
    while i < len(words):
        for size in range(1, max_words + 1):
            phrase = keys[i:i + size]
            if len(phrase) < size or not all(phrase):
                continue
            count = 1
            while keys[i + count * size:i + (count + 1) * size] == phrase:
                count += 1
            if count >= MIN_REPEATS:
                result.extend(words[i:i + size])
                i += count * size
                break
        else:
            result.append(words[i])
            i += 1
    return ' '.join(result)


def remove_hallucinations(text: str) -> str:
    text = HALLUCINATIONS.sub(' ', text)
    text = collapse_repeats(' '.join(text.split()))
    if ' '.join(_key(word) for word in text.split() if _key(word)) in WHOLE_SEGMENT:
        return ''
    # Punctuation that a removed phrase leaves behind is not speech.
    return text if any(character.isalnum() for character in text) else ''


def build_prompt(vocabulary: str, speakers=()) -> str:
    """A short list of terms and names. Whisper uses it to spell rare words correctly."""
    items, seen = [], set()
    for item in re.split(r'[,;\n]', vocabulary or '') + list(speakers):
        item = ' '.join(str(item).split())
        if item and item.casefold() not in seen:
            seen.add(item.casefold())
            items.append(item)
    prompt = ''
    for item in items:
        # Whisper keeps only about 220 prompt tokens; Cyrillic text needs many tokens.
        candidate = f'{prompt}, {item}' if prompt else item
        if len(candidate) >= PROMPT_CHARS:
            break
        prompt = candidate
    return prompt + '.' if prompt else ''


def repeats_prompt(text: str, prompt: str) -> bool:
    """Whisper can copy words from the prompt when it hears no speech."""
    words = {_key(word) for word in text.split()} - {''}
    return bool(prompt and words) and words <= {_key(word) for word in prompt.split()}


def apply_prompted_text(segments: list, prompted: str, min_ratio: float = 0.5) -> list:
    """Put the words of the prompted pass into the timed segments of the plain pass.

    A prompt improves names and terms, but it makes Whisper timestamps unreliable.
    The plain pass keeps the timestamps. If the two passes disagree too much, the plain text stays.
    """
    timed = [(index, word) for index, segment in enumerate(segments) for word in segment.text.split()]
    words = prompted.split()
    if not timed or not words:
        return segments
    matcher = difflib.SequenceMatcher(None, [_key(word) for _, word in timed], [_key(word) for word in words],
                                      autojunk=False)
    if matcher.ratio() < min_ratio:
        return segments
    owner = [None] * len(words)
    for tag, a0, a1, b0, b1 in matcher.get_opcodes():
        if tag == 'equal' or tag == 'replace':
            for k in range(b0, b1):
                # A replaced block spreads over the plain words it replaces.
                owner[k] = timed[a0 + (k - b0) * (a1 - a0) // (b1 - b0)][0]
    # An inserted word joins the segment of the word before it.
    for k in range(1, len(words)):
        if owner[k] is None:
            owner[k] = owner[k - 1]
    first = next((index for index in owner if index is not None), 0)
    texts = {}
    for k, word in enumerate(words):
        texts.setdefault(first if owner[k] is None else owner[k], []).append(word)
    return [dataclasses.replace(segment, text=' '.join(texts[index])) if index in texts else segment
            for index, segment in enumerate(segments)]


def word_units(raw, offset=0):
    """Keep native word-sized boundaries; do not merge turns before diarization."""
    from meeting_assistant import TranscriptSegment, clean_text
    import math
    result = []
    for segment in raw:
        text = clean_text(segment.text)
        if not text:
            continue
        start, end = offset + segment.t0 / 100, offset + segment.t1 / 100
        if not math.isfinite(start) or not math.isfinite(end) or not 0 <= start <= end:
            raise ValueError('Whisper returned invalid word boundaries')
        result.append(TranscriptSegment(start, end, text))
    return result
