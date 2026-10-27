"""Local conversation browsing and project links, without AI or connector writes."""
import copy
import datetime as dt
import hashlib
import json
import math
import threading
from zoneinfo import ZoneInfo

from .work_graph import WorkGraph, digest, now
from .google_calendar import CalendarError
from .work_items import WorkItemConflict

TZ = ZoneInfo('Europe/Sofia')

def transcript_revision(rows):
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()

def iso(value):
    if isinstance(value, (int,float)):
        value=dt.datetime.fromtimestamp(value/1000 if value>100_000_000_000 else value,dt.timezone.utc)
    else:value=dt.datetime.fromisoformat(value.replace('Z','+00:00'))
    if value.tzinfo is None:raise ValueError('Conversation dates need a timezone')
    return value.isoformat()

def scope_revision(meeting):
    return digest({k:meeting.get(k) for k in ('id','project_id','series_id')})

class Conversations:
    def __init__(self, service):
        self.service=service;self.cache={};self.index_lock=threading.RLock()

    def _projects(self, ids):
        if (not isinstance(ids,list) or len(ids)>50
                or any(not isinstance(key,str) or not self.service.projects.get('projects',key) for key in ids)):
            raise ValueError('Choose existing projects')
        return sorted(set(ids))

    def _text(self, meeting):
        directory=self.service.library.directory(meeting['id'])
        path=directory/'transcript.json'
        if not path.exists():path=directory/'live-transcript.json'
        signature=(path.name,path.stat().st_mtime_ns,path.stat().st_size) if path.exists() else None
        with self.index_lock:
            old=self.cache.get(meeting['id'])
            if old and old[0]==signature:return old[1]
        if path.exists():
            if path.stat().st_size>64_000_000:raise ValueError('Transcript exceeds the conversation browser limit')
            rows=json.loads(path.read_text())
            if not isinstance(rows,list):raise ValueError('Invalid transcript')
        else:rows=[]
        result=dict(text='\n'.join(str(s.get('text','')) for s in rows),participants=sorted({s['speaker'] for s in rows if isinstance(s.get('speaker'),str) and s['speaker'].strip()}))
        with self.index_lock:
            self.cache[meeting['id']]=(signature,result)
            while len(self.cache)>256 or sum(len(v[1]['text']) for v in self.cache.values())>20_000_000:
                self.cache.pop(next(iter(self.cache)))
        return result

    def _external(self, provider, key, account=None):
        s=self.service
        if provider=='gmail':
            current=s.gmail._account()
            if account is not None and current!=account:raise WorkItemConflict('The Gmail account changed. Reload conversations.')
            row=s.gmail.detail(key,expected_account=current)
            if not row.get('available',True):raise ValueError('This email thread is unavailable')
            return dict(provider=provider,external_id=key,account=current,title=row['subject'],date=iso(row['date']),
                participants=sorted({m.get('sender','') for m in row['messages']}),revision=row['revision'],text=row['text'],partial=bool(row.get('partial')))
        if provider=='google_chat':
            current=s.chat._account()
            if account is not None and current!=account:raise WorkItemConflict('The Chat account changed. Reload conversations.')
            space=next((row for row in s.chat.spaces() if row['name']==key),None)
            if not space:raise ValueError('This Chat conversation is not cached')
            messages=s.chat.conversation(key)
            if s.chat._account()!=current:raise WorkItemConflict('The Chat account changed. Reload conversations.')
            available=[m for m in messages if m.get('available') and m.get('body')]
            if not available:raise ValueError('This conversation has no cached text')
            content='\n\n'.join(iso(m['date'])+' · '+m['sender']+'\n'+m['body'] for m in available)
            return dict(provider=provider,external_id=key,account=current,title=space.get('label') or key,date=iso(messages[-1]['date']),
                participants=sorted({m['sender'] for m in available}),revision=digest(messages),text=content,partial=True)
        raise ValueError('Choose Gmail or Google Chat')

    def external(self, provider, key):
        """The current cached revision of one Gmail thread or Chat conversation and its project links, without its text."""
        row=self._external(provider,key)
        identity=digest(dict(provider=provider,account=row['account'],external_id='conversation:'+row['external_id']))
        link=next((a for a in self.attachments('') if a['source_id']==identity),None)
        return dict({k:row[k] for k in ('provider','external_id','account','title','date','participants','revision','partial')},
            project_ids=link['project_ids'] if link else [],attachment_id=link['id'] if link else None,attachment_revision=link['revision'] if link else None)

    def listing(self, filters):
        s=self.service
        provider=filters.get('source','meeting');project=filters.get('project','');series=filters.get('series','');query=filters.get('q','').strip().casefold();person=filters.get('participant','')
        if provider not in {'all','meeting','gmail','google_chat','attached'} or len(query)>500:raise ValueError('Invalid conversation filter')
        try:offset=int(filters.get('offset',0))
        except (TypeError,ValueError):raise ValueError('Invalid conversation page') from None
        if not 0<=offset<=100000:raise ValueError('Invalid conversation page')
        bounds=[]
        for name in ('from','to'):
            value=filters.get(name,'')
            try:bounds.append(dt.date.fromisoformat(value) if value else None)
            except ValueError:raise ValueError('Use valid From and Through dates') from None
        if all(bounds) and bounds[0]>bounds[1]:raise ValueError('From must precede Through')
        rows=[];notices=[];meetings=s.library.list();known={m['id'] for m in meetings}
        with self.index_lock:self.cache={k:v for k,v in self.cache.items() if k in known}
        attachments=self.attachments('')
        if provider in {'meeting','all'}:
            for m in meetings:
                try:
                    content=self._text(m)
                    excerpt_projects={p for a in attachments if a['kind']=='excerpt' and a['locator']['meeting_id']==m['id'] for p in a['project_ids']}
                    rows.append(dict(provider='meeting',id='meeting:'+m['id'],external_id=m['id'],title=m['title'],date=iso(m.get('started_at') or m['created']),
                        text=content['text'],participants=content['participants'],project_ids=[m['project_id']] if m.get('project_id') else [],excerpt_projects=sorted(excerpt_projects),
                        series_id=m.get('series_id'),scope_revision=scope_revision(m),status=m['status'],duration=m.get('duration',0)))
                except (OSError,ValueError,TypeError,KeyError,AttributeError):notices.append('A meeting transcript could not be indexed; its original files were kept.')
        if provider in {'gmail','google_chat','all'}:
            kinds=['gmail','google_chat'] if provider=='all' else [provider]
            for kind in kinds:
                try:
                    account=s.gmail._account() if kind=='gmail' else s.chat._account()
                    summaries=s.gmail.listing('all') if kind=='gmail' else s.chat.spaces()
                    for summary in summaries:
                        try:
                            row=self._external(kind,summary['id'] if kind=='gmail' else summary['name'],account)
                            identity=digest(dict(provider=kind,account=row['account'],external_id='conversation:'+row['external_id']))
                            link=next((a for a in attachments if a['source_id']==identity),None)
                            row.update(id=kind+':'+row['external_id'],project_ids=link['project_ids'] if link else [],attachment_id=link['id'] if link else None,attachment_revision=link['revision'] if link else None)
                            rows.append(row)
                        except (ValueError,CalendarError) as exc:notices.append(str(exc))
                except (ValueError,CalendarError):notices.append(('Gmail' if kind=='gmail' else 'Google Chat')+' is disconnected or has no accessible cache.')
        if provider=='attached':
            for a in attachments:
                detail=self.attachment(a['id']);rows.append(dict(a,id='attachment:'+a['id'],provider='attached',external_id=a['id'],text=detail['text'],participants=a.get('participants',[])))
        participants=sorted({p for row in rows for p in row['participants'] if p})
        def matches(row):
            ids=set(row.get('project_ids',[]))|set(row.get('excerpt_projects',[]))
            day=dt.datetime.fromisoformat(row['date']).astimezone(TZ).date()
            return ((not project or (not ids if project=='__none__' else project in ids))
                and (not series or row.get('series_id')==series)
                and (not person or person in row['participants'])
                and (not bounds[0] or day>=bounds[0]) and (not bounds[1] or day<=bounds[1])
                and (not query or query in (row['title']+'\n'+row['text']).casefold()))
        found=sorted((r for r in rows if matches(r)),key=lambda r:(dt.datetime.fromisoformat(r['date']).timestamp(),r['id']),reverse=True)
        page=found[offset:offset+50]
        for row in page:row.pop('text',None)
        return dict(rows=page,total=len(found),offset=offset,limit=50,participants=participants,notices=list(dict.fromkeys(notices))[:5])
    def bulk(self, body):
        s=self.service;entries=body.get('meetings');project=body.get('project_id');series=body.get('series_id')
        if not isinstance(entries,list) or not 1<=len(entries)<=200 or any(not isinstance(e,dict) or not isinstance(e.get('id'),str) for e in entries):raise ValueError('Select 1 to 200 meetings')
        if len({e['id'] for e in entries})!=len(entries):raise ValueError('Select each meeting once')
        with s.lock,s.projects.lock,s.library.lock:
            if project is not None:self._projects([project])
            if series is not None:s.projects.ensure_series({'id':series},project)
            changes=[]
            for entry in entries:
                m=s.library.get(entry['id'])
                if m['id']==s.active or m['id'] in s.busy:raise ValueError('Wait until selected meetings finish recording or processing')
                if entry.get('revision')!=scope_revision(m):raise WorkItemConflict('A meeting moved since selection. Refresh before applying.')
                changes.append(dict(id=m['id'],project_id=project,series_id=series if series else (m.get('series_id') if project and project==m.get('project_id') else None)))
            s.library.assign_scopes(changes)
            return dict(updated=len(changes))

    def attach(self, body):
        s=self.service
        with s.lock,s.items.lock,s.projects.lock:
            ids=self._projects(body.get('project_ids'))
            if not ids:raise ValueError('Choose a project for this conversation')
            kind=body.get('provider')
            if kind=='excerpt':
                meeting=s.library.get(body.get('meeting_id'));path=s.library.directory(meeting['id'])/'transcript.json'
                if not path.exists():raise ValueError('Finish transcription before saving an excerpt')
                rows=json.loads(path.read_text());revision=transcript_revision(rows)
                if revision!=body.get('transcript_revision'):raise WorkItemConflict('The transcript changed. Reopen it before selecting an excerpt.')
                first,last=body.get('first'),body.get('last')
                if body.get('range') is not None:
                    value=body['range']
                    if not isinstance(value,list) or len(value)!=2 or any(type(n) not in (int,float) or not math.isfinite(n) for n in value) or not 0<=value[0]<value[1]:raise ValueError('Choose a valid time range')
                    selected=[i for i,row in enumerate(rows) if row['start']<value[1] and row['end']>value[0]]
                    if not selected:raise ValueError('No transcript turns overlap this range')
                    first,last=selected[0],selected[-1]
                if type(first) is not int or type(last) is not int or not 0<=first<=last<len(rows) or last-first>=500:raise ValueError('Choose up to 500 consecutive transcript segments')
                selected=rows[first:last+1];content='\n'.join(f"[{row['start']:.2f}–{row['end']:.2f}] {row.get('speaker') or 'Speaker'}: {row['text']}" for row in selected)
                locator=dict(meeting_id=meeting['id'],first=first,last=last,start=selected[0]['start'],end=selected[-1]['end'],transcript_revision=revision)
                row=dict(account='local',title=meeting['title'][:450]+' · excerpt',date=iso(meeting.get('started_at') or meeting['created']),participants=sorted({r['speaker'] for r in selected if r.get('speaker')}),revision=revision,text=content,partial=False)
                provider='meeting';external='excerpt:'+meeting['id']+':'+digest(locator)
            else:
                row=self._external(kind,body.get('external_id'),body.get('account'))
                if row['revision']!=body.get('revision'):raise WorkItemConflict('The cached conversation changed. Reload before attaching it.')
                locator=dict(external_id=row['external_id']);provider=kind;external='conversation:'+row['external_id']
            if not row['text'].strip() or len(row['text'])>1_000_000:raise ValueError('Select a smaller conversation or excerpt (local snapshot limit: 1 million characters)')
            identity=dict(provider=provider,account=row['account'],external_id=external);source_id=digest(identity);key=digest(dict(source_id=source_id,locator=locator))
            graph=WorkGraph(s.items)
            def save(data,result):
                old=data['conversation_links'].get(key)
                if old and body.get('attachment_revision')!=old['revision']:raise WorkItemConflict('This conversation is already attached. Open its saved attachment to change projects.')
                data['sources'][source_id]['remote']=dict(authority='conversation',locator=locator)
                data['conversation_links'][key]=dict(id=key,source_id=source_id,source_revision=result['source_revision'],kind=kind,title=row['title'][:500],date=row['date'],participants=row['participants'],
                    locator=locator,project_ids=ids,revision=(old['revision']+1 if old else 1),created=old['created'] if old else now(),updated=now(),partial=row['partial'])
            graph.ingest(dict(identity,revision=row['revision'],text=row['text']),[],after=save)
            return self.attachment(key)

    def attachments(self, project=''):
        known={p['id'] for p in self.service.projects.data['projects']}
        with self.service.items.lock:
            rows=[]
            for saved in self.service.items.data.get('conversation_links',{}).values():
                row=copy.deepcopy(saved);row['project_ids']=[p for p in row['project_ids'] if p in known]
                if not project or (not row['project_ids'] if project=='__none__' else project in row['project_ids']):rows.append(row)
            return rows

    def attachment(self, key):
        with self.service.lock,self.service.items.lock:
            data=self.service.items.data;row=data.get('conversation_links',{}).get(key)
            if not row:raise ValueError('Conversation attachment is unavailable')
            revision=data['source_revisions'][row['source_revision']]
            result=dict(copy.deepcopy(row),text=revision['text'],stale=False)
            if row['kind']=='excerpt':
                try:
                    path=self.service.library.directory(row['locator']['meeting_id'])/'transcript.json'
                    result['stale']=transcript_revision(json.loads(path.read_text()))!=row['locator']['transcript_revision']
                except (OSError,ValueError):result['stale']=True
            else:result['stale']=data['sources'][row['source_id']]['current_revision']!=row['source_revision']
            return result

    def assign(self, body):
        s=self.service
        with s.lock,s.items.lock,s.projects.lock:
            ids=self._projects(body.get('project_ids'))
            def save(data):
                row=data['conversation_links'].get(body.get('id'))
                if not row or type(body.get('revision')) is not int or row['revision']!=body['revision']:raise WorkItemConflict('The attachment changed. Reload before saving.')
                row.update(project_ids=ids,revision=row['revision']+1,updated=now());return row
            return WorkGraph(s.items)._write(save)

    def timeline(self, project, items, meetings):
        events=[dict(id='meeting:'+m['id'],kind='meeting',at=iso(m.get('started_at') or m['created']),text=m['title'],meeting_id=m['id']) for m in meetings]
        for row in self.attachments(project):
            event=dict(id=row['id'],kind=row['kind'],at=row['date'],text=row['title'],attachment_id=row['id'],captured_at=row['created'])
            if row['kind']=='excerpt':event.update(meeting_id=row['locator']['meeting_id'],start=row['locator']['start'],end=row['locator']['end'])
            events.append(event)
        by_id={i['id']:i for i in items}
        for item in items:
            for n,event in enumerate(item.get('history',[])):
                if not event.get('at'):continue
                events.append(dict(id=item['id']+':'+str(n),kind=item['kind'],at=event['at'],text=item['text'],item_id=item['id'],event=event.get('event'),status=item['status']))
        data=self.service.items.data
        linked={ev for item in items for ev in item.get('source_evidence',[])}
        sources={ev['source_id'] for ev in data['source_evidence'].values() if ev['id'] in linked}
        for source_id in sources:
            source=data['sources'][source_id];remote=source.get('remote',{})
            if source['provider']=='github' and remote.get('fetched_at'):
                pull=remote.get('kind')=='pull_request'
                events.append(dict(id='source:'+source_id,kind='pull_request' if pull else 'issue',at=iso(remote['fetched_at']),text=('PR' if pull else 'Issue')+' #'+str(remote.get('number',''))+' · '+remote.get('repository','')+' · saved from GitHub',source_id=source_id))
        relations=[r for r in self.service.items.data.get('relationships',{}).values() if r['from_id'] in by_id and r['to_id'] in by_id]
        chains=self.trace(project,items,meetings)
        seen={e['id'] for e in events}
        for chain in chains:
            for node in chain['stages']['code']:
                if node['date'] and 'code:'+node['id'] not in seen:
                    seen.add('code:'+node['id'])
                    events.append(dict(id='code:'+node['id'],kind='code',at=iso(node['date']),text=node['label'],url=node['ref'].get('url'),report_id=node['ref'].get('report_id')))
        return dict(events=sorted(events,key=lambda e:(dt.datetime.fromisoformat(e['at'].replace('Z','+00:00')).timestamp(),e['id']),reverse=True)[:300],relationships=copy.deepcopy(relations),chains=chains)

    def _code_changes(self):
        """Merged PRs and commits from repository reports of the connected GitHub account, by repository and PR number."""
        reports=self.service.repo_reports
        try:account=reports.account()
        except ValueError:return {}
        found={}
        with reports.lock:
            for row in reports.data['reports'].values():
                if row.get('account')!=account:continue
                for change in row.get('changes',{}).values():
                    if change.get('skipped') or not change.get('url'):continue
                    found.setdefault((row['repository'].casefold(),change['id']),dict(change,report_id=row['id'],repository=row['repository'],meeting_id=row.get('meeting_id')))
        return found

    def trace(self, project, items, meetings):
        """Chains of explicitly recorded links: conversation → decision → task → issue/PR → code change.

        Items join a chain only through saved relationships. Other steps join by identity: the item's own
        meeting links and source quotes, the attached conversation of the same thread, Chat space or
        meeting moment, and the merged PR with the same repository and number in a repository report.
        Nothing is inferred from similar text or from dates.
        """
        data=self.service.items.data;by_id={i['id']:i for i in items};meeting_rows={m['id']:m for m in self.service.library.list()}
        attachments=[a for a in data.get('conversation_links',{}).values()]
        evidence=data['source_evidence'];sources=data['sources'];code=self._code_changes()
        edges=[r for r in data.get('relationships',{}).values() if r['from_id'] in by_id and r['to_id'] in by_id]
        neighbours={key:set() for key in by_id}
        for edge in edges:neighbours[edge['from_id']].add(edge['to_id']);neighbours[edge['to_id']].add(edge['from_id'])
        def seconds(stamp):
            try:return sum(int(part)*60**n for n,part in enumerate(reversed(stamp.split(':'))))
            except (AttributeError,ValueError):return None
        def attachment_node(a):
            ref=dict(attachment_id=a['id'])
            if a['kind']=='excerpt':ref.update(meeting_id=a['locator']['meeting_id'],start=a['locator']['start'],end=a['locator']['end'])
            return dict(id='attachment:'+a['id'],kind=a['kind'],label=a['title'],date=a['date'],ref=ref)
        def origins(item):
            nodes=[]
            for link in item.get('links',[]):
                meeting=meeting_rows.get(link['meeting_id'])
                if not meeting:continue
                moment=seconds(link.get('evidence_timestamp'))
                nodes.append(dict(id='meeting:'+meeting['id'],kind='meeting',label=meeting['title'],date=iso(meeting.get('started_at') or meeting['created']),ref=dict(meeting_id=meeting['id'],timestamp=link.get('evidence_timestamp'))))
                for a in attachments:
                    loc=a['locator']
                    if a['kind']=='excerpt' and loc.get('meeting_id')==meeting['id'] and moment is not None and loc['start']<=moment<=loc['end']:nodes.append(attachment_node(a))
            return nodes
        def from_sources(item):
            stages=dict(conversation=[],github=[],code=[])
            for key in item.get('source_evidence',[]):
                ev=evidence.get(key);source=sources.get(ev['source_id']) if ev else None
                if not source:continue
                remote=source.get('remote',{});provider=source['provider']
                if provider=='github' and remote.get('authority')=='github_code':
                    stages['code'].append(dict(id='source:'+source['id'],kind='code',label=remote.get('repository','')+' · code evidence',date=None,ref=dict(source_id=source['id'],url=remote.get('url'),report_id=remote.get('report_id'))))
                elif provider=='github':
                    kind='pull_request' if remote.get('kind')=='pull_request' else 'issue'
                    stages['github'].append(dict(id='source:'+source['id'],kind=kind,label=remote.get('repository','')+' #'+str(remote.get('number','')),date=remote.get('fetched_at') and iso(remote['fetched_at']),
                        ref=dict(source_id=source['id'],repository=remote.get('repository'),number=remote.get('number'),state=remote.get('state'))))
                    change=code.get((str(remote.get('repository','')).casefold(),'pr:'+str(remote.get('number')))) if kind=='pull_request' else None
                    if change:stages['code'].append(dict(id='change:'+change['report_id']+':'+change['id'],kind='code',label=change['label'],date=change.get('date'),ref=dict(url=change['url'],report_id=change['report_id'],sha=change.get('sha'))))
                elif provider in {'gmail','google_chat'}:
                    stages['conversation'].append(dict(id='source:'+source['id'],kind=provider,label='Gmail thread' if provider=='gmail' else 'Chat message',date=None,ref=dict(source_id=source['id'])))
                    thread=source['external_id'] if provider=='gmail' else source['external_id'].split('/messages/')[0]
                    for a in attachments:
                        if a['kind']==provider and a['locator'].get('external_id')==thread:stages['conversation'].append(attachment_node(a))
                elif remote.get('authority')=='conversation':
                    for a in attachments:
                        if a['source_id']==source['id']:stages['conversation'].append(attachment_node(a))
            return stages
        chains=[];done=set()
        for start in sorted(by_id):
            if start in done or by_id[start]['kind'] not in {'decision','task','question'}:continue
            group,queue=set(),[start]
            while queue:
                key=queue.pop()
                if key in group:continue
                group.add(key);queue.extend(neighbours[key]-group)
            done|=group
            stages=dict(conversation=[],decision=[],task=[],github=[],code=[])
            for key in sorted(group,key=lambda k:(by_id[k].get('created') or '',k)):
                item=by_id[key];found=from_sources(item)
                stages['conversation']+=origins(item)+found['conversation'];stages['github']+=found['github'];stages['code']+=found['code']
                stages['task' if item['kind']=='task' else 'decision'].append(dict(id='item:'+key,kind=item['kind'],label=item['text'],date=item.get('created'),status=item['status'],ref=dict(item_id=key)))
            for name in stages:stages[name]=list({node['id']:node for node in stages[name]}.values())
            dates=[node['date'] for nodes in stages.values() for node in nodes if node.get('date')]
            chains.append(dict(id=start,stages=stages,relationships=[copy.deepcopy(e) for e in edges if e['from_id'] in group],
                latest=max(dates,key=lambda d:dt.datetime.fromisoformat(d.replace('Z','+00:00')).timestamp()) if dates else None,
                complete=sum(bool(stages[name]) for name in stages)))
        return sorted(chains,key=lambda c:(c['complete'],dt.datetime.fromisoformat(c['latest'].replace('Z','+00:00')).timestamp() if c['latest'] else 0),reverse=True)[:100]
