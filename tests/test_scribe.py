import copy
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


class MemoryKeyStore:
    """Stands in for the Keychain in every test of this module."""
    saved, fail, reads = None, False, 0

    def get(self):
        MemoryKeyStore.reads += 1
        if MemoryKeyStore.fail: raise RuntimeError('Keychain denied')
        return copy.deepcopy(MemoryKeyStore.saved)

    def set(self, value):
        if MemoryKeyStore.fail: raise RuntimeError('Keychain denied')
        MemoryKeyStore.saved = copy.deepcopy(value)

    def delete(self):
        if MemoryKeyStore.fail: raise RuntimeError('Keychain denied')
        MemoryKeyStore.saved = None


_keychain = patch('app.scribe.KeyStore', MemoryKeyStore)


def setUpModule():
    _keychain.start()


def tearDownModule():
    _keychain.stop()


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
        self.assertIn(b'scribe_v3', request.data)
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

    def test_pipeline_sends_the_whole_recording_once_without_scribe_speakers(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp); recording(path, 62)
            original = (path/'recording.wav').read_bytes()
            data = dict(text='Здравей. Добре.', words=[
                dict(type='word', text='Здравей.', start=1, end=1.5, speaker_id='speaker_0'),
                dict(type='spacing', text=' ', start=1.5, end=1.6, speaker_id='speaker_0'),
                dict(type='word', text='Добре.', start=61, end=61.5, speaker_id='speaker_1')])
            def upload(audio, key, terms, offset, end, timeout=180):
                self.assertEqual((audio, key, terms, offset, end), (original, 'scribe-key', ['Kubernetes'], 0, 62))
                self.assertGreaterEqual(timeout, 362)
                return scribe.word_units(data, offset, end)
            with patch('app.scribe.transcribe', side_effect=upload) as call:
                processing.transcribe(path, dict(DEFAULTS, transcription='elevenlabs', whisper_vocabulary='Kubernetes'), lambda _:None, 'scribe-key')
            self.assertEqual(call.call_count, 1)
            transcript = json.loads((path/'transcript.json').read_text())
            self.assertEqual([(s['text'], s['speaker']) for s in transcript], [('Здравей.', None), ('Добре.', None)])
            units = json.loads((path/'transcript.alignment.json').read_text())['units']
            self.assertEqual([u['start'] for u in units], [1, 61])
            self.assertFalse((path/'speaker-turns.json').exists())
            metadata = json.loads((path/'transcript.metadata.json').read_text())
            self.assertEqual((metadata['model'], metadata['speaker_recognition']), ('scribe_v3', 'local'))
            self.assertEqual((path/'recording.wav').read_bytes(), original)
            self.assertNotIn('scribe-key', ''.join(p.read_text() for p in path.glob('*.json')))

    def test_request_never_asks_scribe_for_speakers(self):
        with patch('app.scribe.urllib.request.urlopen') as upload:
            upload.return_value.__enter__.return_value = io.StringIO(json.dumps(response()))
            scribe.transcribe(b'audio', 'key', [], 0, 2, timeout=900)
        self.assertIn(b'name="diarize"\r\n\r\nfalse', upload.call_args.args[0].data)
        self.assertEqual(upload.call_args.kwargs['timeout'], 900)

    def setUp(self):
        MemoryKeyStore.saved, MemoryKeyStore.fail, MemoryKeyStore.reads = None, False, 0

    def test_key_is_saved_in_keychain_and_survives_a_restart(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict('os.environ', {'ELEVENLABS_API_KEY':''}):
            root=Path(tmp)
            service=MeetingService(root,PROJECT)
            try:
                self.assertEqual(MemoryKeyStore.reads,0)
                result=service.save_settings(dict(elevenlabs_api_key=' scribe-key '))
                self.assertIsNone(result['elevenlabs_key_error'])
                self.assertEqual(MemoryKeyStore.saved,dict(api_key='scribe-key'))
                self.assertNotIn('scribe-key',''.join(p.read_text() for p in root.glob('*.json')))
            finally:service.close()
            service=MeetingService(root,PROJECT)
            try:
                self.assertEqual(service.elevenlabs_api_key,'scribe-key')
                service.save_settings(dict(elevenlabs_api_key=''))
                self.assertIsNone(MemoryKeyStore.saved)
                self.assertFalse((root/'elevenlabs.json').exists())
            finally:service.close()
            reads=MemoryKeyStore.reads
            service=MeetingService(root,PROJECT)
            try:
                self.assertEqual((service.elevenlabs_api_key,MemoryKeyStore.reads),('',reads))
            finally:service.close()

    def test_refused_keychain_keeps_the_key_for_this_session_and_says_so(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict('os.environ', {'ELEVENLABS_API_KEY':''}):
            service=MeetingService(Path(tmp),PROJECT)
            try:
                MemoryKeyStore.fail=True
                result=service.save_settings(dict(elevenlabs_api_key='scribe-key'))
                self.assertIn('Keychain refused',result['elevenlabs_key_error'])
                self.assertEqual(service.elevenlabs_api_key,'scribe-key')
                self.assertFalse((Path(tmp)/'elevenlabs.json').exists())
            finally:service.close()

    def test_unreadable_keychain_reports_an_error_without_a_key(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict('os.environ', {'ELEVENLABS_API_KEY':''}):
            (Path(tmp)/'elevenlabs.json').write_text('{"saved": true}')
            MemoryKeyStore.fail=True
            service=MeetingService(Path(tmp),PROJECT)
            try:
                self.assertEqual(service.elevenlabs_api_key,'')
                self.assertIn('could not be read',service.elevenlabs_key_error)
            finally:service.close()

    def test_environment_key_is_used_and_not_read_from_keychain(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict('os.environ', {'ELEVENLABS_API_KEY':'env-key'}):
            (Path(tmp)/'elevenlabs.json').write_text('{"saved": true}')
            MemoryKeyStore.saved=dict(api_key='saved-key')
            service=MeetingService(Path(tmp),PROJECT)
            try:
                self.assertEqual((service.elevenlabs_api_key,MemoryKeyStore.reads),('env-key',0))
            finally:service.close()

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

    def test_scribe_skips_automatic_correction_and_routes_keys(self):
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
                self.assertEqual(calls,[('transcribe','scribe-key'),('summarize','openai-key')])
            finally:service.close()

    def test_local_speaker_separation_runs_after_scribe(self):
        with tempfile.TemporaryDirectory() as tmp:
            service=MeetingService(Path(tmp),PROJECT)
            try:
                service.save_settings(dict(transcription='elevenlabs',elevenlabs_api_key='scribe-key',auto_title=False,summarizer='none',diarization_enabled=True))
                meeting=service.library.create('Synthetic','in_person',dict(service.settings))
                path=service.library.directory(meeting['id']);recording(path)
                calls=[]
                def execute(action,directory,settings,progress,key='',*args):
                    calls.append(action)
                    if action=='transcribe':(path/'transcript.json').write_text('[]')
                with patch.object(service,'_execute',side_effect=execute),patch.object(service,'_run_diarization') as diarize,\
                        patch.object(service,'_run_analytics'),patch.object(service,'_queue_metadata'),patch.object(service,'_sync_items'):
                    service.process(meeting['id'],'all')
                    wait_for(lambda:meeting['id'] not in service.busy)
                self.assertEqual(calls,['transcribe'])
                diarize.assert_called_once()
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
