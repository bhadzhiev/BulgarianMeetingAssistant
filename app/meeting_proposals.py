"""Meeting mentions that may be existing tasks become proposals in the one For review queue (PR 4).

A meeting is one more source of the work graph, like Gmail, Chat and GitHub. A proposal comes from
the AI task matching (task-matching.json) or, without it, from the local text similarity of the notes.
A person decides: link as evidence, add the update, apply chosen field changes, choose another task,
make a new task, or reject. One decision is one checked commit; a second click finds no pending proposal.
"""
import copy
import json

from . import items as registry
from .live import read_json
from .task_matching import _cut
from .work_graph import WorkGraph, digest, now
from .work_items import WorkItemConflict

ORIGIN = 'meeting_match'
ACTIONS = ('link', 'update', 'change', 'other', 'new', 'reject')


def _source(meeting_id, rows):
    from .conversations import transcript_revision
    return dict(provider='meeting', account='local', external_id='notes:' + meeting_id,
                revision=transcript_revision(rows), text='\n'.join(row.get('text', '') for row in rows))


def _quote(mention, rows, text):
    """Evidence that occurs in the saved transcript: the segment at the moment, else the exact quote."""
    from meeting_assistant import timestamp
    stamp = mention.get('evidence_timestamp')
    for row in rows:
        if stamp and timestamp(row.get('start', 0)) == stamp and row.get('text', '').strip():
            return row['text'].strip()
    quote = mention.get('quote')
    return quote.strip() if isinstance(quote, str) and quote.strip() and quote.strip() in text else None


def _own_item(service, meeting_id, mention):
    """The proposed task that this meeting's own notes made for the mention, if any."""
    item = service.items.items.get(mention.get('item_id')) if mention.get('item_id') else None
    if item and item.get('acceptance_state') == 'proposed' and item.get('links') and all(l['meeting_id'] == meeting_id for l in item['links']):
        return item
    return None


def suggestions(service, meeting_id):
    """The proposals that one meeting's saved notes ask for, with their match data."""
    directory = service.library.directory(meeting_id)
    minutes = read_json(directory / 'minutes.json', None)
    rows = read_json(directory / 'transcript.json', [])
    if not minutes or not rows:
        return None, []
    record = read_json(directory / 'task-matching.json', {})
    ai = record.get('status') == 'complete' and record.get('notes') == 'minutes.json'
    matches = {m['mention_id']: m for m in record.get('matches', [])} if ai else {}
    sent = {m['id']: m for m in record.get('mentions', [])} if ai else {}
    source = _source(meeting_id, rows)
    found = []
    for field, prefix in (('tasks', 't'), ('updates', 'u')):
        for index, mention in enumerate(minutes.get(field, [])):
            text = mention.get('task' if field == 'tasks' else 'text') or ''
            own = None
            if field == 'tasks':
                own = _own_item(service, meeting_id, mention)
                if mention.get('item_id') and not own:
                    continue  # a task that a person already accepted or linked
            key = prefix + str(index)
            # The answer counts only for the same mention: notes that changed since are matched again later.
            match = matches.get(key) if key in sent and sent[key].get('text') == _cut(text, 200) else None
            local = [c['item_id'] for c in (mention.get('link') or {}).get('candidates', []) if c.get('item_id') in service.items.items]
            if match and match['type'] != 'new_task':
                meta = dict(type=match['type'], task_id=match['task_id'], reason=match['reason'], update_text=match['update_text'],
                            changes=match['changes'], candidates=sent[key]['candidate_ids'], basis='ai')
            elif local:
                meta = dict(type='uncertain', task_id=local[0], reason='Close wording (text similarity).', update_text=None,
                            changes=[], candidates=local, basis='similarity')
            else:
                continue
            quote = _quote(mention, rows, source['text'])
            if not quote:
                continue  # no evidence in the saved transcript, no proposal
            meta.update(meeting_id=meeting_id, field=field, index=index, mention=text, own_item=own['id'] if own else None,
                        evidence_timestamp=mention.get('evidence_timestamp'))
            found.append((dict(kind='task', text=_cut(text, 1000) or 'Mention', quote=quote,
                               locator=dict(meeting_id=meeting_id, evidence_timestamp=mention.get('evidence_timestamp'))), meta))
    return source, found


def build(service, meeting_id):
    """Create the missing proposals of one meeting. Running it again creates nothing new."""
    source, found = suggestions(service, meeting_id)
    if not found:
        return []
    identity = {key: source[key] for key in ('provider', 'account', 'external_id')}
    source_id = digest(identity)
    revision_id = digest(dict(source_id=source_id, external_revision=source['revision'], text=source['text']))
    proposals = service.items.data.get('proposals', {})
    keys = []
    for suggestion, _ in found:
        evidence = digest(dict(source_id=source_id, source_revision=revision_id, quote=suggestion['quote'], locator=suggestion['locator']))
        keys.append(digest(dict(evidence_id=evidence, kind='task', text=suggestion['text'])))
    if all(key in proposals for key in keys):
        return keys

    def after(data, result):
        for key, (_, meta) in zip(result['proposals'], found):
            proposal = data['proposals'][key]
            if proposal['state'] == 'pending' and 'match' not in proposal:
                proposal.update(origin=ORIGIN, match=meta)
    return WorkGraph(service.items).ingest(source, [suggestion for suggestion, _ in found], after=after)['proposals']


