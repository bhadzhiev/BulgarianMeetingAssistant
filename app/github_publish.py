"""Explicit issue/comment publication, with durable intent and no automatic POST retry."""
import datetime as dt
import hashlib
import json
import re
import socket
import urllib.error
import urllib.request
from .commit_journal import CommitJournal
from .github_source import repo_name, _NoRedirect, GitHubError
from .work_items import canonical, WorkItemConflict

# Every issue that Atlanta creates carries this label, so people can find them in GitHub.
ATLANTA_LABEL='created by ATLANTA'


def post(resource,payload,token):
    request=urllib.request.Request('https://api.github.com'+resource,data=json.dumps(payload).encode(),method='POST',headers={
        'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json','Content-Type':'application/json',
        'X-GitHub-Api-Version':'2022-11-28','User-Agent':'Atlanta'})
    with urllib.request.build_opener(_NoRedirect).open(request,timeout=30) as response:
        raw=response.read(8_000_001)
        if len(raw)>8_000_000:raise GitHubError('Response too large; check publication outcome.')
        return json.loads(raw)


def _error_detail(error):
    """One GitHub validation error as short text, for example 'assignees invalid: someone'."""
    if isinstance(error,str):return error
    if not isinstance(error,dict):return ''
    if error.get('message'):return str(error['message'])
    parts=[str(error.get('field') or error.get('resource') or ''),str(error.get('code') or '')]
    text=' '.join(p for p in parts if p)
    value=error.get('value')
    if value not in (None,''):text+=': '+(', '.join(map(str,value)) if isinstance(value,list) else str(value))
    return text


def _refusal(exc):
    """What GitHub said about a refused request: its message, the permission it wants, a rate limit."""
    headers=exc.headers or {}
    try:raw=exc.read(16_000)
    except Exception:raw=b''
    try:data=json.loads(raw)
    except Exception:data={}
    if not isinstance(data,dict):data={}
    message=data.get('message','')
    message=' '.join(str(message).split())[:300] if isinstance(message,str) else ''
    # A 422 lists each failed field in 'errors'. Without it, "Validation Failed" says nothing.
    details=[_error_detail(e) for e in (data.get('errors') or [])[:5] if isinstance(data.get('errors'),list)]
    details=[d for d in details if d]
    if details:message=(message+' ' if message else '')+'('+'; '.join(details)+')'
    # One short line of GitHub's own text. It never contains the token.
    message=' '.join(message.split())[:500]
    wanted=' '.join(str(headers.get('X-Accepted-GitHub-Permissions') or '').split())[:120]
    limited=headers.get('X-RateLimit-Remaining')=='0' or bool(headers.get('Retry-After'))
    return message,wanted,limited


def _refused_text(exc):
    message,wanted,limited=_refusal(exc)
    said=f' GitHub says: “{message}”.' if message else ''
    if limited:
        return f'GitHub refused publication (HTTP {exc.code}): rate limit reached. Wait, then preview again.'+said
    if exc.code==403 and 'personal access token' in message.casefold():
        need=f' GitHub needs: {wanted}.' if wanted else ''
        return (f'GitHub refused publication (HTTP 403): the token in Atlanta lacks a permission.{said}{need} '
                'Edit the fine-grained token on GitHub: set Issues to Read and write for this repository. '
                'If the organization approves tokens, approve the change there.')
    if exc.code==403:
        return f'GitHub refused publication (HTTP 403).{said} Check Issues: Read and write for this repository, organization approval and rate limits.'
    if exc.code==404:
        return f'GitHub refused publication (HTTP 404).{said} The token cannot see this repository. Add the repository to the token on GitHub.'
    return f'GitHub refused the request ({exc.code}).{said}'


def _not_sent(exc):
    """Errors after which GitHub surely has no result. Anything else may have left this Mac."""
    if isinstance(exc,urllib.error.HTTPError):
        return dict(error=_refused_text(exc),status=exc.code) if 400<=exc.code<500 and exc.code!=408 else None
    if isinstance(exc,urllib.error.URLError) and isinstance(exc.reason,(socket.gaierror,ConnectionRefusedError)):
        return dict(error='GitHub could not be reached.',offline=True)
    return None


