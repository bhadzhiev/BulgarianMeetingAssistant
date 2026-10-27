"""GitHub.com GET-only source with explicit credentials and repository selection."""
from contextlib import closing
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from .google_calendar import KeychainStore
from .storage import atomic_json
from .work_items import canonical

LOGIN=re.compile(r'[A-Za-z0-9][A-Za-z0-9-]{0,38}')
REPO=re.compile(r'[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}')
FILTERS={'all':'','assigned':'assignee','created':'author','mentioned':'mentions'}
PAGE_SIZE,MAX_ITEMS=20,200
# The open-item overview reads GET /issues, which spans every repository that the token can read.
OVERVIEW_PAGE_SIZE,OVERVIEW_MAX=100,300
OVERVIEW_FILTERS={'all':'all','assigned':'assigned','created':'created','mentioned':'mentioned'}


class GitHubError(RuntimeError):pass


class TokenStore(KeychainStore):
    def __init__(self,root):
        super().__init__(hashlib.sha256(str(Path(root).resolve()).encode()).hexdigest())
        self.service=b'local.bulgarian-meeting-assistant.github'


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def http_get(resource,query,token):
    # Never follow response links or redirects with a credential-bearing request.
    url='https://api.github.com'+resource+('?' + urllib.parse.urlencode(query) if query else '')
    request=urllib.request.Request(url,headers={'Accept':'application/vnd.github+json','Authorization':'Bearer '+token,
        'X-GitHub-Api-Version':'2026-03-10','User-Agent':'BulgarianMeetingAssistant'},method='GET')
    try:
        with urllib.request.build_opener(_NoRedirect).open(request,timeout=30) as response:
            raw=response.read(8*1024*1024+1)
            if len(raw)>8*1024*1024:raise GitHubError('GitHub response exceeds the local limit.')
            return dict(data=json.loads(raw),has_next=bool(re.search(r'rel="next"',response.headers.get('Link',''))))
    except urllib.error.HTTPError as exc:
        error=GitHubError(f'GitHub request failed (HTTP {exc.code}). Check repository access, token expiry/approval or rate limits. For redirects, select the current repository name.')
        error.status=exc.code;error.rate_limited=exc.headers.get('X-RateLimit-Remaining')=='0' or bool(exc.headers.get('Retry-After'));raise error from None
    except (urllib.error.URLError,TimeoutError):raise GitHubError('GitHub could not be reached. Retry later.') from None


def repo_name(value):
    if not isinstance(value,str) or not REPO.fullmatch(value) or value.rsplit('/',1)[1] in {'.','..'}:
        raise ValueError('Enter a GitHub repository as owner/name')
    return value


class GitHubConnection:
    def __init__(self,root,store=None,request=http_get):
        self.store=store or TokenStore(root);self.request=request;self.lock=threading.RLock();self.bundle=None;self.loaded=False
        self.path=Path(root)/'.github-account.json'
        self.configured=self.path.exists()
    def _load(self):
        if not self.loaded:self.bundle=self.store.get() if self.configured else {};self.loaded=True
        return self.bundle or {}
    def status(self):
        acquired=self.lock.acquire(blocking=False)
        try:
            bundle=self._load() if acquired else self.bundle or {}
            return dict(connected=bool(bundle.get('token') and bundle.get('id')),account_id=str(bundle.get('id','')),login=bundle.get('login',''))
        except Exception:return dict(connected=False,account_id='',login='',error='GitHub credentials could not be read from Keychain. Reconnect.')
        finally:
            if acquired:self.lock.release()
    def connect(self,token):
        if not isinstance(token,str) or not re.fullmatch(r'github_pat_[A-Za-z0-9_]{20,500}',token):
            raise ValueError('Use a fine-grained GitHub personal access token with read-only repository permissions')
        user=self.request('/user',None,token)['data']
        if type(user.get('id')) is not int or user['id']<=0 or not isinstance(user.get('login'),str) or not LOGIN.fullmatch(user['login']):
            raise GitHubError('GitHub returned an invalid account identity.')
        with self.lock:
            bundle=dict(id=user['id'],login=user['login'],token=token)
            self.store.set(bundle);self.bundle=bundle;self.loaded=True;self.configured=True
            atomic_json(self.path,dict(configured=True,account_id=str(user['id']),login=user['login']))
        return self.status()
    def disconnect(self):
        with self.lock:
            self.store.delete();self.bundle={};self.loaded=True;self.configured=False;self.path.unlink(missing_ok=True)
        return self.status()
    def get(self,resource,query=None,expected_account=None):
        allowed=resource in {'/user','/issues','/search/issues'} or re.fullmatch(r'/users/[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})',resource)
        if not allowed:
            match=re.fullmatch(r'/repos/([^/]+/[^/]+)(?:/(issues|pulls)/([1-9][0-9]*))?',resource)
            if not match:
                match=re.fullmatch(r'/repos/([^/]+/[^/]+)/(?:commits(?:/[a-f0-9]{40}(?:/pulls)?)?|pulls/[1-9][0-9]*/files|git/blobs/[a-f0-9]{40}|compare/[a-f0-9]{40}\.\.\.[a-f0-9]{40})',resource)
            if not match:raise ValueError('Unsupported GitHub read endpoint')
            repo_name(match[1])
        with self.lock:
            bundle=self._load()
            if not bundle.get('token'):raise GitHubError('Connect GitHub in My Work first.')
            if expected_account is not None and str(bundle.get('id'))!=expected_account:raise GitHubError('The GitHub account changed. Sync again.')
            return self.request(resource,query,bundle['token'])


