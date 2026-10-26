"""Local, evidence-backed proposals. No connector or AI/network calls live here."""
import copy
import datetime as dt
import hashlib
import uuid

from .work_items import COLLECTIONS, WorkItemConflict, canonical

KINDS = {'task': 'open', 'decision': 'proposed', 'question': 'open'}
RELATIONS = {'same_as', 'derives_from', 'implements', 'supersedes', 'supports'}


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def text(value, name, limit=1000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f'Invalid {name}')
    return value.strip()


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def proposal_fields(fields, quote):
    if not isinstance(fields, dict) or set(fields) - {'owner', 'deadline', 'due_date'}:
        raise ValueError('Invalid proposed task fields')
    clean = {}
    for name, value in fields.items():
        if value is None:
            continue
        value = text(value, name, 160)
        if value.casefold() not in quote.casefold():
            raise ValueError('Owner and deadline fields must occur in the evidence quote')
        if name == 'due_date' and dt.date.fromisoformat(value).isoformat() != value:
            raise ValueError('Proposed due dates must be explicit ISO dates in the quote')
        clean[name] = value
    return clean


def validate_graph(graph, items=None):
    """Validate portable graph records before any database mutation."""
    for collection in COLLECTIONS:
        records = graph.get(collection, {})
        if not isinstance(records, dict):
            raise ValueError('Invalid work graph collection')
        for key, record in records.items():
            if not isinstance(record, dict) or record.get('id') != key:
                raise ValueError('Invalid work graph record')
    sources, revisions, evidence = (graph[name] for name in ('sources', 'source_revisions', 'source_evidence'))
    for source in sources.values():
        identity = {key: source.get(key) for key in ('provider', 'account', 'external_id')}
        for key, value in identity.items():
            text(value, key)
        if source['id'] != digest(identity) or type(source.get('available')) is not bool:
            raise ValueError('Invalid source identity')
        revision = revisions.get(source.get('current_revision'))
        if not revision or revision.get('source_id') != source['id']:
            raise ValueError('Missing current source revision')
    for revision in revisions.values():
        body = {key: revision.get(key) for key in ('source_id', 'external_revision', 'text')}
        text(body['external_revision'], 'source revision')
        text(body['text'], 'source content', 1_000_000)
        if revision['id'] != digest(body) or revision['source_id'] not in sources:
            raise ValueError('Invalid immutable source revision')
    for entry in evidence.values():
        body = {key: entry.get(key) for key in ('source_id', 'source_revision', 'quote', 'locator')}
        revision = revisions.get(entry.get('source_revision'))
        if (entry['id'] != digest(body) or not revision or entry.get('source_id') != revision['source_id']
                or not isinstance(entry.get('quote'), str) or not entry['quote'] or entry['quote'] not in revision['text']
                or not isinstance(entry.get('locator'), dict)):
            raise ValueError('Evidence must quote a pinned source revision')
    for proposal in graph['proposals'].values():
        if (proposal.get('kind') not in KINDS or proposal.get('evidence_id') not in evidence
                or proposal.get('state') not in {'pending', 'accepted', 'linked', 'dismissed', 'stale'}
                or type(proposal.get('revision')) is not int or proposal['revision'] < 1):
            raise ValueError('Invalid proposal')
        text(proposal.get('text'), 'proposal text')
        if proposal.get('fields'):
            if proposal['kind'] != 'task':
                raise ValueError('Only task proposals have owner/date fields')
            proposal_fields(proposal['fields'], evidence[proposal['evidence_id']]['quote'])
        if proposal.get('snoozed_until'):
            if dt.date.fromisoformat(proposal['snoozed_until']).isoformat() != proposal['snoozed_until']:
                raise ValueError('Invalid proposal snooze date')
    for edge in graph['relationships'].values():
        if (edge.get('kind') not in RELATIONS or edge.get('from_id') == edge.get('to_id')
                or not isinstance(edge.get('from_id'), str) or not isinstance(edge.get('to_id'), str)):
            raise ValueError('Invalid work relationship')
        if items is not None and any(key not in items for key in (edge['from_id'], edge['to_id'])):
            raise ValueError('Missing relationship endpoint')
    if items is not None:
        for item in items.values():
            if any(key not in evidence for key in item.get('source_evidence', [])):
                raise ValueError('Missing WorkItem source evidence')


