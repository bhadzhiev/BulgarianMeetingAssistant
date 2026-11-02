"""Local review receipts bound to source and item content; never publish externally."""
import copy
import datetime as dt
import hashlib
from .work_items import canonical, WorkItemConflict


def fingerprint(item):
    return hashlib.sha256(canonical({k:v for k,v in item.items() if k not in {'history','revision','meeting_reviews'}}).encode()).hexdigest()


def snapshot(service, meeting_id):
    meeting = service.detail(meeting_id)
    source = hashlib.sha256(canonical([meeting['transcript_revision'],meeting['minutes_revision']]).encode()).hexdigest()
    rows = []
    for item in meeting['items'].values():
        if not any(link.get('meeting_id')==meeting_id and not link.get('detached') for link in item.get('links',[])):continue
        digest = fingerprint(item)
        receipt = item.get('meeting_reviews',{}).get(meeting_id)
        state = receipt['state'] if receipt and receipt['source']==source and receipt['content']==digest else 'needs_review'
        evidence=[]
        for link in item.get('links',[]):
            if link.get('meeting_id')!=meeting_id or not link.get('evidence_timestamp'):continue
            stamp=link['evidence_timestamp']
            seconds=sum(int(part)*60**n for n,part in enumerate(reversed(stamp.split(':'))))
            segment=next((r for r in meeting.get('transcript',[]) if r['start']<=seconds<r['end']),None)
            if segment:evidence.append(dict(quote=segment['text'],timestamp=stamp))
        rows.append(dict(evidence=evidence,id=item['id'],kind=item['kind'],text=item['text'],owner=item.get('owner'),state=state,
                         revision=item.get('revision'),content=digest,receipt=copy.deepcopy(receipt),
                         links=copy.deepcopy(item.get('links',[]))))
    return dict(meeting_id=meeting_id,source=source,items=rows,summary=(meeting.get('minutes') or {}).get('summary'),
                source_changed=bool(meeting.get('notes_need_refresh')))


def act(service, body):
    meeting_id=body.get('meeting_id');action=body.get('action')
    if action not in {'confirm','dismiss','edit'}:raise ValueError('Choose Confirm or Dismiss')
    with service.lock,service.items.lock,service.items.store.serialized():
        service.items.data,service.items.revision=service.items.store.load()
        current=snapshot(service,meeting_id)
        row=next((r for r in current['items'] if r['id']==body.get('item_id')),None)
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
        receipt=dict(state='edited' if action=='edit' else 'confirmed' if action=='confirm' else 'dismissed',source=current['source'],content=row['content'])
        old=item.get('meeting_reviews',{}).get(meeting_id)
        if old and all(old.get(k)==v for k,v in receipt.items()):return current
        if action=='dismiss' and old and old['state']=='confirmed':raise ValueError('A confirmed commitment cannot be dismissed as a proposal.')
        receipt.update(actor='user',at=dt.datetime.now(dt.timezone.utc).isoformat())
        item.setdefault('meeting_reviews',{})[meeting_id]=receipt
        item.setdefault('history',[]).append(dict(at=receipt['at'],event='meeting_review_'+action,by='user',meeting_id=meeting_id,changes={}))
        service.items.save()
        return snapshot(service,meeting_id)
