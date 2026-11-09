"""Read-only task development projections and explicitly requested GitHub snapshots."""
import copy
import datetime as dt
import hashlib
import re
from .work_items import canonical, WorkItemConflict
from .github_source import repo_name, GitHubError
from .transcripts import segment_at

MAX_EVENTS=300

def now():return dt.datetime.now(dt.timezone.utc).isoformat()

def normalized_time(value):
    if not isinstance(value,str):return None
    try:
        stamp=dt.datetime.fromisoformat(value.replace('Z','+00:00'))
        return (stamp if stamp.tzinfo else stamp.replace(tzinfo=dt.timezone.utc)).astimezone(dt.timezone.utc).isoformat()
    except ValueError:return None

def safe_url(value):
    return value if isinstance(value,str) and re.fullmatch(r'https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/(?:issues|pull|commit)/[A-Za-z0-9]+(?:#[A-Za-z0-9_-]+)?',value) else None

def event_record(raw,repo,number):
    if not isinstance(raw,dict):raise ValueError('Invalid GitHub activity')
    kind=raw.get('event')
    allowed={'closed','reopened','assigned','unassigned','labeled','unlabeled','referenced','cross-referenced','committed','merged','commented','renamed','reviewed','review_requested','review_request_removed','head_ref_force_pushed','head_ref_deleted','connected','disconnected'}
    if kind not in allowed:return None
    key=raw.get('id') or raw.get('node_id') or raw.get('sha') or hashlib.sha256(canonical(raw).encode()).hexdigest()
    actor=raw.get('actor') or raw.get('user') or {}
    at=normalized_time(raw.get('created_at') or raw.get('submitted_at') or (raw.get('author') or {}).get('date'))
    updated=normalized_time(raw.get('updated_at'))
    if kind=='commented' and updated and at and updated>at:kind='comment_edited';at=updated
    details=str(raw.get('body') or '')[:1500]
    if kind in {'assigned','unassigned'}:details=str((raw.get('assignee') or {}).get('login') or '')
    if kind in {'labeled','unlabeled'}:details=str((raw.get('label') or {}).get('name') or '')
    referenced=(raw.get('source') or {}).get('issue') or {}
    if referenced:details=str(referenced.get('title') or '')[:300]
    url=safe_url(raw.get('html_url')) or safe_url(referenced.get('html_url')) or f'https://github.com/{repo}/issues/{number}'
    sha=raw.get('commit_id') or raw.get('sha')
    if isinstance(sha,str) and re.fullmatch('[a-f0-9]{40}',sha):url=f'https://github.com/{repo}/commit/{sha}';details=details or sha[:12]
    return dict(id=str(key),kind=kind,at=at,actor=str(actor.get('login') or '')[:100],text=details,url=url)

