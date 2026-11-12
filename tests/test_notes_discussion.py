"""The details of a meeting by topic, and the summary as an overview (2026-11-13)."""
import json
from pathlib import Path
import tempfile
import unittest

from app import notes, search
from app.notes_consolidation import candidates, consolidate, merge_topics
from app.processing import canonical_notes
from app.service import MeetingService
from meeting_assistant import TranscriptSegment, llm_prompt, minutes_schema, save_minutes, save_transcript, validate_minutes
from tests.test_calendar import FakeGoogle

PROJECT = Path(__file__).resolve().parents[1]


def point(text, stamp='00:00:00', **extra):
    return dict(text=text, evidence_timestamp=stamp, **extra)


def notes_with(*topics):
    return dict(summary=[], decisions=[], tasks=[], open_questions=[], discussion=[dict(topic=name, points=list(points)) for name, points in topics])


def segments():
    return [TranscriptSegment(0, 4, 'Мрежата на склада е стара.', 'Ана'), TranscriptSegment(5, 9, 'Рутерът е от 2015.', 'Борис')]


class DiscussionTests(unittest.TestCase):
    def test_the_schema_and_the_prompt_ask_for_topics_with_points(self):
        schema = minutes_schema()['properties']['discussion']['items']
        self.assertEqual(schema['required'], ['topic', 'points'])
        self.assertEqual(schema['properties']['points']['items']['required'], ['text', 'evidence_timestamp'])
        prompt = llm_prompt('[00:00:00] Да.')
        self.assertIn('discussion: подробностите на срещата по теми', prompt)
        self.assertIn('Всяка тема има кратко име (topic) и 2–8 точки', prompt)
        self.assertIn('Не повтаряй\nрешенията, задачите и въпросите.', prompt)

    def test_validation(self):
        validate_minutes(notes_with(('Мрежа', [point('Стара мрежа'), point('Рутер от 2015', '00:00:05')])), segments())
        old = dict(summary=[], decisions=[], tasks=[], open_questions=[])
        validate_minutes(old)
        self.assertNotIn('discussion', old, 'notes from before the section stay as saved')
        for bad, message in [(notes_with(('', [point('x')])), 'needs a name'),
                             (notes_with(('Мрежа', [point(' ')])), 'need text'),
                             (notes_with(('Мрежа', [point('x', '00:09:99')])), 'does not reference'),
                             (notes_with(('Мрежа', [point('x', quote='q')])), 'need text and a source'),
                             (dict(notes_with(), discussion=[dict(topic='Мрежа')]), 'topic and points')]:
            with self.assertRaisesRegex(ValueError, message):
                validate_minutes(bad, segments())

    def test_markdown_lists_topics_after_the_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            minutes = notes_with(('Мрежа', [point('Стара мрежа')]))
            minutes['summary'] = [point('Обзор')]
            save_minutes(Path(tmp), minutes)
            text = (Path(tmp) / 'minutes.md').read_text()
        self.assertIn('## Резюме\n- Обзор (00:00:00)\n\n## Обсъждане\n\n### Мрежа\n- Стара мрежа (00:00:00)', text)

    def test_a_topic_is_one_change_in_the_review(self):
        saved = notes_with(('Мрежа', [point('Стара мрежа')]), ('Бюджет', [point('Няма бюджет')]))
        validate_minutes(saved)
        newer = notes_with(('мрежа', [point('Стара мрежа'), point('Рутер от 2015')]), ('Бюджет', [point('Няма бюджет')]), ('Зала', [point('Зала 2')]))
        found = notes.changes(saved, newer)
        self.assertEqual(sorted((c['field'], c['kind']) for c in found), [('discussion', 'added'), ('discussion', 'changed')])
        applied = notes.apply(saved, newer, [c['id'] for c in found])
        validate_minutes(applied)
        self.assertEqual([(t['topic'], len(t['points'])) for t in applied['discussion']], [('мрежа', 2), ('Бюджет', 1), ('Зала', 1)])
        self.assertNotIn('review', applied['discussion'][2])
        self.assertEqual(notes.changes(applied, newer), [])
        # Old notes without the section take a new topic as an addition.
        old = dict(summary=[], decisions=[], tasks=[], open_questions=[])
        self.assertEqual([c['kind'] for c in notes.changes(old, newer)], ['added'] * 3)

    def test_consolidation_merges_topics_by_name_without_ai(self):
        first = notes_with(('Мрежа', [point('Стара мрежа')]))
        second = notes_with(('мрежа ', [point('стара  мрежа'), point('Рутер от 2015', '00:00:05')]), ('Бюджет', [point('Няма бюджет')]))
        self.assertEqual([f['field'] for f in candidates([first, second], segments())], [])
        self.assertEqual(merge_topics([first, second]), [dict(topic='Мрежа', points=[point('Стара мрежа'), point('Рутер от 2015', '00:00:05')]),
                                                          dict(topic='Бюджет', points=[point('Няма бюджет')])])
        result, audit = consolidate([first, second], segments(), dict(summarizer='local'), tempfile.mkdtemp(), lambda *_: None)
        self.assertEqual([t['topic'] for t in result['discussion']], ['Мрежа', 'Бюджет'])
        self.assertEqual(audit['requests'], 0)

    def test_spelling_and_speaker_names_reach_the_points(self):
        minutes = notes_with(('PacketFancy', [point('SPEAKER_00: PacketFancy е стар.')]))
        named = notes.name_speakers(minutes, {'SPEAKER_00': 'Ана'})
        self.assertEqual(named['discussion'][0]['points'][0]['text'], 'Ана: PacketFancy е стар.')
        fixed = canonical_notes(named, 'PacketFence | PacketFancy')
        self.assertEqual(fixed['discussion'][0], dict(topic='PacketFence', points=[point('Ана: PacketFence е стар.')]))

    def test_search_finds_a_point_by_its_topic(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            save_transcript(directory, segments())
            (directory / 'minutes.json').write_text(json.dumps(notes_with(('Мрежа', [point('Рутер от 2015', '00:00:05')]))))
            docs = [d for d in search.meeting_docs(dict(title='Среща'), directory) if d.get('field') == 'discussion']
        self.assertEqual(docs, [dict(kind='summary', text='Мрежа: Рутер от 2015', start=5, ref=0, field='discussion')])


class DiscussionEditTests(unittest.TestCase):
    def test_the_editor_saves_the_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = MeetingService(Path(tmp), PROJECT, google=FakeGoogle())
            try:
                meeting = service.library.create('Среща', 'in_person', {})
                save_transcript(service.library.directory(meeting['id']), segments())
                service.edit(meeting['id'], {'minutes': notes_with()})
                before = service.detail(meeting['id'])
                after = [dict(topic='Мрежа', points=[dict(text='Стара мрежа', evidence_timestamp=None, review='verified')])]
                service.edit(meeting['id'], {'minutes_fields': {'discussion': after}, 'minutes_base': {'discussion': []},
                                             'minutes_revision': before['minutes_revision']})
                saved = json.loads((service.library.directory(meeting['id']) / 'minutes.json').read_text())
                self.assertEqual(saved['discussion'], after)
            finally:
                service.close()


if __name__ == '__main__':
    unittest.main()
