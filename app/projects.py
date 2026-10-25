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

    def rename(self, kind: str, entry_id, name) -> None:
        entry = self.get(kind, entry_id)
        if not entry:
            raise ValueError('This entry no longer exists. Reload and try again.')
        entry['name'] = _name(name)

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

    def merge(self, other: dict) -> None:
        """Add projects and series from an archive that this library does not have."""
        for kind in ('projects', 'series'):
            known = {entry['id'] for entry in self.data[kind]}
            self.data[kind].extend(entry for entry in other.get(kind, []) if isinstance(entry, dict) and entry.get('id') not in known)
