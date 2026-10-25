"""Archive the meeting library, prove that the archive restores, and restore meetings that are missing.

An archive is a tar.gz with a manifest of every file's size and SHA-256. "Verified" means more than a
readable archive: it was extracted into a temporary folder, every file matched the manifest, and the
extracted folder opened as a library with every meeting.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import tarfile
import tempfile

FORMAT = 'meeting-assistant-backup'
SHARED = ('settings.json', 'speakers.json', 'trackers.json', 'projects.json', 'items.json')
ARCHIVE_NAME = re.compile(r'meetings-\d{8}-\d{6}\.tar\.gz')
MEMBER = re.compile(r'(?:settings|speakers|trackers|projects|items|manifest)\.json|[a-f0-9]{32}(?:/[^/]+)*')
MEETING_ID = re.compile(r'[a-f0-9]{32}')


class _Hashing:
    """Hash exactly the bytes that go into the archive, so the manifest describes the archive."""
    def __init__(self, handle):
        self.handle, self.digest = handle, hashlib.sha256()

    def read(self, size=-1):
        data = self.handle.read(size)
        self.digest.update(data)
        return data


def _library_files(root: Path, skip):
    for name in SHARED:
        if (root / name).is_file() and not (root / name).is_symlink():
            yield name, root / name
    for directory in sorted(root.iterdir()):
        if not MEETING_ID.fullmatch(directory.name) or directory.is_symlink() or not directory.is_dir() or directory.name in skip:
            continue
        for path in sorted(directory.rglob('*')):
            relative = path.relative_to(root)
            # Dot files are temporary files of a write in progress, not meeting data.
            if path.is_file() and not path.is_symlink() and not any(part.startswith('.') for part in relative.parts):
                yield relative.as_posix(), path


def create(root: Path, destination: Path, skip=()) -> dict:
    destination.mkdir(parents=True, exist_ok=True)
    name = 'meetings-' + dt.datetime.now().strftime('%Y%m%d-%H%M%S') + '.tar.gz'
    partial = destination / ('.' + name + '.partial')
    files, meetings = {}, set()
    try:
        with tarfile.open(partial, 'w:gz', compresslevel=1) as archive:
            for member, path in _library_files(root, set(skip)):
                info = archive.gettarinfo(str(path), arcname=member)
                with path.open('rb') as handle:
                    reader = _Hashing(handle)
                    archive.addfile(info, reader)
                files[member] = dict(size=info.size, sha256=reader.digest.hexdigest())
                if '/' in member:
                    meetings.add(member.split('/')[0])
            manifest = json.dumps(dict(format=FORMAT, version=1, created=dt.datetime.now().astimezone().isoformat(),
                                       meetings=sorted(meetings), files=files), ensure_ascii=False, indent=2).encode()
            info = tarfile.TarInfo('manifest.json')
            info.size, info.mtime = len(manifest), int(dt.datetime.now().timestamp())
            archive.addfile(info, io.BytesIO(manifest))
        result = verify(partial)
        if not result['verified']:
            raise ValueError('The new archive failed its restore test: ' + result['error'])
        os.replace(partial, destination / name)
    finally:
        partial.unlink(missing_ok=True)
    _save_report(destination / name, result)
    return dict(result, name=name)


def _extract(archive_path: Path, target: Path) -> dict:
    """Extract into target after checking every member name; return the manifest after checking every file."""
    with tarfile.open(archive_path, 'r:gz') as archive:
        members = archive.getmembers()
        for member in members:
            if not MEMBER.fullmatch(member.name) or not (member.isfile() or member.isdir()) or '..' in member.name.split('/'):
                raise ValueError(f'Unexpected entry in the archive: {member.name[:120]}')
        archive.extractall(target, members=members, filter='data')
    manifest = json.loads((target / 'manifest.json').read_text())
    if manifest.get('format') != FORMAT or not isinstance(manifest.get('files'), dict):
        raise ValueError('This is not a Meeting Assistant archive')
    extracted = {path.relative_to(target).as_posix() for path in target.rglob('*') if path.is_file()} - {'manifest.json'}
    if extracted != set(manifest['files']):
        raise ValueError('The archive files do not match its manifest')
    for member, expected in manifest['files'].items():
        digest = hashlib.sha256()
        with (target / member).open('rb') as handle:
            for block in iter(lambda: handle.read(1 << 20), b''):
                digest.update(block)
        if digest.hexdigest() != expected.get('sha256'):
            raise ValueError(f'{member} does not match its checksum')
    return manifest


def verify(archive_path: Path) -> dict:
    """The restore test: extract to a temporary folder, compare checksums, open it as a library."""
    from .storage import Library
    report = dict(verified=False, error=None, meetings=0, files=0, bytes=archive_path.stat().st_size,
                  checked=dt.datetime.now().astimezone().isoformat())
    with tempfile.TemporaryDirectory(prefix='.restore-test-', dir=archive_path.parent) as temp:
        try:
            manifest = _extract(archive_path, Path(temp))
            (Path(temp) / 'manifest.json').unlink()
            opened = {meeting['id'] for meeting in Library(Path(temp)).list()}
            if opened != set(manifest['meetings']):
                raise ValueError('Some meetings in the archive do not open')
            report.update(verified=True, meetings=len(opened), files=len(manifest['files']), created=manifest.get('created'))
        except (OSError, ValueError, KeyError, tarfile.TarError) as exc:
            report['error'] = str(exc)
    return report


def _report_path(archive_path: Path) -> Path:
    return archive_path.with_name(archive_path.name + '.json')


def _save_report(archive_path: Path, report: dict) -> None:
    from .storage import atomic_json
    atomic_json(_report_path(archive_path), report)


def archives(destination: Path) -> list[dict]:
    result = []
    for path in sorted(destination.glob('meetings-*.tar.gz'), reverse=True):
        if not ARCHIVE_NAME.fullmatch(path.name):
            continue
        try:
            report = json.loads(_report_path(path).read_text())
        except (OSError, ValueError):
            report = dict(verified=False, error='Not checked yet')
        result.append(dict(report, name=path.name, bytes=path.stat().st_size))
    return result


def archive_path(destination: Path, name) -> Path:
    if not isinstance(name, str) or not ARCHIVE_NAME.fullmatch(name) or not (destination / name).is_file():
        raise ValueError('Choose an archive from the list')
    return destination / name


def restore(archive_file: Path, library, merge=None) -> dict:
    """Add the meetings that the library does not have. Existing meetings are never changed."""
    staging = Path(tempfile.mkdtemp(prefix='.restore-', dir=library.root))
    try:
        manifest = _extract(archive_file, staging)
        restored, skipped = [], []
        for meeting_id in manifest['meetings']:
            if (library.root / meeting_id).exists():
                skipped.append(meeting_id)
            else:
                os.replace(staging / meeting_id, library.root / meeting_id)
                restored.append(meeting_id)
        try:
            library.add_speakers(json.loads((staging / 'speakers.json').read_text()))
        except (OSError, ValueError):
            pass
        try:
            known = {tracker['id'] for tracker in library.trackers()}
            extra = [tracker for tracker in json.loads((staging / 'trackers.json').read_text()) if tracker.get('id') not in known]
            if extra:
                library.save_trackers(library.trackers() + extra)
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        if merge:
            merge(staging)  # data that the service owns: projects and the task registry
        return dict(restored=restored, skipped=skipped)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
