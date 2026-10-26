"""Google desktop OAuth with PKCE, macOS Keychain storage, and idempotent event writes."""
from __future__ import annotations

import base64
import ctypes
import datetime as dt
import hashlib
import html
import json
import os
from pathlib import Path
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from .storage import atomic_json

SCOPES = ('https://www.googleapis.com/auth/calendar.calendarlist.readonly',
          'https://www.googleapis.com/auth/calendar.events')
GMAIL_SCOPE = 'https://www.googleapis.com/auth/gmail.readonly'
GMAIL_URL = 'https://gmail.googleapis.com/gmail/v1/users/me'
AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
TOKEN_URL = 'https://oauth2.googleapis.com/token'
API_URL = 'https://www.googleapis.com/calendar/v3'


class CalendarError(RuntimeError):
    pass


def bundled_client(project: Path):
    """The app's own Desktop OAuth client, so people only sign in with their Google account.

    Google requires every app to have an OAuth client. The app owner sets it once with
    GOOGLE_OAUTH_CLIENT_ID/GOOGLE_OAUTH_CLIENT_SECRET or google_oauth_client.json.
    """
    client_id = os.environ.get('GOOGLE_OAUTH_CLIENT_ID', '').strip()
    secret = os.environ.get('GOOGLE_OAUTH_CLIENT_SECRET', '').strip()
    if client_id and secret:
        return {'installed': {'client_id': client_id, 'client_secret': secret}}
    path = project / 'google_oauth_client.json'
    if path.is_file() and path.stat().st_size <= 50000:
        try:
            return json.loads(path.read_text())
        except ValueError:
            return None
    return None


class KeychainStore:
    """Generic-password APIs keep tokens out of files, command arguments, and responses."""
    def __init__(self, account: str):
        self.account = account.encode()
        self.service = b'local.bulgarian-meeting-assistant.google-calendar'

    def _api(self):
        lib = ctypes.CDLL('/System/Library/Frameworks/Security.framework/Security')
        void, uint = ctypes.c_void_p, ctypes.c_uint32
        lib.SecKeychainFindGenericPassword.argtypes = [void,uint,void,uint,void,ctypes.POINTER(uint),ctypes.POINTER(void),ctypes.POINTER(void)]
        lib.SecKeychainFindGenericPassword.restype = ctypes.c_int32
        lib.SecKeychainAddGenericPassword.argtypes = [void,uint,void,uint,void,uint,void,ctypes.POINTER(void)]
        lib.SecKeychainAddGenericPassword.restype = ctypes.c_int32
        lib.SecKeychainItemModifyAttributesAndData.argtypes = [void,void,uint,void]
        lib.SecKeychainItemModifyAttributesAndData.restype = ctypes.c_int32
        lib.SecKeychainItemDelete.argtypes = [void]
        lib.SecKeychainItemDelete.restype = ctypes.c_int32
        lib.SecKeychainItemFreeContent.argtypes = [void,void]
        lib.SecKeychainItemFreeContent.restype = ctypes.c_int32
        cf = ctypes.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
        cf.CFRelease.argtypes = [void]
        return lib, cf

    def _find(self, lib):
        length, data, item = ctypes.c_uint32(), ctypes.c_void_p(), ctypes.c_void_p()
        status = lib.SecKeychainFindGenericPassword(None,len(self.service),self.service,
            len(self.account),self.account,ctypes.byref(length),ctypes.byref(data),ctypes.byref(item))
        return status, length, data, item

    def get(self):
        lib, cf = self._api()
        status, length, data, item = self._find(lib)
        if status == -25300:
            return None
        if status:
            raise CalendarError(f'Cannot read Google credentials from macOS Keychain (code {status}). Unlock Keychain and retry.')
        try:
            return json.loads(ctypes.string_at(data, length.value))
        finally:
            lib.SecKeychainItemFreeContent(None,data)
            if item:cf.CFRelease(item)

    def set(self, value):
        raw = json.dumps(value).encode()
        lib, cf = self._api()
        status, length, data, item = self._find(lib)
        try:
            if status == -25300:
                status = lib.SecKeychainAddGenericPassword(None,len(self.service),self.service,
                    len(self.account),self.account,len(raw),raw,None)
            elif not status:
                lib.SecKeychainItemFreeContent(None,data)
                status = lib.SecKeychainItemModifyAttributesAndData(item,None,len(raw),raw)
            if status:
                raise CalendarError(f'Cannot save Google credentials in macOS Keychain (code {status}).')
        finally:
            if item:cf.CFRelease(item)

    def delete(self):
        lib, cf = self._api()
        status, length, data, item = self._find(lib)
        if status == -25300:return
        try:
            if status:raise CalendarError(f'Cannot open Google credentials in Keychain (code {status}).')
            lib.SecKeychainItemFreeContent(None,data)
            status = lib.SecKeychainItemDelete(item)
            if status:raise CalendarError(f'Cannot remove Google credentials from Keychain (code {status}).')
        finally:
            if item:cf.CFRelease(item)


