import copy
import datetime as dt
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit,parse_qs

from app.google_calendar import GoogleCalendar,CalendarError,SCOPES,event_payload,TOKEN_URL
from app.meeting_automation import generate_title
from app.service import MeetingService,DEFAULTS
from app.storage import atomic_json
from tests.test_app import wait_for

PROJECT=Path(__file__).resolve().parents[1]
CLIENT={'installed':{'client_id':'123-example.apps.googleusercontent.com','client_secret':'desktop-client-value'}}

class MemoryStore:
    def __init__(self):self.value=None
    def get(self):return copy.deepcopy(self.value)
    def set(self,value):self.value=copy.deepcopy(value)
    def delete(self):self.value=None


class GoogleAuthTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.store=MemoryStore();self.calls=[]
        self.google=GoogleCalendar(self.root,self.store,self.request)
        self.google.configure(CLIENT)
    def tearDown(self):self.tmp.cleanup()
    def request(self,url,method='GET',payload=None,token=None,form=False):
        self.calls.append((url,method,payload,token,form))
        if url==TOKEN_URL:return dict(access_token='access-test',refresh_token='refresh-test',expires_in=3600,scope=' '.join(SCOPES))
        return {'items':[dict(id='owner@example.test',summary='Primary',primary=True,accessRole='owner'),dict(id='read-only',summary='Reader',accessRole='reader')]}
    def connect(self):
        auth=self.google.begin('http://127.0.0.1:8765')
        state=parse_qs(urlsplit(auth).query)['state'][0]
        return self.google.complete(dict(state=state,code='test-code'))
    def test_pkce_offline_loopback_and_single_use_state(self):
        auth=self.google.begin('http://127.0.0.1:8765');params=parse_qs(urlsplit(auth).query)
        self.assertEqual(params['code_challenge_method'],['S256'])
        self.assertEqual(params['access_type'],['offline'])
        self.assertEqual(params['redirect_uri'],['http://127.0.0.1:8765/'])
        state=params['state'][0]
        with self.assertRaises(CalendarError):self.google.complete(dict(state='wrong',code='x'))
        self.assertEqual(len(self.calls),0)
        self.assertTrue(self.google.complete(dict(state=state,code='test'))['connected'])
        self.assertIn('code_verifier',self.calls[0][2])
        with self.assertRaises(CalendarError):self.google.complete(dict(state=state,code='test'))
    def test_expired_or_denied_oauth_does_not_exchange_code(self):
        self.google.begin('http://127.0.0.1:8765');state=self.google.pending['state'];self.google.pending['created']-=601
        with self.assertRaises(CalendarError):self.google.complete(dict(state=state,code='test'))
        self.google.begin('http://127.0.0.1:8765');state=self.google.pending['state']
        with self.assertRaises(CalendarError):self.google.complete(dict(state=state,error='access_denied'))
        self.assertFalse(self.calls)
    def test_tokens_and_client_secret_never_enter_status_or_json_files(self):
        self.connect()
        public=json.dumps(self.google.status())+'\n'+self.google.state_path.read_text()
        for secret in ['refresh-test','access-test','desktop-client-value']:self.assertNotIn(secret,public)
        self.assertEqual(self.store.value['refresh_token'],'refresh-test')
    def test_calendar_listing_excludes_read_only_and_refreshes_expired_token(self):
        self.connect();self.google.bundle['expires_at']=0
        calendars=self.google.list_calendars()
        self.assertEqual([c['id'] for c in calendars],['owner@example.test'])
        self.assertEqual(self.calls[-2][2]['grant_type'],'refresh_token')
    def test_calendar_list_pagination(self):
        self.connect()
        def request(url,**kwargs):
            if 'pageToken' not in url:return {'items':[dict(id='a',accessRole='writer')],'nextPageToken':'next'}
            return {'items':[dict(id='b',accessRole='owner')]}
        self.google.request=request
        self.assertEqual([c['id'] for c in self.google.list_calendars()],['a','b'])
    def test_requires_desktop_client_and_loopback_origin(self):
        with self.assertRaises(ValueError):self.google.configure({'web':CLIENT['installed']})
        with self.assertRaises(ValueError):self.google.begin('https://example.com')
    def test_disconnect_removes_user_tokens_but_keeps_client(self):
        self.connect();status=self.google.disconnect()
        self.assertFalse(status['connected']);self.assertTrue(status['configured'])
        self.assertNotIn('refresh_token',self.store.value)
    def test_repeated_insert_conflict_updates_only_owned_event(self):
        self.connect();mid='a'*32;calls=[]
        def request(url,method='GET',payload=None,**kwargs):
            calls.append((method,payload))
            if method=='POST':
                error=CalendarError('Conflict');error.status=409;raise error
            if method=='GET':return {'extendedProperties':{'private':{'meetingAssistantId':mid}}}
            return dict(id='bma'+mid,htmlLink='https://www.google.com/calendar/event?eid=test')
        self.google.request=request
        meeting=dict(id=mid,title='Meeting',created='2026-10-24T10:00:00+03:00',duration=30)
        self.google.upsert('calendar',meeting,'http://127.0.0.1:8765/?meeting='+mid,'bma'+mid)
        self.assertEqual([c[0] for c in calls],['POST','GET','PATCH'])
    def test_conflicting_foreign_event_is_never_modified(self):
        self.connect();calls=[]
        def request(url,method='GET',payload=None,**kwargs):
            calls.append(method)
            if method=='POST':
                error=CalendarError('Conflict');error.status=409;raise error
            return {'extendedProperties':{'private':{'meetingAssistantId':'someone-else'}}}
        self.google.request=request
        with self.assertRaisesRegex(CalendarError,'another event'):
            self.google.upsert('calendar',dict(id='a'*32,title='x',created='2026-10-24T10:00:00+03:00'),
                               'http://127.0.0.1:8765/?meeting='+'a'*32,'bma'+'a'*32)
        self.assertEqual(calls,['POST','GET'])
    def test_account_is_rechecked_under_the_write_lock(self):
        self.connect();self.calls.clear()
        with self.assertRaisesRegex(CalendarError,'account changed'):
            self.google.upsert('calendar',{},'http://127.0.0.1:8765','event',expected_account='different@example.test')
        self.assertFalse(self.calls)
    def test_payload_uses_wall_times_and_never_includes_transcript(self):
        meeting=dict(id='a'*32,title='Заглавие',created='2026-10-24T10:00:00+03:00',
            started_at='2026-10-24T10:01:00+03:00',ended_at='2026-10-24T11:01:00+03:00',duration=30,transcript='private text')
        payload=event_payload(meeting,'http://127.0.0.1:8765/?meeting='+'a'*32)
        self.assertEqual(payload['start']['dateTime'],meeting['started_at'])
        self.assertEqual(payload['end']['dateTime'],meeting['ended_at'])
        self.assertNotIn('private text',json.dumps(payload));self.assertNotIn('attendees',payload)