def check(service,item_id,body):
    if type(body.get('more',False)) is not bool or type(body.get('clear',False)) is not bool:raise ValueError('Invalid activity option')
    with service.lock,service.items.lock:
        item=service.items.items.get(item_id)
        if not item or item['kind']!='task':raise ValueError('Choose an existing task')
        links=service.github_links.for_resource('item',item_id)
        link=next((l for l in links if l['id']==body.get('link_id')),None)
        if not link:raise WorkItemConflict('This link is no longer attached to the task')
    if body.get('clear') is True:
        service.github_links.save_progress(link['id'],link['revision'],{})
        return build(service,item_id)
    connection=service.github.connection;account=connection.status().get('account_id')
    if not account:raise ValueError('Connect GitHub to check activity')
    repo=repo_name(link['repository']);number=link['number'];old=link.get('progress') or {}
    same=old.get('account_id')==account
    page=old.get('next_page') if body.get('more') is True and same else 1
    if page is None:return build(service,item_id)
    events={event['id']:event for event in old.get('events',[])} if same else {}
    stamp=now()
    try:
        issue=connection.get(f'/repos/{repo}/issues/{number}',expected_account=account)['data']
        if isinstance(issue,dict) and issue.get('url') and issue['url'].casefold()!=f'https://api.github.com/repos/{repo}/issues/{number}'.casefold():raise ValueError('GitHub returned another repository')
        if not isinstance(issue,dict) or type(issue.get('id')) is not int or issue.get('number')!=number or issue.get('state') not in {'open','closed'}:raise ValueError('Invalid GitHub issue identity')
        if link.get('issue_id') and issue['id']!=link['issue_id']:raise WorkItemConflict('The linked GitHub issue identity changed')
        state=issue['state'];kind='pull_request' if 'pull_request' in issue else 'issue'
        if kind=='pull_request':
            pull=connection.get(f'/repos/{repo}/pulls/{number}',expected_account=account)['data']
            if not isinstance(pull,dict) or type(pull.get('id')) is not int or pull.get('number')!=number:raise ValueError('Invalid GitHub PR identity')
            if pull.get('merged_at'):state='merged'
        next_page=None
        for _ in range(2):
            result=connection.get(f'/repos/{repo}/issues/{number}/timeline',dict(per_page=100,page=page),expected_account=account)
            if type(result.get('has_next',False)) is not bool or not isinstance(result.get('data'),list) or len(result['data'])>100:raise ValueError('Incomplete GitHub activity response')
            for raw in result['data']:
                event=event_record(raw,repo,number)
                if event:events[event['id']]=event
            if not result.get('has_next'):break
            page+=1;next_page=page
        else:pass
        # The last response determines pagination, including a completed second page.
        if not result.get('has_next'):next_page=None
        ordered=sorted(events.values(),key=lambda e:e.get('at') or '')
        omitted=max(0,len(ordered)-MAX_EVENTS)
        progress=dict(account_id=account,checked_at=stamp,error=None,events=ordered[-MAX_EVENTS:],next_page=next_page,
                      partial=bool(next_page or omitted or same and old.get('older_events_omitted')),older_events_omitted=bool(omitted or same and old.get('older_events_omitted')),
                      remote_updated_at=normalized_time(issue.get('updated_at')))
        details=dict(kind=kind,title=str(issue.get('title') or '')[:300],state=state,issue_id=issue['id'],verified=True,verification='github',checked_at=stamp)
        if connection.status().get('account_id')!=account:raise WorkItemConflict('GitHub account changed; no activity was saved')
        with service.lock:
            if item_id not in service.items.items:raise WorkItemConflict('The task was deleted; no activity was saved')
            service.github_links.save_progress(link['id'],link['revision'],progress,details)
    except WorkItemConflict:raise
    except (ValueError,GitHubError) as exc:
        if connection.status().get('account_id')!=account:raise WorkItemConflict('GitHub account changed; no activity was saved')
        progress=copy.deepcopy(old) if same else dict(account_id=account,events=[])
        progress.update(error=str(exc) if 'activity cache' in str(exc) else 'GitHub activity could not be checked. Previous snapshots were kept; check access and connection.',last_attempt_at=stamp)
        service.github_links.save_progress(link['id'],link['revision'],progress,dict(verification='offline'))
    return build(service,item_id)

def readiness(service,item_id,repository):
    data=service._resource(dict(kind='item',id=item_id));repo=repo_name(repository)
    if repo.casefold() not in {r.casefold() for b in data['repository_bindings'] for r in b['repositories']}:raise ValueError('Choose a repository linked to the task project')
    conn=service.github.connection;account=conn.status().get('account_id')
    if not account:raise ValueError('Connect GitHub first')
    row=conn.get('/repos/'+repo,expected_account=account)['data']
    if not isinstance(row,dict) or row.get('full_name','').casefold()!=repo.casefold() or type(row.get('id')) is not int:raise ValueError('Repository identity mismatch')
    return dict(repository=repo,account=conn.status().get('login'),checked_at=now(),read_access=True,
                issues_enabled=row.get('has_issues') is not False,archived=bool(row.get('archived') or row.get('disabled')),
                write_permission='not_verified',message='Read access checked. Issues write permission is checked only when you approve publication. No write probe was sent.')

