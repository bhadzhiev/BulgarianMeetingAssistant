"""Local links between Atlanta resources and GitHub issues or pull requests.

A link lives only on this Mac. It does not change GitHub, and GitHub does not know about it unless the
published text includes an Atlanta reference.
"""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import threading

from .github_source import repo_name
from .storage import atomic_json

KINDS = {'item', 'attachment'}
RESOURCE_ID = re.compile(r'[a-f0-9]{8,64}')
URL = re.compile(r'https://github\.com/([A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100})/(?:issues|pull)/([1-9][0-9]{0,9})(?:[/?#].*)?')
SHORT = re.compile(r'(?:([A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}))?#([1-9][0-9]{0,9})')
MAX_LINKS = 5000


from .work_items import WorkItemConflict as Conflict


def parse(reference, repository=''):
    """(owner/name, number) from "#123", "owner/name#123" or an issue or pull request URL."""
    if not isinstance(reference, str):
        raise ValueError('Enter #123, owner/name#123 or a GitHub URL')
    reference = reference.strip()
    match = URL.fullmatch(reference) or SHORT.fullmatch(reference)
    if not match:
        raise ValueError('Enter #123, owner/name#123 or a GitHub URL')
    repo = match[1] or repository
    if not repo:
        raise ValueError('Choose the repository for #' + match[2])
    return repo_name(repo), int(match[2])


def resource(value):
    if not isinstance(value, dict) or value.get('kind') not in KINDS or not isinstance(value.get('id'), str) or not RESOURCE_ID.fullmatch(value['id']):
        raise ValueError('Choose a task, decision, question or saved excerpt')
    return dict(kind=value['kind'], id=value['id'])


class GitHubLinks:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.lock = threading.RLock()
        try:
            data = json.loads(self.path.read_text())
            self.links = {key: row for key, row in data.items() if isinstance(row, dict)} if isinstance(data, dict) else {}
        except (OSError, ValueError):
            self.links = {}

    def _save(self):
        atomic_json(self.path, self.links)

    @staticmethod
    def key(target, repository, number):
        return hashlib.sha256(f'{target["kind"]}:{target["id"]}:{repository.casefold()}:{number}'.encode()).hexdigest()[:24]

    def link(self, target, repository, number, details=None):
        """Save one link. Linking the same resource and issue again refreshes the cached title and state."""
        target, repository = resource(target), repo_name(repository)
        if type(number) is not int or number <= 0:
            raise ValueError('Invalid issue number')
        details = details or {}
        with self.lock:
            key = self.key(target, repository, number)
            old = self.links.get(key)
            if not old and len(self.links) >= MAX_LINKS:
                raise ValueError(f'At most {MAX_LINKS} GitHub links')
            row = dict(id=key, resource=target, repository=repository, number=number,
                       url=f'https://github.com/{repository}/{"pull" if details.get("kind") == "pull_request" else "issues"}/{number}',
                       kind=details.get('kind') or 'unknown', title=str(details.get('title') or '')[:300], state=details.get('state'),
                       issue_id=details.get('issue_id'), verified=bool(details.get('verified')),
                       linked_at=old['linked_at'] if old else dt.datetime.now(dt.timezone.utc).isoformat(),
                       revision=old['revision'] + 1 if old else 1)
            self.links[key] = row
            self._save()
            return copy.deepcopy(row)

    def unlink(self, key, revision):
        with self.lock:
            old = self.links.get(key)
            if not old or old['revision'] != revision:
                raise Conflict('This link changed. Reload and try again.')
            del self.links[key]
            self._save()

    def for_resource(self, kind, key):
        with self.lock:
            return copy.deepcopy(sorted((r for r in self.links.values() if r['resource'] == dict(kind=kind, id=key)), key=lambda r: r['linked_at']))

    def for_issue(self, repository, number):
        with self.lock:
            return copy.deepcopy([r for r in self.links.values() if r['repository'].casefold() == repository.casefold() and r['number'] == number])

    def all(self):
        with self.lock:
            return copy.deepcopy(list(self.links.values()))

    def merge(self, other):
        """Add archived links that this library does not have."""
        with self.lock:
            for key, row in (other.items() if isinstance(other, dict) else []):
                try:
                    if key in self.links or row['id'] != key:
                        continue
                    resource(row['resource'])
                    repo_name(row['repository'])
                    if type(row['number']) is not int or row['number'] <= 0:
                        continue
                    self.links[key] = row
                except (ValueError, TypeError, KeyError):
                    continue
            self._save()