class FakeGoogle:
    def __init__(self):self.calls=[];self.connected=True;self.account='account@example.test';self.fail=False
    def status(self):return dict(configured=True,connected=self.connected,account=self.account,error=None,authorizing=False)
    def list_calendars(self):return [dict(id='first',name='First'),dict(id='second',name='Second')]
    def upsert(self,calendar_id,meeting,link,event_id,expected_account=None):
        if expected_account and expected_account!=self.account:raise CalendarError('Google account changed')
        self.calls.append(dict(calendar_id=calendar_id,title=meeting['title'],link=link,id=event_id))
        if self.fail:raise CalendarError('Offline')
        return dict(id=event_id,htmlLink='https://www.google.com/calendar/event?eid=test')


class MeetingAutomationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.google=FakeGoogle()
        self.service=MeetingService(Path(self.tmp.name),PROJECT,google=self.google)
        self.service.save_settings(dict(calendar_enabled=True,calendar_id='first',transcript_correction='none'))
    def tearDown(self):self.service.close();self.tmp.cleanup()
    def meeting(self,title='',transcript=True):
        meeting=self.service.library.create(title,'in_person',dict(self.service.settings))
        self.service.library.update(meeting['id'],status='recorded',duration=30,started_at='2026-10-24T10:00:00+03:00',ended_at='2026-10-24T10:01:00+03:00')
        if transcript:atomic_json(self.service.library.directory(meeting['id'])/'transcript.json',[dict(start=0,end=30,text='Обсъждаме бюджета.',speaker=None)])
        return meeting['id']
    def settled(self,mid):
        wait_for(lambda:self.service.library.get(mid).get('calendar_sync',{}).get('status') in {'synced','error'})
        wait_for(lambda:mid not in self.service.automation.running and mid not in self.service.automation.pending)
    def test_ai_title_and_calendar_are_automatic_and_idempotent(self):
        mid=self.meeting()
        with patch('app.meeting_automation.generate_title',return_value=('Планиране на бюджета','final')):
            self.service._queue_metadata(mid,enrich=True);self.settled(mid)
        meeting=self.service.library.get(mid)
        self.assertEqual(meeting['title'],'Планиране на бюджета')
        self.assertEqual(meeting['title_source'],'ai')
        self.assertEqual(self.google.calls[-1]['title'],meeting['title'])
        self.assertNotIn('token=',self.google.calls[-1]['link'])
        self.service.sync_calendar(mid);self.settled(mid)
        self.assertEqual(len({c['id'] for c in self.google.calls}),1)
    def test_manual_titles_are_preserved(self):
        mid=self.meeting('My explicit title')
        with patch('app.meeting_automation.generate_title') as generate:
            self.service._queue_metadata(mid,enrich=True);self.settled(mid)
        generate.assert_not_called()
        self.assertEqual(self.service.library.get(mid)['title'],'My explicit title')
    def test_rename_during_ai_generation_wins_and_updates_calendar(self):
        mid=self.meeting();started=threading.Event();release=threading.Event()
        def title(*args):started.set();release.wait(3);return 'Old generated title','final'
        with patch('app.meeting_automation.generate_title',side_effect=title):
            self.service._queue_metadata(mid,enrich=True);self.assertTrue(started.wait(2))
            self.service.edit(mid,{'title':'My new title'});release.set();self.settled(mid)
        self.assertEqual(self.service.library.get(mid)['title'],'My new title')
        self.assertEqual(self.google.calls[-1]['title'],'My new title')
    def test_changing_default_calendar_keeps_existing_event_destination(self):
        mid=self.meeting('Manual');self.service._queue_metadata(mid);self.settled(mid)
        self.service.save_settings({'calendar_id':'second'})
        self.service.edit(mid,{'title':'Renamed'});self.settled(mid)
        self.assertEqual(self.google.calls[-1]['calendar_id'],'first')
        other=self.meeting('Next');self.service._queue_metadata(other);self.settled(other)
        self.assertEqual(self.google.calls[-1]['calendar_id'],'second')
    def test_wrong_google_account_cannot_publish_bound_meeting(self):
        mid=self.meeting('Manual');self.google.account='different@example.test'
        self.service._queue_metadata(mid);self.settled(mid)
        self.assertFalse(self.google.calls)
        self.assertIn('another Google account',self.service.library.get(mid)['calendar_sync']['error'])
    def test_calendar_failure_does_not_change_recording_status(self):
        mid=self.meeting('Manual');self.google.fail=True
        self.service._queue_metadata(mid);self.settled(mid)
        meeting=self.service.library.get(mid)
        self.assertEqual(meeting['status'],'recorded');self.assertEqual(meeting['calendar_sync']['status'],'error')
        self.assertGreater(meeting['calendar_sync']['next_retry'],time.time())
    def test_title_failure_still_publishes_recording_link(self):
        mid=self.meeting()
        with patch('app.meeting_automation.generate_title',side_effect=RuntimeError('LLM unavailable')):
            self.service._queue_metadata(mid,enrich=True);self.settled(mid)
        meeting=self.service.library.get(mid)
        self.assertEqual(meeting['title_status'],'error');self.assertEqual(meeting['calendar_sync']['status'],'synced')
    def test_title_generator_uses_transcript_and_validates_response(self):
        mid=self.meeting();directory=self.service.library.directory(mid)
        with patch('meeting_assistant.post_json',return_value={'choices':[{'message':{'content':'{"title":"Преглед на бюджета"}'}}]}) as request:
            title,basis=generate_title(directory,self.service.settings,'')
        self.assertEqual((title,basis),('Преглед на бюджета','final'))
        self.assertIn('Обсъждаме бюджета.',request.call_args.args[1]['messages'][1]['content'])
        with patch('meeting_assistant.post_json',return_value={'choices':[{'message':{'content':'{"title":"Bad\\ntitle"}'}}]}):
            with self.assertRaises(ValueError):generate_title(directory,self.service.settings,'')
    def test_disconnected_account_cannot_enable_new_calendar_destination(self):
        self.google.connected=False
        with self.assertRaisesRegex(ValueError,'Sign in with Google'):self.service.save_settings({'calendar_id':'second'})

    def test_processing_retry_preserves_original_unsynced_calendar_choice(self):
        import numpy as np
        from meeting_assistant import write_wav
        mid=self.meeting('Manual')
        directory=self.service.library.directory(mid)
        write_wav(directory/'recording.wav',np.zeros(16000,dtype=np.int16))
        self.service.save_settings({'calendar_id':'second'})
        with patch('app.processing.transcribe'):
            self.service.process(mid,'transcribe')
            wait_for(lambda:mid not in self.service.busy)
            self.settled(mid)
        self.assertEqual(self.google.calls[-1]['calendar_id'],'first')
    def test_restart_style_scan_recovers_a_missing_calendar_write(self):
        mid=self.meeting('Manual')
        self.service.automation.retry_pending();self.settled(mid)
        self.assertEqual(self.google.calls[-1]['id'],'bma'+mid)
