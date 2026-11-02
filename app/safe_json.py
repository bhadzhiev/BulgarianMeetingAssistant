"""Fail-closed metadata files. Missing is empty; unreadable or invalid is read-only.

Recovery is called only by the verified archive path. Original bytes are retained
before replacement. Store mutators check the guard before changing their state.
"""
import copy
import json
from pathlib import Path
import secrets

from .storage import atomic_json


class SafeJSON:
    def _load_file(self, path, label, default, validator):
        self.path=Path(path);self.label=label;self.error=None;self._validator=validator
        try:
            self._original=self.path.read_bytes()
            return self._decode(self._original)
        except FileNotFoundError:
            self._original=None
        except (OSError,ValueError,TypeError,KeyError,AttributeError,RecursionError):
            self.error=self._message()
        return copy.deepcopy(default)

    def _message(self):
        return f'{self.path.name} could not be read or changed outside Atlanta. {self.label} are read-only. Restore a verified archive in Settings → Backup; the original file will be preserved.'

    def _decode(self, raw):
        if len(raw)>8_000_000:raise ValueError('Metadata file exceeds the local limit')
        return self._validator(json.loads(raw))

    def guard_write(self):
        if self.error:raise ValueError(self.error)
        try:
            try:current=self.path.read_bytes()
            except FileNotFoundError:current=None
            if current!=self._original:raise ValueError('Metadata file changed outside the app')
        except (OSError,ValueError):
            self.error=self._message()
            raise ValueError(self.error) from None

    def _write_file(self, value):
        self.guard_write()
        # Validate the whole candidate before replacing the file.
        self._validator(copy.deepcopy(value))
        atomic_json(self.path,value)
        self._original=self.path.read_bytes()

    def validate_archive(self, path):
        return self._decode(Path(path).read_bytes())

    def recover_file(self, path):
        """Restore unreadable metadata from an already verified archive, never a partial subset."""
        with self.lock:
            if not self.error:raise ValueError('This metadata file does not need recovery')
            value=self.validate_archive(path)
            # Exclusive creation, no accidental replacement of a prior recovery copy.
            try:original=self.path.read_bytes()
            except FileNotFoundError:original=self._original
            preserved=self.path.with_name(self.path.stem+'.corrupt-'+secrets.token_hex(8)+'.json')
            if original is not None:
                with preserved.open('xb') as handle:handle.write(original)
            atomic_json(self.path,value)
            self._original=self.path.read_bytes();self.error=None
            setattr(self,self._data_attribute,value)
            return value