class Publisher:
    def __init__(self,service,write=post):
        self.service=service;self.connection=service.github.connection;self.write=write
        self.journal=CommitJournal(service.items.store.path)

    @staticmethod
    def _check_binding(data,repo):
        if repo.casefold() not in {name.casefold() for b in data.get('repository_bindings',[]) for name in b['repositories']}:
            raise WorkItemConflict('Repository is no longer linked to this project. Choose a linked repository and preview again.')

    def resource_revision(self,resource):
        data=self.service._resource(resource)
        if data.get('moment'):
            meeting=self.service.detail(data['moment']['meeting_id'])
            data=dict(data,transcript_revision=meeting['transcript_revision'],minutes_revision=meeting['minutes_revision'])
        return hashlib.sha256(canonical(data).encode()).hexdigest()

    def preview(self,body):
        repo=repo_name(body.get('repository'));action=body.get('format')
        title=body.get('title','');text=body.get('body')
        if action not in {'issue','comment'} or not isinstance(text,str) or not text.strip() or len(text)>60000:raise ValueError('Choose an issue/comment with text up to 60000 characters')
        if not isinstance(title,str) or action=='issue' and not 1<=len(title.strip())<=256:raise ValueError('Enter an issue title')
        target=body.get('target')
        if action=='comment' and (type(target) is not int or target<1):raise ValueError('Enter the target issue number')
        data=self.service._resource(body.get('resource'));resource=data['target']
        self._check_binding(data,repo)
        revision=self.resource_revision(resource)
        if action=='issue' and hasattr(self.service.github_links,'for_resource') and self.service.github_links.for_resource(resource['kind'],resource['id']):raise ValueError('This resource is already linked to GitHub. Open the linked issue or add a comment.')
        account=self.connection.get('/user')['data'];account_id=str(account['id'])
        remote=self.connection.get('/repos/'+repo,expected_account=account_id)['data']
        if remote.get('full_name','').lower()!=repo.lower() or type(remote.get('id')) is not int:raise ValueError('Repository identity mismatch')
        if remote.get('archived') or remote.get('disabled'):raise ValueError('This repository is archived or disabled. Choose an active repository.')
        if action=='issue' and remote.get('has_issues') is False:raise ValueError('Issues are disabled for this repository. Choose another repository.')
        if action=='comment':self.connection.get(f'/repos/{repo}/issues/{target}',expected_account=account_id)
        payload=dict(resource=resource,resource_revision=revision,source_revision=revision,account_id=account_id,repository_id=remote['id'],action=action,target=target if action=='comment' else None,title=title.strip(),body=text)
        assignee=self.assignee(body.get('assignee')) if action=='issue' else None
        if assignee:payload['assignees']=[assignee]
        if action=='issue':payload['labels']=[ATLANTA_LABEL]
        operation=self.journal.approve(payload)
        operation=self.journal.destination(operation['id'],repo,account['login'])
        return dict(operation=operation,repository=repo,account=account['login'],assignees=payload.get('assignees',[]),labels=payload.get('labels',[]))

    def assignee(self,value):
        """Only a GitHub username of a person in Atlanta can be an assignee."""
        if value in (None,''):return None
        if not isinstance(value,str):raise ValueError('Invalid assignee')
        login=value.strip().lstrip('@').casefold()
        found=next((p['login'] for p in self.service.github_assignees() if p['login'].casefold()==login),None)
        if not found:raise ValueError('Choose an assignee from the people in Atlanta with a GitHub username.')
        return found

    def publish(self,key,repository):
        repo=repo_name(repository);operation=self.journal.get(key);payload=operation['payload']
        if operation['state']!='approved':return operation
        connection=self.connection
        with connection.lock:
            account=connection.get('/user',expected_account=payload['account_id'])['data']
            remote=connection.get('/repos/'+repo,expected_account=payload['account_id'])['data']
            if str(account['id'])!=payload['account_id'] or remote.get('id')!=payload['repository_id']:raise WorkItemConflict('Account or repository changed. Review again.')
            self._check_binding(self.service._resource(payload['resource']),repo)
            if self.resource_revision(payload['resource'])!=payload['resource_revision']:raise WorkItemConflict('Resource changed. Review again.')
            endpoint=f'/repos/{repo}/issues'+(f'/{payload["target"]}/comments' if payload['action']=='comment' else '')
            marker=f'<!-- atlanta:operation={key} -->'
            request=dict(body=payload['body']+'\n\n'+marker)
            if payload['action']=='issue':request['title']=payload['title']
            if payload.get('assignees'):request['assignees']=payload['assignees']
            if payload.get('labels'):request['labels']=payload['labels']
            self.journal.transition(key,'approved','sending')
            try:
                result=self.write(endpoint,request,connection._load()['token'])
                if type(result.get('id')) is not int or marker not in (result.get('body') or ''):raise ValueError('Unexpected GitHub response')
                number=payload['target'] if payload['action']=='comment' else result.get('number')
                if type(number) is not int or number<1:raise ValueError('Unexpected issue number')
                locator=f'/repos/{repo}/issues/'+(f'comments/{result["id"]}' if payload['action']=='comment' else str(number))
                url=f'https://github.com/{repo}/issues/{number}'+(f'#issuecomment-{result["id"]}' if payload['action']=='comment' else '')
                operation=self.journal.transition(key,'sending','created',dict(id=result['id'],number=number,url=url,locator=locator,repository=repo))
            except Exception as exc:
                failure=_not_sent(exc)
                return self.journal.transition(key,'sending','failed',failure) if failure else self.journal.transition(key,'sending','unknown')
        return self.verify(key)

    def reconcile(self,key,repository):
        repo=repo_name(repository);operation=self.journal.get(key);payload=operation['payload']
        if operation['state']!='unknown':return self.verify(key)
        account=payload['account_id']
        remote=self.connection.get('/repos/'+repo,expected_account=account)['data']
        if remote.get('id')!=payload['repository_id']:raise WorkItemConflict('Repository changed')
        endpoint=f'/repos/{repo}/issues'+(f'/{payload["target"]}/comments' if payload['action']=='comment' else '')
        matches=[];marker=f'<!-- atlanta:operation={key} -->'
        for page in range(1,101):
            response=self.connection.get(endpoint,dict(page=page,per_page=100,**({'state':'all'} if payload['action']=='issue' else {})),expected_account=account)
            if not isinstance(response.get('data'),list):raise ValueError('Incomplete GitHub lookup')
            matches.extend(row for row in response['data'] if marker in (row.get('body') or '') and str(row.get('user',{}).get('id'))==account)
            if not response.get('has_next'):break
        else:return operation
        if len(matches)!=1:return self.journal.record_check(key,len(matches))
        row=matches[0];number=payload['target'] if payload['action']=='comment' else row.get('number')
        if type(row.get('id')) is not int or type(number) is not int:return operation
        locator=f'/repos/{repo}/issues/'+(f'comments/{row["id"]}' if payload['action']=='comment' else str(number))
        url=f'https://github.com/{repo}/issues/{number}'+(f'#issuecomment-{row["id"]}' if payload['action']=='comment' else '')
        self.journal.transition(key,'unknown','created',dict(id=row['id'],number=number,url=url,locator=locator,repository=repo))
        return self.verify(key)

    def abandon(self,key):
        """A person confirms there is no result after a complete check. A new preview may follow."""
        operation=self.journal.get(key);check=(operation.get('result') or {}).get('last_check')
        if operation['state']!='unknown' or not check or check['matches']:
            raise ValueError('Check GitHub first. A new attempt is possible only when a complete check finds nothing.')
        return self.journal.transition(key,'unknown','abandoned',dict(operation['result'],abandoned_at=dt.datetime.now(dt.timezone.utc).isoformat()))

    def verify(self,key):
        operation=self.journal.get(key)
        if operation['state'] not in {'created','verified'}:return operation
        result=operation['result'];payload=operation['payload']
        try:
            remote=self.connection.get(result['locator'],expected_account=payload['account_id'])['data']
            if remote.get('id')!=result['id'] or f'<!-- atlanta:operation={key} -->' not in (remote.get('body') or ''):return operation
            issue=remote if payload['action']=='issue' else self.connection.get(f'/repos/{result["repository"]}/issues/{result["number"]}',expected_account=payload['account_id'])['data']
            if type(issue.get('id')) is not int or issue.get('number')!=result['number']:return operation
            checked_at=dt.datetime.now(dt.timezone.utc).isoformat()
            details=dict(kind='pull_request' if 'pull_request' in issue else 'issue',title=issue.get('title') or payload['title'],
                state=issue.get('state'),issue_id=issue['id'],verified=True,verification='github',checked_at=checked_at)
            self.service.github_links.link(payload['resource'],result['repository'],result['number'],details)
            if operation['state']=='created':operation=self.journal.transition(key,'created','verified',dict(result,checked_at=checked_at))
        except (ValueError,GitHubError):pass
        return operation
