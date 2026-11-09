"""Bounded Gmail read-only sync. Cache is rebuildable and never sent to AI.

One run continues page by page until the cache is current. Each page is saved, so a stop or a
recording keeps the work done; the next run continues from there. Changes come newest first.
"""
import base64
from contextlib import closing
import hashlib
from html.parser import HTMLParser
from email.message import Message
import json
from pathlib import Path
import sqlite3
import threading
import time

from .google_calendar import CalendarError, RATE_LIMIT_REASONS
from .work_items import canonical

MAX_THREADS = 200
PAGE_SIZE = 20
# Seconds to wait before each retry after a Gmail rate limit.
RETRY_DELAYS = (2, 5, 15, 30)
# One run reads at most this many pages; the next run continues.
MAX_STEPS = 100
# History pages read before the threads; the rest stays for the next pass.
MAX_HISTORY_PAGES = 50


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.hidden = [], 0
    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style'}: self.hidden += 1
        if tag in {'br', 'p', 'div', 'li'} and not self.hidden: self.parts.append('\n')
    def handle_endtag(self, tag):
        if tag in {'script', 'style'} and self.hidden: self.hidden -= 1
    def handle_data(self, value):
        if not self.hidden: self.parts.append(value)


def message_text(payload, depth=0):
    if not isinstance(payload, dict) or depth > 12 or payload.get('filename'):
        return ''
    parts = payload.get('parts', [])
    if parts:
        if not isinstance(parts, list) or len(parts) > 100:
            raise ValueError('Gmail message has too many MIME parts')
        plain = [p for p in parts if p.get('mimeType') == 'text/plain']
        return '\n'.join(message_text(p, depth+1) for p in (plain or parts))[:100000]
    if payload.get('mimeType') not in {'text/plain', 'text/html'}:
        return ''
    data = payload.get('body', {}).get('data', '')
    if not isinstance(data, str) or len(data) > 200000:
        raise ValueError('Gmail message body exceeds the local limit')
    content_type = next((h.get('value','') for h in payload.get('headers',[]) if h.get('name','').lower()=='content-type'), '')
    mime = Message(); mime['content-type'] = content_type
    charset = (mime.get_content_charset() or 'utf-8').lower()
    if charset not in {'utf-8','utf8','windows-1251','cp1251','iso-8859-1','iso-8859-5','us-ascii','koi8-r','utf-16'}:
        charset = 'utf-8'
    raw = base64.urlsafe_b64decode(data + '=' * (-len(data) % 4)).decode(charset, errors='replace')[:100000]
    if payload['mimeType'] == 'text/html':
        parser = _Text(); parser.feed(raw)
        raw = ''.join(parser.parts)
    return raw.strip()


def thread_record(thread, cutoff):
    messages = thread.get('messages')
    if not isinstance(messages, list) or not messages:
        raise ValueError('Gmail returned an invalid thread')
    ordered = sorted((m for m in messages if 'DRAFT' not in m.get('labelIds', [])), key=lambda m: int(m.get('internalDate', 0)))
    relevant = any(int(m.get('internalDate', 0)) >= cutoff * 1000 and set(m.get('labelIds', [])) & {'INBOX', 'SENT'} for m in ordered)
    if not ordered or not relevant:
        return None
    saved, texts = [], []
    for message in ordered[-100:]:
        headers = {h['name'].lower(): h.get('value','') for h in message.get('payload', {}).get('headers', [])}
        body = message_text(message.get('payload', {}))
        saved.append(dict(id=message['id'], sender=headers.get('from',''), subject=headers.get('subject',''),
                          date=int(message.get('internalDate', 0)), sent='SENT' in message.get('labelIds', []), body=body))
        texts.append(f"Message {message['id']}\nFrom: {headers.get('from','')}\nDate: {message.get('internalDate',0)}\nSubject: {headers.get('subject','')}\n{body}")
    content = '\n\n'.join(texts)
    if len(content) > 900000:
        raise ValueError('Gmail thread exceeds the local text limit')
    last = saved[-1]
    return dict(id=thread['id'], subject=last['subject'] or '(No subject)', sender=last['sender'], date=last['date'],
                view='waiting' if last['sent'] else 'needs_reply', messages=saved, text=content,
                revision=hashlib.sha256(content.encode()).hexdigest(), partial=len(ordered)>100, fetched_at=time.time())


