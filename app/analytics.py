"""Deterministic conversation analytics and optional local semantic topic matching."""
from __future__ import annotations

import json
import math
from pathlib import Path
import re

from .storage import atomic_json

VERSION = 1
GENERIC_SPEAKER = re.compile(r'^(?:SPEAKER[ _-]?\d+|speaker[ _-]?\d+)$', re.IGNORECASE)
QUESTION_CUES = re.compile(
    r'^(?:'
    r'как|какво|каква|какви|кога|къде|защо|кой|коя|кои|чий|чия|чие|чии|колко|дали|нали|'
    r'може|мога|бих|бихте|искаш|искате|'
    r'who|what|when|where|why|how|which|whose|can|could|would|should|shall|may|might|'
    r'is|are|was|were|do|does|did|will|have|has'
    r')\b',
    re.IGNORECASE,
)


def is_generic_speaker(name) -> bool:
    return isinstance(name, str) and bool(GENERIC_SPEAKER.fullmatch(name.strip()))


def relabel_range(timeline, start, end, old, new) -> list[dict]:
    """Give the part of the old speaker's turns inside [start, end] to the new speaker."""
    result = []
    for turn in timeline:
        first, last = turn.get('start'), turn.get('end')
        if (turn.get('speaker') != old or type(first) not in {int, float} or type(last) not in {int, float}
                or last <= start or first >= end):
            result.append(turn)
            continue
        if first < start:
            result.append(dict(turn, end=start))
        result.append(dict(turn, start=max(first, start), end=min(last, end), speaker=new))
        if last > end:
            result.append(dict(turn, start=end))
    return result


def clean_intervals(intervals) -> list[dict]:
    result = []
    for item in intervals or []:
        try:
            start, end, speaker = float(item['start']), float(item['end']), item.get('speaker')
        except (KeyError, TypeError, ValueError):
            continue
        if (math.isfinite(start) and math.isfinite(end) and 0 <= start < end
                and isinstance(speaker, str) and speaker.strip()):
            result.append({'start': start, 'end': end, 'speaker': speaker.strip()})
    return sorted(result, key=lambda item: (item['start'], item['end'], item['speaker']))


def merge_intervals(intervals) -> list[dict]:
    """Merge touching/overlapping turns belonging to one speaker."""
    merged = []
    for item in clean_intervals(intervals):
        if merged and item['start'] <= merged[-1]['end']:
            merged[-1]['end'] = max(merged[-1]['end'], item['end'])
        else:
            merged.append(dict(item))
    return merged


def assign_speakers(segments, intervals) -> list[dict]:
    """Assign each transcript segment by maximum overlap, then midpoint fallback."""
    timeline = clean_intervals(intervals)
    result = []
    for segment in segments:
        updated = dict(segment)
        if timeline:
            start, end = float(segment['start']), float(segment['end'])
            overlap = {}
            for turn in timeline:
                seconds = max(0.0, min(end, turn['end']) - max(start, turn['start']))
                if seconds:
                    overlap[turn['speaker']] = overlap.get(turn['speaker'], 0.0) + seconds
            if overlap:
                updated['speaker'] = max(overlap, key=overlap.get)
            else:
                midpoint = (start + end) / 2
                containing = [turn for turn in timeline if turn['start'] <= midpoint <= turn['end']]
                if containing:
                    updated['speaker'] = containing[0]['speaker']
        result.append(updated)
    return result


def split_sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r'(?<=[.!?…])\s+|[\r\n]+', text) if part.strip()]


def is_question(text: str) -> bool:
    stripped = text.strip()
    if '?' in stripped or '？' in stripped:
        return True
    normalized = re.sub(r'^[\s\-–—*>"“”„«»()[\]{}]+', '', stripped)
    return bool(QUESTION_CUES.match(normalized))


def detect_questions(segments, previous=None) -> list[dict]:
    # A position ID is not enough: a new transcript can put another question at the same position.
    # Text and time identify the question; the speaker is left out so that renaming keeps the state.
    answered = {}
    for item in (previous or {}).get('questions', []):
        answered[(item.get('text'), item.get('timestamp'))] = bool(item.get('answered'))
    questions = []
    for segment_index, segment in enumerate(segments):
        for sentence_index, sentence in enumerate(split_sentences(segment.get('text', ''))):
            if not is_question(sentence):
                continue
            question_id = f'q-{segment_index}-{sentence_index}'
            timestamp = float(segment['start'])
            speaker = segment.get('speaker') or None
            was_answered = answered.get((sentence, timestamp), False)
            questions.append({
                'id': question_id,
                'segment_index': segment_index,
                'text': sentence,
                'speaker': speaker,
                'timestamp': timestamp,
                'answered': was_answered,
            })
    return questions


