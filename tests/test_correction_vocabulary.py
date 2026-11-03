import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from app import correction
from app.storage import atomic_json

class VocabularyCorrectionTests(unittest.TestCase):
    def run_correction(self,original,corrected,provider='local'):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);segments=[dict(start=0,end=3,text=original,speaker='Иван')];atomic_json(root/'transcript.json',segments)
            settings=dict(transcript_correction=provider,whisper_vocabulary='Kubernetes, Terraform; Keycloak\nИван Петров',local_ai_model='test',llm_model='test')
            with patch('app.correction.ask',return_value={'segments':[dict(id=0,text=corrected)]}) as ask:
                result=correction.correct(root,settings,lambda _:None,speakers=['Иван Петров'])
            system=ask.call_args.args[1][0]['content']
            saved=json.loads((root/'transcript.json').read_text());raw=json.loads((root/'transcript.raw.json').read_text())
            return result,system,saved,raw
    def test_local_and_cloud_correction_receive_bulgarian_technical_context_and_dictionary(self):
        for provider in ('local','openai'):
            with self.subTest(provider=provider):
                _,system,_,_=self.run_correction('Проверяваме Kubernetes.','Проверяваме Kubernetes.',provider)
                for expected in ['българска реч','компютърни термини','Kubernetes','Terraform','Keycloak','Иван Петров','справочни данни','не превеждай']:
                    self.assertIn(expected,system)
    def test_existing_technical_spelling_cannot_be_transliterated_away(self):
        result,_,saved,_=self.run_correction('Проверяваме Kubernetes deployment днес.','Проверяваме кубернетис deployment днес.')
        self.assertEqual(result['rejected'],1);self.assertIn('Kubernetes',saved[0]['text'])
    def test_supported_phonetic_term_can_be_corrected_with_original_and_timing_preserved(self):
        original='Проверяваме кубернетис deployment днес.';corrected='Проверяваме Kubernetes deployment днес.'
        result,_,saved,raw=self.run_correction(original,corrected)
        self.assertEqual(result['changed'],1);self.assertEqual(saved[0]['text'],corrected);self.assertEqual(raw[0]['text'],original)
        self.assertEqual((saved[0]['start'],saved[0]['end'],saved[0]['speaker']),(0,3,'Иван'))
