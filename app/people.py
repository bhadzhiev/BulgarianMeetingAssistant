"""People: the real person behind speaker labels, task owners and a GitHub account. Local only.

A speaker label belongs to one meeting; a person joins the labels, names and accounts that a human has
confirmed. Nothing here is guessed from a voice, and no email leaves this Mac by default.
"""
from __future__ import annotations

import copy
import datetime as dt
from email.utils import parseaddr
import json
from pathlib import Path
import re
import threading
import uuid

from .storage import atomic_json

EMAIL = re.compile(r'[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{2,63}')
LOGIN = re.compile(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})')
MAX_PEOPLE = 500


from .work_items import WorkItemConflict as Conflict


def _text(value, field, limit=80, required=False):
    if value is None and not required:
        return ''
    if not isinstance(value, str) or any(ord(c) < 32 for c in value):
        raise ValueError(f'{field} must be one line of text')
    value = ' '.join(value.split())
    if required and not value or len(value) > limit:
        raise ValueError(f'{field} must have 1 to {limit} characters' if required else f'{field} is too long')
    return value


def _names(person):
    return [person['name'], *person['aliases']]


class People:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.lock = threading.RLock()
        try:
            data = json.loads(self.path.read_text())
            self.people = [self._valid(p, keep=True) for p in data] if isinstance(data, list) else []
        except (OSError, ValueError, TypeError, KeyError):
            self.people = []

    def _valid(self, value, keep=False):
        if not isinstance(value, dict):
            raise ValueError('Invalid person')
        person = dict(id=value.get('id') if keep or value.get('id') else uuid.uuid4().hex[:12],
                      name=_text(value.get('name'), 'Name', required=True),
                      emails=[], aliases=[], identities=[], github=None, notes=_text(value.get('notes'), 'Notes', 1000),
                      revision=value.get('revision', 1) if keep else value.get('revision'))
        if not isinstance(person['id'], str) or not re.fullmatch(r'[a-f0-9]{12}', person['id']):
            raise ValueError('Invalid person ID')
        for email in value.get('emails') or []:
            email = _text(email, 'Email', 254).casefold()
            if not EMAIL.fullmatch(email):
                raise ValueError(f'"{email}" is not an email address')
            if email not in person['emails']:
                person['emails'].append(email)
        for alias in value.get('aliases') or []:
            alias = _text(alias, 'Also appears as', required=True)
            if not keep and re.fullmatch(r'SPEAKER[ _-]?\d+',alias,re.I):raise ValueError('Numbered speakers belong to one meeting; link them there with This is…')
            if alias.casefold() != person['name'].casefold() and alias.casefold() not in {a.casefold() for a in person['aliases']}:
                person['aliases'].append(alias)
        if len(person['emails']) > 10 or len(person['aliases']) > 30:
            raise ValueError('A person has at most 10 emails and 30 other names')
        identities = value.get('identities') or []
        if not isinstance(identities,list) or len(identities)>30:raise ValueError('At most 30 confirmed channel identities')
        for identity in identities:
            if not isinstance(identity,dict) or identity.get('provider') not in {'gmail','google_chat'}:raise ValueError('Invalid channel identity')
            account=_text(identity.get('account'),'Channel account',254,True)
            key=_text(identity.get('external_id'),'Sender identity',254,True)
            if identity['provider']=='gmail':
                key=key.casefold()
                if not EMAIL.fullmatch(key):raise ValueError('Choose a valid sender email')
            elif not re.fullmatch(r'users/[A-Za-z0-9_-]{1,128}',key):raise ValueError('Chat needs a stable users/ identity; refresh its cache first')
            entry=dict(provider=identity['provider'],account=account,external_id=key)
            if entry not in person['identities']:person['identities'].append(entry)
        github = value.get('github')
        if github:
            login = github.get('login') if isinstance(github, dict) else None
            if not isinstance(login, str) or not LOGIN.fullmatch(login):
                raise ValueError('Enter a GitHub username')
            account = github.get('id')
            if account is not None and (type(account) is not int or account <= 0):
                raise ValueError('Invalid GitHub user ID')
            person['github'] = dict(login=login, id=account)
        return person

    def save_file(self):
        atomic_json(self.path, self.people)

    def list(self):
        with self.lock:
            return copy.deepcopy(sorted(self.people, key=lambda p: p['name'].casefold()))

    def get(self, person_id):
        return next((p for p in self.people if p['id'] == person_id), None)

    def save(self, value):
        """Create a person, or update one at its current revision. Names and GitHub accounts stay unique."""
        with self.lock:
            old = self.get(value.get('id')) if value.get('id') else None
            value=dict(value)
            if old:
                value.setdefault('identities',old.get('identities',[]))
                if old['name'].casefold()!=str(value.get('name','')).strip().casefold() and not re.fullmatch(r'SPEAKER[ _-]?\d+',old['name'],re.I):
                    value['aliases']=[*(value.get('aliases') or []),old['name']]
            person = self._valid(value)
            if value.get('id') and not old:
                raise Conflict('This person no longer exists. Reload and try again.')
            if old and (type(value.get('revision')) is not int or value.get('revision') != old['revision']):
                raise Conflict('This person changed. Reload and try again.')
            person['revision'] = old['revision'] + 1 if old else 1
            others = [p for p in self.people if p['id'] != person['id']]
            taken = {name.casefold(): p['name'] for p in others for name in _names(p)}
            for name in _names(person):
                if name.casefold() in taken:
                    raise ValueError(f'"{name}" already belongs to {taken[name.casefold()]}')
            if any(set(person['emails']) & set(p['emails']) for p in others):raise ValueError('This email already belongs to another person')
            if any(identity in p.get('identities',[]) for identity in person['identities'] for p in others):raise ValueError('This sender already belongs to another person')
            github = person['github']
            if github and any(p['github'] and (github['id'] and p['github']['id'] == github['id'] or p['github']['login'].casefold() == github['login'].casefold()) for p in others):
                raise ValueError('This GitHub account already belongs to another person')
            if not old and len(self.people) >= MAX_PEOPLE:
                raise ValueError(f'At most {MAX_PEOPLE} people')
            self.people = others + [person]
            self.save_file()
            return copy.deepcopy(person)

    def delete(self, person_id, revision):
        with self.lock:
            old = self.get(person_id)
            if not old or old['revision'] != revision:
                raise Conflict('This person changed. Reload and try again.')
            self.people = [p for p in self.people if p['id'] != person_id]
            self.save_file()

    def match(self, name):
        """The person who has this exact name or confirmed other name, ignoring case."""
        if not isinstance(name, str) or not name.strip():
            return None
        key = ' '.join(name.split()).casefold()
        if re.fullmatch(r'SPEAKER[ _-]?\d+',key,re.I):return None
        return next((copy.deepcopy(p) for p in self.people if key in {n.casefold() for n in _names(p)}), None)

    def match_channel(self,provider,account,sender):
        with self.lock:
            if provider=='gmail':
                email=parseaddr(sender or '')[1].casefold()
                if not EMAIL.fullmatch(email):return None
                key=email
            else:key=sender
            identity=dict(provider=provider,account=account,external_id=key)
            found=[p for p in self.people if identity in p.get('identities',[]) or provider=='gmail' and key in p['emails']]
            return copy.deepcopy(found[0]) if len(found)==1 else None

    def confirm_channel(self,person_id,revision,provider,account,sender):
        with self.lock:
            person=self.get(person_id)
            if not person or type(revision) is not int or revision!=person['revision']:raise Conflict('This person changed. Reopen the sender link.')
            value=copy.deepcopy(person)
            key=parseaddr(sender or '')[1].casefold() if provider=='gmail' else sender
            identity=dict(provider=provider,account=account,external_id=key)
            value.setdefault('identities',[])
            if identity not in value['identities']:value['identities'].append(identity)
            if provider=='gmail' and key not in value['emails']:value['emails'].append(key)
            return self.save(value)

    def merge(self, other):
        """Add archived people that this library does not have, by ID; local people stay as they are."""
        with self.lock:
            known = {p['id'] for p in self.people}
            names = {n.casefold() for p in self.people for n in _names(p)}
            for value in other if isinstance(other, list) else []:
                try:
                    person = self._valid(value, keep=True)
                except (ValueError, TypeError, KeyError, AttributeError):
                    continue
                if (person['id'] in known or any(n.casefold() in names for n in _names(person))
                        or any(set(person['emails']) & set(p['emails']) or any(i in p.get('identities',[]) for i in person['identities']) for p in self.people)):
                    continue
                self.people.append(person)
                known.add(person['id'])
                names |= {n.casefold() for n in _names(person)}
            self.save_file()
