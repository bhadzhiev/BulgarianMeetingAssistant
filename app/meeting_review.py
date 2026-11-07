"""Local review receipts bound to source and item content; never publish externally.

Confirm and Dismiss reach the whole app: Dismiss sets the item's dismissed flag, which My Work,
Prepare me and Follow-up respect, and review_state tells them what a person has confirmed.
"""
import copy
import datetime as dt
import hashlib
import re
from .transcripts import segment_at
from .work_items import canonical, WorkItemConflict

# A person reviews what an item says. Status, snooze and dismissal change later without a new review.
REVIEWED=('kind','text','owner','deadline','due_date','details','completion_criteria','owner_person_id')
ORDER={'needs_review':0,'edited':1,'confirmed':2,'dismissed':3}


def fingerprint(item):
    fields={k:item.get(k) for k in REVIEWED[:5]}
    fields.update({k:item[k] for k in REVIEWED[5:] if item.get(k) not in (None,'')})
    return hashlib.sha256(canonical(fields).encode()).hexdigest()


def legacy_minutes_evidence(minutes):
    """The first evidence: the whole notes without review markers. Receipts made with it stay valid while it holds."""
    def clean(value):
        if isinstance(value,dict):return {k:clean(v) for k,v in value.items() if k!='review'}
        if isinstance(value,list):return [clean(v) for v in value]
        return value
    return hashlib.sha256(canonical(clean(minutes)).encode()).hexdigest()


def minutes_evidence(minutes):
    """What the notes say, without their task and decision lists.

    Those lists mirror the registry: an owner, a due date, a status or a new task that a person sets is
    written back into them. Each item has its own content fingerprint, so a change to one item asks for
    a new review of that item only, not of every item in the meeting.
    """
    if isinstance(minutes,dict):minutes={k:v for k,v in minutes.items() if k not in ('tasks','decisions')}
    return legacy_minutes_evidence(minutes)


def source_matches(receipt, source):
    if isinstance(source,dict):
        # Older receipts stay valid on their original exact source; no review is invented.
        if receipt.get('evidence'):return receipt['evidence'] in {source.get('evidence'),source.get('legacy_evidence')}
        return receipt.get('source')==source.get('source')
    return receipt.get('source')==source


def accept_content(item):
    """Accept the displayed commitment; speaker placeholders are never confirmed people."""
    changes={}
    if item['kind']=='task':
        if item.get('acceptance_state')!='accepted':changes['acceptance_state']=[item.get('acceptance_state'),'accepted']
        item.update(acceptance_state='accepted',legacy_unreviewed=False)
        owner=item.get('owner')
        if owner and not re.fullmatch(r'SPEAKER[ _-]?\d+',owner.strip(),re.I) and 'owner' not in item['manual']:
            item['manual'].append('owner');changes['owner']=[owner,owner]
    elif item['kind']=='decision':
        if item['status']!='accepted':changes['status']=[item['status'],'accepted']
        item['status']='accepted'
        if 'status' not in item['manual']:item['manual'].append('status')
    return changes


# A person sets these as the current state of an item. Setting them is itself a check, not new wording.
PERSON_STATE=('owner','owner_person_id','due_date')


def keep_confirmed(item, before, changed):
    """A person's own owner or due date keeps the reviews that held before it.

    Without this, every owner or date set after a confirmation asks for the same confirmation again.
    New wording, details or an AI change still need a new review.
    """
    if not set(changed)&set(REVIEWED) or set(changed)&set(REVIEWED)-set(PERSON_STATE):return
    after=fingerprint(item)
    for receipt in item.get('meeting_reviews',{}).values():
        if receipt.get('state')=='confirmed' and receipt.get('content')==before:receipt['content']=after


def confirm_linked(service, item):
    """An explicit global Accept reviews the current linked sources, never a stale/busy source."""
    sources=service.review_sources();at=dt.datetime.now(dt.timezone.utc).isoformat()
    for link in item.get('links',[]):
        mid=link['meeting_id']
        if link.get('detached') or mid not in sources or mid==service.active or mid in service.busy:continue
        meeting=service.library.get(mid)
        if meeting.get('notes_need_refresh') or meeting.get('notes_refresh_error'):continue
        source=sources[mid];old=item.get('meeting_reviews',{}).get(mid)
        receipt=dict(state='confirmed',source=source['source'] if isinstance(source,dict) else source,content=fingerprint(item),actor='user',at=at)
        if isinstance(source,dict):receipt['evidence']=source['evidence']
        if old and old.get('state')=='confirmed' and old.get('content')==receipt['content'] and source_matches(old,source):continue
        item.setdefault('meeting_reviews',{})[mid]=receipt
        item.setdefault('history',[]).append(dict(at=at,event='meeting_review_confirm',by='user',meeting_id=mid,changes={}))


