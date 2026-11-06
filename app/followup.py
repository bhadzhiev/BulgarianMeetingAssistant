"""Evidence-backed follow-up projections. Never changes local commitments from remote state."""
from . import meeting_types
from .meeting_review import review_state
from .transcripts import segment_at
from .task_progress import normalized_time,safe_url


def build(service, briefing, registry, meetings, minutes):
    typed=sorted((m for m in meetings if meeting_types.of(m)['id']==briefing['meeting_type']),key=lambda m:m.get('started_at') or m['created'])
    anchor=typed[-1] if typed else None
    boundary=(anchor.get('started_at') or anchor['created']) if anchor else None
    boundary_time=normalized_time(boundary)
    meaningful=lambda e:bool(e.get('changes')) or e.get('event') in {'progress_update','source_linked','discussed','duplicate','created','merged'}
    since=lambda event:bool(boundary_time and normalized_time(event.get('at')) and normalized_time(event['at'])>boundary_time and meaningful(event))
    scoped={r['id']:r for r in registry if not r.get('dismissed') and r.get('workflow_state')!='cancelled' and r.get('acceptance_state')!='proposed' and (any(l.get('meeting_id') in {m['id'] for m in meetings} and not l.get('detached') for l in r.get('links',[])) or not briefing.get('series_id') and briefing.get('project_id') in r.get('effective_project_ids',[]))}
    visible={t['item_id'] for t in briefing['tasks']}|{t['item_id'] for t in briefing.get('done',[])}|{t['item_id'] for t in briefing.get('done_unknown',[])}|{t['item_id'] for t in briefing['decisions']}|{t['item_id'] for t in briefing['proposed']}
    scoped={key:item for key,item in scoped.items() if key in visible or item['kind']=='question' and not item.get('snoozed_until')}
    github=getattr(service,'github',None);connection=getattr(github,'connection',None);account=connection.status().get('account_id') if connection else None
    def row(item):
        links=service.github_links.for_resource('item',item['id'])
        external=[];github_updates=[]
        for link in links:
            progress=link.get('progress') or {}
            external.append(dict({k:v for k,v in link.items() if k!='progress'},activity_checked_at=progress.get('checked_at'),activity_partial=bool(progress.get('partial')),completion_suggested=item.get('status')=='open' and link.get('state') in {'closed','merged'}))
            if progress.get('account_id')==account:
                for event in progress.get('events',[]):
                    if boundary_time and normalized_time(event.get('at')) and normalized_time(event['at'])>boundary_time:github_updates.append(dict(event,url=safe_url(event.get('url')),repository=link['repository'],number=link['number']))
        source=next((t.get('source') for t in briefing['tasks'] if t['item_id']==item['id']),None)
        if not source:
            linked=[l for l in item.get('links',[]) if any(m['id']==l['meeting_id'] for m in meetings) and not l.get('detached')]
            if linked:
                link=linked[-1];meeting=next(m for m in meetings if m['id']==link['meeting_id'])
                source=dict(meeting_id=meeting['id'],meeting_title=meeting['title'],meeting_date=meeting.get('started_at') or meeting['created'],timestamp=link.get('evidence_timestamp'))
        quote=None
        if source and source.get('timestamp'):
            segment=segment_at(service.detail(source['meeting_id'])['transcript'],source['timestamp'])
            if segment:quote=segment['text'];source=dict(source,start=segment['start'],end=segment['end'])
        person,how=service.people.owner_of(item) if item['kind']=='task' else (None,None)
        updates=[copy for copy in item.get('history',[]) if since(copy)]
        last_update=next(iter(sorted((e for e in reversed(item.get('history',[])) if e.get('event')=='progress_update'),key=lambda e:e.get('at',''),reverse=True)),None)
        return dict(github_updates=sorted(github_updates,key=lambda e:e.get('at') or '',reverse=True)[:20],github_updates_omitted=max(0,len(github_updates)-20),workflow_state=item.get('workflow_state') or ('done' if item['status']=='done' else 'todo'),follow_up_date=item.get('follow_up_date'),updates_since=updates,last_update=last_update,item_id=item['id'],revision=item.get('revision'),kind=item['kind'],text=item['text'],owner=item.get('owner'),
                    person_id=person['id'] if person else None,person_name=person['name'] if person else None,person_link=how,source=source,quote=quote,external=external,status=item['status'],review=review_state(item,sources))
    sources=service.review_sources() if hasattr(service,'review_sources') else None
    rows={key:row(item) for key,item in scoped.items()}
    unchanged=[]
    if boundary:
        for key,item in scoped.items():
            if item['kind']!='task' or item['status']!='open' or not item.get('created') or item['created']>boundary:continue
            if not any(since(e) for e in item.get('history',[])):unchanged.append(rows[key])
    blockers=[]
    if anchor:
        for entry in (minutes.get(anchor['id']) or {}).get('blockers',[]):
            if isinstance(entry,dict):
                blockers.append(dict(text=entry['text'],confirmed=entry.get('review')=='verified',source=dict(meeting_id=anchor['id'],meeting_title=anchor['title'],meeting_date=boundary,timestamp=entry.get('evidence_timestamp'))))
    today=service.task_summary()['today'] if hasattr(service,'task_summary') else __import__('datetime').datetime.now(__import__('datetime').timezone.utc).date().isoformat()
    return dict(anchor=anchor,externally_updated=[rows[k] for k in rows if rows[k]['github_updates']],updated=[rows[k] for k,i in scoped.items() if i['kind']=='task' and rows[k]['updates_since']],waiting=[rows[k] for k,i in scoped.items() if i.get('workflow_state')=='waiting'],follow_up_due=[rows[k] for k,i in scoped.items() if i['kind']=='task' and i['status']!='done' and i.get('follow_up_date') and i['follow_up_date']<=today],completed=[rows[t['item_id']] for t in briefing.get('done',[]) if t['item_id'] in rows],
                completed_unknown=[rows[t['item_id']] for t in briefing.get('done_unknown',[]) if t['item_id'] in rows],
                unchanged=unchanged,blocked=[b for b in blockers if b['confirmed']],blockers_to_review=[b for b in blockers if not b['confirmed']],
                questions=[rows[k] for k,i in scoped.items() if i['kind']=='question' and i['status']=='open'],
                decisions=[rows[k] for k,i in scoped.items() if i['kind']=='decision' and i['status'] in {'accepted','proposed'}],
                commitments=[rows[k] for k,i in scoped.items() if i['kind']=='task' and i['status']=='open'])


def check(service,body):
    context=dict(project_id=body.get('project_id'),series_id=body.get('series_id'),meeting_type=body.get('meeting_type'))
    prepared=service.prepare(**context)
    account=service.github.connection.status().get('account_id')
    checked=set();errors=[]
    for row in prepared['followup']['commitments']:
        for link in row['external']:
            if len(checked)>=100:break
            key=(link['repository'],link['number'],row['item_id'])
            if key in checked:continue
            if service.github.connection.status().get('account_id')!=account:raise ValueError('GitHub account changed. Check again.')
            checked.add(key)
            try:
                with service.lock,service.github.connection.lock:
                    if service.github.connection.status().get('account_id')!=account:raise ValueError('GitHub account changed. Check again.')
                    service.github_link(dict(resource=dict(kind='item',id=row['item_id']),reference=link['url'],verify_live=True))
            except (ValueError,RuntimeError) as exc:errors.append(str(exc))
    result=service.prepare(**context);result['followup']['check_errors']=errors
    return result