class WorkGraph:
    def __init__(self, registry):
        self.registry = registry

    def _write(self, operation):
        registry = self.registry
        with registry.lock, registry.store.serialized():
            data, revision = registry.store.load()
            result = operation(data)
            revision = registry.store.save(data, revision)
            registry.data, registry.revision = data, revision
            return copy.deepcopy(result)

    def snapshot(self):
        registry = self.registry
        with registry.lock:
            return {name: copy.deepcopy(list(registry.data.get(name, {}).values())) for name in COLLECTIONS}

    @staticmethod
    def _activity(data, event, **values):
        key = uuid.uuid4().hex
        data['activity'][key] = dict(id=key, at=now(), actor='user', event=event, **values)

    def ingest(self, source, suggestions, after=None):
        """One immutable content revision + all proposals commit together, or none do.

        source/suggestions are untrusted data. Ingestion grants no AI-export permission.
        """
        identity = {key: text(source.get(key), key) for key in ('provider', 'account', 'external_id')}
        source_id = digest(identity)
        body = dict(source_id=source_id, external_revision=text(source.get('revision'), 'source revision'),
                    text=text(source.get('text'), 'source content', 1_000_000))
        revision_id = digest(body)
        if not isinstance(suggestions, list) or len(suggestions) > 100:
            raise ValueError('At most 100 proposals per revision')
        def apply(data):
            for old in data['source_revisions'].values():
                if old['source_id'] == source_id and old['external_revision'] == body['external_revision'] and old['id'] != revision_id:
                    raise WorkItemConflict('This source revision already has different content.')
            previous = data['sources'].get(source_id)
            if previous and previous['current_revision'] != revision_id and revision_id in data['source_revisions']:
                raise WorkItemConflict('An older source revision cannot replace the current one.')
            data['source_revisions'][revision_id] = dict(body, id=revision_id)
            # Consent stays explicit even if the same account is used for Calendar.
            same = previous and previous['current_revision'] == revision_id
            data['sources'][source_id] = dict(identity, id=source_id, current_revision=revision_id,
                available=True, ai_export_allowed=bool(same and previous.get('ai_export_allowed')))
            if same and previous.get('ai_consent'):
                data['sources'][source_id]['ai_consent'] = previous['ai_consent']
            for proposal in data['proposals'].values():
                ev = data['source_evidence'][proposal['evidence_id']]
                if proposal['state'] == 'pending' and ev['source_id'] == source_id and ev['source_revision'] != revision_id:
                    proposal.update(state='stale', revision=proposal['revision'] + 1)
            ids = []
            for suggestion in suggestions:
                if not isinstance(suggestion, dict) or suggestion.get('kind') not in KINDS:
                    raise ValueError('Invalid suggestion kind')
                quote = text(suggestion.get('quote'), 'evidence quote', 10000)
                locator = suggestion.get('locator', {})
                if quote not in body['text'] or not isinstance(locator, dict):
                    raise ValueError('Evidence must occur in the saved source content')
                ev = dict(source_id=source_id, source_revision=revision_id, quote=quote, locator=locator)
                ev_id = digest(ev)
                data['source_evidence'][ev_id] = dict(ev, id=ev_id)
                content = text(suggestion.get('text'), 'proposal text')
                fields = proposal_fields(suggestion.get('fields', {}), quote)
                if fields and suggestion['kind'] != 'task':
                    raise ValueError('Only task proposals have owner/date fields')
                proposal_identity = dict(evidence_id=ev_id, kind=suggestion['kind'], text=content)
                if fields:
                    proposal_identity['fields'] = fields
                key = digest(proposal_identity)
                if key not in data['proposals']:
                    data['proposals'][key] = dict(id=key, kind=suggestion['kind'], text=content, evidence_id=ev_id,
                        state='pending', revision=1, snoozed_until=None, created=now(), fields=fields)
                    if suggestion.get('origin') == 'gmail_ai':
                        data['proposals'][key]['origin'] = 'gmail_ai'
                ids.append(key)
            result = dict(source_id=source_id, source_revision=revision_id, proposals=ids)
            if after:
                after(data, result)
            return result
        return self._write(apply)

    def ai_consent(self, source_id, source_revision, consent):
        def apply(data):
            source = data['sources'].get(source_id)
            if not source or source['current_revision'] != source_revision or not source['available']:
                raise WorkItemConflict('The source changed. Reopen the message before approving AI access.')
            source['ai_export_allowed'] = consent is not None
            if consent is None:
                source.pop('ai_consent', None)
            else:
                source['ai_consent'] = consent
            self._activity(data, 'source_ai_consent', source_id=source_id, allowed=consent is not None)
            return source
        return self._write(apply)

    def availability(self, source_id, source_revision, available):
        if type(available) is not bool:
            raise ValueError('Availability must be true or false')
        def apply(data):
            source = data['sources'].get(source_id)
            if not source or source['current_revision'] != source_revision:
                raise WorkItemConflict('The source changed. Reload before changing availability.')
            source['available'] = available
            if not available:
                source['ai_export_allowed'] = False
                source.pop('ai_consent', None)
            self._activity(data, 'source_availability', source_id=source_id, available=available)
            return source
        return self._write(apply)

    def review(self, key, revision, action, *, target_id=None, target_revision=None, snoozed_until=None):
        def apply(data):
            proposal = data['proposals'].get(key)
            if not proposal or type(revision) is not int or proposal['revision'] != revision:
                raise WorkItemConflict('This proposal changed. Reload Suggested.')
            if proposal['state'] not in {'pending', 'dismissed'}:
                raise WorkItemConflict('This proposal is no longer available for review.')
            evidence = data['source_evidence'][proposal['evidence_id']]
            source = data['sources'][evidence['source_id']]
            if action in {'accept', 'link', 'restore'} and (not source['available'] or source['current_revision'] != evidence['source_revision']):
                raise WorkItemConflict('The source changed or is unavailable. Review its current revision first.')
            if action in {'accept', 'link'}:
                if proposal['state'] != 'pending':
                    raise ValueError('Restore the proposal before accepting it')
                if action == 'accept':
                    target_id_value = uuid.uuid4().hex[:16]
                    item = dict(id=target_id_value, kind=proposal['kind'], text=proposal['text'], status=KINDS[proposal['kind']],
                        managed_by='work_graph', links=[], source_evidence=[], created=now(), manual=[], history=[],
                        owner=None, deadline=None, due_date=None, supersedes=[], superseded_by=None)
                    item.update(proposal.get('fields', {}))
                    data['items'][target_id_value] = item
                else:
                    item = data['items'].get(target_id)
                    if not item or type(target_revision) is not int or item.get('revision') != target_revision:
                        raise WorkItemConflict('The target item changed. Reload before linking.')
                    if item['kind'] != proposal['kind']:
                        raise ValueError('Link to an item of the same kind')
                    target_id_value = target_id
                item.setdefault('source_evidence', [])
                if evidence['id'] not in item['source_evidence']:
                    item['source_evidence'].append(evidence['id'])
                # Link adds evidence only; it cannot overwrite a human's state or wording.
                item['history'].append(dict(at=now(), event='source_linked', by='user', changes={}, meeting_id=None,
                                            evidence_id=evidence['id']))
                proposal.update(state='accepted' if action == 'accept' else 'linked', result_id=target_id_value)
            elif action in {'dismiss', 'restore'}:
                proposal.update(state='dismissed' if action == 'dismiss' else 'pending', snoozed_until=None)
            elif action == 'snooze':
                if proposal['state'] != 'pending':
                    raise ValueError('Only pending proposals can be snoozed')
                if snoozed_until is not None:
                    if not isinstance(snoozed_until, str) or dt.date.fromisoformat(snoozed_until).isoformat() != snoozed_until:
                        raise ValueError('Snooze date must use YYYY-MM-DD')
                proposal['snoozed_until'] = snoozed_until
            else:
                raise ValueError('Unknown proposal action')
            proposal['revision'] += 1
            self._activity(data, 'proposal_' + action, proposal_id=key, result_id=proposal.get('result_id'))
            return proposal
        return self._write(apply)

    def question(self, value, *, item_id=None, revision=None, answer=None):
        def apply(data):
            if item_id:
                item = data['items'].get(item_id)
                if not item or item['kind'] != 'question' or type(revision) is not int or revision != item.get('revision'):
                    raise WorkItemConflict('This question changed. Reload My Work.')
                before = {name: item.get(name) for name in ('status', 'answer')}
                item.update(status='answered' if answer is not None else 'open', answer=text(answer, 'answer', 10000) if answer is not None else None)
                item.setdefault('manual', []).extend(name for name in ('status', 'answer') if name not in item['manual'])
            else:
                key = uuid.uuid4().hex[:16]
                item = dict(id=key, kind='question', text=text(value, 'question'), status='open', answer=None,
                    managed_by='work_graph', links=[], source_evidence=[], created=now(), manual=['text', 'status'], history=[],
                    supersedes=[], superseded_by=None)
                data['items'][key] = item
            changes = {name: [before[name], item.get(name)] for name in before if before[name] != item.get(name)} if item_id else {}
            item['history'].append(dict(at=now(), event='question_updated' if item_id else 'created', by='user', changes=changes, meeting_id=None))
            self._activity(data, 'question_changed', item_id=item['id'], status=item['status'])
            return item
        return self._write(apply)

    def relate(self, from_id, to_id, kind, from_revision, to_revision):
        if kind not in RELATIONS or from_id == to_id:
            raise ValueError('Invalid relationship')
        def apply(data):
            for key, revision in ((from_id, from_revision), (to_id, to_revision)):
                if key not in data['items'] or type(revision) is not int or data['items'][key].get('revision') != revision:
                    raise WorkItemConflict('A related item changed. Reload first.')
            left, right = sorted((from_id, to_id)) if kind == 'same_as' else (from_id, to_id)
            # Directed relationships cannot introduce cycles of the same type.
            reachable, queue = set(), [right]
            while queue:
                node = queue.pop()
                if node in reachable:
                    continue
                reachable.add(node)
                queue.extend(edge['to_id'] for edge in data['relationships'].values() if edge['kind'] == kind and edge['from_id'] == node)
            if kind != 'same_as' and left in reachable:
                raise ValueError('This relationship would create a cycle')
            body = dict(kind=kind, from_id=left, to_id=right)
            key = digest(body)
            if key not in data['relationships']:
                data['relationships'][key] = dict(body, id=key)
                self._activity(data, 'relationship_added', relationship_id=key)
            return data['relationships'][key]
        return self._write(apply)