def speaker_statistics(intervals, questions) -> tuple[list[dict], float]:
    by_speaker = {}
    for item in clean_intervals(intervals):
        by_speaker.setdefault(item['speaker'], []).append(item)
    question_counts = {}
    for question in questions:
        speaker = question.get('speaker')
        if speaker:
            question_counts[speaker] = question_counts.get(speaker, 0) + 1
    stats = []
    for speaker, turns in by_speaker.items():
        turns = merge_intervals(turns)
        durations = [turn['end'] - turn['start'] for turn in turns]
        seconds = sum(durations)
        stats.append({
            'speaker': speaker,
            'talk_seconds': round(seconds, 3),
            'turns': len(turns),
            'longest_monologue_seconds': round(max(durations), 3),
            'average_turn_seconds': round(seconds / len(turns), 3),
            'questions': question_counts.get(speaker, 0),
        })
    total = sum(item['talk_seconds'] for item in stats)
    for item in stats:
        item['talk_percent'] = round(100 * item['talk_seconds'] / total, 1) if total else 0.0
    stats.sort(key=lambda item: (-item['talk_seconds'], item['speaker'].casefold()))
    return stats, round(total, 3)


def literal_topic_matches(segments, tracker) -> list[dict]:
    phrases = [phrase for phrase in tracker.get('phrases', []) if phrase.strip()]
    folded = [(phrase, phrase.casefold()) for phrase in phrases]
    matches = []
    for index, segment in enumerate(segments):
        text = segment.get('text', '')
        found = [original for original, phrase in folded if phrase in text.casefold()]
        if found:
            matches.append({
                'segment_index': index,
                'timestamp': float(segment['start']),
                'speaker': segment.get('speaker') or None,
                'text': text,
                'phrases': found,
                'semantic': False,
            })
    return matches


def semantic_topic_matches(segments, tracker, settings) -> list[dict]:
    from .local_ai import complete_json
    schema = {
        'type': 'object',
        'properties': {'matches': {'type': 'array', 'items': {'type': 'integer'}}},
        'required': ['matches'],
        'additionalProperties': False,
    }
    transcript = '\n'.join(f'[{index}] {segment.get("text", "")}' for index, segment in enumerate(segments))
    messages = [
        {'role': 'system', 'content': 'Match transcript segments to a discussion topic. Return only relevant segment IDs; do not infer IDs that are absent.'},
        {'role': 'user', 'content': f'Topic: {tracker["name"]}\nPhrases: {json.dumps(tracker.get("phrases", []), ensure_ascii=False)}\nTranscript:\n{transcript}'},
    ]
    response = complete_json(settings, messages, schema, 'topic_matches', timeout=300)
    ids = response.get('matches')
    if not isinstance(ids, list) or any(type(index) is not int or not 0 <= index < len(segments) for index in ids):
        raise ValueError('Local AI returned invalid transcript segment IDs for a topic')
    matches = []
    for index in sorted(set(ids)):
        segment = segments[index]
        matches.append({
            'segment_index': index,
            'timestamp': float(segment['start']),
            'speaker': segment.get('speaker') or None,
            'text': segment.get('text', ''),
            'phrases': [],
            'semantic': True,
        })
    return matches


def build_topics(segments, trackers, settings=None, progress=lambda message: None) -> tuple[list[dict], str | None]:
    topics, errors = [], []
    for tracker in trackers:
        matches = literal_topic_matches(segments, tracker)
        if tracker.get('semantic_matching'):
            progress(f'Checking topic · {tracker["name"]}')
            try:
                semantic = semantic_topic_matches(segments, tracker, settings or {})
                known = {match['segment_index'] for match in matches}
                matches.extend(match for match in semantic if match['segment_index'] not in known)
                matches.sort(key=lambda match: match['segment_index'])
            except Exception as exc:
                errors.append(f'{tracker["name"]}: {exc}')
        topics.append({'id': tracker['id'], 'name': tracker['name'], 'matches': matches, 'match_count': len(matches)})
    return topics, '; '.join(errors) or None


def build_analytics(segments, intervals, trackers, settings=None, previous=None, progress=lambda message: None) -> dict:
    questions = detect_questions(segments, previous)
    speakers, total = speaker_statistics(intervals, questions)
    topics, semantic_error = build_topics(segments, trackers, settings, progress)
    result = {
        'version': VERSION,
        'speakers': speakers,
        'total_speech_seconds': total,
        'topics': topics,
        'questions': questions,
        'unanswered_questions': sum(not question['answered'] for question in questions),
    }
    if semantic_error:
        result['semantic_error'] = semantic_error
    return result


def analyze(directory: Path, settings: dict, trackers, progress=lambda message: None) -> dict:
    transcript_path = directory / 'transcript.json'
    segments = json.loads(transcript_path.read_text())
    timeline_path = directory / 'speaker-timeline.json'
    intervals = json.loads(timeline_path.read_text()) if timeline_path.exists() else []
    analytics_path = directory / 'analytics.json'
    previous = json.loads(analytics_path.read_text()) if analytics_path.exists() else None
    result = build_analytics(segments, intervals, trackers, settings, previous, progress)
    atomic_json(analytics_path, result)
    return result