def _owner_change(service, value):
    person = next((p for p in service.people.list() if p['name'] == value), None) if value else None
    return dict(owner_person_id=person['id']) if person else dict(owner=value, owner_person_id=None) if value else dict(owner=None, owner_person_id=None)


def review(service, body):
    """A person's decision on one meeting proposal. Everything applies in one commit, or nothing does."""
    from meeting_assistant import save_minutes, validate_minutes
    action = body.get('action')
    if action not in ACTIONS:
        raise ValueError('Unknown review action')
    with service.lock, service.items.lock:
        data = service.items.data
        proposal = data['proposals'].get(body.get('id'))
        if not proposal or proposal.get('origin') != ORIGIN or proposal.get('revision') != body.get('revision'):
            raise WorkItemConflict('This proposal changed or was reviewed. Reload the For review list.')
        if proposal['state'] != 'pending':
            raise WorkItemConflict('This proposal was already reviewed.')
        meta = proposal['match']
        evidence = data['source_evidence'][proposal['evidence_id']]
        if data['sources'][evidence['source_id']]['current_revision'] != evidence['source_revision']:
            raise WorkItemConflict('The transcript changed after this proposal. Process the notes again.')
        meeting_id = meta['meeting_id']
        if meeting_id == service.active or meeting_id in service.busy:
            raise ValueError('Wait until processing finishes')
        directory = service.library.directory(meeting_id)
        minutes = json.loads((directory / 'minutes.json').read_text())
        validate_minutes(minutes)
        mentions = minutes.get(meta['field'], [])
        if not 0 <= meta['index'] < len(mentions) or mentions[meta['index']].get('task' if meta['field'] == 'tasks' else 'text') != meta['mention']:
            raise WorkItemConflict('The notes changed after this proposal. Reload and review the notes first.')
        mention = mentions[meta['index']]
        previous = copy.deepcopy(service.items.data)
        result_id = None
        try:
            if action in ('link', 'update', 'change', 'other'):
                target_id = body.get('task_id')
                if action != 'other' and target_id != meta['task_id'] and target_id not in meta['candidates']:
                    raise ValueError('Choose one of the suggested tasks, or use Other task')
                target = service.items.items.get(target_id)
                if not target or target['kind'] != 'task' or target.get('acceptance_state') == 'proposed':
                    raise ValueError('Choose an accepted task')
                if type(body.get('task_revision')) is not int or target.get('revision') != body['task_revision']:
                    raise WorkItemConflict('This task changed after the proposal opened. Check the current values and choose again.')
                # Link: the meeting becomes evidence of the task. Nothing else changes here.
                said = mention if meta['field'] == 'tasks' else dict(task=mention['text'], evidence_timestamp=mention.get('evidence_timestamp'))
                service.items.link(target_id, 'task', said, meeting_id)
                target['history'][-1]['proposal_id'] = proposal['id']
                if meta['field'] == 'tasks':
                    own = service.items.items.get(meta.get('own_item') or '')
                    if own and own['id'] != target_id and own.get('acceptance_state') == 'proposed':
                        del service.items.items[own['id']]
                    mention['item_id'] = target_id
                    mention.pop('link', None)
                    mention['status'] = target['status']
                if action == 'update':
                    note = body.get('update_text') if isinstance(body.get('update_text'), str) else meta.get('update_text')
                    note = ' '.join((note or '').split())
                    if not note or len(note) > 5000:
                        raise ValueError('Write the update of 1–5000 characters')
                    target['history'].append(dict(at=registry.now(), event='progress_update', by='user', changes={}, text=note,
                        meeting_id=meeting_id, evidence_timestamp=meta.get('evidence_timestamp'), quote=evidence['quote'][:500],
                        proposal_id=proposal['id'], accepted_at=now()))
                if action == 'change':
                    chosen = body.get('fields') or []
                    offered = {c['field']: c['value'] for c in meta.get('changes', [])}
                    if not chosen or any(name not in offered for name in chosen):
                        raise ValueError('Choose at least one of the proposed changes')
                    changes = {}
                    for name in chosen:
                        changes.update(_owner_change(service, offered[name]) if name == 'owner' else {name: offered[name]})
                    clean = service._clean_item_changes(target, changes)
                    service.items.update(target_id, clean)
                result_id = target_id
                proposal.update(state='linked', result_id=target_id)
            else:
                # New task or reject: the mention keeps or gets its own task; an update needs nothing.
                if meta['field'] == 'tasks' and not mention.get('item_id'):
                    mention['item_id'] = service.items.create('task', mention, meeting_id)
                    mention.pop('link', None)
                result_id = mention.get('item_id') if meta['field'] == 'tasks' else None
                proposal.update(state='dismissed' if action == 'reject' else 'accepted', result_id=result_id)
            proposal['revision'] += 1
            key = WorkGraph._activity(data, 'proposal_' + action, proposal_id=proposal['id'], result_id=result_id)
            if meta['field'] == 'tasks':
                service.items.sync(meeting_id, minutes)
                save_minutes(directory, minutes)
            service.items.save()
        except WorkItemConflict:
            raise
        except Exception:
            service.items.data = previous
            raise
    if result_id and action in ('link', 'update', 'change', 'other'):
        service._sync_linked({result_id}, except_meeting=meeting_id)
    return dict(proposal)
