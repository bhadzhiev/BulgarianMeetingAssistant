import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import URLError

from app.local_ai import complete_json, validate_base_url, migrate_settings, list_models
from app.processing import summarize
from app.service import MeetingService, DEFAULTS
from app.meeting_automation import generate_title
from meeting_assistant import generate_minutes, TranscriptSegment, validate_minutes

PROJECT = Path(__file__).resolve().parents[1]
NOTES = dict(summary=['Обновяване на сайта'], decisions=['Обновяваме сайта'],
    tasks=[dict(task='Изпрати оферта', owner='Иван', deadline='петък', evidence_timestamp='00:00:00')], open_questions=[])
SCHEMA = {'type': 'object', 'properties': {}}

def response(value):
    return {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(value, ensure_ascii=False)}}]}

class LocalAITests(unittest.TestCase):
    def test_url_validation(self):
        self.assertEqual(validate_base_url('http://localhost:1235/v1/'), 'http://localhost:1235/v1')
        self.assertEqual(validate_base_url('https://host.test/custom/v1'), 'https://host.test/custom/v1')
        for value in ['', 'file:///tmp/a', 'http://user:key@localhost/v1', 'http://localhost/v1?q=x',
                      'http://localhost/v1#x', 'http://localhost:invalid/v1', 'http://localhost/\n',
                      'http://localhost/v1/chat/completions']:
            with self.subTest(value=value), self.assertRaises(ValueError): validate_base_url(value)

    def test_shared_endpoint_model_and_json_modes(self):
        settings=dict(DEFAULTS,local_ai_base_url='http://127.0.0.1:9999/custom/v1/',local_ai_model='chosen-model')
        for mode in ['json_schema','json_object','text']:
            settings['local_ai_format']=mode
            with patch('meeting_assistant.post_json', return_value=response({'ok':True})) as post:
                self.assertEqual(complete_json(settings,[],SCHEMA,'test'), {'ok':True})
                self.assertEqual(post.call_args.args[0], 'http://127.0.0.1:9999/custom/v1/chat/completions')
                payload=post.call_args.args[1]
                self.assertEqual(payload['model'],'chosen-model')
                self.assertEqual(payload['max_tokens'],4096)
                self.assertNotIn('headers',post.call_args.kwargs)  # Never send the cloud key locally.
                self.assertEqual('response_format' in payload, mode!='text')
                if mode!='text':self.assertEqual(payload['response_format']['type'],mode)

    def test_reasoning_and_output_limits_are_shared(self):
        for effort in ['default','none','low','medium','high']:
            settings=dict(DEFAULTS,local_ai_reasoning=effort,local_ai_max_tokens=8192)
            with patch('meeting_assistant.post_json',return_value=response({'ok':True})) as post:
                complete_json(settings,[],SCHEMA,'test')
                payload=post.call_args.args[1]
                self.assertEqual(payload['max_tokens'],8192)
                if effort=='default':self.assertNotIn('reasoning_effort',payload)
                else:self.assertEqual(payload['reasoning_effort'],effort)
        for limit in [True,0,127,32769,'4096']:
            with self.assertRaises(ValueError):complete_json(dict(DEFAULTS,local_ai_max_tokens=limit),[],SCHEMA,'test')

    def test_failures_do_not_fall_back_to_cloud(self):
        with patch('meeting_assistant.post_json',side_effect=URLError('offline')) as post:
            with self.assertRaisesRegex(ValueError,'No cloud fallback'):complete_json(DEFAULTS,[],SCHEMA,'test')
            self.assertEqual(post.call_count,1)

    def test_invalid_empty_and_truncated_responses_are_rejected(self):
        for value in [{}, {'choices':[]}, response([]), response('not json'),
                      {'choices':[{'finish_reason':'length','message':{'content':'{}'}}]},
                      {'choices':[{'message':{'content':''}}]}]:
            with self.subTest(value=value),patch('meeting_assistant.post_json',return_value=value):
                with self.assertRaises(ValueError):complete_json(DEFAULTS,[],SCHEMA,'test')

    def test_notes_and_tasks_use_shared_client(self):
        settings=dict(DEFAULTS,summarizer='local',local_ai_model='same-model')
        segments=[TranscriptSegment(0,10,'Иван ще изпрати оферта до петък.')]
        with patch('meeting_assistant.post_json',return_value=response(NOTES)) as post:
            result=generate_minutes(SimpleNamespace(**settings),segments)
            validate_minutes(result,segments)
            self.assertEqual(result['tasks'][0]['owner'],'Иван')
            self.assertEqual(post.call_args.args[1]['model'],'same-model')
            schema=post.call_args.args[1]['response_format']['json_schema']['schema']
            self.assertEqual(schema['properties']['tasks']['items']['properties']['evidence_timestamp']['enum'],['00:00:00'])

    def test_saved_notes_and_title_share_configuration(self):
        settings=dict(DEFAULTS,summarizer='local',local_ai_base_url='http://localhost:9999/v1',local_ai_model='shared')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'transcript.json').write_text(json.dumps([dict(start=0,end=10,text='Иван ще изпрати оферта до петък.',speaker=None)]))
            with patch('meeting_assistant.post_json',return_value=response(NOTES)) as post:
                summarize(root,settings,lambda message:None,'cloud-secret')
                self.assertEqual(json.loads((root/'minutes.json').read_text())['tasks'],[dict(t,due_date=None,status='open',review='ai') for t in NOTES['tasks']])
                self.assertEqual(post.call_args.args[0],'http://localhost:9999/v1/chat/completions')
                self.assertEqual(post.call_args.args[1]['model'],'shared')
            with patch('meeting_assistant.post_json',return_value=response({'title':'Оферта за новия сайт'})) as post:
                self.assertEqual(generate_title(root,settings,'cloud-secret')[0],'Оферта за новия сайт')
                self.assertEqual(post.call_args.args[1]['model'],'shared')
                self.assertNotIn('cloud-secret',str(post.call_args))

    def test_old_providers_migrate_and_config_persists(self):
        self.assertEqual(migrate_settings({'summarizer':'ollama','title_provider':'ollama'}),
                         {'summarizer':'local','title_provider':'local'})
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'settings.json').write_text(json.dumps({'summarizer':'ollama','title_provider':'ollama'}))
            service=MeetingService(root,PROJECT)
            try:
                self.assertEqual(service.settings['summarizer'],'local')
                service.save_settings({'local_ai_base_url':'http://localhost:9999/v1/','local_ai_model':'other'})
                saved=json.loads((root/'settings.json').read_text())
                self.assertEqual(saved['local_ai_base_url'],'http://localhost:9999/v1')
                self.assertEqual(saved['local_ai_model'],'other')
                for invalid in ['bogus',None]:
                    with self.assertRaises(ValueError):service.save_settings({'local_ai_format':invalid})
            finally:service.close()

    def test_model_discovery_preserves_ids(self):
        with patch('app.local_ai.urlopen') as request:
            request.return_value.__enter__.return_value.read.return_value=json.dumps({'data':[{'id':'chat-model'},{'id':'chat-model'},{'id':'embedding-model'},{}]}).encode()
            self.assertEqual(list_models('http://localhost:1235/v1'),['chat-model','embedding-model'])
            self.assertEqual(request.call_args.args[0],'http://localhost:1235/v1/models')