def http_json(url: str, method='GET', payload=None, token=None, form=False):
    headers = {'Accept':'application/json'}
    data = None
    if payload is not None:
        if form:
            data = urllib.parse.urlencode(payload).encode()
            headers['Content-Type'] = 'application/x-www-form-urlencoded'
        else:
            data = json.dumps(payload).encode()
            headers['Content-Type'] = 'application/json'
    if token:headers['Authorization'] = 'Bearer ' + token
    request = urllib.request.Request(url,data=data,headers=headers,method=method)
    try:
        with urllib.request.urlopen(request,timeout=30) as response:
            raw = response.read(8 * 1024 * 1024 + 1)
            if len(raw) > 8 * 1024 * 1024:
                raise CalendarError('Google response exceeds the local response limit.')
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        # Keep authorization codes, tokens, response bodies, and client secrets out of errors.
        error = CalendarError(f'Google request failed (HTTP {exc.code}). Reconnect for 401/403 errors, or retry later.')
        error.status = exc.code
        raise error from None
    except (urllib.error.URLError, TimeoutError):
        raise CalendarError('Google could not be reached. Check your connection and retry.') from None


class GoogleCalendar:
    def __init__(self, root: Path, store=None, request=http_json, builtin=None):
        self.root = root
        self.builtin = builtin
        self.store = store or KeychainStore(hashlib.sha256(str(root.resolve()).encode()).hexdigest())
        self.request = request
        self.state_path = root / '.google-calendar.json'
        self.state = json.loads(self.state_path.read_text()) if self.state_path.exists() else {}
        self.lock = threading.RLock()
        self.pending = None
        self.bundle = None
        self.loaded = False
        self.calendars = []
        self.last_error = None

    def _load(self):
        if not self.loaded:
            self.bundle = self.store.get() if self.state.get('configured') else None
            self.loaded = True
        return self.bundle or {}

    def status(self):
        # Do not make the recorder/UI wait behind a Google request or OAuth exchange.
        acquired = self.lock.acquire(blocking=False)
        try:
            try:
                bundle = self._load() if acquired else (self.bundle or {})
                connected = bool(bundle.get('refresh_token') and bundle.get('account_id'))
            except Exception as exc:
                connected = False
                self.last_error = str(exc)
            return dict(configured=bool(self.state.get('configured')),connected=connected,
                        sign_in_available=bool(self.state.get('configured') or self.builtin),
                        account=self.state.get('account_id',''),error=self.last_error,
                        capabilities=dict(calendar=connected and set(SCOPES).issubset(self._scopes(bundle)),
                                          gmail=connected and GMAIL_SCOPE in self._scopes(bundle)),
                        authorizing=bool(self.pending and time.monotonic()-self.pending['created'] < 600))
        finally:
            if acquired:self.lock.release()

    def configure(self, content):
        if not isinstance(content, dict) or not isinstance(content.get('installed'), dict):
            raise ValueError('Import the JSON for a Google OAuth client of type Desktop app.')
        client = content['installed']
        client_id, secret = client.get('client_id'), client.get('client_secret')
        if not isinstance(client_id,str) or not re.fullmatch(r'[A-Za-z0-9_.-]+\.apps\.googleusercontent\.com',client_id):
            raise ValueError('Invalid Google Desktop OAuth client ID')
        if not isinstance(secret,str) or not 1 <= len(secret) <= 512 or any(ord(c)<32 for c in secret):
            raise ValueError('Invalid Google Desktop OAuth client secret')
        with self.lock:
            old = self._load()
            if old.get('client_id') == client_id and old.get('client_secret') == secret:
                return self.status()
            bundle = dict(client_id=client_id,client_secret=secret)
            self.store.set(bundle)
            self.bundle, self.loaded = bundle, True
            self.state = dict(configured=True)
            self.pending, self.calendars, self.last_error = None, [], None
            atomic_json(self.state_path,self.state)
            return self.status()

    def _scopes(self, bundle=None):
        bundle = self._load() if bundle is None else bundle
        # Credentials created before capability tracking were Calendar-only.
        return set(bundle.get('scopes', SCOPES if bundle.get('account_id') else ()))

    def begin(self, origin, capability='calendar'):
        if capability not in {'calendar', 'gmail'}:
            raise ValueError('Unknown Google capability')
        parts = urllib.parse.urlsplit(origin)
        if parts.scheme != 'http' or parts.hostname != '127.0.0.1' or not parts.port or parts.path:
            raise ValueError('Google sign-in requires this app’s loopback address')
        with self.lock:
            # Use the app's own client unless one was imported or is already stored.
            if self.builtin and not self._load().get('client_id'):
                self.configure(self.builtin)
            bundle = self._load()
            if not bundle.get('client_id'):
                raise CalendarError('Google sign-in is not set up for this app. Add google_oauth_client.json '
                                    '(see README), or import a Desktop OAuth client JSON under Advanced.')
            scopes = self._scopes(bundle) | (set(SCOPES) if capability == 'calendar' else {GMAIL_SCOPE})
            verifier = secrets.token_urlsafe(48)
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
            self.pending = dict(state=secrets.token_urlsafe(32),verifier=verifier,
                                redirect_uri=origin+'/',created=time.monotonic(),scopes=sorted(scopes),capability=capability)
            query = dict(client_id=bundle['client_id'],redirect_uri=self.pending['redirect_uri'],
                response_type='code',scope=' '.join(sorted(scopes)),state=self.pending['state'],
                code_challenge=challenge,code_challenge_method='S256',access_type='offline',prompt='consent')
            return AUTH_URL+'?'+urllib.parse.urlencode(query)

    def complete(self, params):
        with self.lock:
            pending = self.pending
            state = params.get('state','')
            if (not pending or time.monotonic()-pending['created']>600 or not isinstance(state,str)
                or not secrets.compare_digest(state,pending['state'])):
                raise CalendarError('Google sign-in expired or did not match this app. Click Sign in with Google again.')
            self.pending = None  # single use, including denied/failed exchanges
            if params.get('error'):
                raise CalendarError('Google sign-in was cancelled or denied. No new Google permissions were connected.')
            code = params.get('code')
            if not isinstance(code,str) or not code or len(code)>4096:
                raise CalendarError('Google did not return an authorization code.')
            old = self._load()
            token = self.request(TOKEN_URL,'POST',dict(client_id=old['client_id'],
                client_secret=old['client_secret'],code=code,code_verifier=pending['verifier'],
                redirect_uri=pending['redirect_uri'],grant_type='authorization_code'),form=True)
            if not isinstance(token.get('access_token'),str) or not token.get('refresh_token'):
                raise CalendarError('Google did not grant background access. Reconnect and approve the requested Google permissions.')
            granted = set(token.get('scope', ' '.join(pending['scopes'])).split())
            if not set(pending['scopes']).issubset(granted):
                raise CalendarError('Requested Google permissions were not fully granted. Existing connection was kept.')
            bundle = dict(old,access_token=token['access_token'],refresh_token=token['refresh_token'],
                          expires_at=time.time()+float(token.get('expires_in',3600)),scopes=sorted(granted))
            # Query calendars using this candidate credential before committing it.
            calendars = self._calendars(bundle['access_token']) if set(SCOPES).issubset(granted) else []
            primary = next((c['id'] for c in calendars if c['primary']),None)
            if GMAIL_SCOPE in granted:
                profile = self.request(GMAIL_URL+'/profile',token=bundle['access_token'])
                address = profile.get('emailAddress')
                if not isinstance(address,str) or '@' not in address:
                    raise CalendarError('Cannot verify the Gmail account.')
                if primary and primary.casefold() != address.casefold():
                    raise CalendarError('Calendar and Gmail account identities did not match. Existing connection was kept.')
                primary = address
            if not primary:
                raise CalendarError('Cannot identify your primary calendar. Allow calendar-list access and reconnect.')
            bundle['account_id'] = primary
            self.store.set(bundle)
            self.bundle = bundle
            self.state = dict(configured=True,account_id=primary)
            atomic_json(self.state_path,self.state)
            self.calendars, self.last_error = calendars, None
            return self.status()

    def _access(self):
        bundle = self._load()
        if not bundle.get('refresh_token'):
            raise CalendarError('Sign in with Google in Settings first.')
        if time.time()+60 >= bundle.get('expires_at',0):
            token = self.request(TOKEN_URL,'POST',dict(client_id=bundle['client_id'],
                client_secret=bundle['client_secret'],refresh_token=bundle['refresh_token'],grant_type='refresh_token'),form=True)
            if not isinstance(token.get('access_token'),str):
                raise CalendarError('Google token refresh failed. Reconnect in Settings.')
            bundle = dict(bundle,access_token=token['access_token'],
                          expires_at=time.time()+float(token.get('expires_in',3600)))
            self.store.set(bundle)
            self.bundle = bundle
        return bundle['access_token']

    def _calendars(self, token):
        calendars, page = [], None
        while True:
            query = dict(minAccessRole='writer',maxResults=250)
            if page:query['pageToken']=page
            result = self.request(API_URL+'/users/me/calendarList?'+urllib.parse.urlencode(query),token=token)
            for item in result.get('items',[]):
                if item.get('accessRole') in {'writer','owner'} and not item.get('deleted'):
                    calendars.append(dict(id=item['id'],name=item.get('summaryOverride') or item.get('summary',item['id']),
                                          primary=bool(item.get('primary')),timezone=item.get('timeZone')))
            page = result.get('nextPageToken')
            if not page:return calendars

    def list_calendars(self):
        with self.lock:
            if not set(SCOPES).issubset(self._scopes()):
                raise CalendarError('Connect Calendar permission in Settings first.')
            self.calendars = self._calendars(self._access())
            self.last_error = None
            return self.calendars

    def gmail_get(self, path, query=None, expected_account=None):
        # This adapter has no write method and accepts only the endpoints it uses.
        if not re.fullmatch(r'/(profile|threads|history|threads/[A-Za-z0-9_-]{1,128})', path):
            raise ValueError('Unsupported Gmail endpoint')
        with self.lock:
            if GMAIL_SCOPE not in self._scopes():
                raise CalendarError('Connect Gmail read-only permission first.')
            if expected_account and self._load().get('account_id') != expected_account:
                raise CalendarError('The Google account changed. Start sync again for the connected account.')
            url = GMAIL_URL + path + ('?' + urllib.parse.urlencode(query) if query else '')
            return self.request(url, token=self._access())

    def disconnect(self):
        with self.lock:
            bundle = self._load()
            warning = None
            if bundle.get('refresh_token'):
                try:
                    self.request('https://oauth2.googleapis.com/revoke','POST',{'token':bundle['refresh_token']},form=True)
                except CalendarError:
                    warning = 'Local access removed. Google revocation could not be confirmed; you can also remove access in your Google Account.'
            # Retain the client configuration; remove all user authorization.
            client = {k:bundle[k] for k in ['client_id','client_secret'] if k in bundle}
            if client:self.store.set(client)
            else:self.store.delete()
            self.bundle = client
            self.pending, self.calendars = None, []
            self.state = dict(configured=bool(client))
            atomic_json(self.state_path,self.state)
            self.last_error = warning
            return self.status()

    def upsert(self, calendar_id: str, meeting: dict, link: str, event_id: str, expected_account=None):
        with self.lock:
            if expected_account is not None and self._load().get('account_id') != expected_account:
                raise CalendarError('The connected Google account changed. Reconnect the original meeting account before syncing.')
            token = self._access()
            base = API_URL+'/calendars/'+urllib.parse.quote(calendar_id,safe='')+'/events'
            payload = event_payload(meeting,link)
            try:
                return self.request(base+'?sendUpdates=none','POST',dict(payload,id=event_id),token=token)
            except CalendarError as exc:
                if getattr(exc,'status',None) != 409:raise
            existing = self.request(base+'/'+event_id,token=token)
            if existing.get('extendedProperties',{}).get('private',{}).get('meetingAssistantId') != meeting['id']:
                raise CalendarError('The calendar event ID is already in use by another event. No event was changed.')
            return self.request(base+'/'+event_id+'?sendUpdates=none','PATCH',payload,token=token)

    def delete_event(self, calendar_id: str, event_id: str, meeting_id: str, expected_account=None):
        """Delete only the event this app created for the meeting. Returns False if it is already gone."""
        with self.lock:
            if expected_account is not None and self._load().get('account_id') != expected_account:
                raise CalendarError('This calendar event belongs to another Google account. Sign in with that account, '
                                    'or delete the meeting and keep the event.')
            token = self._access()
            url = API_URL+'/calendars/'+urllib.parse.quote(calendar_id,safe='')+'/events/'+urllib.parse.quote(event_id,safe='')
            try:
                existing = self.request(url,token=token)
                if existing.get('status') == 'cancelled':
                    return False
                if existing.get('extendedProperties',{}).get('private',{}).get('meetingAssistantId') != meeting_id:
                    raise CalendarError('The calendar event does not belong to this meeting. No event was deleted.')
                self.request(url+'?sendUpdates=none','DELETE',token=token)
                return True
            except CalendarError as exc:
                if getattr(exc,'status',None) in {404,410}:
                    return False
                raise


def event_payload(meeting: dict, link: str):
    start = dt.datetime.fromisoformat(meeting.get('started_at') or meeting['created'])
    end = dt.datetime.fromisoformat(meeting['ended_at']) if meeting.get('ended_at') else start+dt.timedelta(seconds=max(1,meeting.get('duration',0)))
    if end<=start:end=start+dt.timedelta(seconds=1)
    return dict(summary=meeting['title'],
        description='<p><a href="'+html.escape(link,quote=True)+'">Open recording, transcript, and notes</a></p><p>Meeting Assistant must be running. This link opens locally on the recording Mac.</p>',
        start={'dateTime':start.isoformat()},end={'dateTime':end.isoformat()},
        extendedProperties={'private':{'meetingAssistantId':meeting['id']}},
        reminders={'useDefault':False},transparency='transparent')
