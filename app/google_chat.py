"""Selected-space Google Chat polling. GET-only, bounded and independent of AI."""
from contextlib import closing
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import threading
import time

from .google_calendar import CalendarError
from .work_items import canonical

SPACE = re.compile(r'spaces/[A-Za-z0-9_-]{1,128}')
MESSAGE = re.compile(r'spaces/[A-Za-z0-9_-]{1,128}/messages/[A-Za-z0-9_-][A-Za-z0-9_.-]{0,127}')
PAGE_SIZE, MAX_MESSAGES = 20, 200


def timestamp(value):
    if not isinstance(value,str): raise ValueError('Invalid Chat timestamp')
    parsed=dt.datetime.fromisoformat(value.replace('Z','+00:00'))
    if parsed.tzinfo is None: raise ValueError('Chat timestamps need a timezone')
    return parsed.timestamp()


def message_record(message, space, expected=None):
    name=message.get('name')
    if not isinstance(name,str) or not MESSAGE.fullmatch(name) or name.rsplit('/messages/',1)[0]!=space or expected and name!=expected:
        raise ValueError('Chat message identity did not match the selected conversation')
    deleted=bool(message.get('deleteTime') or message.get('deletionMetadata'))
    body='' if deleted else message.get('text','')
    if not isinstance(body,str) or len(body)>100000:
        raise ValueError('Chat message text exceeds the local limit')
    created=message.get('createTime')
    date=timestamp(created or message.get('deleteTime')) if created or message.get('deleteTime') else 0
    if not deleted and not created:raise ValueError('Chat message has no creation time')
    sender=message.get('sender',{})
    thread=message.get('thread',{}).get('name','')
    if thread and (not isinstance(thread,str) or not thread.startswith(space+'/threads/')):
        raise ValueError('Chat thread belongs to another conversation')
    content=dict(name=name,text=body,createTime=created,lastUpdateTime=message.get('lastUpdateTime'),
                 deleteTime=message.get('deleteTime'),deleted=deleted,sender=sender.get('name',''),thread=thread)
    return dict(name=name,space=space,thread=thread,date=date,sender=sender.get('displayName') or sender.get('name','Unknown sender'),
                sender_id=sender.get('name',''),body=body,available=not deleted,revision=hashlib.sha256(canonical(content).encode()).hexdigest(),
                fetched_at=time.time(),updated=message.get('lastUpdateTime'))


