import tempfile
import unittest
from pathlib import Path

from app import vocabulary
from app.service import MeetingService
from tests.test_calendar import FakeGoogle

PROJECT = Path(__file__).resolve().parents[1]


class VocabularyTermsTests(unittest.TestCase):
    def test_known_terms_are_added_once_and_invalid_ones_skipped(self):
        text = vocabulary.with_terms('PaperCut\nKubernetes | кубернетис', ['Мария Петрова', 'kubernetes', 'кубернетис', 'Atlas',
                                                                          'a' * 60, 'x<y', 'one two three four five six', 'example.org'])
        self.assertEqual(text, 'PaperCut\nKubernetes | кубернетис\nМария Петрова\nAtlas\nexample.org')
        self.assertEqual(vocabulary.with_terms('', ['Atlas']), 'Atlas')
        self.assertEqual(vocabulary.with_terms('Atlas', []), 'Atlas')

    def test_a_short_correction_suggests_the_term_and_what_was_heard(self):
        s = vocabulary.suggestions
        self.assertEqual(s('репо MCP Ex Am Pull.', 'репо MCP example.org.'), [dict(term='example.org', variant='Ex Am Pull')])
        self.assertEqual(s('чекове в синга (time)', 'чекове в Icinga (time)'), [dict(term='Icinga', variant='синга')])
        self.assertEqual(s('потребител в Atlas.', 'потребител в ATLAS.'), [dict(term='ATLAS', variant=None)])

    def test_rewrites_placeholders_and_known_corrections_suggest_nothing(self):
        s = vocabulary.suggestions
        self.assertEqual(s('Прекарване на кабела до AP.', 'Във връзка с монтажа на нова точка трябва да се прекара кабел от лабораторията до мястото'), [])
        self.assertEqual(s('SPEAKER_00 да говори с Петров', 'Мария да говори с Петров'), [])
        self.assertEqual(s('тест със server team', 'тест със team'), [])
        self.assertEqual(s('репо Ex Am Pull', 'репо example.org', 'example.org | Ex Am Pull'), [])
        self.assertEqual(s('сървър 1', 'сървър 2'), [])

    def test_add_a_term_or_a_variant(self):
        self.assertEqual(vocabulary.add('PaperCut', 'example.org', 'Ex Am Pull'), 'PaperCut\nexample.org | Ex Am Pull')
        self.assertEqual(vocabulary.add('example.org | ex am pull', 'example.org', 'Екз Ам'), 'example.org | ex am pull, Екз Ам')
        self.assertEqual(vocabulary.add('example.org | ex am pull', 'example.org', 'ex am pull'), 'example.org | ex am pull')
        self.assertEqual(vocabulary.add('PaperCut', 'ATLAS'), 'PaperCut\nATLAS')
        with self.assertRaises(ValueError):
            vocabulary.add('PaperCut', '')


class ServiceVocabularyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.s = MeetingService(Path(self.tmp.name), PROJECT, google=FakeGoogle());self.addCleanup(self.s.close)
        self.s.save_person(dict(name='Мария Петрова', aliases=['Мими']))

    def test_people_and_projects_go_to_the_processing_vocabulary(self):
        self.s.create_project('Atlas')
        settings = self.s._with_known_terms(dict(self.s.settings, whisper_vocabulary='PaperCut'))
        self.assertEqual(settings['whisper_vocabulary'].split('\n'), ['PaperCut', 'Мария Петрова', 'Мими', 'Atlas'])
        self.assertEqual(self.s.settings['whisper_vocabulary'], '')

    def test_a_text_correction_returns_suggestions_and_add_saves_them(self):
        item = self.s.create_task(dict(text='Да създаде репо Ex Am Pull', request_id='a' * 32))
        saved = self.s.update_item(item['id'], item['text'], dict(text='Да създаде репо example.org'), item['revision'])
        self.assertEqual(saved['vocabulary_suggestions'], [dict(term='example.org', variant='Ex Am Pull')])
        self.assertNotIn('vocabulary_suggestions', self.s.items.items[item['id']])
        self.s.add_vocabulary(dict(term='example.org', variant='Ex Am Pull'))
        self.assertEqual(self.s.settings['whisper_vocabulary'], 'example.org | Ex Am Pull')
        # A name that Atlanta knows needs no offer.
        other = self.s.create_task(dict(text='Задача за мими', request_id='b' * 32))
        other = self.s.items.items[other['id']]
        again = self.s.update_item(other['id'], other['text'], dict(text='Задача за Мими'), other['revision'])
        self.assertEqual(again['vocabulary_suggestions'], [])


if __name__ == '__main__':
    unittest.main()
