"""One built-in source per AI stage, a stated output language, and name fixes in transcript correction."""
import tempfile
import unittest
from pathlib import Path

from app import correction, followup_email, notes_consolidation, task_matching
from app.prompts import POLICY, STAGES, Prompts, apply


class StageDescriptionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.prompts = Prompts(Path(self.tmp.name) / 'ai-prompts.json')
        self.messages = [dict(role='system', content='Built-in prompt'), dict(role='user', content='source')]

    def test_without_a_layer_only_the_built_in_prompt_goes(self):
        sent = apply(dict(_prompt_snapshot=self.prompts.snapshot()), self.messages, 'task_draft')
        self.assertEqual(sent, self.messages)

    def test_a_layer_adds_only_its_own_text_and_the_policy(self):
        self.prompts.save('task_draft', 'global', 'Пиши кратко.', 0)
        snapshot = self.prompts.snapshot()
        self.assertEqual(snapshot['stages']['task_draft']['effective'], 'Пиши кратко.')
        sent = str(apply(dict(_prompt_snapshot=snapshot), self.messages, 'task_draft'))
        self.assertIn('Пиши кратко.', sent)
        self.assertIn(POLICY, sent)
        # The description of the stage is for the editor. It is not a second built-in prompt.
        self.assertNotIn(STAGES['task_draft'][1], sent)

    def test_the_follow_up_description_does_not_ask_for_fixed_sections(self):
        self.assertIn('Пропусни секция, за която няма данни', STAGES['followup_email'][1])
        self.assertNotIn('Следващи стъпки', STAGES['followup_email'][1])


class OutputLanguageTests(unittest.TestCase):
    def test_every_free_text_answer_has_a_language(self):
        self.assertIn('Write each summary text in Bulgarian', notes_consolidation.SYSTEM)
        self.assertIn('Write the subject and the body in Bulgarian', followup_email.SYSTEM)
        self.assertIn('reason: one short sentence in Bulgarian. update_text: in Bulgarian', task_matching.SYSTEM)


class NameCorrectionTests(unittest.TestCase):
    NAMES = ['Мария Петрова', 'Иван Иванов', 'Иван']

    def test_a_misspelled_name_may_become_the_name(self):
        self.assertTrue(correction.accept('Говорих с Мариа Петрова днес.', 'Говорих с Мария Петрова днес.', self.NAMES))

    def test_one_person_never_becomes_another(self):
        self.assertFalse(correction.accept('Говорих с Мария Петрова днес.', 'Говорих с Иван Иванов днес.', self.NAMES))

    def test_a_name_never_goes_away_or_comes_from_nowhere(self):
        self.assertFalse(correction.accept('Говорих с Мария Петрова днес.', 'Говорих с колегата днес.', self.NAMES))
        self.assertFalse(correction.accept('Говорих с колегата днес.', 'Говорих с Мария Петрова днес.', self.NAMES))

    def test_a_short_name_keeps_its_grammatical_form(self):
        # "Иване" is the correct form for a direct address, not a misspelling of "Иван".
        self.assertFalse(correction.accept('Иване, ела.', 'Иван, ела.', self.NAMES))

    def test_near_names_counts_each_place_once(self):
        self.assertEqual(correction.near_names('Мариа Петрова и Мария Петрова', 'Мария Петрова'), 2)
        self.assertEqual(correction.near_names('Мария', 'Мария Петрова'), 0)


if __name__ == '__main__':
    unittest.main()
