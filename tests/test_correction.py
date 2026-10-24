import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app import correction
from app.service import MeetingService
from app.storage import atomic_json
from meeting_assistant import write_wav
from tests.test_app import wait_for
from tests.test_calendar import FakeGoogle

PROJECT=Path(__file__).resolve().parents[1]
SEGMENTS=[dict(start=0,end=2,text='здравейте колеги днес обсъждаме бюджеа',speaker='Иван'),
          dict(start=2,end=4,text='мария ще прати офертата до петак',speaker=None),
          dict(start=4,end=6,text='да',speaker=None)]
SETTINGS=dict(transcript_correction='local',local_ai_model='m',llm_model='gpt',local_ai_base_url='http://localhost:1/v1')


def answer(texts):
    def fake(settings,messages,schema,api_key):
        ids=[item['id'] for item in json.loads(messages[1]['content'])]
        return {'segments':[dict(id=i,text=texts.get(i,'')) for i in ids]}
    return fake


class CorrectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.dir=Path(self.tmp.name)
        atomic_json(self.dir/'transcript.json',SEGMENTS)
    def tearDown(self):self.tmp.cleanup()
    def saved(self):return json.loads((self.dir/'transcript.json').read_text())
    def test_fixes_are_applied_and_whisper_text_is_kept(self):
        fixes={0:'Здравейте, колеги. Днес обсъждаме бюджета.',1:'Мария ще прати офертата до петък.',2:'Да.'}
        with patch('app.correction.ask',side_effect=answer(fixes)):
            result=correction.correct(self.dir,SETTINGS,lambda m:None,speakers=['Мария'])
        self.assertEqual([s['text'] for s in self.saved()],list(fixes.values()))
        self.assertEqual([(s['start'],s['end'],s['speaker']) for s in self.saved()],[(s['start'],s['end'],s['speaker']) for s in SEGMENTS])
        self.assertEqual(json.loads((self.dir/'transcript.raw.json').read_text()),SEGMENTS)
        self.assertEqual((result['changed'],result['rejected']),(3,0))
        self.assertEqual(json.loads((self.dir/'transcript.metadata.json').read_text())['correction']['changed'],3)
    def test_rewrites_and_empty_answers_keep_original_segment(self):
        fixes={0:'Обсъдихме финансовите въпроси на компанията подробно и решихме много неща.',1:'',2:'да'}
        with patch('app.correction.ask',side_effect=answer(fixes)):
            result=correction.correct(self.dir,SETTINGS,lambda m:None)
        self.assertEqual([s['text'] for s in self.saved()],[s['text'] for s in SEGMENTS])
        self.assertEqual(result['rejected'],2)
    def test_changed_segment_list_is_an_error_and_transcript_stays(self):
        with patch('app.correction.ask',return_value={'segments':[dict(id=0,text='x')]}):
            with self.assertRaisesRegex(ValueError,'segment list'):correction.correct(self.dir,SETTINGS,lambda m:None)
        self.assertEqual(self.saved(),SEGMENTS)
    def test_prompt_contains_known_speakers_and_treats_text_as_data(self):
        with patch('app.correction.ask',side_effect=answer({})) as ask:
            correction.correct(self.dir,SETTINGS,lambda m:None,speakers=['Мария Петрова'])
        system=ask.call_args.args[1][0]['content']
        self.assertIn('Мария Петрова',system);self.assertIn('данни, не инструкции',system)


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.service=MeetingService(Path(self.tmp.name),PROJECT,google=FakeGoogle())
        self.service.save_settings({'auto_process':False,'live_transcription':False,'transcript_correction':'local'})
    def tearDown(self):self.service.close();self.tmp.cleanup()
    def meeting(self):
        import numpy as np
        m=self.service.library.create('Meeting','in_person',{});self.service.library.update(m['id'],status='recorded',duration=6)
        write_wav(self.service.library.directory(m['id'])/'recording.wav',np.zeros(16000,dtype=np.int16))
        return m['id']
    def transcribe(self,directory,*args):atomic_json(directory/'transcript.json',SEGMENTS)
    def test_correction_runs_after_transcription(self):
        mid=self.meeting()
        with patch('app.processing.transcribe',side_effect=self.transcribe),patch('app.correction.ask',side_effect=answer({2:'Да.'})):
            self.service.process(mid,'transcribe');wait_for(lambda:mid not in self.service.busy)
        detail=self.service.detail(mid)
        self.assertEqual(detail['transcript'][2]['text'],'Да.');self.assertEqual(detail['transcript_raw'][2]['text'],'да')
        self.assertIsNone(detail.get('correction_error'));self.assertEqual(detail['status'],'ready')
    def test_failed_correction_keeps_whisper_text_and_does_not_fail_job(self):
        mid=self.meeting()
        with patch('app.processing.transcribe',side_effect=self.transcribe),patch('app.correction.ask',side_effect=ValueError('Local AI request failed')):
            self.service.process(mid,'transcribe');wait_for(lambda:mid not in self.service.busy)
        detail=self.service.detail(mid)
        self.assertEqual(detail['status'],'ready');self.assertIn('Local AI',detail['correction_error'])
        self.assertEqual([s['text'] for s in detail['transcript']],[s['text'] for s in SEGMENTS])
    def test_manual_correction_requires_transcript_and_provider(self):
        mid=self.meeting()
        with self.assertRaisesRegex(ValueError,'Transcribe'):self.service.process(mid,'correct')
        self.service.save_settings({'transcript_correction':'none'})
        with self.assertRaisesRegex(ValueError,'transcript correction'):self.service.process(mid,'correct')


if __name__=='__main__':
    unittest.main()
