import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

from app import backup
from app.service import MeetingService
from app.storage import atomic_json

PROJECT = Path(__file__).resolve().parents[1]


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.service = MeetingService(self.root / 'library', PROJECT, backup_dir=self.root / 'backups')
        self.ids = []
        for title, status in [('Първа', 'ready'), ('Втора', 'processing')]:
            meeting = self.service.library.create(title, 'in_person', {})
            self.service.library.update(meeting['id'], status=status)
            directory = self.service.library.directory(meeting['id'])
            (directory / 'recording.wav').write_bytes(b'RIFF' + bytes(4000))
            (directory / 'versions' / '20261024').mkdir(parents=True)
            atomic_json(directory / 'versions' / '20261024' / 'minutes.json', {'summary': []})
            (directory / '.recording.wav').write_bytes(b'temporary')
            self.ids.append(meeting['id'])
        self.service.save_speakers(['Иван'])
        self.service.save_trackers([dict(name='Бюджет', phrases=['бюджет'], semantic_matching=False)])

    def tearDown(self):
        self.service.close()
        self.tmp.cleanup()

    def test_backups_started_in_the_same_second_make_two_verified_archives(self):
        import threading
        from unittest.mock import patch
        frozen = __import__('datetime').datetime(2026, 10, 27, 10, 0, 0)
        results, errors = [], []
        def run():
            try:
                results.append(self.service.create_backup()['created'])
            except Exception as exc:
                errors.append(exc)
        with patch('app.backup.dt') as clock:
            clock.datetime.now.return_value = frozen
            threads = [threading.Thread(target=run) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(60)
        self.assertEqual(errors, [])
        self.assertEqual(len({r['name'] for r in results}), 2)
        self.assertTrue(all(r['verified'] for r in results))
        self.assertEqual(list((self.root / 'backups').glob('.*.partial')), [])

    def test_archive_passes_a_restore_test_and_restores_only_missing_meetings(self):
        created = self.service.create_backup()['created']
        self.assertTrue(created['verified'])
        self.assertEqual(created['meetings'], 2)
        with tarfile.open(self.root / 'backups' / created['name']) as archive:
            names = archive.getnames()
        self.assertIn(f'{self.ids[0]}/versions/20261024/minutes.json', names)
        self.assertFalse(any(name.endswith('.recording.wav') for name in names))
        listed = self.service.backups()['archives']
        self.assertEqual((listed[0]['name'], listed[0]['verified']), (created['name'], True))

        other = MeetingService(self.root / 'other', PROJECT, backup_dir=self.root / 'backups')
        try:
            result = other.restore_backup(created['name'])
            self.assertEqual(sorted(result['restored']), sorted(self.ids))
            self.assertEqual(other.library.get(self.ids[0])['title'], 'Първа')
            self.assertEqual(other.library.get(self.ids[1])['status'], 'interrupted')
            self.assertEqual(other.library.speakers(), ['Иван'])
            self.assertEqual([t['name'] for t in other.library.trackers()], ['Бюджет'])
            again = other.restore_backup(created['name'])
            self.assertEqual((again['restored'], sorted(again['skipped'])), ([], sorted(self.ids)))
            self.assertEqual(list((self.root / 'other').glob('.restore-*')), [])
        finally:
            other.close()

    def test_active_recording_is_left_out(self):
        self.service.active = self.ids[1]
        try:
            result = self.service.create_backup()
        finally:
            self.service.active = None
        self.assertTrue(result['skipped_active'])
        self.assertEqual(result['created']['meetings'], 1)

    def test_damaged_or_unsafe_archives_fail_the_restore_test(self):
        name = self.service.create_backup()['created']['name']
        path = self.root / 'backups' / name
        with tarfile.open(path) as archive:
            members = [(member, archive.extractfile(member).read() if member.isfile() else None) for member in archive.getmembers()]
        for label, change in [('checksum', lambda m, data: (m, b'changed' if m.name.endswith('recording.wav') else data)),
                              ('Unexpected entry', lambda m, data: (tarfile.TarInfo('../evil.txt') if m.name == 'manifest.json' else m, data))]:
            damaged = self.root / 'backups' / 'meetings-20200101-000000.tar.gz'
            with tarfile.open(damaged, 'w:gz') as archive:
                for member, data in members:
                    member, data = change(member, data)
                    if data is not None:
                        member.size = len(data)
                    archive.addfile(member, io.BytesIO(data) if data is not None else None)
            report = backup.verify(damaged)
            self.assertFalse(report['verified'])
            self.assertIn(label, report['error'])
            with self.assertRaises(ValueError):
                self.service.restore_backup(damaged.name)
        self.assertFalse((self.root / 'evil.txt').exists())
        with self.assertRaisesRegex(ValueError, 'Choose an archive'):
            self.service.restore_backup('../library/settings.json')