class ChatSync:
    def __init__(self,root,google,priority=lambda:False,on_message=lambda *args:None,on_unavailable=lambda *args:None):
        self.path=Path(root)/'chat-cache.sqlite3'
        self.google,self.priority,self.on_message,self.on_unavailable=google,priority,on_message,on_unavailable
        self.lock=threading.RLock();self.cancel=threading.Event();self.thread=None
        self.job=dict(running=False,status='idle',error=None)
        with closing(self.connect()) as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS accounts(id TEXT PRIMARY KEY,label TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS spaces(account TEXT,name TEXT,document TEXT,PRIMARY KEY(account,name));
                CREATE TABLE IF NOT EXISTS state(account TEXT,space TEXT,document TEXT,PRIMARY KEY(account,space));
                CREATE TABLE IF NOT EXISTS messages(account TEXT,name TEXT,space TEXT,date REAL,summary TEXT,document TEXT,PRIMARY KEY(account,name));
                CREATE INDEX IF NOT EXISTS chat_space_date ON messages(account,space,date DESC);''')
        self.path.chmod(0o600)
    def connect(self):return sqlite3.connect(self.path,timeout=5)
    def _account(self):
        status=self.google.status()
        if not status.get('connected') or not status.get('capabilities',{}).get('chat') or not status.get('chat_account_id'):
            raise CalendarError('Connect Google Chat read-only permission first.')
        return status['chat_account_id']
    def _check(self,account):
        if self.cancel.is_set():raise InterruptedError('cancelled')
        if self.priority():raise InterruptedError('paused for recording or processing')
        if self._account()!=account:raise InterruptedError('Google account changed; sync again')
    def _get(self,account,resource,query=None):
        self._check(account)
        result=self.google.chat_get(resource,query,expected_account=account)
        self._check(account)
        if not isinstance(result,dict):raise ValueError('Invalid Chat response')
        return result
    def _state(self,account,space):
        with closing(self.connect()) as db:
            row=db.execute('SELECT document FROM state WHERE account=? AND space=?',(account,space)).fetchone()
        return json.loads(row[0]) if row else {}
    def _label(self,account):
        status=self.google.status()
        return status.get('account',account) if status.get('chat_account_id')==account else account
    def _save(self,account,space,state,record=None):
        with closing(self.connect()) as db,db:
            db.execute('INSERT OR REPLACE INTO accounts VALUES (?,?)',(account,self._label(account)))
            if record:
                summary={key:record[key] for key in ('name','space','thread','date','sender','available','revision','fetched_at')}
                summary['excerpt']=record['body'][:160]
                db.execute('INSERT OR REPLACE INTO messages VALUES (?,?,?,?,?,?)',(account,record['name'],space,record['date'],canonical(summary),canonical(record)))
            db.execute('INSERT OR REPLACE INTO state VALUES (?,?,?)',(account,space,canonical(state)))
    def status(self):
        google=self.google.status();account=google.get('chat_account_id','')
        with self.lock:job=dict(self.job)
        with closing(self.connect()) as db:
            accounts=[dict(id=row[0],label=row[1]) for row in db.execute('SELECT id,label FROM accounts ORDER BY label')]
            rows=db.execute('SELECT space,document FROM state WHERE account=?',(account,)).fetchall()
        states={space:{key:value for key,value in json.loads(document).items() if key!='pending'} for space,document in rows}
        return dict(connected=bool(google.get('capabilities',{}).get('chat') and account),account=google.get('account',''),
                    account_id=account,cached_accounts=accounts,states=states,job=job)
    def spaces(self):
        """Known conversations with their cached participants and latest activity, newest first."""
        account=self._account()
        with closing(self.connect()) as db:
            spaces=[json.loads(row[0]) for row in db.execute('SELECT document FROM spaces WHERE account=? ORDER BY name',(account,))]
            stats={row[0]:dict(count=row[1],last=row[2]) for row in db.execute('SELECT space,count(*),max(date) FROM messages WHERE account=? GROUP BY space',(account,))}
            people={}
            for space,sender,count in db.execute("SELECT space,json_extract(summary,'$.sender'),count(*) FROM messages WHERE account=? GROUP BY space,2 ORDER BY 3 DESC",(account,)):
                people.setdefault(space,[]).append(sender)
        for space in spaces:
            space.update(count=stats.get(space['name'],{}).get('count',0),last=stats.get(space['name'],{}).get('last') or 0,participants=people.get(space['name'],[]))
        return sorted(spaces,key=lambda s:(-s['last'],s['label'].casefold()))
    def conversation(self,space):
        """The cached messages of one conversation in reading order, with their full text."""
        if not isinstance(space,str) or not SPACE.fullmatch(space):raise ValueError('Invalid Chat space')
        account=self._account()
        with closing(self.connect()) as db:
            rows=db.execute('SELECT document FROM messages WHERE account=? AND space=? ORDER BY date DESC LIMIT ?',(account,space,MAX_MESSAGES)).fetchall()
        return [json.loads(row[0]) for row in reversed(rows)]
    def messages(self,space):
        if not isinstance(space,str) or not SPACE.fullmatch(space):raise ValueError('Invalid Chat space')
        account=self._account()
        with closing(self.connect()) as db:
            return [json.loads(row[0]) for row in db.execute('SELECT summary FROM messages WHERE account=? AND space=? ORDER BY date DESC LIMIT 200',(account,space))]
    def detail(self,name,expected_account=None):
        if not isinstance(name,str) or not MESSAGE.fullmatch(name):raise ValueError('Invalid Chat message')
        account=self._account()
        if expected_account is not None and account!=expected_account:raise CalendarError('The Chat account changed. Reopen the message.')
        with closing(self.connect()) as db:
            row=db.execute('SELECT document FROM messages WHERE account=? AND name=?',(account,name)).fetchone()
        if not row:raise ValueError('This Chat message is not cached. Sync the conversation.')
        return json.loads(row[0])
    def start(self,kind,resource='',restart=False):
        if kind not in {'spaces','messages','refresh'} or type(restart) is not bool:raise ValueError('Invalid Chat sync action')
        if kind=='messages' and (not isinstance(resource,str) or not SPACE.fullmatch(resource)):raise ValueError('Choose a Chat space')
        if kind=='refresh' and (not isinstance(resource,str) or not MESSAGE.fullmatch(resource)):raise ValueError('Invalid Chat message')
        account=self._account()
        with self.lock:
            if self.thread and self.thread.is_alive():raise ValueError('A Chat sync is already running')
            if self.priority():raise ValueError('Stop recording/processing before syncing Google Chat')
            self.cancel.clear();self.job=dict(running=True,status='syncing '+kind,error=None)
            self.thread=threading.Thread(target=self._run,args=(account,kind,resource,restart),daemon=True)
            self.thread.start()
        return self.status()
    def _run(self,account,kind,resource,restart):
        try:
            if kind=='spaces':self._discover(account,restart)
            elif kind=='messages':self._messages(account,resource,restart)
            else:self._refresh(account,resource)
        except InterruptedError as exc:
            with self.lock:self.job=dict(running=False,status=str(exc),error=None)
        except Exception as exc:
            if isinstance(exc,CalendarError) and getattr(exc,'status',None) in {403,404} and kind!='spaces':
                try:
                    self._check(account)
                    with self.lock:
                        self.on_unavailable(account,resource if kind=='refresh' else resource+'/')
                        self._unavailable(account,resource,kind=='refresh')
                except Exception:pass
            with self.lock:self.job=dict(running=False,status='error',error=str(exc) if isinstance(exc,CalendarError) else 'Chat data could not be processed. Restart the recent window or retry.')
    def _done(self,state):
        with self.lock:self.job=dict(running=False,status='synced' if state.get('complete',True) else 'continue',error=None)
    def _discover(self,account,restart):
        state={} if restart else self._state(account,'')
        if state.get('complete'):state={}
        query=dict(pageSize=50)
        if state.get('page'):query['pageToken']=state['page']
        result=self._get(account,'spaces',query)
        records=result.get('spaces',[])
        if not isinstance(records,list) or len(records)>50:raise ValueError('Invalid Chat spaces page')
        parsed=[]
        for row in records:
            name=row.get('name')
            if not isinstance(name,str) or not SPACE.fullmatch(name):raise ValueError('Invalid Chat space identity')
            parsed.append(dict(name=name,label=row.get('displayName') or name,type=row.get('spaceType','UNKNOWN'),fetched_at=time.time()))
        remaining=max(0,200-state.get('count',0));truncated=len(parsed)>remaining
        parsed=parsed[:remaining]
        count=state.get('count',0)+len(parsed);page=result.get('nextPageToken')
        state=dict(count=count,page=None if count>=200 else page,complete=not page or count>=200,limited=bool((page or truncated) and count>=200))
        self._check(account)
        with closing(self.connect()) as db,db:
            db.execute('INSERT OR REPLACE INTO accounts VALUES (?,?)',(account,self._label(account)))
            db.executemany('INSERT OR REPLACE INTO spaces VALUES (?,?,?)',[(account,row['name'],canonical(row)) for row in parsed])
            db.execute('INSERT OR REPLACE INTO state VALUES (?,?,?)',(account,'',canonical(state)))
        self._done(state)
    def _messages(self,account,space,restart):
        state=self._state(account,space)
        if restart or not state or state.get('complete'):
            upper=dt.datetime.now(dt.timezone.utc)
            state=dict(cutoff=(upper-dt.timedelta(days=30)).isoformat(),upper=upper.isoformat(),page=None,count=0,pending=[],complete=False)
            self._save(account,space,state)
        if not state.get('pending') and 'next_page' not in state:
            query=dict(pageSize=PAGE_SIZE,orderBy='createTime desc',showDeleted='true',
                       filter=f'createTime > "{state["cutoff"]}" AND createTime < "{state["upper"]}"')
            if state.get('page'):query['pageToken']=state['page']
            result=self._get(account,space+'/messages',query)
            rows=result.get('messages',[])
            if not isinstance(rows,list) or len(rows)>PAGE_SIZE:raise ValueError('Invalid Chat messages page')
            records=[message_record(row,space) for row in rows]
            remaining=max(0,MAX_MESSAGES-state['count'])
            state.update(pending=records[:remaining],next_page=result.get('nextPageToken'),page_limited=len(records)>remaining)
            self._save(account,space,state)
        for record in list(state['pending']):
            with self.lock:
                self._check(account);self.on_message(account,record)
                state['pending'].pop(0);state['count']+=1
                self._save(account,space,state,record)
        page=state.pop('next_page',None)
        truncated=state.pop('page_limited',False)
        state.update(page=page,complete=not page or state['count']>=MAX_MESSAGES,limited=bool((page or truncated) and state['count']>=MAX_MESSAGES),last_sync=time.time())
        if state['complete']:state['page']=None
        self._save(account,space,state);self._done(state)
    def _refresh(self,account,name):
        space=name.rsplit('/messages/',1)[0]
        try:record=message_record(self._get(account,name),space,expected=name)
        except CalendarError as exc:
            if getattr(exc,'status',None) not in {403,404}:raise
            with self.lock:
                self._check(account);self.on_unavailable(account,name)
                self._unavailable(account,name,True)
            self._done({});return
        with self.lock:
            self._check(account);self.on_message(account,record)
            self._save(account,space,self._state(account,space),record)
        self._done({})
    def _unavailable(self,account,resource,is_message):
        with closing(self.connect()) as db:
            rows=db.execute('SELECT document FROM messages WHERE account=? AND '+('name' if is_message else 'space')+'=?',(account,resource)).fetchall()
        for row in rows:
            record=json.loads(row[0]);record.update(available=False,body='',fetched_at=time.time())
            self._save(account,record['space'],self._state(account,record['space']),record)

    def stop(self):self.cancel.set();return self.status()
    def clear(self,account):
        if not isinstance(account,str) or not account:raise ValueError('Choose a cached Chat account')
        with self.lock:
            if self.thread and self.thread.is_alive():raise ValueError('Cancel Chat sync and wait before clearing the cache')
            with closing(self.connect()) as db,db:
                for table in ('messages','spaces','state'):db.execute(f'DELETE FROM {table} WHERE account=?',(account,))
                db.execute('DELETE FROM accounts WHERE id=?',(account,))
        return self.status()
    def close(self):
        self.cancel.set()
        if self.thread:self.thread.join(timeout=1)
