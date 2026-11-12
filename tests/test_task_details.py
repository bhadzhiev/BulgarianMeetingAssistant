"""A task from meeting notes is a short title and a description (details) that a person can edit."""
import tempfile
import unittest
from pathlib import Path

import meeting_assistant as ma
from app.items import Registry
from app.notes import apply, changes


def notes(**task):
    return dict(summary=[], decisions=[], open_questions=[], tasks=[dict(dict(task='Мария да провери бекъпа', owner='Мария',
                deadline=None, evidence_timestamp='00:00:01'), **task)])


class TaskDetailsTests(unittest.TestCase):
    def test_schema_and_prompt_ask_for_a_description(self):
        task = ma.minutes_schema()['properties']['tasks']['items']
        self.assertEqual(task['properties']['details'], {'type': ['string', 'null']})
        self.assertIn('details', task['required'])
        prompt = ma.llm_prompt('[00:00:01] Мария: ще проверя бекъпа на сървъра до петък.')
        self.assertIn('details: описание на задачата в 1–4 кратки изречения', prompt)

    def test_validation_accepts_text_or_null_and_old_notes_without_it(self):
        for value in ('Пълен бекъп на базата и проверка на възстановяването.', None):
            ma.validate_minutes(notes(details=value))
        old = notes()
        ma.validate_minutes(old)
        self.assertNotIn('details', old['tasks'][0])
        with self.assertRaises(ValueError):
            ma.validate_minutes(notes(details=['списък']))

    def test_new_item_keeps_the_description_and_a_notes_edit_follows(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = Registry(Path(directory) / 'items.json')
            minutes = notes(details='Пълен бекъп на базата.')
            registry.sync('m1', minutes)
            item = registry.items[minutes['tasks'][0]['item_id']]
            self.assertEqual((item['text'], item['details']), ('Мария да провери бекъпа', 'Пълен бекъп на базата.'))
            minutes['tasks'][0]['details'] = 'Пълен бекъп и тест на възстановяването.'
            registry.sync('m1', minutes)
            self.assertEqual(item['details'], 'Пълен бекъп и тест на възстановяването.')
            self.assertIn('details', item['manual'])

    def test_update_notes_offers_a_new_description_and_never_clears_it(self):
        current, proposed = notes(), notes(details='Пълен бекъп на базата.')
        found = changes(current, proposed)
        self.assertEqual([(c['kind'], c['field']) for c in found], [('changed', 'tasks')])
        self.assertEqual(apply(current, proposed, {found[0]['id']})['tasks'][0]['details'], 'Пълен бекъп на базата.')
        self.assertEqual(apply(current, proposed, set())['tasks'][0].get('details'), None)
        self.assertEqual(changes(proposed, notes()), [])

    def test_markdown_shows_the_description_after_the_title(self):
        with tempfile.TemporaryDirectory() as directory:
            minutes = notes(details='Пълен бекъп на базата.')
            ma.validate_minutes(minutes)
            ma.save_minutes(Path(directory), minutes)
            self.assertIn('| Мария да провери бекъпа — Пълен бекъп на базата. |', (Path(directory) / 'minutes.md').read_text())


if __name__ == '__main__':
    unittest.main()
