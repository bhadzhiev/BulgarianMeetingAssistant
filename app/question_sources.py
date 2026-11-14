"""Resolve a meeting question or decision to its canonical item without changing the saved wording."""
from __future__ import annotations


def tracked_question(registry: dict, meeting_id: str, entry: dict) -> dict | None:
    item = registry.get(entry.get('item_id'))
    if item and item['kind'] == 'question':
        return item
    for item in registry.values():
        origin = item.get('origin') or {}
        if (item['kind'] == 'question' and origin.get('meeting_id') == meeting_id
                and item['text'].strip() == entry['text'].strip()
                and origin.get('evidence_timestamp') == entry.get('evidence_timestamp')):
            return item
    return None


def tracked_decision(registry: dict, meeting_id: str, entry: dict) -> dict | None:
    item = registry.get(entry.get('item_id'))
    if item and item['kind'] == 'decision':
        return item
    for item in registry.values():
        if item['kind'] != 'decision' or item['text'].strip() != entry['text'].strip():continue
        sources = [item.get('origin') or {}, *item['links']]
        if any(source.get('meeting_id') == meeting_id and source.get('evidence_timestamp') == entry.get('evidence_timestamp') for source in sources):
            return item
    return None