def item_record(issue,repo,user_id,pull=None):
    number=issue.get('number');issue_id=issue.get('id')
    if type(number) is not int or number<=0 or type(issue_id) is not int or issue_id<=0:raise ValueError('Invalid GitHub issue identity')
    expected=f'https://api.github.com/repos/{repo["full_name"]}/issues/{number}'
    if not isinstance(issue.get('url'),str) or issue['url'].casefold()!=expected.casefold():raise ValueError('GitHub result belongs to another repository')
    title=issue.get('title');body=issue.get('body') or ''
    if not isinstance(title,str) or not title.strip() or len(title)>1000 or not isinstance(body,str) or len(body)>200000:
        raise ValueError('GitHub text exceeds the local limit')
    state=issue.get('state')
    if state not in {'open','closed'}:raise ValueError('Invalid GitHub issue state')
    kind='pull_request' if 'pull_request' in issue else 'issue'
    metadata={}
    if kind=='pull_request':
        if not isinstance(pull,dict) or pull.get('number')!=number or pull.get('base',{}).get('repo',{}).get('id')!=repo['id']:
            raise ValueError('Pull request identity did not match the repository')
        if pull.get('state')!=state:raise GitHubError('GitHub changed while reading the pull request. Retry this page.')
        merged=bool(pull.get('merged_at') or pull.get('merged'))
        if merged and state!='closed':raise ValueError('Invalid merged PR state')
        state='merged' if merged else state
        metadata=dict(pull_id=pull.get('id'),draft=bool(pull.get('draft')),head_sha=pull.get('head',{}).get('sha'),merge_sha=pull.get('merge_commit_sha'))
    assignees=[str(a['id']) for a in issue.get('assignees',[]) if type(a.get('id')) is int]
    author=str(issue.get('user',{}).get('id',''))
    content=dict(issue_id=issue_id,repository_id=repo['id'],repository=repo['full_name'],number=number,kind=kind,title=title,body=body,state=state,
                 updated=issue.get('updated_at'),assignees=assignees,author=author,**metadata)
    source_text=f'{repo["full_name"]} #{number}: {title}\nGitHub state: {state}\n\n{body}'
    return dict(content,text=source_text,url=f'https://github.com/{repo["full_name"]}/{"pull" if kind=="pull_request" else "issues"}/{number}',
                revision=hashlib.sha256(canonical(content).encode()).hexdigest(),fetched_at=time.time(),available=True,
                assigned=str(user_id) in assignees,created=author==str(user_id))


