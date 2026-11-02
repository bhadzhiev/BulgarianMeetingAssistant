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
from .safe_json import SafeJSON
from .work_items import WorkItemConflict as Conflict


class Templates(SafeJSON):
    _data_attribute = 'templates'
    def __init__(self, path: Path):
        self.lock = threading.RLock()
        self.templates = self._load_file(path, 'Meeting templates', [], self._valid_library)

    def _valid_library(self, data):
        from .meeting_types import CUSTOM_ID
        if not isinstance(data,list) or len(data)>MAX_TEMPLATES:raise ValueError('Invalid template library')
        result=[];ids=set();names=set()
        for value in data:
            if not isinstance(value,dict) or not isinstance(value.get('id'),str) or not CUSTOM_ID.fullmatch(value['id']):raise ValueError('Invalid saved template ID')
            template=dict(check_template(value),revision=value.get('revision',1))
            if type(template['revision']) is not int or template['revision']<1:raise ValueError('Invalid template revision')
            if template['id'] in ids or template['label'].casefold() in names:raise ValueError('Duplicate template')
            result.append(template);ids.add(template['id']);names.add(template['label'].casefold())
        return result

    def _save(self, templates=None):
        candidate=self.templates if templates is None else templates
        self._write_file(candidate)
        self.templates=candidate

    def list(self):
        with self.lock:
            return copy.deepcopy(sorted(self.templates, key=lambda t: t['label'].casefold()))

    def get(self, template_id):
        with self.lock:
            return copy.deepcopy(next((t for t in self.templates if t['id'] == template_id), None))

    def save(self, value):
        """Create a template, or update one at its current revision. Names stay unique."""
        with self.lock:
            self.guard_write()
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
            self._save(others + [template])
            return copy.deepcopy(template)

    def delete(self, template_id, revision):
        with self.lock:
            self.guard_write()
            old = next((t for t in self.templates if t['id'] == template_id), None)
            if not old or old['revision'] != revision:
                raise Conflict('This template changed. Reload and try again.')
            self._save([t for t in self.templates if t['id'] != template_id])

    def merge(self, other):
        """Add archived templates that this library does not have, by ID and by name."""
        with self.lock:
            self.guard_write()
            other=self._valid_library(other)
            merged=copy.deepcopy(self.templates)
            ids, names = {t['id'] for t in self.templates}, {t['label'].casefold() for t in self.templates}
            for value in other if isinstance(other, list) else []:
                try:
                    template = dict(check_template(value), revision=value.get('revision') or 1)
                except (ValueError, TypeError, AttributeError):
                    continue
                if template['id'] in ids or template['label'].casefold() in names or len(merged) >= MAX_TEMPLATES:
                    continue
                merged.append(template)
                ids.add(template['id'])
                names.add(template['label'].casefold())
            self._save(merged)