def review_state(item, sources=None):
    """The item's review across meetings: confirmed, edited, needs_review, or None without a meeting."""
    digest=fingerprint(item);states={r['state'] for mid,r in item.get('meeting_reviews',{}).items() if r['content']==digest and (sources is None or source_matches(r,sources.get(mid)))}
    if 'confirmed' in states and not (item['kind']=='decision' and item.get('status')!='accepted'):return 'confirmed'
    if 'edited' in states:return 'edited'
    return 'needs_review' if any(not link.get('detached') for link in item.get('links',[])) else None


def source_digest(transcript_revision, minutes_revision):
    return hashlib.sha256(canonical([transcript_revision,minutes_revision]).encode()).hexdigest()


def linked(item, meeting_id):
    return any(link.get('meeting_id')==meeting_id and not link.get('detached') for link in item.get('links',[]))


def meeting_state(item, meeting_id, source):
    """The item's review in one meeting; the receipt holds only while source and content stay the same."""
    receipt = item.get('meeting_reviews',{}).get(meeting_id)
    state = receipt['state'] if receipt and source_matches(receipt,source) and receipt['content']==fingerprint(item) else 'needs_review'
    if state=='confirmed' and item['kind']=='decision' and item.get('status')!='accepted':return 'needs_review'
    # Restored in My Work: the dismissal no longer holds.
    return 'needs_review' if state=='dismissed' and not item.get('dismissed') else state


def current_sources(service, meeting_ids, meeting_id, source):
    """Resolve actual source revisions; a receipt alone is never proof of a current review."""
    if hasattr(service,'review_sources'):
        result=dict(service.review_sources())
    else:
        result={}
        for mid in meeting_ids:
            try:
                meeting=service.detail(mid)
                result[mid]=source_digest(meeting['transcript_revision'],meeting['minutes_revision'])
            except (OSError,ValueError,KeyError):pass
    result.setdefault(meeting_id,source)
    return result


def dismissal(item, meeting_id, source, sources):
    digest=fingerprint(item)
    confirmed=[mid for mid,receipt in item.get('meeting_reviews',{}).items()
               if mid!=meeting_id and linked(item,mid) and receipt.get('state')=='confirmed'
               and receipt.get('content')==digest and mid in sources and source_matches(receipt,sources[mid])]
    if meeting_state(item,meeting_id,source)=='confirmed':reason='confirmed_here'
    elif confirmed:reason='confirmed_elsewhere'
    elif item['kind']=='task' and item.get('acceptance_state')=='accepted':reason='accepted_task'
    else:reason=None
    return dict(can_dismiss=reason is None,dismiss_blocked_reason=reason,confirmed_in=confirmed)


def snapshot(service, meeting_id):
    meeting = service.detail(meeting_id)
    source = source_digest(meeting['transcript_revision'],meeting['minutes_revision'])
    rows = []
    linked_ids={link['meeting_id'] for item in meeting['items'].values() for link in item.get('links',[]) if not link.get('detached')}
    sources=current_sources(service,linked_ids,meeting_id,source)
    refs=meeting.get('item_meetings',{})
    for item in meeting['items'].values():
        if not linked(item,meeting_id):continue
        digest = fingerprint(item)
        receipt = item.get('meeting_reviews',{}).get(meeting_id)
        state = meeting_state(item,meeting_id,sources.get(meeting_id,source))
        evidence=[]
        stamps=list(dict.fromkeys([m.get('evidence_timestamp') for field in ('tasks','decisions') for m in (meeting.get('minutes') or {}).get(field,[]) if m.get('item_id')==item['id']] + [link.get('evidence_timestamp') for link in item.get('links',[]) if link.get('meeting_id')==meeting_id and not link.get('detached')]))
        for stamp in stamps:
            if not stamp:continue
            segment=segment_at(meeting.get('transcript',[]),stamp)
            if segment:evidence.append(dict(quote=segment['text'],timestamp=stamp,start=segment['start'],end=segment['end']))
        # Routing is not review content: a project or destination change keeps the review.
        projects=service.effective_project_ids(item)
        routing=dict(project_ids=copy.deepcopy(item.get('project_ids')),effective_project_ids=projects,
                     destination_repository=item.get('destination_repository'),repositories=service.project_repositories(projects) if item['kind']=='task' else [])
        guard=dismissal(item,meeting_id,sources.get(meeting_id,source),sources)
        guard['confirmed_in']=[dict(meeting_id=mid,title=refs.get(mid,{}).get('title') or 'Confirmed meeting') for mid in guard['confirmed_in']]
        rows.append(dict(routing,**guard,evidence=evidence,id=item['id'],kind=item['kind'],text=item['text'],owner=item.get('owner'),state=state,
                         revision=item.get('revision'),content=digest,receipt=copy.deepcopy(receipt),
                         links=copy.deepcopy(item.get('links',[]))))
    rows.sort(key=lambda row:ORDER[row['state']])
    return dict(meeting_id=meeting_id,source=source,items=rows,summary=(meeting.get('minutes') or {}).get('summary'),
                source_changed=bool(meeting.get('notes_need_refresh')))


