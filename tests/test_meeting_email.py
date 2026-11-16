import base64
import email
import email.policy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import meeting_email
from app.service import MeetingService
from app.storage import atomic_json
from tests.test_followup_email import DraftGoogle
from tests.test_manual_meeting_tasks import minutes

PROJECT = Path(__file__).resolve().parents[1]


class MeetingEmailTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.google = DraftGoogle()
        self.s = MeetingService(Path(self.tmp.name) / 'library', PROJECT, google=self.google, backup_dir=Path(self.tmp.name) / 'backups')
        self.addCleanup(self.s.close)
        self.me = self.s.save_person(dict(name='Bozhidar', emails=['account@example.test', 'my.alias@example.test']))['person']
        self.maria = self.s.save_person(dict(name='Maria', emails=['maria@example.test', 'maria.alt@example.test']))['person']
        self.s.save_person(dict(name='Other owner', emails=['owner@example.test']))
        self.mid = self.s.library.create('Infrastructure daily', 'in_person', {})['id']
        self.s.library.update(self.mid, status='ready')
        directory = self.s.library.directory(self.mid)
        notes = minutes('Accepted work', 'Suggested work')
        notes.update(summary=[dict(text='Public unchecked summary', review='ai')],
                     decisions=[dict(text='Verified decision', review='verified'), dict(text='Decision awaiting confirmation')],
                     discussion=[dict(topic='Environment', points=[dict(text='Public discussion')])],
                     custom_1=[dict(text='Public additional notes')],
                     observations=[dict(text='PRIVATE OBSERVATION')])
        for field, rows in notes.items():
            for row in rows:
                if 'text' in row:row.setdefault('evidence_timestamp', None)
                for point in row.get('points', []):point.setdefault('evidence_timestamp', None)
        atomic_json(directory / 'minutes.json', notes)
        atomic_json(directory / 'transcript.json', [dict(start=n*5, end=n*5+5, speaker=name, text='Public words')
                                                   for n, name in enumerate(['Bozhidar', 'Maria', 'Missing email', 'SPEAKER_02'])])
        self.s.create_task(dict(text='Accepted work', owner='Other owner', meeting_id=self.mid, mention_index=0,
                                minutes_revision=self.s._minutes_revision(directory), request_id='a'*32))

    def prepare(self):
        return meeting_email.prepare(self.s, dict(meeting_id=self.mid))

    def test_public_notes_tasks_and_decisions_are_shared_without_private_observations(self):
        body = self.prepare()['body']
        for text in ['Public unchecked summary', 'Public discussion', 'Public additional notes', 'Verified decision',
                     'Decision awaiting confirmation', 'Accepted work', 'Suggested work']:
            self.assertIn(text, body)
        self.assertIn('Задачи в My Work:', body)
        self.assertIn('Предложения за задачи — още не са приети:', body)
        self.assertIn('Решения от бележките — за потвърждение:', body)
        self.assertNotIn('PRIVATE OBSERVATION', body)
        self.assertTrue(body.endswith(meeting_email.FOOTER))
        self.assertNotIn('\n\n\n', body)
        from app.task_email import formatted_body
        self.assertIn('>Предложения за задачи — още не са приети:</h2>', formatted_body(body))

    def test_participants_are_preselected_but_the_sender_and_aliases_are_excluded(self):
        data = self.prepare()
        self.assertEqual([r['email'] for r in data['recipients'] if r['involved']], ['maria@example.test'])
        self.assertIn('owner@example.test', [r['email'] for r in data['recipients'] if not r['involved']])
        self.assertEqual(data['excluded_emails'], ['account@example.test', 'my.alias@example.test'])
        self.assertFalse(any(r['person_id'] == self.me['id'] for r in data['recipients']))
        self.assertIn('Missing email', data['missing_participants'])
        self.assertIn('Неидентифициран участник', data['missing_participants'])
        self.assertNotIn('Bozhidar', data['missing_participants'])

    def test_profile_identity_also_excludes_a_person_with_a_different_account(self):
        detail = self.s.detail(self.mid)
        with patch.object(self.google, 'status', return_value=dict(account='other.account@example.test')):
            data = meeting_email.recipients(self.s, detail, self.me['id'])
        self.assertIn('my.alias@example.test', data['excluded_emails'])
        self.assertNotIn(self.me['id'], [r['person_id'] for r in data['recipients']])

    def test_notes_only_meeting_needs_no_accepted_task(self):
        mid = self.s.library.create('Notes only', 'in_person', {})['id']
        atomic_json(self.s.library.directory(mid)/'minutes.json',dict(summary=[dict(text='Notes without tasks')]))
        data = meeting_email.prepare(self.s, dict(meeting_id=mid))
        self.assertIn('Notes without tasks', data['body'])

    def test_save_enforces_sender_exclusion_signature_and_safe_multipart(self):
        content = dict(meeting_id=self.mid, to=['account@example.test', 'MY.ALIAS@example.test', 'maria@example.test'],
                       subject='Meeting notes', body='Edited <script>alert(1)</script>')
        first = meeting_email.save_draft(self.s, content)
        message = email.message_from_bytes(base64.urlsafe_b64decode(self.google.sent[-1][0]), policy=email.policy.default)
        self.assertEqual(message['To'], 'maria@example.test')
        self.assertEqual(message.get_content_type(), 'multipart/alternative')
        self.assertIn(meeting_email.FOOTER, message.get_body(preferencelist=('plain',)).get_content())
        self.assertNotIn('<script>', message.get_body(preferencelist=('html',)).get_content())
        self.assertIn('&lt;script&gt;', message.get_body(preferencelist=('html',)).get_content())
        second = meeting_email.save_draft(self.s, content)
        self.assertEqual(first['draft_id'], second['draft_id'])
        self.assertEqual(self.google.sent[-1][1], first['draft_id'])
        self.assertIsNotNone(self.prepare()['draft'])
        self.assertIsNone(self.s.library.get(self.mid).get('followup_draft'),'separate from the reviewed-only follow-up draft')

    def test_self_only_recipients_are_rejected_and_long_notes_are_not_truncated(self):
        with self.assertRaisesRegex(ValueError, 'other than yourself'):
            meeting_email.save_draft(self.s, dict(meeting_id=self.mid,to=['my.alias@example.test'],subject='S',body='B'))
        text = 'Full public notes ' * 2000
        meeting_email.save_draft(self.s, dict(meeting_id=self.mid,to=['maria@example.test'],subject='S',body=text))
        message = email.message_from_bytes(base64.urlsafe_b64decode(self.google.sent[-1][0]), policy=email.policy.default)
        self.assertIn(text.strip(), message.get_body(preferencelist=('plain',)).get_content())
        with self.assertRaises(ValueError):
            meeting_email.save_draft(self.s, dict(meeting_id=self.mid,to=['maria@example.test'],subject='S',body='x'*100001))

    def test_stale_notes_require_update_before_preparing(self):
        meeting = self.s.detail(self.mid)
        with patch.object(self.s, 'detail', return_value=dict(meeting, notes_need_refresh=True)):
            with self.assertRaisesRegex(ValueError, 'notes wait for an update'):
                self.prepare()


class MeetingEmailHTTPTests(unittest.TestCase):
    from tests.test_http import HTTPTests as _HTTP
    setUp = _HTTP.setUp
    tearDown = _HTTP.tearDown
    request = _HTTP.request

    def test_route_requires_session_and_returns_the_public_template(self):
        mid=self.service.library.create('Meeting', 'in_person', {})['id']
        atomic_json(self.service.library.directory(mid)/'minutes.json',dict(summary=[dict(text='Public notes')]))
        self.assertEqual(self.request('/api/meeting-email/prepare',dict(meeting_id=mid),headers={})[0],403)
        status,body,_=self.request('/api/meeting-email/prepare',dict(meeting_id=mid))
        self.assertEqual(status,200)
        self.assertIn('Public notes',body.decode())
