"""One Keychain item for Atlanta, with isolated library/provider slots.

Tokens never enter files. Legacy credentials are copied and verified, not removed
on migration. Explicit disconnect writes a tombstone before removing legacy data.
"""
import copy
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import threading

_LOCK=threading.RLock()
SERVICE=b'io.github.bhadzhiev.atlanta.credentials'
ACCOUNT=b'Atlanta'


@contextmanager
def vault_lock():
    # One writer across libraries/processes. This file contains no credentials.
    directory=Path.home()/'Library/Caches/io.github.bhadzhiev.meeting-assistant'
    directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    with _LOCK, open(directory/'credentials.lock','a',opener=lambda path,flags:os.open(path,flags,0o600)) as handle:
        fcntl.flock(handle,fcntl.LOCK_EX)
        try:yield
        finally:fcntl.flock(handle,fcntl.LOCK_UN)


def validate(document):
    if document is None:return dict(version=1,slots={})
    if not isinstance(document,dict) or set(document)!={'version','slots'} or document['version']!=1 or not isinstance(document['slots'],dict):raise ValueError('Atlanta credentials could not be read. Existing Keychain data was kept.')
    for key,value in document['slots'].items():
        if not isinstance(key,str) or not isinstance(value,dict) or set(value)!={'value'} or value['value'] is not None and not isinstance(value['value'],dict):raise ValueError('Invalid Atlanta credential slot. Existing Keychain data was kept.')
    return copy.deepcopy(document)


class _NoLegacy:
    """A provider that never had its own Keychain item before the shared vault."""
    def get(self):return None
    def delete(self):pass


class CredentialStore:
    def __init__(self,account,provider,backend=None,legacy=None,lock=vault_lock):
        if provider not in {'google','github','elevenlabs'}:raise ValueError('Unknown credential provider')
        if provider=='elevenlabs' and legacy is None:legacy=_NoLegacy()
        self.key=provider+':'+account;self.lock=lock
        if backend is None or legacy is None:
            from .google_calendar import LegacyKeychainStore
            if backend is None:
                backend=LegacyKeychainStore(ACCOUNT.decode());backend.service=SERVICE
            if legacy is None:
                legacy=LegacyKeychainStore(account)
                if provider=='github':legacy.service=b'local.bulgarian-meeting-assistant.github'
        self.backend,self.legacy=backend,legacy

    def _save(self,document):
        validate(document);self.backend.set(document)
        if validate(self.backend.get())!=document:raise ValueError('Atlanta credential verification failed. Legacy credentials were kept.')

    def get(self):
        with self.lock():
            document=validate(self.backend.get())
            if self.key in document['slots']:return copy.deepcopy(document['slots'][self.key]['value'])
            value=self.legacy.get()
            if value is not None and not isinstance(value,dict):raise ValueError('Legacy credentials could not be read. Existing Keychain data was kept.')
            document['slots'][self.key]=dict(value=copy.deepcopy(value));self._save(document)
            return copy.deepcopy(value)

    def set(self,value):
        if not isinstance(value,dict):raise ValueError('Invalid credentials')
        with self.lock():
            document=validate(self.backend.get());document['slots'][self.key]=dict(value=copy.deepcopy(value));self._save(document)

    def delete(self):
        with self.lock():
            document=validate(self.backend.get());document['slots'][self.key]=dict(value=None);self._save(document)
            self.legacy.delete()
