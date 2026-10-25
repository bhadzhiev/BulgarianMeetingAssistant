import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest

from app.service import MeetingService
from desktop_app import Server
from tests.test_app import pcm_fixture
from app.capture import render_recording

PROJECT=Path(__file__).resolve().parents[1]


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.service=MeetingService(Path(self.tmp.name),PROJECT)
        self.server=Server(('127.0.0.1',0),self.service)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.headers={'Cookie':'meeting_session='+self.server.token,'Origin':self.server.origin,'Content-Type':'application/json'}
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.service.close();self.thread.join();self.tmp.cleanup()
    def request(self,path,body=None,headers=None):
        connection=http.client.HTTPConnection('127.0.0.1',self.server.server_port)
        connection.request('GET' if body is None else 'POST',path,body=None if body is None else json.dumps(body),headers=self.headers if headers is None else headers)
        response=connection.getresponse();status=response.status;result=response.read();response_headers=dict(response.getheaders());connection.close()
        return status,result,response_headers
    def test_api_rejects_unauthenticated_requests(self):
        self.assertEqual(self.request('/api/state',headers={})[0],403)
    def test_launch_token_sets_the_session_in_a_same_origin_step(self):
        # A native window opens the launch URL from another origin; WebKit then drops a Strict cookie.
        status,body,headers=self.request('/?token='+self.server.token,headers={})
        self.assertEqual(status,200);self.assertNotIn('Set-Cookie',headers)
        self.assertIn(b'http-equiv="refresh" content="0;url=/session?token='+self.server.token.encode(),body)
        status,body,headers=self.request('/session?token='+self.server.token,headers={})
        self.assertEqual(status,303);self.assertEqual(headers['Location'],'/')
        self.assertIn('HttpOnly',headers['Set-Cookie']);self.assertIn('SameSite=Strict',headers['Set-Cookie'])
        for path in ['/session?token=wrong','/session','/?token=wrong']:
            status,body,headers=self.request(path,headers={})
            self.assertEqual(status,403);self.assertNotIn('Set-Cookie',headers)
        status,_,headers=self.request('/session?token='+self.server.token,headers={'Host':'evil.example'})
        self.assertEqual(status,403);self.assertNotIn('Set-Cookie',headers)
    def test_foreign_origin_cannot_change_settings(self):
        headers=dict(self.headers,Origin='https://example.com')
        self.assertEqual(self.request('/api/settings',{},headers)[0],403)
    def test_foreign_host_is_rejected(self):
        headers=dict(self.headers,Host='example.com')
        self.assertEqual(self.request('/api/state',headers=headers)[0],403)
    def test_state_never_exposes_key(self):
        self.service.api_key='never-expose-this'
        status,body,headers=self.request('/api/state')
        self.assertEqual(status,200);self.assertNotIn(b'never-expose-this',body)
        self.assertIn('no-store',headers['Cache-Control'])
    def test_audio_ranges_support_seeking(self):
        m=self.service.library.create('Playback','online',{})
        directory=self.service.library.directory(m['id']);pcm_fixture(directory,online=True);render_recording(directory)
        path='/files/'+m['id']+'/recording.wav'
        status,body,headers=self.request(path,headers=dict(self.headers,Range='bytes=44-143'))
        self.assertEqual(status,206);self.assertEqual(len(body),100)
        self.assertTrue(headers['Content-Range'].startswith('bytes 44-143/'))
        self.assertEqual(self.request(path,headers=dict(self.headers,Range='bytes=999999-'))[0],416)
    def test_arbitrary_files_cannot_be_downloaded(self):
        m=self.service.library.create('Meeting','online',{})
        self.assertEqual(self.request('/files/'+m['id']+'/meeting.json')[0],404)
    def test_static_assets_and_search(self):
        self.assertEqual(self.request('/app.js')[0],200)
        m=self.service.library.create('Българска среща','in_person',{})
        self.assertEqual(len(json.loads(self.request('/api/search?q=%D1%81%D1%80%D0%B5%D1%89%D0%B0')[1])),1)

    def test_google_oauth_callback_uses_state_without_requiring_app_cookie(self):
        from app.google_calendar import GoogleCalendar,SCOPES,TOKEN_URL
        from tests.test_calendar import MemoryStore,CLIENT
        from urllib.parse import urlsplit,parse_qs
        def request(url,method='GET',payload=None,**kwargs):
            if url==TOKEN_URL:return dict(access_token='access',refresh_token='refresh',expires_in=3600,scope=' '.join(SCOPES))
            return {'items':[dict(id='me@example.test',accessRole='owner',primary=True)]}
        self.service.google=GoogleCalendar(self.service.library.root,MemoryStore(),request)
        status,body,headers=self.request('/api/calendar/credentials',{'credentials':CLIENT})
        self.assertEqual(status,200);self.assertNotIn(b'desktop-client-value',body)
        url=self.service.google.begin(self.server.origin);state=parse_qs(urlsplit(url).query)['state'][0]
        self.assertEqual(self.request('/?state=invalid&code=test',headers={})[0],400)
        status,body,_=self.request('/?state='+state+'&code=test',headers={})
        self.assertEqual(status,200);self.assertIn(b'signed in with Google',body)
        self.assertNotIn(b'refresh',body)
        self.assertEqual(self.request('/?state='+state+'&code=test',headers={})[0],400)

    def test_stable_meeting_link_serves_app_without_embedding_session_credential(self):
        m=self.service.library.create('Stable link','in_person',{})
        status,body,_=self.request('/?meeting='+m['id'])
        self.assertEqual(status,200);self.assertIn(b'/app.js',body)
        self.assertNotIn(self.server.token.encode(),body)
        self.assertEqual(self.request('/?meeting='+m['id'],headers={})[0],403)

    def test_calendar_list_requires_connection(self):
        self.assertEqual(self.request('/api/calendar/calendars')[0],400)