class GmailSync:
    def __init__(self, root, google, priority=lambda:False, on_thread=lambda *args:None):
        self.path = Path(root) / 'gmail-cache.sqlite3'
        self.google, self.priority, self.on_thread = google, priority, on_thread
        self.lock = threading.RLock()
        self.cancel = threading.Event()
        self.thread = None
        self.job = dict(running=False, status='idle', error=None)
        with closing(self.connect()) as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS sync_state(account TEXT PRIMARY KEY, document TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS threads(account TEXT NOT NULL,id TEXT NOT NULL,document TEXT NOT NULL,view TEXT,date INTEGER,summary TEXT,PRIMARY KEY(account,id));
                CREATE INDEX IF NOT EXISTS mail_view_date ON threads(account,view,date DESC);
                CREATE INDEX IF NOT EXISTS mail_date ON threads(account,date DESC);''')
        self.path.chmod(0o600)
    def connect(self):
        return sqlite3.connect(self.path, timeout=5)
    def _state(self, account):
        with closing(self.connect()) as db:
            row = db.execute('SELECT document FROM sync_state WHERE account=?', (account,)).fetchone()
        return json.loads(row[0]) if row else {}
    def _save(self, account, state, key=None, record=None):
        with closing(self.connect()) as db, db:
            if key:
                if record is None: db.execute('DELETE FROM threads WHERE account=? AND id=?', (account,key))
                else:
                    summary = {name:record[name] for name in ('id','subject','sender','date','view','fetched_at','partial')}
                    db.execute('INSERT OR REPLACE INTO threads VALUES (?,?,?,?,?,?)', (account,key,canonical(record),record['view'],record['date'],canonical(summary)))
            db.execute('INSERT OR REPLACE INTO sync_state VALUES (?,?)', (account,canonical(state)))
    def _account(self):
        status = self.google.status()
        if not status.get('capabilities', {}).get('gmail'):
            raise CalendarError('Connect Gmail read-only permission first.')
        return status['account']
    def status(self):
        google = self.google.status()
        account = google.get('account','')
        with self.lock: job = dict(self.job)
        state = self._state(account) if account else {}
        with closing(self.connect()) as db:
            count = db.execute('SELECT count(*) FROM threads WHERE account=?', (account,)).fetchone()[0]
        with closing(self.connect()) as db:
            cached_accounts = [row[0] for row in db.execute('SELECT account FROM sync_state ORDER BY account')]
        return dict(account=account, cached_accounts=cached_accounts, connected=google.get('capabilities',{}).get('gmail',False), count=count,
                    sync=state, job=job)
    def listing(self, view='needs_reply'):
        if view not in {'needs_reply','waiting','all'}: raise ValueError('Invalid Gmail view')
        account = self._account()
        with closing(self.connect()) as db:
            if view == 'all':
                rows = db.execute('SELECT summary FROM threads WHERE account=? ORDER BY date DESC LIMIT 200',(account,)).fetchall()
            else:
                rows = db.execute('SELECT summary FROM threads WHERE account=? AND view=? ORDER BY date DESC LIMIT 200',(account,view)).fetchall()
        return [json.loads(row[0]) for row in rows]
    def detail(self, key, expected_account=None):
        account = self._account()
        if expected_account is not None and account != expected_account:
            raise CalendarError('The Google account changed. Reopen the email thread.')
        with closing(self.connect()) as db:
            row = db.execute('SELECT document FROM threads WHERE account=? AND id=?', (account,key)).fetchone()
        if not row: raise ValueError('This cached Gmail thread is unavailable. Sync again.')
        return json.loads(row[0])
    def start(self):
        account = self._account()
        with self.lock:
            if self.thread and self.thread.is_alive(): return self.status()
            if self.priority(): raise ValueError('Stop recording/processing before syncing Gmail.')
            self.cancel.clear()
            self.job = dict(running=True,status='syncing',error=None)
            self.thread = threading.Thread(target=self._run,args=(account,),daemon=True)
            self.thread.start()
        return self.status()
    def stop(self):
        self.cancel.set()
        return self.status()
    def _check(self):
        if self.cancel.is_set(): raise InterruptedError('cancelled')
        if self.priority(): raise InterruptedError('paused for recording or processing')
    def _get(self, account, path, query=None):
        # A rate limit (429, or 403 with a rate-limit reason) waits and retries; other errors stop the run.
        for delay in RETRY_DELAYS + (None,):
            self._check()
            try:
                result = self.google.gmail_get(path,query,expected_account=account)
                break
            except CalendarError as exc:
                limited = getattr(exc,'status',None) == 429 or getattr(exc,'reason','') in RATE_LIMIT_REASONS
                if not limited or delay is None: raise
                with self.lock: self.job = dict(self.job, status='waiting for Gmail rate limit')
                if self.cancel.wait(delay): raise InterruptedError('cancelled')
        self._check()
        if not isinstance(result, dict): raise ValueError('Invalid Gmail response')
        return result
    def _run(self, account):
        try:
            done = False
            for _ in range(MAX_STEPS):
                # The run ends after a full history pass, so mail that came during the first window is in too.
                was_history = self._state(account).get('mode') == 'history'
                state = self._step(account)
                done = was_history and not (state.get('pending') or state.get('page'))
                with self.lock: self.job = dict(running=True,status='syncing',error=None,pending=len(state.get('pending') or []))
                if done: break
            with self.lock: self.job = dict(running=False,status='synced' if done else 'continue',error=None)
        except InterruptedError as exc:
            with self.lock: self.job = dict(running=False,status=str(exc),error=None)
        except Exception as exc:
            # Never include message bodies or credential-bearing exception strings in public errors.
            with self.lock: self.job = dict(running=False,status='error',error=str(exc) if isinstance(exc,CalendarError) else 'Gmail sync failed. Retry the current page.')
    def _step(self, account):
        """One page: list the next threads or history changes, then fetch up to PAGE_SIZE threads."""
        state = self._state(account)
        if not state.get('mode'):
            profile = self._get(account,'/profile')
            if profile.get('emailAddress') != account: raise ValueError('Gmail account identity changed')
            if not str(profile.get('historyId','')).isdigit(): raise ValueError('Invalid Gmail history cursor')
            state = dict(mode='full', anchor=str(profile['historyId']), cutoff=int(time.time())-30*86400,
                         count=0, pending=[], page=None)
            self._save(account,state)
        # One page (20 threads) per step; each step is saved, so a stop resumes durably.
        if not state.get('pending'):
            if state['mode']=='full':
                page = self._get(account,'/threads',dict(q=f"after:{state['cutoff']} {{in:inbox in:sent}}", maxResults=PAGE_SIZE, **({'pageToken':state['page']} if state.get('page') else {})))
                ids = [row['id'] for row in page.get('threads', [])]
            else:
                # Read the history pages first (IDs only), then fetch the threads newest first.
                # History is oldest first, so the last change comes last in the pages.
                changed, token = [], state.get('page')
                for _ in range(MAX_HISTORY_PAGES):
                    try:
                        page = self._get(account,'/history',dict(startHistoryId=state['history_id'],maxResults=PAGE_SIZE,**({'pageToken':token} if token else {})))
                    except CalendarError as exc:
                        if getattr(exc,'status',None)!=404: raise
                        state.pop('mode',None); self._save(account,state)
                        raise InterruptedError('history expired; sync again to rebuild the recent window')
                    changed += [message['threadId'] for row in page.get('history',[]) for message in (row.get('messages',[]) + [event['message'] for name in ('messagesAdded','messagesDeleted','labelsAdded','labelsRemoved') for event in row.get(name,[])]) if message.get('threadId')]
                    state['next_history_id'] = str(page['historyId'])
                    token = page.get('nextPageToken')
                    if not token: break
                # Each thread once, at the place of its newest change. Keep all IDs in a durable queue.
                ids = list(dict.fromkeys(reversed(changed)))
                page = dict(nextPageToken=token)
            state.update(pending=ids,next_page=page.get('nextPageToken'))
            self._save(account,state)
        for key in list(state['pending'])[:PAGE_SIZE]:
            try: record = thread_record(self._get(account,'/threads/'+key,{'format':'full'}), state['cutoff'])
            except CalendarError as exc:
                if getattr(exc,'status',None)!=404: raise
                record = None
            self._check()
            # Refresh only sources already promoted to WorkItems; this never extracts new AI proposals.
            self.on_thread(account,key,record)
            state['pending'].remove(key)
            if state['mode']=='full': state['count'] += 1
            self._save(account,state,key,record)
        if not state['pending']:
            state['page'] = state.pop('next_page',None)
            if state['mode']=='full' and (not state['page'] or state['count']>=MAX_THREADS):
                state.update(limited=bool(state['page']), mode='history', history_id=state['anchor'],page=None)
            elif state['mode']=='history' and not state['page']:
                state['history_id'] = state.pop('next_history_id', state['history_id'])
            state['last_sync'] = time.time()
            self._save(account,state)
        return state
    def clear(self, account=None):
        with self.lock:
            if self.thread and self.thread.is_alive(): raise ValueError('Cancel sync and wait for it to finish before clearing the cache.')
            account = account or self.google.status().get('account')
            if not isinstance(account,str) or not account:
                raise ValueError('Choose a cached account to remove')
            with closing(self.connect()) as db, db:
                db.execute('DELETE FROM threads WHERE account=?',(account,))
                db.execute('DELETE FROM sync_state WHERE account=?',(account,))
        return self.status()
    def close(self):
        self.cancel.set()
        if self.thread: self.thread.join(timeout=1)
