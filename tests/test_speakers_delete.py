import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit,parse_qs

from app.google_calendar import GoogleCalendar,CalendarError,bundled_client
from app.service import MeetingService
from app.storage import Library,atomic_json
from meeting_assistant import llm_prompt
from tests.test_calendar import FakeGoogle,MemoryStore,CLIENT
from tests.test_http import HTTPTests

PROJECT=Path(__file__).resolve().parents[1]


class SpeakerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.service=MeetingService(Path(self.tmp.name),PROJECT,google=FakeGoogle())
    def tearDown(self):self.service.close();self.tmp.cleanup()
    def test_speakers_are_normalized_and_deduplicated(self):
        names=self.service.library.save_speakers(['  Мария   Петрова ','мария петрова','Иван',''])
        self.assertEqual(names,['Мария Петрова','Иван'])
        self.assertEqual(self.service.snapshot()['speakers'],['Мария Петрова','Иван'])
        for bad in ['x'*81,'null\x00char',5]:
            with self.assertRaises(ValueError):self.service.save_speakers([bad])
    def test_saved_transcript_labels_become_known_for_all_meetings(self):
        self.service.save_speakers(['Иван'])
        m=self.service.library.create('Meeting','in_person',{});self.service.library.update(m['id'],duration=10)
        self.service.edit(m['id'],{'transcript':[dict(start=0,end=1,text='Здравейте',speaker='иван'),
            dict(start=1,end=2,text='Добре',speaker='Мария'),dict(start=2,end=3,text='Да',speaker='x'*90)]})
        self.assertEqual(self.service.library.speakers(),['Иван','Мария'])
        other=self.service.library.create('Other','in_person',{})
        self.assertEqual(self.service.snapshot()['speakers'],['Иван','Мария'])
        self.assertTrue(other)
    def test_notes_prompt_lists_known_speakers_only_when_present(self):
        self.assertIn('- Мария',llm_prompt('[00:00:00] text',['Мария']))
        self.assertNotIn('Известни участници',llm_prompt('[00:00:00] text',[]))


class DeleteGoogle(FakeGoogle):
    def __init__(self):super().__init__();self.deleted=[];self.delete_fails=False
    def delete_event(self,calendar_id,event_id,meeting_id,expected_account=None):
        if self.delete_fails:raise CalendarError('Offline')
        self.deleted.append((calendar_id,event_id,meeting_id,expected_account));return True


class DeleteTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.google=DeleteGoogle()
        self.service=MeetingService(Path(self.tmp.name),PROJECT,google=self.google)
    def tearDown(self):self.service.close();self.tmp.cleanup()
    def meeting(self,binding=None):
        m=self.service.library.create('Delete me','in_person',{})
        self.service.library.update(m['id'],status='recorded',calendar_sync=binding)
        (self.service.library.directory(m['id'])/'recording.wav').write_bytes(b'audio')
        return m['id']
    def test_delete_removes_files_and_library_entry(self):
        mid=self.meeting()
        self.assertEqual(self.service.delete(mid)['deleted'],mid)
        self.assertFalse((self.service.library.root/mid).exists())
        self.assertFalse(list(self.service.library.root.glob('.deleted-*')))
        self.assertEqual(self.service.library.list(),[])
        with self.assertRaises(FileNotFoundError):self.service.detail(mid)
    def test_busy_or_recording_meeting_cannot_be_deleted(self):
        mid=self.meeting();self.service.busy.add(mid)
        with self.assertRaisesRegex(ValueError,'Wait'):self.service.delete(mid)
        self.service.busy.discard(mid);self.service.active=mid
        with self.assertRaisesRegex(ValueError,'Wait'):self.service.delete(mid)
        self.service.active=None
        self.assertTrue((self.service.library.root/mid).exists())
    def test_calendar_event_is_deleted_only_on_request(self):
        binding=dict(calendar_id='first',event_id='bma'+'0'*32,account_id='account@example.test',status='synced')
        kept=self.meeting(binding);self.service.delete(kept)
        self.assertEqual(self.google.deleted,[])
        removed=self.meeting(binding);result=self.service.delete(removed,calendar_event=True)
        self.assertTrue(result['calendar_event_deleted'])
        self.assertEqual(self.google.deleted,[('first','bma'+'0'*32,removed,'account@example.test')])
    def test_failed_event_delete_keeps_meeting_and_allows_sync_again(self):
        mid=self.meeting(dict(calendar_id='first',event_id='bmax',account_id='account@example.test'))
        self.google.delete_fails=True
        with self.assertRaises(CalendarError):self.service.delete(mid,calendar_event=True)
        self.assertTrue((self.service.library.root/mid).exists())
        self.assertNotIn(mid,self.service.automation.deleted)
        self.assertNotIn(mid,self.service.busy)
    def test_leftover_trash_is_removed_on_start(self):
        leftover=self.service.library.root/'.deleted-abc';leftover.mkdir();(leftover/'x').write_text('x')
        Library(self.service.library.root)
        self.assertFalse(leftover.exists())


class GoogleSignInTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def test_bundled_client_lets_people_sign_in_without_importing_json(self):
        google=GoogleCalendar(self.root,MemoryStore(),lambda *a,**k:{},builtin=CLIENT)
        self.assertTrue(google.status()['sign_in_available']);self.assertFalse(google.status()['configured'])
        params=parse_qs(urlsplit(google.begin('http://127.0.0.1:8765')).query)
        self.assertEqual(params['client_id'],[CLIENT['installed']['client_id']])
        self.assertTrue(google.status()['configured'])
    def test_without_any_client_sign_in_explains_setup(self):
        google=GoogleCalendar(self.root,MemoryStore(),lambda *a,**k:{})
        self.assertFalse(google.status()['sign_in_available'])
        with self.assertRaisesRegex(CalendarError,'google_oauth_client.json'):google.begin('http://127.0.0.1:8765')
    def test_bundled_client_sources(self):
        with patch.dict(os.environ,{'GOOGLE_OAUTH_CLIENT_ID':'id.apps.googleusercontent.com','GOOGLE_OAUTH_CLIENT_SECRET':'s'}):
            self.assertEqual(bundled_client(self.root)['installed']['client_id'],'id.apps.googleusercontent.com')
        with patch.dict(os.environ,{'GOOGLE_OAUTH_CLIENT_ID':'','GOOGLE_OAUTH_CLIENT_SECRET':''}):
            self.assertIsNone(bundled_client(self.root))
            (self.root/'google_oauth_client.json').write_text(json.dumps(CLIENT))
            self.assertEqual(bundled_client(self.root),CLIENT)
    def connected(self,request):
        from app.google_calendar import SCOPES,TOKEN_URL
        def wrapped(url,method='GET',payload=None,token=None,form=False):
            if url==TOKEN_URL:return dict(access_token='a',refresh_token='r',expires_in=3600,scope=' '.join(SCOPES))
            if 'calendarList' in url:return {'items':[dict(id='me@example.test',accessRole='owner',primary=True)]}
            return request(url,method)
        google=GoogleCalendar(self.root,MemoryStore(),wrapped,builtin=CLIENT)
        state=parse_qs(urlsplit(google.begin('http://127.0.0.1:8765')).query)['state'][0]
        google.complete(dict(state=state,code='c'));return google
    def test_delete_event_checks_ownership_and_tolerates_missing_event(self):
        calls=[]
        def request(url,method):
            calls.append(method)
            if method=='GET':return {'extendedProperties':{'private':{'meetingAssistantId':'mine'}}}
            return {}
        google=self.connected(request)
        self.assertTrue(google.delete_event('cal','ev','mine'));self.assertEqual(calls,['GET','DELETE'])
        calls.clear()
        with self.assertRaisesRegex(CalendarError,'does not belong'):google.delete_event('cal','ev','other')
        self.assertEqual(calls,['GET'])
        with self.assertRaisesRegex(CalendarError,'another Google account'):
            google.delete_event('cal','ev','mine',expected_account='someone@example.test')
        def missing(url,method):
            error=CalendarError('gone');error.status=404;raise error
        self.assertFalse(self.connected(missing).delete_event('cal','ev','mine'))


class SpeakerDeleteHTTPTests(unittest.TestCase):
    setUp,tearDown,request=HTTPTests.setUp,HTTPTests.tearDown,HTTPTests.request
    def test_speakers_and_delete_routes(self):
        status,body,_=self.request('/api/speakers',{'speakers':['Мария','мария']})
        self.assertEqual((status,json.loads(body)),(200,{'speakers':['Мария']}))
        m=self.service.library.create('Route','in_person',{})
        status,body,_=self.request('/api/meetings/'+m['id']+'/delete',{'calendar_event':False})
        self.assertEqual(status,200);self.assertEqual(self.request('/api/meetings/'+m['id'])[0],404)
        headers=dict(self.headers,Origin='https://example.com')
        other=self.service.library.create('Other','in_person',{})
        self.assertEqual(self.request('/api/meetings/'+other['id']+'/delete',{},headers)[0],403)
        self.assertTrue((self.service.library.root/other['id']).exists())


if __name__=='__main__':
    unittest.main()
