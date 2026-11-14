"""1:1 reviews of a team member, kept as Markdown files with their metadata. Local only.

team-reviews/<person-id>/<review-id>/
  review.md              the review: facts, evidence and questions. Fixed after Finalize.
  conversation-notes.md  notes, actions and goals of the conversation. Always editable.
  metadata.json          period, status, version, coverage and the generator snapshot.
  evidence.json          saved copies of the evidence. Fixed after Finalize.
  agreements.json        the actions and goals that the manager saved after the conversation. Always editable.

A review starts as a Draft, becomes Finalized and is then fixed. A correction is a new version: a new
Draft that names the review it replaces. When that version is finalized, the old one becomes Superseded.
Only finalized reviews move the next period; a draft, an error or a discarded draft never do.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
import re
import shutil
import threading
import uuid
from zoneinfo import ZoneInfo

from .storage import atomic_json, atomic_text
from .work_items import WorkItemConflict as Conflict

TZ = ZoneInfo('Europe/Sofia')
TIMEZONE = 'Europe/Sofia'
FIRST_PERIOD_DAYS = 7
MAX_PERIOD_DAYS = 366
MAX_REVIEW = 500_000
MAX_NOTES = 200_000
MAX_AGREEMENTS = 50
AGREEMENT_KINDS = {'action', 'goal'}
AGREEMENT_OWNERS = {'person', 'manager', 'both'}
AGREEMENT_STATES = {'open', 'done', 'dropped'}
ID = re.compile(r'[a-f0-9]{12}')
SECTIONS = ['Coverage', 'Commitments', 'Tasks', 'Decisions', 'Blockers', 'GitHub contribution',
            'Previous agreements and goals', 'Questions for the conversation']


def _now():
    return dt.datetime.now(TZ).replace(second=0, microsecond=0)


def _moment(value, field):
    """A time in Europe/Sofia. A value without an offset is a Sofia wall-clock time."""
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError(f'{field} must be a date and time')
    try:
        moment = dt.datetime.fromisoformat(value)
    except ValueError:
        raise ValueError(f'{field} must be a date and time') from None
    moment = moment.replace(tzinfo=TZ) if moment.tzinfo is None else moment.astimezone(TZ)
    return moment.replace(second=0, microsecond=0)


def _iso(moment):
    return moment.isoformat()


def _template(person_name, start, end):
    period = f"{start.strftime('%d.%m.%Y %H:%M')} – {end.strftime('%d.%m.%Y %H:%M')} ({TIMEZONE})"
    lines = [f'# 1:1 review · {person_name}', '', f'Period: {period}', '']
    for section in SECTIONS:
        lines += [f'## {section}', '', '_No facts collected yet._', '']
    return '\n'.join(lines)


class TeamReviews:
    def __init__(self, root: Path):
        self.root = Path(root) / 'team-reviews'
        self.lock = threading.RLock()

    # Files ----------------------------------------------------------------------------------------
    def directory(self, review_id):
        return self._directory(review_id)

    def _directory(self, review_id):
        if not isinstance(review_id, str) or not ID.fullmatch(review_id):
            raise ValueError('Invalid review')
        found = [path for path in self.root.glob('*/' + review_id) if path.is_dir() and ID.fullmatch(path.parent.name)]
        if len(found) != 1:
            raise ValueError('This review no longer exists. Reload and try again.')
        return found[0]

    def _read(self, directory, text=False):
        meta = json.loads((directory / 'metadata.json').read_text(encoding='utf-8'))
        if text:
            meta = dict(meta, review_md=(directory / 'review.md').read_text(encoding='utf-8'),
                        notes_md=(directory / 'conversation-notes.md').read_text(encoding='utf-8'),
                        evidence=json.loads((directory / 'evidence.json').read_text(encoding='utf-8')),
                        agreements=self._agreements(directory),
                        context=self._optional(directory, 'review-context.json', {}),
                        private_preparation=(directory / 'private-preparation.md').read_text(encoding='utf-8') if (directory / 'private-preparation.md').exists() else '')
        return meta

    @staticmethod
    def _optional(directory, name, default):
        path = directory / name
        return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default

    def overlaps(self, review):
        return [dict(id=r['id'], period=r['period']) for r in self._all(review['person_id'])
                if r['status'] == 'finalized' and r['id'] not in {review['id'], review.get('supersedes')}
                and _moment(r['period']['start'], 'Start') < _moment(review['period']['end'], 'End')
                and _moment(review['period']['start'], 'Start') < _moment(r['period']['end'], 'End')]

    def verified_results(self, task_id):
        with self.lock:
            checks = []
            for review in self._all():
                if review['status'] == 'superseded':
                    continue
                for row in self._agreements(self._directory(review['id'])):
                    if row.get('task_id') == task_id and row.get('verified_at') and row.get('expected_result') and row.get('result_evidence'):
                        checks.append(dict(row, review_id=review['id']))
            return sorted(checks, key=lambda row: row['verified_at'], reverse=True)

    def outstanding(self, person_id, before=None, exclude=()):
        with self.lock:
            seen, rows = set(), []
            for review in self._all(person_id):
                if review['status'] != 'finalized' or review['id'] in exclude:
                    continue
                if before and _moment(review['period']['end'], 'End') > _moment(before, 'Start'):
                    continue
                for row in self._agreements(self._directory(review['id'])):
                    if row['id'] in seen:
                        continue
                    seen.add(row['id'])
                    if row['status'] == 'open':
                        rows.append(dict(row, review_id=review['id'], review_end=review['period']['end']))
            return rows

    def history(self, person_id):
        """One row per review version, with live agreements but no private preparation text."""
        with self.lock:
            rows = []
            labels = {'task_completed': 'Recorded completion', 'result_confirmed': 'Result checked', 'task_overdue': 'Overdue'}
            for review in self._all(person_id):
                directory = self._directory(review['id'])
                highlights, seen = [], set()
                for record in self._optional(directory, 'evidence.json', []):
                    if record.get('kind') not in labels:
                        continue
                    try:
                        when = _moment(record.get('occurred_at'), 'Evidence date')
                    except ValueError:
                        continue
                    key = (record['kind'], (record.get('source_ref') or {}).get('item_id'), (record.get('facts') or {}).get('text'))
                    if key in seen or not _moment(review['period']['start'], 'Start') <= when < _moment(review['period']['end'], 'End'):
                        continue
                    seen.add(key)
                    highlights.append(dict(label=labels[record['kind']], text=(record.get('facts') or {}).get('text', '')))
                rows.append(dict(review, agreements=self._agreements(directory), overlaps=self.overlaps(review), highlights=highlights[:3]))
            return rows

    def save_context(self, review_id, revision, context):
        with self.lock:
            directory, meta = self._current(review_id, revision)
            if meta['status'] != 'draft':
                raise ValueError('Make a new version to change the preparation context')
            if not isinstance(context, dict):
                raise ValueError('Invalid review context')
            clean = {}
            for key in ('role', 'employee_view', 'manager_support', 'focus'):
                value = context.get(key, '')
                if not isinstance(value, str) or len(value) > 5000:
                    raise ValueError('Each context field has at most 5000 characters')
                clean[key] = value.strip()
            if type(context.get('include_in_ai', False)) is not bool:
                raise ValueError('Choose whether context may be included in the AI preview')
            clean['include_in_ai'] = context.get('include_in_ai', False)
            observations = context.get('observations', [])
            if not isinstance(observations, list) or len(observations) > 20:
                raise ValueError('Choose at most 20 observations')
            # The service resolves selected IDs to saved source snapshots; client text is never trusted.
            clean['observations'] = observations
            atomic_json(directory / 'review-context.json', clean)
            (directory / 'private-preparation.md').unlink(missing_ok=True)
            self._write_meta(directory, dict(meta, generator=None, revision=meta['revision'] + 1, updated=_iso(dt.datetime.now(TZ))))
            return self.get(review_id)

    def save_conversation(self, review_id, revision, held_at):
        with self.lock:
            directory, meta = self._current(review_id, revision)
            if held_at is not None:
                held_at = _moment(held_at, 'Conversation date')
                if held_at > dt.datetime.now(TZ):
                    raise ValueError('A conducted conversation cannot be in the future')
                held_at = _iso(held_at)
            self._write_meta(directory, dict(meta, conversation_at=held_at, revision=meta['revision'] + 1, updated=_iso(dt.datetime.now(TZ))))
            return self.get(review_id)

    @staticmethod
    def _agreements(directory):
        path = directory / 'agreements.json'
        return json.loads(path.read_text(encoding='utf-8')) if path.exists() else []

    def _all(self, person_id=None):
        if not self.root.exists():
            return []
        rows = []
        if person_id is not None and not (isinstance(person_id, str) and ID.fullmatch(person_id)):
            return []
        for path in self.root.glob(('*' if person_id is None else person_id) + '/*/metadata.json'):
            if not ID.fullmatch(path.parent.name) or not ID.fullmatch(path.parent.parent.name):
                continue
            try:
                rows.append(self._read(path.parent))
            except (OSError, ValueError):
                continue
        return sorted(rows, key=lambda r: (r['period']['end'], r['created']), reverse=True)

    def _write_meta(self, directory, meta):
        atomic_json(directory / 'metadata.json', meta)

    def _current(self, review_id, revision):
        directory = self._directory(review_id)
        meta = self._read(directory)
        if type(revision) is not int or revision != meta['revision']:
            raise Conflict('This review changed. Reload and try again.')
        return directory, meta

    # Reading --------------------------------------------------------------------------------------
    def list(self, person_id=None):
        with self.lock:
            return self._all(person_id)

    def get(self, review_id):
        with self.lock:
            return self._read(self._directory(review_id), text=True)

    def next_period(self, person_id):
        """The next period: from the end of the last finalized review until now; the last 7 days for the first review."""
        with self.lock:
            end = _now()
            done = [r for r in self._all(person_id) if r['status'] in {'finalized', 'superseded'}]
            if done:
                start = max(_moment(r['period']['end'], 'End') for r in done)
                first = False
            else:
                start = end - dt.timedelta(days=FIRST_PERIOD_DAYS)
                first = True
            if start >= end:
                start = end - dt.timedelta(days=1)
            return dict(start=_iso(start), end=_iso(end), timezone=TIMEZONE, first=first)

    def summary(self, person_id):
        """The last finalized review and the open draft of a person, for the Team card."""
        rows = self.list(person_id)
        last = next((r for r in rows if r['status'] == 'finalized'), None)
        draft = next((r for r in rows if r['status'] == 'draft'), None)
        return dict(last_finalized=last and dict(id=last['id'], end=last['period']['end'], finalized_at=last['finalized_at']),
                    draft=draft and dict(id=draft['id']))

    # Changes --------------------------------------------------------------------------------------
    def create(self, person, start, end, supersedes=None, collect=None):
        """A new Draft for a period [start, end). One draft per person at a time."""
        with self.lock:
            start, end = _moment(start, 'Start'), _moment(end, 'End')
            if start >= end:
                raise ValueError('The period must end after it starts')
            if end - start > dt.timedelta(days=MAX_PERIOD_DAYS):
                raise ValueError(f'Choose a period of at most {MAX_PERIOD_DAYS} days')
            if end > _now() + dt.timedelta(days=1):
                raise ValueError('The period cannot end in the future')
            rows = self._all(person['id'])
            if any(r['status'] == 'draft' for r in rows):
                raise ValueError(f'{person["name"]} already has a draft review. Open it, or discard it first.')
            review_md, evidence, version = _template(person['name'], start, end), [], 1
            coverage = dict(sources=[], limitations=[])
            if collect is not None and supersedes is None:
                # The facts of the period, collected without AI. They replace the empty template.
                facts = collect(_iso(start), _iso(end), self.previous(person['id'], _iso(start)))
                review_md, evidence, coverage = facts['review_md'], facts['evidence'], dict(facts['coverage'], excluded_items=facts['excluded'])
            if supersedes is not None:
                old_dir = self._directory(supersedes)
                old = self._read(old_dir)
                if old['person_id'] != person['id'] or old['status'] != 'finalized':
                    raise ValueError('Only a finalized review of this person can get a new version')
                review_md = (old_dir / 'review.md').read_text(encoding='utf-8')
                evidence = json.loads((old_dir / 'evidence.json').read_text(encoding='utf-8'))
                start, end, version = _moment(old['period']['start'], 'Start'), _moment(old['period']['end'], 'End'), old['version'] + 1
                coverage = old.get('coverage') or coverage
            review_id = uuid.uuid4().hex[:12]
            now = _iso(dt.datetime.now(TZ))
            meta = dict(id=review_id, person_id=person['id'], person_name=person['name'],
                        period=dict(start=_iso(start), end=_iso(end), timezone=TIMEZONE), status='draft', version=version,
                        supersedes=supersedes, superseded_by=None, created=now, updated=now, finalized_at=None, revision=1,
                        coverage=coverage, generator=None)
            # The files go to a hidden folder first; one rename makes the review appear complete.
            person_dir = self.root / person['id']
            person_dir.mkdir(parents=True, exist_ok=True)
            partial = person_dir / ('.' + review_id)
            partial.mkdir()
            try:
                atomic_text(partial / 'review.md', review_md)
                atomic_text(partial / 'conversation-notes.md', (old_dir / 'conversation-notes.md').read_text(encoding='utf-8') if supersedes else '')
                if supersedes:
                    atomic_json(partial / 'agreements.json', self._agreements(old_dir))
                    if (old_dir / 'review-context.json').exists():
                        atomic_json(partial / 'review-context.json', self._optional(old_dir, 'review-context.json', {}))
                    if (old_dir / 'private-preparation.md').exists():
                        atomic_text(partial / 'private-preparation.md', (old_dir / 'private-preparation.md').read_text(encoding='utf-8'))
                    meta['conversation_at'] = old.get('conversation_at')
                if not supersedes:
                    previous = self.previous(person['id'], _iso(start))
                    if previous:
                        context = self._optional(self._directory(previous['id']), 'review-context.json', {})
                        reusable = {k: context[k] for k in ('role', 'focus') if context.get(k)}
                        if reusable:
                            atomic_json(partial / 'review-context.json', dict(reusable, include_in_ai=False, observations=[]))
                atomic_json(partial / 'evidence.json', evidence)
                atomic_json(partial / 'metadata.json', meta)
                partial.rename(person_dir / review_id)
            finally:
                if partial.exists():
                    shutil.rmtree(partial)
            return self.get(review_id)

    def previous(self, person_id, before=None, replaces=None):
        """The last finalized review of a person with its evidence, for the carried-over commitments and the comparison.

        A new version compares with the review before the one it corrects, never with that review itself.
        """
        done = [r for r in self._all(person_id) if r['status'] == 'finalized' and r['id'] != replaces
                and (before is None or _moment(r['period']['end'], 'End') <= _moment(before, 'Start'))]
        if not done:
            return None
        directory = self._directory(done[0]['id'])
        return dict(id=done[0]['id'], period=done[0]['period'], coverage=done[0].get('coverage') or {}, revision=done[0]['revision'],
                    evidence=json.loads((directory / 'evidence.json').read_text(encoding='utf-8')), agreements=self._agreements(directory),
                    outstanding=self.outstanding(person_id, before, exclude=(done[0]['id'],)))

    def recollect(self, review_id, revision, collect):
        """Collect the facts of a draft again. The new text replaces the old one; the notes stay."""
        with self.lock:
            directory, meta = self._current(review_id, revision)
            if meta['status'] != 'draft':
                raise ValueError('Only a draft collects facts again')
            facts = collect(meta['period']['start'], meta['period']['end'], self.previous(meta['person_id'], meta['period']['start'], meta.get('supersedes')))
            atomic_text(directory / 'review.md', facts['review_md'])
            atomic_json(directory / 'evidence.json', facts['evidence'])
            (directory / 'private-preparation.md').unlink(missing_ok=True)
            self._write_meta(directory, dict(meta, coverage=dict(facts['coverage'], excluded_items=facts['excluded']), generator=None, revision=meta['revision'] + 1, updated=_iso(dt.datetime.now(TZ))))
            return self.get(review_id)

    def set_generator(self, review_id, revision, generator):
        """Record the AI target, prompt and input of a run before it starts. An incomplete run blocks Finalize."""
        with self.lock:
            directory, meta = self._current(review_id, revision)
            if meta['status'] != 'draft':
                raise ValueError('Only a draft gets AI preparation')
            self._write_meta(directory, dict(meta, generator=generator, revision=meta['revision'] + 1, updated=_iso(dt.datetime.now(TZ))))

    def apply_ai(self, review_id, revision, text, generator):
        """Save the AI part of a draft. A draft that changed during the run keeps its text; the run can repeat."""
        with self.lock:
            try:
                directory, meta = self._current(review_id, revision)
            except Conflict:
                raise Conflict('The draft changed during the AI preparation. Run it again; the finished parts are kept.') from None
            if meta['status'] != 'draft' or len(text) > MAX_REVIEW:
                raise ValueError('The AI result does not fit this draft')
            atomic_text(directory / ('private-preparation.md' if generator.get('private') else 'review.md'), text)
            self._write_meta(directory, dict(meta, generator=generator, revision=meta['revision'] + 1, updated=_iso(dt.datetime.now(TZ))))
            return self.get(review_id)

    def apply_github(self, review_id, revision, result, records, section, replace_section):
        """Save the GitHub part of a draft. New records replace the old GitHub records; the other records keep their IDs.

        The AI part goes away, because it may cite the old records. A person runs the AI again.
        """
        with self.lock:
            try:
                directory, meta = self._current(review_id, revision)
            except Conflict:
                raise Conflict('The draft changed during the GitHub collection. Run it again; the read parts are kept.') from None
            if meta['status'] != 'draft':
                raise ValueError('Only a draft collects GitHub contribution')
            evidence = [r for r in json.loads((directory / 'evidence.json').read_text(encoding='utf-8')) if (r.get('source_ref') or {}).get('provider') != 'github']
            first = max((int(r['id'][1:]) for r in evidence), default=0) + 1
            evidence += records(result, meta['person_id'], first)
            text = (directory / 'review.md').read_text(encoding='utf-8')
            text = re.sub(r'\n## AI observations\n.*?(?=\n## Questions for the conversation\n)', '\n', text, flags=re.S)
            last = self.previous(meta['person_id'])
            text = replace_section(text, section(result, ((last or {}).get('coverage') or {}).get('github', {}).get('counts')))
            coverage = dict(meta.get('coverage') or {})
            coverage['sources'] = sorted(set(coverage.get('sources', [])) | {'github'})
            coverage['github'] = dict(included=result['included'], limitations=result['limitations'], calls=result['calls'],
                                      counts=dict(authored=len(result['authored']), reviews=len(result['reviews']), commits=len(result['commits'])))
            atomic_text(directory / 'review.md', text)
            atomic_json(directory / 'evidence.json', evidence)
            (directory / 'private-preparation.md').unlink(missing_ok=True)
            self._write_meta(directory, dict(meta, coverage=coverage, generator=None, revision=meta['revision'] + 1, updated=_iso(dt.datetime.now(TZ))))
            return self.get(review_id)

    def save_review(self, review_id, revision, text):
        """Edit the text of a Draft. A finalized review is fixed."""
        with self.lock:
            if not isinstance(text, str) or len(text) > MAX_REVIEW:
                raise ValueError(f'A review has at most {MAX_REVIEW} characters')
            directory, meta = self._current(review_id, revision)
            if meta['status'] != 'draft':
                raise ValueError('A finalized review is fixed. Make a new version to correct it.')
            atomic_text(directory / 'review.md', text)
            self._write_meta(directory, dict(meta, revision=meta['revision'] + 1, updated=_iso(dt.datetime.now(TZ))))
            return self.get(review_id)

    def save_agreements(self, review_id, revision, rows, verifier='The manager'):
        """The actions and goals of the conversation. Only what the manager saves counts; they change apart from the review."""
        with self.lock:
            if not isinstance(rows, list) or len(rows) > MAX_AGREEMENTS:
                raise ValueError(f'Save at most {MAX_AGREEMENTS} actions and goals')
            directory, meta = self._current(review_id, revision)
            old = {row['id']: row for row in self._agreements(directory)}
            now, clean = _iso(dt.datetime.now(TZ)), []
            for row in rows:
                if not isinstance(row, dict):
                    raise ValueError('Invalid action or goal')
                text = row.get('text')
                if not isinstance(text, str) or not text.strip() or len(text) > 1000:
                    raise ValueError('Each action or goal needs a text of up to 1000 characters')
                if row.get('kind') not in AGREEMENT_KINDS or row.get('owner') not in AGREEMENT_OWNERS or row.get('status') not in AGREEMENT_STATES:
                    raise ValueError('Choose the kind, the owner and the state of each action or goal')
                due = row.get('due_date')
                if due is not None:
                    try:
                        due = dt.date.fromisoformat(due).isoformat()
                    except (TypeError, ValueError):
                        raise ValueError('A due date must be YYYY-MM-DD') from None
                key = row.get('id') if isinstance(row.get('id'), str) and row['id'] in old else uuid.uuid4().hex[:12]
                task = row.get('task_id') if isinstance(row.get('task_id'), str) and re.fullmatch(r'[a-f0-9]{12,32}', row['task_id']) else None
                fields = {}
                for field in ('expected_result', 'result_evidence'):
                    value = row.get(field, '')
                    if not isinstance(value, str) or len(value) > 2000:
                        raise ValueError('Expected result and evidence have at most 2000 characters')
                    fields[field] = value.strip()
                check = row.get('verified', bool(row.get('verified_at')))
                if type(check) is not bool:
                    raise ValueError('Choose whether the result was checked')
                if check and row['status'] != 'done':
                    raise ValueError('A checked result must be marked done')
                if check and (not fields['expected_result'] or not fields['result_evidence']):
                    raise ValueError('A checked result needs an expected result and evidence of the check')
                unchanged_check = check and old.get(key, {}).get('verified_at') and all(old[key].get(k) == fields[k] for k in fields)
                entry = dict(id=key, kind=row['kind'], text=' '.join(text.split()), owner=row['owner'], due_date=due, status=row['status'], task_id=task,
                             **fields, verified_at=(old[key]['verified_at'] if unchanged_check else now) if check else None,
                             verified_by=(old[key].get('verified_by', verifier) if unchanged_check else verifier) if check else None,
                             created=old.get(key, {}).get('created', now), updated=now)
                changes = {k: [old.get(key, {}).get(k), v] for k, v in entry.items() if k not in {'updated', 'created'} and old.get(key, {}).get(k) != v}
                entry['history'] = list(old.get(key, {}).get('history', []))
                if changes:
                    entry['history'].append(dict(at=now, changes=changes))
                else:
                    entry['updated'] = old.get(key, {}).get('updated', now)
                clean.append(entry)
            if len({r['id'] for r in clean}) != len(clean):
                raise ValueError('Each action or goal is saved once')
            atomic_json(directory / 'agreements.json', clean)
            self._write_meta(directory, dict(meta, revision=meta['revision'] + 1, updated=now))
            return self.get(review_id)

    def delete(self, review_id, revision):
        """Delete a review with its notes, agreements and evidence. The version links of the others stay valid."""
        with self.lock:
            directory, meta = self._current(review_id, revision)
            now = _iso(dt.datetime.now(TZ))
            if meta.get('supersedes'):
                try:
                    old_dir = self._directory(meta['supersedes'])
                    old = self._read(old_dir)
                    if old.get('superseded_by') == review_id:
                        # The review that this version replaced is the current one again.
                        self._write_meta(old_dir, dict(old, status='finalized' if old['status'] == 'superseded' else old['status'], superseded_by=None, revision=old['revision'] + 1, updated=now))
                except ValueError:
                    pass
            if meta.get('superseded_by'):
                try:
                    new_dir = self._directory(meta['superseded_by'])
                    new = self._read(new_dir)
                    self._write_meta(new_dir, dict(new, supersedes=None, revision=new['revision'] + 1, updated=now))
                except ValueError:
                    pass
            shutil.rmtree(directory)
            if directory.parent.exists() and not any(directory.parent.iterdir()):
                directory.parent.rmdir()
            return dict(deleted=review_id, person_id=meta['person_id'])

    def save_notes(self, review_id, revision, text):
        """The conversation notes change apart from the review, also after Finalize."""
        with self.lock:
            if not isinstance(text, str) or len(text) > MAX_NOTES:
                raise ValueError(f'Notes have at most {MAX_NOTES} characters')
            directory, meta = self._current(review_id, revision)
            atomic_text(directory / 'conversation-notes.md', text)
            self._write_meta(directory, dict(meta, revision=meta['revision'] + 1, updated=_iso(dt.datetime.now(TZ))))
            return self.get(review_id)

    def finalize(self, review_id, revision, acknowledge_overlap=False):
        with self.lock:
            directory, meta = self._current(review_id, revision)
            if meta['status'] != 'draft':
                raise ValueError('Only a draft can be finalized')
            if meta.get('generator') and not meta['generator'].get('complete'):
                raise ValueError('The AI preparation is incomplete. Run it again, or collect the facts again without AI.')
            overlaps = self.overlaps(meta)
            if overlaps and acknowledge_overlap is not True:
                raise ValueError('This period overlaps another finalized review. Check the periods and explicitly acknowledge the overlap.')
            now = _iso(dt.datetime.now(TZ))
            if meta['supersedes']:
                old_dir = self._directory(meta['supersedes'])
                old = self._read(old_dir)
                if old['status'] == 'finalized':
                    self._write_meta(old_dir, dict(old, status='superseded', superseded_by=review_id, revision=old['revision'] + 1, updated=now))
            self._write_meta(directory, dict(meta, status='finalized', finalized_at=now, revision=meta['revision'] + 1, updated=now))
            return self.get(review_id)

    def discard(self, review_id, revision):
        """Delete a Draft. It never moved the period, so nothing else changes."""
        with self.lock:
            directory, meta = self._current(review_id, revision)
            if meta['status'] != 'draft':
                raise ValueError('Only a draft can be discarded')
            shutil.rmtree(directory)
            return dict(discarded=review_id, person_id=meta['person_id'])

