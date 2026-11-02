import tempfile
import unittest
from pathlib import Path
from app.commit_journal import CommitJournal
from app.work_items import WorkItemConflict

class JournalTests(unittest.TestCase):
    def test_duplicate_click_and_unknown_result_cannot_resend(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'work.sqlite3';journal=CommitJournal(path)
            payload=dict(resource='item:one',resource_revision=1,source_revision='source',account_id=10,repository_id=20,action='issue',target=None,title='Title',body='Text')
            first=journal.approve(payload);self.assertEqual(first,journal.approve(payload))
            journal.transition(first['id'],'approved','sending')
            with self.assertRaises(WorkItemConflict):journal.transition(first['id'],'approved','sending')
            restarted=CommitJournal(path);restarted.recover()
            self.assertEqual(restarted.approve(payload)['state'],'unknown')
            with self.assertRaises(ValueError):restarted.transition(first['id'],'unknown','sending')
    def test_restored_approval_requires_review_instead_of_automatic_send(self):
        with tempfile.TemporaryDirectory() as directory:
            journal=CommitJournal(Path(directory)/'work.sqlite3')
            row=journal.approve(dict(resource='item:one',resource_revision=1,source_revision='s',account_id=1,repository_id=2,action='comment',target=3,title='',body='Text'))
            journal.recover();self.assertEqual(journal.get(row['id'])['state'],'unknown')
    def test_archive_restore_preserves_deduplication_without_reapproving(self):
        with tempfile.TemporaryDirectory() as directory:
            source=CommitJournal(Path(directory)/'source.sqlite3');target=CommitJournal(Path(directory)/'target.sqlite3')
            payload=dict(resource='item:one',resource_revision=1,source_revision='s',account_id=1,repository_id=2,action='issue',target=None,title='Title',body='Text')
            row=source.approve(payload);target.restore(source.export())
            self.assertEqual(target.approve(payload)['state'],'unknown')
            self.assertEqual(target.get(row['id'])['state'],'unknown')
