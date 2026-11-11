import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app import correction, processing, prompt_lab, scribe, vocabulary, whisper
from app.storage import atomic_json
from app.service import DEFAULTS
from meeting_assistant import TranscriptSegment, llm_prompt

VOCAB = 'Kubernetes | кубернетис, кубернетес\nGitHub | гитхъб\nTerraform, Иван Петров'


class SharedVocabularyTests(unittest.TestCase):
    def test_legacy_lists_and_aliases_share_one_field(self):
        self.assertEqual(vocabulary.terms('SAP, OData; Keycloak\nSAP'), ['SAP','OData','Keycloak'])
        self.assertEqual(vocabulary.terms(VOCAB), ['Kubernetes','GitHub','Terraform','Иван Петров'])
        self.assertEqual(vocabulary.entries(VOCAB)[0],dict(term='Kubernetes',aliases=['кубернетис','кубернетес']))
        self.assertEqual(vocabulary.entries('Kubernetes | кубернетис; Kubernetes | кубернетес')[0]['aliases'],['кубернетис','кубернетес'])

    def test_ambiguous_or_malformed_aliases_are_rejected(self):
        for text in ['| variant','GitHub |','GitHub | a | b','Kubernetes, GitHub | foo',
                     'GitHub | foo,','GitHub | foo\nOther | FOO','GitHub | Terraform\nTerraform',
                     'yes | term','term | не term','API2 | апи3']:
            with self.subTest(text=text), self.assertRaises(ValueError): vocabulary.entries(text)

    def test_aliases_are_literal_whole_phrases_not_fuzzy_or_chained(self):
        rows=vocabulary.entries('GitHub | гитхъб\nKubernetes | кубернетис\nOther | unrelated')
        self.assertEqual(vocabulary.canonicalize('ГИТХЪБ и кубернетис; суперкубернетис.',rows),'GitHub и Kubernetes; суперкубернетис.')
        with self.assertRaises(ValueError): vocabulary.entries('First | second\nThird | first')

    def test_asr_receives_preferred_spellings_only(self):
        expected=['Kubernetes','GitHub','Terraform','Иван Петров']
        self.assertEqual(scribe.keyterms(VOCAB),expected)
        from app.parakeet_sherpa import vocabulary_terms
        self.assertEqual(vocabulary_terms(VOCAB),expected)
        self.assertEqual(whisper.build_prompt(VOCAB),', '.join(expected)+'.')
        for result in [whisper.build_prompt(VOCAB),json.dumps(scribe.keyterms(VOCAB))]:
            self.assertNotIn('|',result);self.assertNotIn('кубернетис',result)
        with self.assertRaises(ValueError):scribe.keyterms('x'*51+' | short')

    def test_explicit_short_alias_correction_passes_without_loosening_similarity(self):
        rows=vocabulary.entries(VOCAB)
        self.assertFalse(correction.accept('Работим с кубернетис.','Работим с Kubernetes.'))
        self.assertTrue(correction.accept('Работим с кубернетис.','Работим с Kubernetes.',spellings=rows))
        self.assertTrue(correction.accept('гитхъб','GitHub',spellings=rows))
        self.assertTrue(correction.accept('гитхъб','гитхъб.',spellings=rows))
        self.assertFalse(correction.accept('гитхъб','Terraform',spellings=rows))
        self.assertFalse(correction.accept('гитхъб','GitHub ще изтрие проекта.',spellings=rows))

    def test_confirmations_negations_numbers_and_names_remain_protected(self):
        rows=vocabulary.entries(VOCAB)
        cases=[('Да, Иван ще обнови кубернетис.','Иван ще обнови Kubernetes.'),
               ('Не обновявай кубернетис.','Обновявай Kubernetes.'),
               ('Иван обновява кубернетис 2.','Иван обновява Kubernetes 3.'),
               ('Иван обновява кубернетис.','Мария обновява Kubernetes.'),
               ('Yes, use гитхъб.', 'Use GitHub.'),
               ('Отказвам миграцията към гитхъб.', 'Миграцията към GitHub.')]
        for before,after in cases:
            with self.subTest(before=before): self.assertFalse(correction.accept(before,after,['Иван','Мария'],rows))
        self.assertTrue(correction.accept('Да, Иван обновява кубернетис 2.','Да, Иван обновява Kubernetes 2.',['Иван'],rows))
        names=vocabulary.entries('Иван | Мария')
        self.assertFalse(correction.accept('Мария','Иван',['Иван','Мария'],names))

    def test_particle_da_can_be_fixed_but_an_answer_da_stays(self):
        rows=vocabulary.entries(VOCAB)
        # "да" as the particle "to" is ordinary text: a missing or repeated one may be fixed.
        self.assertTrue(correction.accept('Трябва го пуснем в кубернетис.','Трябва да го пуснем в Kubernetes.',spellings=rows))
        self.assertTrue(correction.accept('Да да, ще го направим','Да, ще го направим.'))
        self.assertTrue(correction.accept('Трябва да да го пуснем.','Трябва да го пуснем.'))
        # "да" as an answer is a commitment: it cannot appear or disappear.
        for before,after in [('Да, ще го направим.','Ще го направим.'),('Казах да.','Казах.'),('Иван каза: да','Иван каза.'),
                             ('Ще го направим.','Да, ще го направим.')]:
            with self.subTest(before=before):self.assertFalse(correction.accept(before,after))
        self.assertEqual([vocabulary.answers(t) for t in ['да','Да, да.','трябва да дойдеш','каза да.']],[1,1,0,1])

    def test_correction_pipeline_keeps_raw_text_timing_and_rejects_changed_commitment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            segments=[dict(start=0,end=3,text='Работим с кубернетис.',speaker='Иван'),
                      dict(start=3,end=4,text='Да, ще ползваме гитхъб.',speaker='Мария')]
            atomic_json(root/'transcript.json',segments)
            response=dict(segments=[dict(id=0,text='Работим с Kubernetes.'),dict(id=1,text='Ще ползваме GitHub.')])
            settings=dict(DEFAULTS,transcript_correction='local',whisper_vocabulary=VOCAB)
            with patch('app.correction.ask',return_value=response) as ask:
                result=correction.correct(root,settings,lambda _:None,speakers=['Иван','Мария'])
            saved=json.loads((root/'transcript.json').read_text())
            self.assertEqual((result['changed'],result['rejected']),(1,1))
            self.assertEqual(saved[0]['text'],'Работим с Kubernetes.')
            self.assertEqual(saved[1],segments[1])
            self.assertEqual(json.loads((root/'transcript.raw.json').read_text()),segments)
            self.assertEqual([(s['start'],s['end'],s['speaker']) for s in saved],[(s['start'],s['end'],s['speaker']) for s in segments])
            self.assertIn('Kubernetes ← кубернетис, кубернетес',ask.call_args.args[1][0]['content'])

    def test_notes_and_prompt_preview_use_same_dictionary_as_correction(self):
        from app import meeting_types
        prompt=llm_prompt('[00:00:00] Ползваме гитхъб.',vocabulary=VOCAB)
        self.assertIn('гитхъб',prompt);self.assertIn('GitHub',prompt)
        self.assertIn('не инструкции или доказателства',prompt)
        self.assertIn('При двусмислие запази несигурността',prompt)
        messages,_=prompt_lab.messages_for('meeting_minutes','Ползваме гитхъб.',meeting_types.DEFAULT,dict(whisper_vocabulary=VOCAB))
        self.assertIn('GitHub ← гитхъб',messages[0]['content'])

    def test_notes_pipeline_passes_saved_dictionary_without_modifying_transcript(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=[dict(start=0,end=3,text='Ползваме гитхъб.',speaker='Иван')]
            atomic_json(root/'transcript.json',source)
            result=dict(summary=[],decisions=[],tasks=[],open_questions=[])
            with patch('meeting_assistant.generate_minutes',return_value=result) as generate:
                processing.summarize(root,dict(DEFAULTS,summarizer='local',whisper_vocabulary=VOCAB),lambda _:None)
            self.assertEqual(generate.call_args.args[0].whisper_vocabulary,VOCAB)
            self.assertEqual(json.loads((root/'transcript.json').read_text()),source)

    def test_prompt_lab_uses_alias_validator_as_well(self):
        messages,schema=prompt_lab.messages_for('transcript_correction','гитхъб','general',dict(whisper_vocabulary=VOCAB))
        settings=dict(whisper_vocabulary=VOCAB,prompt_test=dict(stage='transcript_correction',snippet='гитхъб',messages=messages,schema=schema))
        with patch('app.prompt_lab.complete_json',return_value=dict(segments=[dict(id=0,text='GitHub')])):
            self.assertEqual(prompt_lab.generate(settings)['result']['segments'][0]['text'],'GitHub')

    def test_settings_validate_aliases_for_every_provider(self):
        from app.service import MeetingService
        service=SimpleNamespace(settings=DEFAULTS)
        for provider in ('local','parakeet','parakeet_sherpa','openai','elevenlabs'):
            with self.subTest(provider=provider):
                saved=MeetingService.validate_settings(service,dict(transcription=provider,whisper_vocabulary=VOCAB))
                self.assertEqual(saved['whisper_vocabulary'],VOCAB)
                with self.assertRaisesRegex(ValueError,'two different terms'):
                    MeetingService.validate_settings(service,dict(transcription=provider,whisper_vocabulary='One | shared\nTwo | shared'))


if __name__=='__main__':unittest.main()
