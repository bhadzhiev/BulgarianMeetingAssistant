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
    def test_restart_keeps_an_unsent_approval_without_sending_it(self):
        with tempfile.TemporaryDirectory() as directory:
            journal=CommitJournal(Path(directory)/'work.sqlite3')
            row=journal.approve(dict(resource='item:one',resource_revision=1,source_revision='s',account_id=1,repository_id=2,action='comment',target=3,title='',body='Text'))
            journal.recover();self.assertEqual(journal.get(row['id'])['state'],'approved')
    def test_restored_approval_is_cancelled_and_frees_the_resource(self):
        with tempfile.TemporaryDirectory() as directory:
            source=CommitJournal(Path(directory)/'source.sqlite3');target=CommitJournal(Path(directory)/'target.sqlite3')
            payload=dict(resource='item:one',resource_revision=1,source_revision='s',account_id=1,repository_id=2,action='issue',target=None,title='Title',body='Text')
            row=source.approve(payload);target.restore(source.export())
            self.assertEqual(target.get(row['id'])['state'],'cancelled')
            again=target.approve(payload);self.assertEqual(again['state'],'approved');self.assertNotEqual(again['id'],row['id'])
    def test_restored_send_needs_a_check(self):
        with tempfile.TemporaryDirectory() as directory:
            source=CommitJournal(Path(directory)/'source.sqlite3');target=CommitJournal(Path(directory)/'target.sqlite3')
            payload=dict(resource='item:one',resource_revision=1,source_revision='s',account_id=1,repository_id=2,action='issue',target=None,title='Title',body='Text')
            row=source.approve(payload);source.transition(row['id'],'approved','sending');target.restore(source.export())
            self.assertEqual(target.approve(payload)['state'],'unknown')
            with self.assertRaises(WorkItemConflict):target.approve(dict(payload,body='Other'))
    def test_new_preview_replaces_an_unsent_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            journal=CommitJournal(Path(directory)/'work.sqlite3')
            payload=dict(resource='item:one',resource_revision=1,source_revision='s',account_id=1,repository_id=2,action='issue',target=None,title='Title',body='Text')
            first=journal.approve(payload);second=journal.approve(dict(payload,body='Edited'))
            self.assertEqual(journal.get(first['id'])['state'],'cancelled');self.assertEqual(second['state'],'approved')
            self.assertEqual(journal.approve(payload)['state'],'approved')
            self.assertEqual(journal.get(second['id'])['state'],'cancelled')
    def test_failed_and_abandoned_attempts_allow_a_new_one(self):
        with tempfile.TemporaryDirectory() as directory:
            journal=CommitJournal(Path(directory)/'work.sqlite3')
            payload=dict(resource='item:one',resource_revision=1,source_revision='s',account_id=1,repository_id=2,action='issue',target=None,title='Title',body='Text')
            first=journal.approve(payload);journal.transition(first['id'],'approved','sending');journal.transition(first['id'],'sending','failed',dict(error='403'))
            second=journal.approve(payload);self.assertNotEqual(second['id'],first['id'])
            journal.transition(second['id'],'approved','sending');journal.transition(second['id'],'sending','unknown')
            with self.assertRaises(WorkItemConflict):journal.approve(dict(payload,body='Edited'))
            journal.transition(second['id'],'unknown','abandoned')
            self.assertEqual(journal.approve(payload)['state'],'approved')
            self.assertEqual(len(journal.export()),3)
    def test_created_issue_blocks_a_second_issue_but_not_a_new_comment(self):
        with tempfile.TemporaryDirectory() as directory:
            journal=CommitJournal(Path(directory)/'work.sqlite3')
            issue=dict(resource='item:one',resource_revision=1,source_revision='s',account_id=1,repository_id=2,action='issue',target=None,title='Title',body='Text')
            comment=dict(issue,action='comment',target=7,title='')
            for payload in (issue,comment):
                row=journal.approve(payload);journal.transition(row['id'],'approved','sending');journal.transition(row['id'],'sending','created',dict(id=1))
            with self.assertRaises(WorkItemConflict):journal.approve(dict(issue,body='Edited'))
            self.assertEqual(journal.approve(dict(comment,body='Second update'))['state'],'approved')
