"""Own meeting templates: a name, up to three note sections and the agenda style of a built-in type.

A template is data, not a prompt editor: each section has a short title and a one-line instruction, and the
notes schema stays the same. Local only; archives include the templates.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import threading

from .meeting_types import MAX_TEMPLATES, check_template
from .storage import atomic_json
from .work_items import WorkItemConflict as Conflict


class Templates:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.lock = threading.RLock()
        self.templates = []
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            data = []
        for value in data if isinstance(data, list) else []:
            try:
                self.templates.append(dict(check_template(value), revision=value.get('revision') or 1))
            except (ValueError, TypeError, AttributeError):
                continue

    def _save(self):
        atomic_json(self.path, self.templates)

    def list(self):
        with self.lock:
            return copy.deepcopy(sorted(self.templates, key=lambda t: t['label'].casefold()))

    def get(self, template_id):
        with self.lock:
            return copy.deepcopy(next((t for t in self.templates if t['id'] == template_id), None))

    def save(self, value):
        """Create a template, or update one at its current revision. Names stay unique."""
        with self.lock:
            template = check_template(value)
            old = next((t for t in self.templates if t['id'] == value.get('id')), None) if value.get('id') else None
            if value.get('id') and not old:
                raise Conflict('This template no longer exists. Reload and try again.')
            if old and value.get('revision') != old['revision']:
                raise Conflict('This template changed. Reload and try again.')
            others = [t for t in self.templates if t['id'] != template['id']]
            if any(t['label'].casefold() == template['label'].casefold() for t in others):
                raise ValueError('Another template already has this name')
            if not old and len(self.templates) >= MAX_TEMPLATES:
                raise ValueError(f'At most {MAX_TEMPLATES} templates')
            template['revision'] = old['revision'] + 1 if old else 1
            self.templates = others + [template]
            self._save()
            return copy.deepcopy(template)

    def delete(self, template_id, revision):
        with self.lock:
            old = next((t for t in self.templates if t['id'] == template_id), None)
            if not old or old['revision'] != revision:
                raise Conflict('This template changed. Reload and try again.')
            self.templates = [t for t in self.templates if t['id'] != template_id]
            self._save()

    def merge(self, other):
        """Add archived templates that this library does not have, by ID and by name."""
        with self.lock:
            ids, names = {t['id'] for t in self.templates}, {t['label'].casefold() for t in self.templates}
            for value in other if isinstance(other, list) else []:
                try:
                    template = dict(check_template(value), revision=value.get('revision') or 1)
                except (ValueError, TypeError, AttributeError):
                    continue
                if template['id'] in ids or template['label'].casefold() in names or len(self.templates) >= MAX_TEMPLATES:
                    continue
                self.templates.append(template)
                ids.add(template['id'])
                names.add(template['label'].casefold())
            self._save()
