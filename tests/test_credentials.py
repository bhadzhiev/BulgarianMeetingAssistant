import copy
from contextlib import contextmanager
import threading
import unittest
from app.credentials import CredentialStore

class Memory:
    def __init__(self,value=None):self.value=copy.deepcopy(value);self.reads=0;self.fail=False
    def get(self):
        self.reads+=1
        if self.fail:raise RuntimeError('Keychain denied')
        return copy.deepcopy(self.value)
    def set(self,value):
        if self.fail:raise RuntimeError('Keychain denied')
        self.value=copy.deepcopy(value)
    def delete(self):self.value=None

class CredentialsTests(unittest.TestCase):
    def setUp(self):
        self.backend=Memory();self.legacy_google=Memory(dict(refresh_token='google-secret'));self.legacy_github=Memory(dict(token='github-secret'))
        self.mutex=threading.RLock()
        @contextmanager
        def locked():
            with self.mutex:yield
        self.lock=locked
        self.google=self.store('library','google',self.legacy_google);self.github=self.store('library','github',self.legacy_github)
    def store(self,account,provider,legacy):return CredentialStore(account,provider,self.backend,legacy,self.lock)
    def test_migrate_verify_preserve_old_and_avoid_reopening_legacy(self):
        self.assertEqual(self.google.get(),self.legacy_google.value);self.assertEqual(self.github.get(),self.legacy_github.value)
        self.assertEqual(len(self.backend.value['slots']),2);self.assertIsNotNone(self.legacy_google.value)
        reads=self.legacy_google.reads;self.google.get();self.assertEqual(self.legacy_google.reads,reads)
    def test_provider_and_library_isolation(self):
        self.google.get();self.github.get();other=self.store('other','google',Memory(dict(refresh_token='other')));other.get()
        self.google.set(dict(refresh_token='updated'));self.assertEqual(self.github.get()['token'],'github-secret');self.assertEqual(other.get()['refresh_token'],'other')
        self.google.delete();self.assertIsNone(self.google.get());self.assertIsNone(self.legacy_google.value);self.assertEqual(self.github.get()['token'],'github-secret')
    def test_failed_migration_keeps_legacy_credentials(self):
        original=self.backend.set
        self.backend.set=lambda value:None
        with self.assertRaises(ValueError):self.google.get()
        self.assertEqual(self.legacy_google.value,dict(refresh_token='google-secret'));self.backend.set=original
    def test_denied_or_corrupt_shared_item_does_not_fall_back_or_overwrite(self):
        for value in ('broken',dict(version=2,slots={})):
            self.backend.value=value
            with self.assertRaises(ValueError):self.google.get()
            self.assertEqual(self.backend.value,value);self.assertEqual(self.legacy_google.reads,0)
        self.backend.fail=True
        with self.assertRaises(RuntimeError):self.google.get()
        self.assertEqual(self.legacy_google.reads,0)
    def test_concurrent_provider_updates_do_not_lose_other_slot(self):
        errors=[]
        def write(store,key):
            try:
                for n in range(20):store.set({key:str(n)})
            except Exception as error:errors.append(error)
        threads=[threading.Thread(target=write,args=(self.google,'refresh_token')),threading.Thread(target=write,args=(self.github,'token'))]
        for t in threads:t.start()
        for t in threads:t.join()
        self.assertEqual(errors,[]);self.assertEqual(self.google.get()['refresh_token'],'19');self.assertEqual(self.github.get()['token'],'19')
    def test_restart_reads_unified_item_without_accessing_legacy(self):
        self.google.get();self.legacy_google.fail=True
        restarted=self.store('library','google',self.legacy_google)
        self.assertEqual(restarted.get()['refresh_token'],'google-secret')
    def test_saved_new_token_is_not_replaced_by_legacy_backup(self):
        self.github.set(dict(token='new-token'))
        self.assertEqual(self.github.get()['token'],'new-token')
        self.assertEqual(self.legacy_github.value['token'],'github-secret')
    def test_denied_legacy_migration_does_not_create_shared_item(self):
        self.legacy_google.fail=True
        with self.assertRaises(RuntimeError):self.google.get()
        self.assertIsNone(self.backend.value)
    def test_disconnect_tombstone_prevents_reimport_after_restart(self):
        self.github.get();self.github.delete()
        self.legacy_github.value=dict(token='stale-backup')
        restarted=self.store('library','github',self.legacy_github)
        self.assertIsNone(restarted.get())


class RealVaultLockTests(unittest.TestCase):
    def test_real_lock_is_private_exclusive_and_released_without_keychain_access(self):
        import fcntl
        from pathlib import Path
        import stat
        import tempfile
        from unittest.mock import patch
        from app.credentials import vault_lock
        with tempfile.TemporaryDirectory() as tmp, patch('app.credentials.Path.home',return_value=Path(tmp)):
            path=Path(tmp)/'Library/Caches/io.github.bhadzhiev.meeting-assistant/credentials.lock'
            with vault_lock():
                self.assertEqual(stat.S_IMODE(path.stat().st_mode),0o600)
                with path.open('a') as other:
                    with self.assertRaises(BlockingIOError):
                        fcntl.flock(other,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with path.open('a') as other:
                fcntl.flock(other,fcntl.LOCK_EX|fcntl.LOCK_NB)
                fcntl.flock(other,fcntl.LOCK_UN)
            self.assertEqual(path.read_bytes(),b'')
