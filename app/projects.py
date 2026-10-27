"""Projects (for example "DevOps" or "Client X") and series of recurring meetings inside a project."""
from __future__ import annotations

import json
from pathlib import Path
import threading
import uuid

from .storage import atomic_json


def _name(value) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 80 or any(ord(c) < 32 for c in value):
        raise ValueError('A name must be one line of 1 to 80 characters')
    return ' '.join(value.split())


class Projects:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.RLock()
        try:
            data = json.loads(path.read_text())
            if not isinstance(data.get('projects'), list) or not isinstance(data.get('series'), list):
                raise ValueError
        except (OSError, ValueError, AttributeError):
            data = dict(projects=[], series=[])
        self.data = data

    def save(self) -> None:
        atomic_json(self.path, self.data)

    def get(self, kind: str, entry_id):
        return next((entry for entry in self.data[kind] if entry['id'] == entry_id), None)

    def ensure_project(self, spec) -> str | None:
        """None, {"id": ...} for an existing project, or {"name": ...} for an existing or new one."""
        if spec is None:
            return None
        if not isinstance(spec, dict):
            raise ValueError('Invalid project')
        if 'id' in spec:
            if not self.get('projects', spec['id']):
                raise ValueError('This project no longer exists. Reload and try again.')
            return spec['id']
        name = _name(spec.get('name'))
        found = next((p for p in self.data['projects'] if p['name'].casefold() == name.casefold()), None)
        if found:
            return found['id']
        project = dict(id=uuid.uuid4().hex[:12], name=name)
        self.data['projects'].append(project)
        return project['id']

    def ensure_series(self, spec, project_id) -> str | None:
        if spec is None:
            return None
        if project_id is None:
            raise ValueError('Choose a project for the series')
        if not isinstance(spec, dict):
            raise ValueError('Invalid series')
        if 'id' in spec:
            series = self.get('series', spec['id'])
            if not series or series['project_id'] != project_id:
                raise ValueError('This series does not belong to the project')
            return spec['id']
        name = _name(spec.get('name'))
        found = next((s for s in self.data['series'] if s['project_id'] == project_id and s['name'].casefold() == name.casefold()), None)
        if found:
            return found['id']
        series = dict(id=uuid.uuid4().hex[:12], name=name, project_id=project_id)
        self.data['series'].append(series)
        return series['id']

    def _same_name(self, kind: str, name: str, project_id=None):
        """The entry with this name, ignoring case. Series names are unique inside one project."""
        return next((e for e in self.data[kind] if e['name'].casefold() == name.casefold()
                     and (kind == 'projects' or e['project_id'] == project_id)), None)

    def rename(self, kind: str, entry_id, name) -> None:
        entry = self.get(kind, entry_id)
        if not entry:
            raise ValueError('This entry no longer exists. Reload and try again.')
        name = _name(name)
        other = self._same_name(kind, name, entry.get('project_id'))
        if other and other['id'] != entry_id:
            raise ValueError(('A project' if kind == 'projects' else 'A series in this project') + ' already has this name')
        entry['name'] = name

    def set_series_type(self, series_id, kind) -> None:
        """The default meeting type of a series. New meetings of the series start with it. The caller checks the type."""
        series = self.get('series', series_id)
        if not series:
            raise ValueError('This series no longer exists. Reload and try again.')
        series['type'] = kind

    def series_type(self, series_id) -> str:
        from .meeting_types import CUSTOM_ID, DEFAULT, TYPES
        kind = (self.get('series', series_id) or {}).get('type')
        return kind if kind in TYPES or isinstance(kind, str) and CUSTOM_ID.fullmatch(kind) else DEFAULT

    def set_repositories(self, project_id, repositories) -> list[str]:
        """The GitHub repositories of a project. One repository can belong to several projects."""
        from .github_source import repo_name
        project = self.get('projects', project_id)
        if not project:
            raise ValueError('This project no longer exists. Reload and try again.')
        if not isinstance(repositories, list) or len(repositories) > 30:
            raise ValueError('A project has at most 30 repositories')
        result = []
        for value in repositories:
            name = repo_name(value.strip() if isinstance(value, str) else value)
            if name.casefold() not in {r.casefold() for r in result}:
                result.append(name)
        project['repositories'] = result
        return result

    def delete(self, kind: str, entry_id) -> set[str]:
        """Remove a project with its series, or one series. Returns the removed series IDs."""
        if not self.get(kind, entry_id):
            raise ValueError('This entry no longer exists. Reload and try again.')
        if kind == 'projects':
            removed = {s['id'] for s in self.data['series'] if s['project_id'] == entry_id}
            self.data['projects'] = [p for p in self.data['projects'] if p['id'] != entry_id]
        else:
            removed = {entry_id}
        self.data['series'] = [s for s in self.data['series'] if s['id'] not in removed]
        return removed

    def merge(self, other: dict) -> dict:
        """Add the projects and series of an archive. Returns {kind: {archived ID: ID in this library}}.

        An archived entry with the name of a local entry joins the local entry. An archived entry
        whose ID is used locally for a different name gets a new ID, so its meetings keep their group.
        """
        from .meeting_types import CUSTOM_ID, TYPES
        mapping = dict(projects={}, series={})
        for kind in ('projects', 'series'):
            entries = other.get(kind, [])
            for entry in entries if isinstance(entries, list) else []:
                if not isinstance(entry, dict) or not isinstance(entry.get('id'), str):
                    continue
                try:
                    name = _name(entry.get('name'))
                except ValueError:
                    continue
                project_id = None
                if kind == 'series':
                    project_id = mapping['projects'].get(entry.get('project_id'), entry.get('project_id'))
                    if not self.get('projects', project_id):
                        continue
                same = self._same_name(kind, name, project_id)
                if same:
                    mapping[kind][entry['id']] = same['id']
                    continue
                new_id = entry['id'] if not self.get(kind, entry['id']) else uuid.uuid4().hex[:12]
                added = dict(id=new_id, name=name, **({'project_id': project_id} if kind == 'series' else {}))
                if kind == 'projects' and isinstance(entry.get('repositories'), list):
                    from .github_source import REPO
                    added['repositories'] = [r for r in entry['repositories'] if isinstance(r, str) and REPO.fullmatch(r)][:30]
                if kind == 'series' and (entry.get('type') in TYPES or isinstance(entry.get('type'), str) and CUSTOM_ID.fullmatch(entry['type'])):
                    added['type'] = entry['type']
                self.data[kind].append(added)
                mapping[kind][entry['id']] = new_id
        return mapping