def act(service, body):
    meeting_id=body.get('meeting_id');action=body.get('action')
    if action not in {'confirm','dismiss','edit','restore'}:raise ValueError('Choose Confirm or Dismiss')
    with service.lock,service.items.lock,service.items.store.serialized():
        service.items.data,service.items.revision=service.items.store.load()
        current=snapshot(service,meeting_id)
        row=next((r for r in current['items'] if r['id']==body.get('item_id')),None)
        # A lost response may retry the exact approval after our own review-marker sync.
        # Only the already-current receipt can acknowledge it; changed evidence still conflicts.
        existing=service.items.items.get(body.get('item_id'))
        receipt=(existing or {}).get('meeting_reviews',{}).get(meeting_id,{})
        if (action=='confirm' and row and row['state']=='confirmed' and not current['source_changed']
                and row['content']==body.get('content') and receipt.get('source')==body.get('source')
                and current['source']!=body.get('source')
                and (existing['kind']!='task' or existing.get('acceptance_state')=='accepted')):
            return current
        if not row or current['source']!=body.get('source') or row['content']!=body.get('content'):
            raise WorkItemConflict('Source or item changed. Review again.')
        if current['source_changed']:raise WorkItemConflict('Update the notes from the changed transcript before confirming.')
        item=service.items.items[row['id']]
        if action=='edit':
            changes=body.get('changes')
            if not isinstance(changes,dict) or not changes or set(changes)-({'text','owner'} if item['kind']=='task' else {'text'}):raise ValueError('Edit text or task owner')
            service.update_item(item['id'],item['text'],changes,item.get('revision'))
            current=snapshot(service,meeting_id)
            row=next(r for r in current['items'] if r['id']==item['id'])
            item=service.items.items[row['id']]
        old=item.get('meeting_reviews',{}).get(meeting_id)
        now=dt.datetime.now(dt.timezone.utc).isoformat()
        if action=='restore':
            if row['state']!='dismissed':return current
            item['dismissed']=False;item['meeting_reviews'].pop(meeting_id)
            item.setdefault('history',[]).append(dict(at=now,event='meeting_review_restore',by='user',meeting_id=meeting_id,changes={'dismissed':[True,False]}))
            service.items.save();return snapshot(service,meeting_id)
        previous=copy.deepcopy(service.items.data)
        receipt=dict(state='edited' if action=='edit' else 'confirmed' if action=='confirm' else 'dismissed',source=current['source'],content=row['content'])
        if old and all(old.get(k)==v for k,v in receipt.items()) and action!='confirm':return current
        if action=='dismiss':
            if not row['can_dismiss']:
                raise ValueError('This task is already confirmed or accepted. Open the task to review its current state. If it no longer applies, choose Cancel task.' if item['kind']=='task' else 'This item is already confirmed. Open it in My Work to review its current state.')
        changes={}
        # Dismiss hides the item everywhere; Confirm brings a dismissed item back.
        if item.get('dismissed')!=(action=='dismiss') and action!='edit':
            changes['dismissed']=[bool(item.get('dismissed')),action=='dismiss'];item['dismissed']=action=='dismiss'
        if action=='confirm':changes.update(accept_content(item))
        receipt['content']=fingerprint(item)
        context=current_sources(service,[meeting_id],meeting_id,current['source']).get(meeting_id)
        if isinstance(context,dict):receipt['evidence']=context['evidence']
        if old and old.get('state')==receipt['state'] and old.get('content')==receipt['content'] and source_matches(old,context) and not changes:return current
        receipt.update(actor='user',at=now)
        item.setdefault('meeting_reviews',{})[meeting_id]=receipt
        item.setdefault('history',[]).append(dict(at=now,event='meeting_review_'+action,by='user',meeting_id=meeting_id,changes=changes))
        try:service.items.save()
        except WorkItemConflict:raise
        except Exception:
            service.items.data=previous
            raise
        if action=='confirm' and hasattr(service,'_sync_linked'):service._sync_linked({item['id']})
        return snapshot(service,meeting_id)
