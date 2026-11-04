import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import wave

from app import processing, scribe
from app.service import MeetingService, DEFAULTS
from tests.test_app import wait_for

PROJECT = Path(__file__).resolve().parents[1]


def response(text='Проверихме Kubernetes.', start=0, end=.7):
    return dict(text=text, words=[dict(type='word', text=text, start=start, end=end)])


def recording(path, seconds=2):
    with wave.open(str(path/'recording.wav'), 'wb') as wav:
        wav.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        wav.writeframes(b'\0\0' * 16000 * seconds)


class ScribeTests(unittest.TestCase):
    def test_request_uses_scribe_repeated_keyterms_and_auto_language(self):
        with patch('app.scribe.urllib.request.urlopen') as upload:
            upload.return_value.__enter__.return_value = io.StringIO(json.dumps(response()))
            units = scribe.transcribe(b'audio', 'synthetic-key', ['SAP', 'Transit Gateway'], 60, 62)
        request = upload.call_args.args[0]
        self.assertEqual(request.full_url, scribe.ENDPOINT)
        self.assertEqual(request.get_header('Xi-api-key'), 'synthetic-key')
        self.assertEqual(request.data.count(b'name="keyterms"'), 2)
        self.assertIn(b'scribe_v2', request.data)
        self.assertNotIn(b'language_code', request.data)
        self.assertEqual((units[0]['start'], units[0]['end']), (60, 60.7))

    def test_errors_do_not_expose_provider_body_or_key(self):
        error = urllib.error.HTTPError(scribe.ENDPOINT, 401, 'synthetic-key', {}, io.BytesIO(b'synthetic-key'))
        with patch('app.scribe.urllib.request.urlopen', side_effect=error), self.assertRaisesRegex(ValueError, 'Check the ElevenLabs API key') as caught:
            scribe.transcribe(b'audio', 'synthetic-key', [], 0, 2)
        self.assertNotIn('synthetic-key', str(caught.exception))

    def test_invalid_words_are_rejected(self):
        for data in [None, {}, dict(text='speech', words=[]), response(start=-1), response(end=float('nan')), response(end=3), response(start=True)]:
            with self.subTest(data=data), self.assertRaises(ValueError):
                scribe.word_units(data, 0, 2)
        self.assertEqual(scribe.word_units(dict(text='', words=[]), 0, 2), [])

    def test_keyterms_validation(self):
        self.assertEqual(scribe.keyterms('SAP, OData\nSAP'), ['SAP', 'OData'])
        for text in ['x'*51, 'a b c d e f', '[term]', 'a\\b']:
            with self.assertRaises(ValueError):
                scribe.keyterms(text)

    def test_pipeline_preserves_words_and_original_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp); recording(path, 62)
            original = (path/'recording.wav').read_bytes()
            def upload(audio, key, terms, offset, end):
                self.assertEqual(key, 'scribe-key')
                self.assertEqual(terms, ['Kubernetes'])
                return scribe.word_units(response(), offset, end)
            with patch('app.scribe.transcribe', side_effect=upload) as call:
                processing.transcribe(path, dict(DEFAULTS, transcription='elevenlabs', whisper_vocabulary='Kubernetes'), lambda _:None, 'scribe-key')
            self.assertEqual(call.call_count, 2)
            units = json.loads((path/'transcript.alignment.json').read_text())['units']
            self.assertGreater(units[1]['start'], 50)
            self.assertEqual(json.loads((path/'transcript.metadata.json').read_text())['model'], 'scribe_v2')
            self.assertEqual((path/'recording.wav').read_bytes(), original)
            self.assertNotIn('scribe-key', ''.join(p.read_text() for p in path.glob('*.json')))

    def test_failed_request_resumes_without_reuploading_completed_chunk(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp); recording(path, 62)
            settings=dict(DEFAULTS, transcription='elevenlabs')
            def first(audio,key,terms,offset,end):
                if offset:raise ValueError('offline')
                return scribe.word_units(response(),offset,end)
            with patch('app.scribe.transcribe',side_effect=first), self.assertRaisesRegex(ValueError,'offline'):
                processing.transcribe(path,settings,lambda _:None,'key')
            with patch('app.scribe.transcribe',side_effect=lambda a,k,t,o,e:scribe.word_units(response(),o,e)) as upload:
                processing.transcribe(path,settings,lambda _:None,'key')
            self.assertEqual(upload.call_count,1)
            self.assertGreater(upload.call_args.args[3],50)

    def test_service_keeps_separate_keys_out_of_settings_and_checks_readiness(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict('os.environ', {'ELEVENLABS_API_KEY':''}):
            service=MeetingService(Path(tmp),PROJECT)
            try:
                service.save_settings(dict(transcription='elevenlabs', api_key='openai-key',elevenlabs_api_key='scribe-key',auto_title=False,transcript_correction='none'))
                self.assertTrue(service.readiness()['model']['ready'])
                self.assertNotIn('scribe-key',service.settings_path.read_text())
                self.assertEqual(service.api_key,'openai-key')
                service.save_settings(dict(elevenlabs_api_key=''))
                self.assertFalse(service.readiness()['model']['ready'])
                meeting=service.library.create('Synthetic','in_person',dict(service.settings))
                with self.assertRaisesRegex(ValueError,'ElevenLabs API key'):
                    service.process(meeting['id'],'transcribe')
            finally:service.close()

    def test_service_routes_only_transcription_to_elevenlabs_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            service=MeetingService(Path(tmp),PROJECT)
            try:
                service.save_settings(dict(transcription='elevenlabs',api_key='openai-key',elevenlabs_api_key='scribe-key',auto_title=False,transcript_correction='openai',summarizer='openai',diarization_enabled=False))
                meeting=service.library.create('Synthetic','in_person',dict(service.settings))
                path=service.library.directory(meeting['id']);recording(path)
                calls=[]
                def execute(action,directory,settings,progress,key='',*args):
                    calls.append((action,key))
                    if action=='transcribe':(path/'transcript.json').write_text('[]')
                with patch.object(service,'_execute',side_effect=execute),patch.object(service,'_run_analytics'),patch.object(service,'_queue_metadata'),patch.object(service,'_sync_items'):
                    service.process(meeting['id'],'all')
                    wait_for(lambda:meeting['id'] not in service.busy)
                self.assertEqual(calls,[('transcribe','scribe-key'),('correct','openai-key'),('summarize','openai-key')])
            finally:service.close()


class ScribeHTTPTests(unittest.TestCase):
    from tests.test_http import HTTPTests as _HTTP
    setUp, tearDown, request = _HTTP.setUp, _HTTP.tearDown, _HTTP.request

    def test_settings_and_state_never_return_the_key(self):
        status, body, _ = self.request('/api/settings', dict(transcription='elevenlabs', elevenlabs_api_key='synthetic-private-key'))
        self.assertEqual(status, 200, body)
        self.assertTrue(json.loads(body)['elevenlabs_api_key_configured'])
        self.assertNotIn(b'synthetic-private-key', body)
        status, body, _ = self.request('/api/state')
        self.assertEqual(status, 200, body)
        self.assertTrue(json.loads(body)['elevenlabs_api_key_configured'])
        self.assertNotIn(b'synthetic-private-key', body)
        self.assertNotIn('synthetic-private-key', self.service.settings_path.read_text())
        status, body, _ = self.request('/api/settings', dict(elevenlabs_api_key=''))
        self.assertEqual(status, 200, body)
        self.assertFalse(json.loads(body)['elevenlabs_api_key_configured'])