class GitHubSync:
    def __init__(self,root,connection,priority=lambda:False,on_item=lambda *args:None,on_unavailable=lambda *args:None):
        self.path=Path(root)/'github-cache.sqlite3';self.connection=connection;self.priority=priority
        self.on_item,self.on_unavailable=on_item,on_unavailable
        self.lock=threading.RLock();self.cancel=threading.Event();self.thread=None;self.job=dict(running=False,status='idle',error=None)
        with closing(self.db()) as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS accounts(id TEXT PRIMARY KEY,login TEXT);
                CREATE TABLE IF NOT EXISTS repos(account TEXT,id INTEGER,document TEXT,PRIMARY KEY(account,id));
                CREATE TABLE IF NOT EXISTS state(account TEXT,repo INTEGER,filter TEXT,document TEXT,PRIMARY KEY(account,repo,filter));
                CREATE TABLE IF NOT EXISTS objects(account TEXT,id INTEGER,repo INTEGER,kind TEXT,number INTEGER,summary TEXT,document TEXT,PRIMARY KEY(account,id));
                CREATE TABLE IF NOT EXISTS matches(account TEXT,repo INTEGER,filter TEXT,id INTEGER,generation TEXT,PRIMARY KEY(account,repo,filter,id));
                CREATE INDEX IF NOT EXISTS github_matches ON matches(account,repo,filter,generation);''')
        self.path.chmod(0o600)
    def db(self):return sqlite3.connect(self.path,timeout=5)
    def _account(self):
        status=self.connection.status()
        if not status['connected']:raise GitHubError('Connect GitHub in My Work first.')
        return status['account_id']
    def _check(self,account):
        if self.cancel.is_set():raise InterruptedError('cancelled')
        if self.priority():raise InterruptedError('paused for recording or processing')
        if self._account()!=account:raise InterruptedError('GitHub account changed; sync again')
    def _get(self,account,resource,query=None):
        self._check(account);result=self.connection.get(resource,query,expected_account=account);self._check(account)
        return result
    def _state(self,account,repo,role):
        with closing(self.db()) as db:row=db.execute('SELECT document FROM state WHERE account=? AND repo=? AND filter=?',(account,repo,role)).fetchone()
        return json.loads(row[0]) if row else {}
    def _save(self,account,repo,role,state,record=None):
        with closing(self.db()) as db,db:
            if record:
                summary={k:record.get(k) for k in ('issue_id','repository_id','repository','number','kind','title','state','url','available','revision','fetched_at','assigned','created','updated')}
                db.execute('INSERT OR REPLACE INTO objects VALUES (?,?,?,?,?,?,?)',(account,record['issue_id'],record['repository_id'],record['kind'],record['number'],canonical(summary),canonical(record)))
                if state.get('generation'):db.execute('INSERT OR REPLACE INTO matches VALUES (?,?,?,?,?)',(account,repo,role,record['issue_id'],state['generation']))
            if role:db.execute('INSERT OR REPLACE INTO state VALUES (?,?,?,?)',(account,repo,role,canonical(state)))
    def status(self):
        connection=self.connection.status();account=connection['account_id']
        with self.lock:job=dict(self.job)
        with closing(self.db()) as db:
            accounts=[dict(id=row[0],login=row[1]) for row in db.execute('SELECT id,login FROM accounts')]
            rows=db.execute('SELECT repo,filter,document FROM state WHERE account=?',(account,)).fetchall()
        states={str(repo)+':'+role:{k:v for k,v in json.loads(doc).items() if k!='pending'} for repo,role,doc in rows}
        return dict(connection=connection,job=job,states=states,cached_accounts=accounts)
    def repos(self):
        account=self._account()
        with closing(self.db()) as db:repos=[json.loads(row[0]) for row in db.execute('SELECT document FROM repos WHERE account=?',(account,))]
        return sorted(repos,key=lambda r:r['full_name'].casefold())
    def listing(self,repo,role='all',kind='all'):
        if type(repo) is not int or repo<=0 or role not in FILTERS or kind not in {'all','issue','pull_request'}:raise ValueError('Invalid GitHub view')
        account=self._account();state=self._state(account,repo,role)
        with closing(self.db()) as db:
            rows=db.execute('SELECT o.summary FROM objects o JOIN matches m ON o.account=m.account AND o.id=m.id WHERE m.account=? AND m.repo=? AND m.filter=? AND m.generation=? ORDER BY o.number DESC LIMIT 200',
                (account,repo,role,state.get('generation',''))).fetchall()
        records=[json.loads(row[0]) for row in rows]
        return [r for r in records if (kind=='all' or r['kind']==kind) and (role!='assigned' or r['assigned']) and (role!='created' or r['created'])]
    def overview(self,role='all',kind='all'):
        """Open issues and pull requests from the last overview sync of this filter, newest change first."""
        if role not in OVERVIEW_FILTERS or kind not in {'all','issue','pull_request'}:raise ValueError('Invalid GitHub view')
        account=self._account();state=self._state(account,0,'open:'+role)
        with closing(self.db()) as db:
            rows=db.execute("SELECT o.summary FROM objects o JOIN matches m ON o.account=m.account AND o.id=m.id WHERE m.account=? AND m.repo=0 AND m.filter=? AND (? OR m.generation=?) ORDER BY json_extract(o.summary,'$.updated') DESC LIMIT ?",
                (account,'open:'+role,not state.get('complete',False),state.get('generation',''),OVERVIEW_MAX)).fetchall()
        records=[json.loads(row[0]) for row in rows]
        return dict(items=[r for r in records if kind=='all' or r['kind']==kind],state={k:v for k,v in state.items() if k not in {'generation','pending','has_next'}})
    def start_overview(self,role='all'):
        if role not in OVERVIEW_FILTERS:raise ValueError('Invalid GitHub filter')
        account=self._account()
        with self.lock:
            if self.thread and self.thread.is_alive():raise ValueError('A GitHub sync is already running')
            if self.priority():raise ValueError('Stop recording/processing before syncing GitHub')
            self.cancel.clear();self.job=dict(running=True,status='syncing',error=None)
            self.thread=threading.Thread(target=self._run_overview,args=(account,role),daemon=True);self.thread.start()
        return self.status()
    def _run_overview(self,account,role):
        try:
            user=self._get(account,'/user')['data']
            if str(user.get('id'))!=account or not LOGIN.fullmatch(user.get('login','')):raise GitHubError('GitHub user identity changed. Reconnect.')
            with closing(self.db()) as db,db:db.execute('INSERT OR REPLACE INTO accounts VALUES (?,?)',(account,user['login']))
            key='open:'+role;state=self._state(account,0,key)
            if not state or state.get('complete') or 'page' not in state or state.get('login')!=user['login']:
                state=dict(generation=uuid.uuid4().hex,complete=False,count=0,login=user['login'],page=1,pending=[],last_sync=state.get('last_sync'))
                self._save(account,0,key,state)
            while True:
                if not state.get('pending') and 'has_next' not in state:
                    result=self._get(account,'/issues',dict(filter=OVERVIEW_FILTERS[role],state='open',sort='updated',direction='desc',per_page=OVERVIEW_PAGE_SIZE,page=state['page']))
                    rows=result['data']
                    if not isinstance(rows,list) or len(rows)>OVERVIEW_PAGE_SIZE:raise ValueError('Invalid GitHub issue page')
                    remaining=max(0,OVERVIEW_MAX-state['count'])
                    state.update(pending=rows[:remaining],has_next=bool(result.get('has_next') or len(rows)>remaining))
                    self._save(account,0,key,state)
                for row in list(state['pending']):
                    repository=row.get('repository')
                    if not isinstance(repository,dict) or type(repository.get('id')) is not int or repository['id']<=0:raise ValueError('GitHub issue has no repository')
                    repo=dict(id=repository['id'],full_name=repo_name(repository.get('full_name')))
                    with closing(self.db()) as db,db:db.execute('INSERT OR REPLACE INTO repos VALUES (?,?,?)',(account,repo['id'],canonical(repo)))
                    pull=self._get(account,f'/repos/{repo["full_name"]}/pulls/{row.get("number")}')['data'] if 'pull_request' in row else None
                    record=item_record(row,repo,account,pull)
                    with self.lock:
                        self._check(account);self.on_item(account,record)
                        state['pending'].pop(0);state['count']+=1
                        # Source callbacks are idempotent; record, matches and remaining queue share this commit.
                        self._save(account,0,key,state,record)
                more=state.pop('has_next',False)
                state.update(page=state['page']+1,complete=not more or state['count']>=OVERVIEW_MAX,
                             limited=bool(more and state['count']>=OVERVIEW_MAX),last_sync=time.time())
                self._save(account,0,key,state)
                if state['complete']:break
            with self.lock:self.job=dict(running=False,status='synced',error=None)
        except InterruptedError as exc:
            with self.lock:self.job=dict(running=False,status=str(exc),error=None)
        except Exception as exc:
            with self.lock:self.job=dict(running=False,status='error',error=str(exc) if isinstance(exc,GitHubError) else 'GitHub data could not be processed. Retry the sync.')
    def find(self,repository,number):
        """The cached issue or pull request with this repository and number, or None."""
        account=self._account()
        with closing(self.db()) as db:
            row=db.execute("SELECT summary FROM objects WHERE account=? AND number=? AND lower(json_extract(summary,'$.repository'))=lower(?)",(account,number,repository)).fetchone()
        return json.loads(row[0]) if row else None
    def assigned_to(self,user_id):
        """Cached open and closed items assigned to a GitHub user ID, newest change first."""
        account=self._account()
        with closing(self.db()) as db:
            rows=db.execute("SELECT o.summary FROM objects o, json_each(o.document,'$.assignees') a WHERE o.account=? AND a.value=? ORDER BY json_extract(o.summary,'$.updated') DESC LIMIT 50",(account,str(user_id))).fetchall()
        return [json.loads(row[0]) for row in rows]
    def detail(self,key,expected_account=None):
        if type(key) is not int or key<=0:raise ValueError('Invalid GitHub object ID')
        account=self._account()
        if expected_account is not None and expected_account!=account:raise GitHubError('GitHub account changed. Reopen the object.')
        with closing(self.db()) as db:row=db.execute('SELECT document FROM objects WHERE account=? AND id=?',(account,key)).fetchone()
        if not row:raise ValueError('GitHub object is not cached. Sync its repository/filter.')
        return json.loads(row[0])
    def start(self,repository=None,role='all',restart=False,key=None):
        if key is None:repo_name(repository)
        elif type(key) is not int or key<=0:raise ValueError('Invalid GitHub object ID')
        if role not in FILTERS or type(restart) is not bool:raise ValueError('Invalid GitHub sync action')
        account=self._account()
        with self.lock:
            if self.thread and self.thread.is_alive():raise ValueError('A GitHub sync is already running')
            if self.priority():raise ValueError('Stop recording/processing before syncing GitHub')
            self.cancel.clear();self.job=dict(running=True,status='syncing',error=None)
            self.thread=threading.Thread(target=self._run,args=(account,repository,role,restart,key),daemon=True);self.thread.start()
        return self.status()
    def _repo(self,account,name):
        record=self._get(account,'/repos/'+repo_name(name))['data']
        if type(record.get('id')) is not int or record['id']<=0 or repo_name(record.get('full_name')).casefold()!=name.casefold():raise ValueError('GitHub repository identity did not match')
        with closing(self.db()) as db,db:db.execute('INSERT OR REPLACE INTO repos VALUES (?,?,?)',(account,record['id'],canonical(dict(id=record['id'],full_name=record['full_name']))))
        return record
    def _read(self,account,repo,number,expected_id):
        issue=self._get(account,f'/repos/{repo["full_name"]}/issues/{number}')['data']
        if issue.get('id')!=expected_id:raise ValueError('GitHub issue ID changed unexpectedly')
        pull=self._get(account,f'/repos/{repo["full_name"]}/pulls/{number}')['data'] if 'pull_request' in issue else None
        return item_record(issue,repo,account,pull)
    def _run(self,account,repository,role,restart,key):
        try:
            user=self._get(account,'/user')['data']
            if str(user.get('id'))!=account or not LOGIN.fullmatch(user.get('login','')):raise GitHubError('GitHub user identity changed. Reconnect.')
            with closing(self.db()) as db,db:db.execute('INSERT OR REPLACE INTO accounts VALUES (?,?)',(account,user['login']))
            if key is not None:
                old=self.detail(key,expected_account=account)
                with closing(self.db()) as db:row=db.execute('SELECT document FROM repos WHERE account=? AND id=?',(account,old['repository_id'])).fetchone()
                repo=self._repo(account,json.loads(row[0])['full_name'])
                try:record=self._read(account,repo,old['number'],key)
                except GitHubError as exc:
                    if getattr(exc,'status',None) not in {403,404} or getattr(exc,'rate_limited',False):raise
                    self._check(account);record=dict(old,available=False,body='',text='',fetched_at=time.time())
                with self.lock:
                    self._check(account);self.on_item(account,record);self._save(account,repo['id'],'',{},record)
                with self.lock:self.job=dict(running=False,status='synced',error=None)
                return
            repo=self._repo(account,repository);state=self._state(account,repo['id'],role)
            if restart or not state or state.get('complete'):
                state=dict(generation=uuid.uuid4().hex,upper=dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),page=1,count=0,pending=[],complete=False,login=user['login'],repository=repo['full_name'])
                self._save(account,repo['id'],role,state)
            if state.get('repository',repo['full_name']).casefold()!=repo['full_name'].casefold():raise GitHubError('Repository name changed. Restart this filter refresh.')
            if state['login']!=user['login']:raise GitHubError('Your GitHub login changed. Restart this filter refresh.')
            if not state.get('pending') and 'has_next' not in state:
                q=f'repo:{repo["full_name"]} updated:<={state["upper"]}'
                if FILTERS[role]:q+=' '+FILTERS[role]+':'+user['login']
                result=self._get(account,'/search/issues',dict(q=q,sort='updated',order='desc',per_page=PAGE_SIZE,page=state['page']))
                payload=result['data'];rows=payload.get('items')
                if not isinstance(rows,list) or len(rows)>PAGE_SIZE:raise ValueError('Invalid GitHub search page')
                pending=[]
                for row in rows:
                    number=row.get('number');item_id=row.get('id')
                    if type(number) is not int or number<=0 or type(item_id) is not int or item_id<=0 or row.get('url','').casefold()!=f'https://api.github.com/repos/{repo["full_name"]}/issues/{number}'.casefold():raise ValueError('GitHub search result belongs to another repository')
                    pending.append(dict(number=number,id=item_id))
                remaining=max(0,MAX_ITEMS-state['count'])
                state.update(pending=pending[:remaining],has_next=bool(result.get('has_next') or len(pending)>remaining),incomplete=bool(state.get('incomplete') or payload.get('incomplete_results')))
                self._save(account,repo['id'],role,state)
            for item in list(state['pending']):
                record=self._read(account,repo,item['number'],item['id'])
                with self.lock:
                    self._check(account);self.on_item(account,record);state['pending'].pop(0);state['count']+=1
                    self._save(account,repo['id'],role,state,record)
            more=state.pop('has_next',False)
            state.update(complete=not more or state['count']>=MAX_ITEMS,limited=bool(more and state['count']>=MAX_ITEMS),last_sync=time.time(),page=state['page']+1)
            self._save(account,repo['id'],role,state)
            with self.lock:self.job=dict(running=False,status='synced' if state['complete'] else 'continue',error=None)
        except InterruptedError as exc:
            with self.lock:self.job=dict(running=False,status=str(exc),error=None)
        except Exception as exc:
            if isinstance(exc,GitHubError) and getattr(exc,'status',None) in {403,404} and not getattr(exc,'rate_limited',False):
                try:
                    self._check(account)
                    with self.lock:
                        if key is not None:
                            record=self.detail(key,expected_account=account)
                            record.update(available=False,body='',text='',fetched_at=time.time())
                            self.on_item(account,record);self._save(account,record['repository_id'],'',{},record)
                        else:
                            with closing(self.db()) as db:
                                known=db.execute("SELECT id FROM repos WHERE account=? AND lower(json_extract(document,'$.full_name'))=lower(?)",(account,repository)).fetchone()
                            if known:
                                self.on_unavailable(account,known[0])
                                self._unavailable(account,known[0])
                except Exception:pass
            with self.lock:self.job=dict(running=False,status='error',error=str(exc) if isinstance(exc,GitHubError) else 'GitHub data could not be processed. Retry or restart this filter refresh.')
    def _unavailable(self,account,repo):
        with closing(self.db()) as db:rows=db.execute('SELECT document FROM objects WHERE account=? AND repo=?',(account,repo)).fetchall()
        for row in rows:
            record=json.loads(row[0]);record.update(available=False,body='',text='',fetched_at=time.time())
            self._save(account,repo,'',{},record)
    def stop(self):self.cancel.set();return self.status()
    def clear(self,account):
        if not isinstance(account,str) or not account:raise ValueError('Choose a cached GitHub account')
        with self.lock:
            if self.thread and self.thread.is_alive():raise ValueError('Cancel GitHub sync and wait before clearing its cache')
            with closing(self.db()) as db,db:
                for table in ('repos','state','objects','matches'):db.execute(f'DELETE FROM {table} WHERE account=?',(account,))
                db.execute('DELETE FROM accounts WHERE id=?',(account,))
        return self.status()
    def close(self):
        self.cancel.set()
        if self.thread:self.thread.join(timeout=1)