def build(service,item_id):
    with service.lock,service.items.lock:
        item=copy.deepcopy(service.items.items.get(item_id))
        if not item or item['kind']!='task':raise ValueError('Choose an existing task')
        graph=copy.deepcopy(service.items.data);links=service.github_links.for_resource('item',item_id)
    account=service.github.connection.status().get('account_id')
    events=[]
    def add(kind,at,text='',**fields):
        event=dict(kind=kind,at=normalized_time(at),text=text,**fields);event['id']=hashlib.sha256(canonical(event).encode()).hexdigest();events.append(event)
    for event in item.get('history',[]):
        evidence=graph['source_evidence'].get(event.get('evidence_id'))
        fields=dict(changes=event.get('changes',{}),by=event.get('by'),meeting_id=event.get('meeting_id'))
        if event.get('evidence_timestamp'):fields['timestamp']=event['evidence_timestamp']
        if event.get('quote') and not event.get('evidence_id'):fields['quote']=event['quote']
        if evidence:fields.update(quote=evidence['quote'],source_id=evidence['source_id'],locator=evidence.get('locator',{}))
        add(event['event'],event.get('at'),event.get('text',''),**fields)
    if not any(e['kind']=='created' for e in events):add('created',item.get('created'),'Created locally')
    for link in item.get('links',[]):
        if link.get('detached'):continue
        try:
            meeting=service.library.get(link['meeting_id']);directory=service.library.directory(link['meeting_id'])
            from .live import read_json
            rows=read_json(directory/'transcript.json',[])
            segment=segment_at(rows,link['evidence_timestamp']) if link.get('evidence_timestamp') else None
            add('meeting_evidence',None,meeting['title'],meeting_id=meeting['id'],source_date=meeting.get('created'),timestamp=link.get('evidence_timestamp'),quote=segment['text'] if segment else None)
        except (ValueError,OSError):continue
    referenced={e.get('source_id') for e in events if e.get('source_id')}
    for key in item.get('source_evidence',[]):
        ev=graph['source_evidence'].get(key)
        if ev and ev['source_id'] not in referenced:add('source_linked',None,'Saved source evidence',quote=ev['quote'],source_id=ev['source_id'],locator=ev.get('locator',{}))
    for link in links:
        link['url']=safe_url(link.get('url')) or f'https://github.com/{link["repository"]}/issues/{link["number"]}'
        add('github_linked',link['linked_at'],link['repository']+' #'+str(link['number']),url=link['url'],verification=link.get('verification'))
        for observation in link.get('observations',[]):add('github_observed',observation.get('at'),'GitHub state: '+str(observation.get('state') or 'unknown'),url=link['url'],verification=observation.get('verification'))
        progress=link.get('progress') or {}
        if progress.get('account_id')!=account:link['progress']=dict(error='Activity belongs to another GitHub account. Check again.',events=[]) if progress else {};continue
        for remote in progress.get('events',[]):add('github_'+remote['kind'],remote.get('at'),remote.get('text',''),actor=remote.get('actor'),url=safe_url(remote.get('url')),repository=link['repository'],number=link['number'])
    from .commit_journal import CommitJournal
    publications=[]
    for operation in CommitJournal(service.items.store.path).for_resource('item',item_id):
        if operation['payload']['resource']!=dict(kind='item',id=item_id):continue
        result=operation.get('result') or {}
        publications.append(dict(id=operation['id'],state=operation['state'],repository=operation.get('repository') or result.get('repository'),account_id=operation['payload']['account_id'],account_login=operation.get('account_login'),url=safe_url(result.get('url')),last_check=result.get('last_check'),error=str(result.get('error') or '')[:1000]))
        history=list(operation.get('history') or [dict(state=operation['state'],at=None)])
        if history[-1]['state']!=operation['state']:history.append(dict(state=operation['state'],at=operation.get('updated_at')))
        for change in history:add('publication_'+change['state'],change.get('at'),'GitHub '+operation['payload']['action'],operation_id=operation['id'],url=safe_url((operation.get('result') or {}).get('url')))
    events=list({event['id']:event for event in events}.values());events.reverse();events.sort(key=lambda e:e['at'] or '',reverse=True)
    return dict(item_id=item_id,revision=item.get('revision'),events=events,links=links,publications=publications,account_id=account,local_state=item.get('workflow_state') or item['status'],
                checked_at=now(),note='Local edits use their action time. Undated evidence has no invented attachment date. GitHub snapshots never change the local task.')
