"""The GitHub contribution of a 1:1 review: pull requests, reviews and commits of one person in a period. No AI.

- A pull request belongs to its author. A review belongs to its reviewer. The person who merges gets no authorship.
- Release and back-merge pull requests are noise: one count, no list. A hotfix stays.
- A commit of a known pull request joins it; the other commits are listed apart. Each URL counts once.
- Work without a link to an Atlanta work item is "unlinked work". A link needs a person's choice.
- A repository that GitHub denies, a rate limit or a partial search is a coverage limit, never "no contribution".
- GitHub never adds to the task counts.

Each GitHub answer is saved as a checkpoint next to the review, so an interrupted collection continues from there.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import secrets
import threading
import time

from .github_source import GitHubError, repo_name
from .storage import atomic_json
from .team_facts import _time
from .work_items import WorkItemConflict

SEARCH_PAGES = 3
PAGE = 100
MAX_PULLS = 150
MAX_COMMITS = 60
NOISE = re.compile(r'^(?:release\b|back[- ]?merge\b|merge (?:branch|main|master|develop|release)\b|sync (?:main|master|develop)\b)', re.I)
NOISE_BRANCH = re.compile(r'^(?:release|back[-_]?merge)[/-]', re.I)
HOTFIX = re.compile(r'hot[- ]?fix', re.I)


def is_noise(pull):
    """A release or back-merge pull request. A hotfix is never noise."""
    title, head = pull.get('title') or '', (pull.get('head') or {}).get('ref') or ''
    if HOTFIX.search(title) or HOTFIX.search(head):
        return False
    base = (pull.get('base') or {}).get('ref') or ''
    back = head in {'main', 'master'} and base in {'develop', 'dev'}
    return bool(NOISE.search(title) or NOISE_BRANCH.search(head) or back)


class Reader:
    """GitHub reads with a checkpoint: an answer that came once is not asked again."""

    def __init__(self, connection, checkpoint, save):
        self.connection, self.cache, self.save, self.calls = connection, checkpoint, save, 0

    def get(self, resource, query=None):
        key = resource + '?' + json.dumps(query or {}, sort_keys=True)
        if key not in self.cache:
            self.calls += 1
            self.cache[key] = self.connection.get(resource, query)
            self.save(self.cache)
        return self.cache[key]

    def search(self, resource, q, limitations, label):
        rows, page = [], 1
        while page <= SEARCH_PAGES:
            result = self.get(resource, dict(q=q, per_page=PAGE, page=page))
            data = result['data']
            if not isinstance(data, dict) or not isinstance(data.get('items'), list):
                raise GitHubError('GitHub returned an invalid search page.')
            rows += data['items']
            if data.get('incomplete_results'):
                limitations.add(f'GitHub returned incomplete {label} search results.')
            if not result.get('has_next'):
                break
            page += 1
        else:
            limitations.add(f'Only the first {SEARCH_PAGES * PAGE} {label} search results are read.')
        return rows


def _repository(row):
    match = re.match(r'https://api\.github\.com/repos/([^/]+/[^/]+)$', row.get('repository_url') or '')
    return repo_name(match[1]) if match else None


def _days(start, end):
    return f'{start.astimezone(dt.timezone.utc).date().isoformat()}..{end.astimezone(dt.timezone.utc).date().isoformat()}'


def discover(reader, login, start, end):
    """The repositories where the person has pull requests or reviews in the period, with counts."""
    limitations, repos, pulls = set(), {}, {}
    days = _days(start, end)
    for role, q, label in (('author', f'type:pr author:{login} updated:{days}', 'pull request'),
                           ('reviewer', f'type:pr reviewed-by:{login} updated:{days}', 'review')):
        for row in reader.search('/search/issues', q, limitations, label):
            repository = _repository(row)
            if not repository or type(row.get('number')) is not int:
                continue
            key = f'{repository}#{row["number"]}'
            entry = pulls.setdefault(key, dict(repository=repository, number=row['number'], title=row.get('title') or '', url=row.get('html_url') or '', roles=set()))
            entry['roles'].add(role)
            counts = repos.setdefault(repository, dict(authored=0, reviewed=0))
            counts['authored' if role == 'author' else 'reviewed'] += 1
    return dict(repositories=[dict(name=name, **counts) for name, counts in sorted(repos.items())],
                pulls=[dict(v, roles=sorted(v['roles'])) for v in pulls.values()], limitations=sorted(limitations))


def collect(reader, login, start, end, include, links, progress=lambda text: None):
    """Read each pull request of the chosen repositories once, with its reviews; then the commits."""
    found = discover(reader, login, start, end)
    limitations = set(found['limitations'])
    chosen = [p for p in found['pulls'] if p['repository'] in include]
    if len(chosen) > MAX_PULLS:
        limitations.add(f'Only the first {MAX_PULLS} of {len(chosen)} pull requests are read.')
        chosen = chosen[:MAX_PULLS]
    authored, reviews, merged_for_others, noise, denied = [], [], 0, 0, set()
    seen_urls, pull_shas = set(), {}
    in_period = lambda value: (lambda m: m is not None and start <= m < end)(_time(value))
    for index, entry in enumerate(chosen):
        progress(f'Reading pull request {index + 1} of {len(chosen)}')
        repository, number = entry['repository'], entry['number']
        try:
            pull = reader.get(f'/repos/{repository}/pulls/{number}')['data']
        except GitHubError as exc:
            # A rate limit stops the collection; only a denied or missing repository is skipped.
            if getattr(exc, 'status', None) in {403, 404} and not getattr(exc, 'rate_limited', False):
                denied.add(repository)
                continue
            raise
        url = pull.get('html_url') or entry['url']
        if url in seen_urls:
            continue
        seen_urls.add(url)
        author = ((pull.get('user') or {}).get('login') or '')
        title = f'{repository} #{number}: {pull.get("title") or entry["title"]}'
        if pull.get('merge_commit_sha'):
            pull_shas[pull['merge_commit_sha']] = url
        if pull.get('head', {}).get('sha'):
            pull_shas[pull['head']['sha']] = url
        linked = bool(links(repository, number))
        if author.casefold() == login.casefold():
            if is_noise(pull):
                noise += 1
            else:
                events = []
                if in_period(pull.get('created_at')): events.append(('opened', pull['created_at']))
                if pull.get('merged_at') and in_period(pull['merged_at']): events.append(('merged', pull['merged_at']))
                elif pull.get('closed_at') and in_period(pull['closed_at']): events.append(('closed without merge', pull['closed_at']))
                if not events: events.append(('changed', pull.get('updated_at')))
                authored.append(dict(title=title, url=url, repository=repository, number=number, events=events, linked=linked,
                                     state='merged' if pull.get('merged_at') else pull.get('state'), hotfix=bool(HOTFIX.search(title) or HOTFIX.search((pull.get('head') or {}).get('ref') or '')), commits=0))
        elif ((pull.get('merged_by') or {}).get('login') or '').casefold() == login.casefold() and in_period(pull.get('merged_at')):
            merged_for_others += 1
        if 'reviewer' in entry['roles']:
            page = reader.get(f'/repos/{repository}/pulls/{number}/reviews', dict(per_page=PAGE))
            for review in page['data'] if isinstance(page['data'], list) else []:
                if ((review.get('user') or {}).get('login') or '').casefold() == login.casefold() and in_period(review.get('submitted_at')):
                    reviews.append(dict(title=title, url=review.get('html_url') or url, pull_url=url, state=(review.get('state') or '').lower().replace('_', ' '),
                                        at=review['submitted_at'], linked=linked))
            if page.get('has_next'):
                limitations.add('Some pull requests have more than 100 reviews; only the first 100 are read.')
    # Commits: a commit of a read pull request joins it; the others are listed apart.
    progress('Reading commits')
    commits = []
    try:
        rows = reader.search('/search/commits', f'author:{login} author-date:{_days(start, end)}', limitations, 'commit')
    except GitHubError as exc:
        if getattr(exc, 'status', None) not in {403, 422} or getattr(exc, 'rate_limited', False):
            raise
        rows = []
        limitations.add('GitHub did not return the commit search. Commits are not in this review.')
    by_url = {p['url']: p for p in authored}
    for row in rows[:MAX_COMMITS]:
        repository = (row.get('repository') or {}).get('full_name')
        sha, url = row.get('sha'), row.get('html_url')
        if not repository or repository not in include or not isinstance(sha, str) or not re.fullmatch(r'[a-f0-9]{40}', sha) or url in seen_urls:
            continue
        seen_urls.add(url)
        when = ((row.get('commit') or {}).get('author') or {}).get('date')
        if not in_period(when):
            continue
        pull_url = pull_shas.get(sha)
        if not pull_url:
            try:
                owners = reader.get(f'/repos/{repository}/commits/{sha}/pulls')['data']
                pull_url = next((p.get('html_url') for p in owners if isinstance(p, dict) and p.get('html_url') in by_url), None) if isinstance(owners, list) else None
            except GitHubError as exc:
                if getattr(exc, 'status', None) not in {403, 404, 422} or getattr(exc, 'rate_limited', False):
                    raise
        if pull_url and pull_url in by_url:
            by_url[pull_url]['commits'] += 1
        elif not any(p['url'] == pull_url for p in authored):
            message = ((row.get('commit') or {}).get('message') or '').splitlines()[0][:200]
            commits.append(dict(title=f'{repository} {sha[:8]}: {message}', url=url, at=when))
    if len(rows) > MAX_COMMITS:
        limitations.add(f'Only the first {MAX_COMMITS} commits are read.')
    for repository in sorted(denied):
        limitations.add(f'GitHub denied access to {repository}. Its contribution is not in this review.')
    return dict(repositories=found['repositories'], included=sorted(include), authored=authored, reviews=reviews, commits=commits,
                merged_for_others=merged_for_others, noise=noise, limitations=sorted(limitations), calls=reader.calls)


def records(result, person_id, first_id):
    """Evidence records for the GitHub facts, numbered after the other records."""
    rows, number = [], first_id
    def add(kind, at, basis, facts, url):
        nonlocal number
        rows.append(dict(id=f'e{number}', kind=kind, person_id=person_id, source_ref=dict(item_id=None, meeting_id=None, timestamp=None, provider='github', url=url),
                         occurred_at=at, confirmation_basis=basis, facts=facts, quote=''))
        number += 1
        return rows[-1]['id']
    for pull in result['authored']:
        pull['refs'] = [add('github_pr_' + event.replace(' ', '_'), at, 'GitHub: the person is the author of the pull request',
                            dict(text=pull['title'], event=event, state=pull['state'], unlinked=not pull['linked'], hotfix=pull['hotfix'], commits=pull['commits']), pull['url'])
                        for event, at in pull['events']]
    for review in result['reviews']:
        review['ref'] = add('github_review', review['at'], 'GitHub: the person submitted the review', dict(text=review['title'], state=review['state'], unlinked=not review['linked']), review['url'])
    for commit in result['commits']:
        commit['ref'] = add('github_commit', commit['at'], 'GitHub: the person is the commit author; no pull request found', dict(text=commit['title'], unlinked=True), commit['url'])
    return rows


def counts(result):
    return dict(authored=len(result['authored']), reviews=len(result['reviews']), commits=len(result['commits']))


def section(result, previous=None):
    """The GitHub section of the review. Counts stay apart from the task counts."""
    refs = lambda ids: ' ' + ' '.join(f'[{i}]' for i in ids)
    out = ['## GitHub contribution', '']
    excluded = [r['name'] for r in result['repositories'] if r['name'] not in result['included']]
    out.append(f"- Repositories: {len(result['included'])} included" + (f" · excluded by you: {', '.join(excluded)}" if excluded else ''))
    out += [f'- {text}' for text in result['limitations']]
    out.append('- GitHub contribution is not added to the task counts.')
    if previous:
        now = counts(result)
        out.append(f"- Last review: {previous.get('authored', 0)} pull requests · {previous.get('reviews', 0)} reviews · {previous.get('commits', 0)} commits without a pull request. This review: {now['authored']} · {now['reviews']} · {now['commits']}. The repositories can differ.")
    out += ['', f"### Pull requests by the person · {len(result['authored'])}", '']
    for pull in result['authored']:
        notes = [', '.join(e for e, _ in pull['events'])] + (['hotfix'] if pull['hotfix'] else []) + ([f"{pull['commits']} commits"] if pull['commits'] else []) + ([] if pull['linked'] else ['unlinked work'])
        out.append(f"- {pull['title']} · {pull['state']} · {' · '.join(notes)}{refs(pull['refs'])}")
    if not result['authored']:
        out.append('_No pull requests by the person in this period and these repositories._')
    out += ['', f"### Reviews given · {len(result['reviews'])}", '']
    out += [f"- {r['title']} · {r['state']}{' · unlinked work' if not r['linked'] else ''}{refs([r['ref']])}" for r in result['reviews']] or ['_No reviews in this period._']
    if result['commits']:
        out += ['', f"### Commits without a pull request · {len(result['commits'])}", '']
        out += [f"- {c['title']} · unlinked work{refs([c['ref']])}" for c in result['commits']]
    out.append('')
    if result['noise']:
        out.append(f"- Release and back-merge pull requests: {result['noise']} (not listed)")
    if result['merged_for_others']:
        out.append(f"- Pull requests of others that the person merged: {result['merged_for_others']} (merging is not authorship)")
    out.append('- Unlinked work has no link to an Atlanta work item. Link it from the GitHub tab when you choose to.')
    return '\n'.join(out) + '\n'


def replace_section(review_md, text):
    pattern = re.compile(r'## GitHub contribution\n.*?(?=\n## )', re.S)
    if pattern.search(review_md):
        return pattern.sub(lambda _m: text.rstrip('\n') + '\n', review_md, count=1)
    return review_md.rstrip('\n') + '\n\n' + text


class TeamGitHub:
    """One cancellable GitHub collection at a time, with a checkpoint next to the review."""

    def __init__(self, service):
        self.service, self.lock, self.cancel, self.thread, self.job = service, threading.RLock(), threading.Event(), None, {}

    def _person(self, review):
        person = self.service.people.get(review['person_id'])
        login = ((person or {}).get('github') or {}).get('login')
        if not login:
            raise ValueError('Add the GitHub username of this person in People first.')
        if not self.service.github.connection.status().get('connected'):
            raise ValueError('Connect GitHub in My Work → GitHub first.')
        return person, login

    def _reader(self, review_id):
        path = self.service.team_reviews.directory(review_id) / '.github-checkpoint.json'
        cache = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        return Reader(self.service.github.connection, cache, lambda data: atomic_json(path, data)), path

    def discover(self, review_id):
        """The repositories with activity of the person in the period, for the person to choose."""
        review = self.service.team_reviews.get(review_id)
        if review['status'] != 'draft':
            raise ValueError('Only a draft collects GitHub contribution')
        person, login = self._person(review)
        reader, _path = self._reader(review_id)
        try:
            found = discover(reader, login, _time(review['period']['start']), _time(review['period']['end']))
        except GitHubError as exc:
            raise ValueError(('GitHub rate limit reached. Try again later. ' if getattr(exc, 'rate_limited', False) else '') + str(exc)) from None
        return dict(login=login, repositories=found['repositories'], limitations=found['limitations'], pulls=len(found['pulls']), revision=review['revision'])

    def start(self, body):
        review_id, include = body.get('id'), body.get('repositories')
        if not isinstance(include, list) or not include or len(include) > 200 or any(not isinstance(r, str) for r in include):
            raise ValueError('Choose at least one repository')
        review = self.service.team_reviews.get(review_id)
        if review['revision'] != body.get('revision'):
            raise WorkItemConflict('The draft changed. Find the activity again.')
        self._person(review)
        with self.lock:
            if self.thread and self.thread.is_alive():
                raise ValueError('Finish or cancel the current GitHub collection first')
            self.cancel.clear()
            run = secrets.token_hex(16)
            self.job = dict(id=run, review_id=review_id, running=True, status='Reading GitHub', error=None, started_at=time.time())
            self.thread = threading.Thread(target=self._run, args=(review_id, sorted(set(map(repo_name, include)))), daemon=True, name='team-github')
            self.thread.start()
            return dict(self.job)

    def _progress(self, text):
        if self.cancel.is_set() or self.service.closed.is_set():
            raise InterruptedError('Cancelled')
        with self.lock:
            self.job['status'] = text

    def _run(self, review_id, include):
        try:
            review = self.service.team_reviews.get(review_id)
            person, login = self._person(review)
            reader, path = self._reader(review_id)
            result = collect(reader, login, _time(review['period']['start']), _time(review['period']['end']), set(include),
                             lambda repository, number: self.service.github_links.for_issue(repository, number), self._progress)
            self.service.team_reviews.apply_github(review_id, review['revision'], result, records, section, replace_section)
            path.unlink(missing_ok=True)
            with self.lock:
                self.job.update(status='Ready to review')
        except InterruptedError:
            with self.lock:
                self.job.update(status='Cancelled · the read parts are kept')
        except GitHubError as exc:
            message = ('GitHub rate limit reached. ' if getattr(exc, 'rate_limited', False) else '') + str(exc) + ' The read parts are kept; run it again to continue.'
            with self.lock:
                self.job.update(status='Stopped', error=message)
        except Exception as exc:
            with self.lock:
                self.job.update(status='Failed', error=self.service.redact(str(exc)))
        finally:
            with self.lock:
                self.job.update(running=False)

    def status(self, key):
        with self.lock:
            if key != self.job.get('id'):
                raise ValueError('This GitHub collection is no longer available')
            return dict(self.job)

    def stop(self, key):
        with self.lock:
            if key != self.job.get('id'):
                raise ValueError('This GitHub collection is no longer available')
            self.cancel.set()
            self.job['status'] = 'Cancelling'
            return dict(self.job)

    def close(self):
        self.cancel.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=5)
