import base64
import email
import email.policy
import tempfile
import unittest
from pathlib import Path

from app import followup_email, prompt_lab
from app.google_calendar import CalendarError, GMAIL_COMPOSE_SCOPE, GoogleCalendar
from app.service import MeetingService
from app.storage import atomic_json
from tests.test_calendar import FakeGoogle

PROJECT = Path(__file__).resolve().parents[1]


class DraftGoogle(FakeGoogle):
    def __init__(self):
        super().__init__();self.drafts = {};self.compose = True;self.sent = []
    def status(self):
        return dict(super().status(), capabilities=dict(gmail_compose=self.compose))
    def gmail_draft(self, raw, draft_id=None, expected_account=None):
        self.sent.append((raw, draft_id, expected_account))
        if draft_id in self.drafts:
            return self.drafts[draft_id]
        key = 'd%d' % (len(self.drafts) + 1)
        self.drafts[key] = dict(id=key, message=dict(id='m' + key))
        return self.drafts[key]


class FollowupEmailTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.google = DraftGoogle()
        self.s = MeetingService(Path(self.tmp.name) / 'library', PROJECT, google=self.google, backup_dir=Path(self.tmp.name) / 'backups')
        self.addCleanup(self.s.close)
        self.s.settings.update(summarizer='none')
        self.maria = self.s.save_person(dict(name='Maria', emails=['maria@example.test']))['person']
        self.s.save_person(dict(name='Guest', emails=['guest@example.test']))
        self.mid = self.s.library.create('Release planning', 'in_person', self.s.settings)['id']
        self.s.library.update(self.mid, status='ready', started_at='2026-11-05T10:00:00+02:00')
        atomic_json(self.s.library.directory(self.mid) / 'transcript.json', [
            dict(start=0, end=8, speaker='Maria', text='We release on Friday.'),
            dict(start=8, end=16, speaker='SPEAKER_01', text='I will update the runbook.')])
        self.s.edit(self.mid, dict(minutes=dict(
            summary=[dict(text='Release scope agreed', evidence_timestamp='00:00:00', review='verified'),
                     dict(text='Unchecked summary', evidence_timestamp='00:00:00')],
            decisions=[dict(text='Release on Friday', evidence_timestamp='00:00:00'),
                       dict(text='Proposed only', evidence_timestamp='00:00:08')],
            tasks=[dict(task='Update the runbook', owner='Maria', deadline=None, evidence_timestamp='00:00:08'),
                   dict(task='Proposed task', owner='SPEAKER_01', deadline=None, evidence_timestamp='00:00:08')],
            next_steps=[dict(text='Review again next week', evidence_timestamp='00:00:08', review='verified')],
            open_questions=[dict(text='Who approves the rollback window?', evidence_timestamp='00:00:08', review='verified'),
                            dict(text='Unchecked question', evidence_timestamp='00:00:08')],
            observations=[dict(text='Private remark about a person', evidence_timestamp='00:00:00')])))
        items = self.s.detail(self.mid)['items'].values()
        decision = next(i for i in items if i['text'] == 'Release on Friday')
        task = next(i for i in items if i['text'] == 'Update the runbook')
        self.s.update_item(decision['id'], decision['text'], dict(status='accepted'), decision['revision'])
        self.s.update_item(task['id'], task['text'], dict(acceptance_state='accepted', due_date='2026-11-12'), task['revision'])

    def test_source_has_only_reviewed_content_and_no_private_notes(self):
        data = followup_email.source(self.s, self.mid)
        self.assertEqual(data['decisions'], ['Release on Friday'])
        self.assertEqual(data['tasks'], [dict(task='Update the runbook', owner='Maria', due_date='2026-11-12', said_deadline=None)])
        self.assertEqual(data['summary'], ['Release scope agreed'])
        self.assertEqual(data['next_steps'], ['Review again next week'])
        self.assertEqual(data['open_questions'], ['Who approves the rollback window?'])
        self.assertEqual(data['meeting_date'], '05.11.2026')
        self.assertNotIn('Private remark', repr(data));self.assertNotIn('Proposed', repr(data))

    def test_no_open_questions_means_no_section(self):
        data = dict(followup_email.source(self.s, self.mid), open_questions=[])
        self.assertNotIn('Отворени въпроси', followup_email.template(data)['body'])

    def test_nothing_reviewed_is_refused(self):
        other = self.s.library.create('Empty', 'in_person', self.s.settings)['id']
        with self.assertRaisesRegex(ValueError, 'Accept at least one'):
            followup_email.source(self.s, other)

    def test_prepare_gives_template_and_participants_first(self):
        result = followup_email.prepare(self.s, dict(meeting_id=self.mid))
        self.assertIn('Update the runbook — Maria — 12.11.2026', result['body'])
        self.assertIn('Release on Friday', result['body']);self.assertNotIn('Private remark', result['body'])
        self.assertIn('Отворени въпроси:\n- Who approves the rollback window?', result['body']);self.assertNotIn('Unchecked question', result['body'])
        self.assertLess(result['body'].index('План за действие'), result['body'].index('Отворени въпроси'))
        self.assertLess(result['body'].index('Отворени въпроси'), result['body'].index('Следващи стъпки'))
        self.assertEqual([(r['email'], r['involved']) for r in result['recipients']],
                         [('maria@example.test', True), ('guest@example.test', False)])
        self.assertFalse(result['ai']['available']);self.assertTrue(result['gmail']['drafts']);self.assertIsNone(result['draft'])

    def test_ai_draft_uses_the_reviewed_data_and_is_validated(self):
        self.s.settings.update(summarizer='local', local_ai_model='synthetic')
        seen = {}
        def complete(target, messages, schema, name, **kw):
            seen.update(messages=messages, name=name, target=target)
            return dict(subject='Follow-up', body='Решения: Release on Friday')
        result = followup_email.generate(self.s, dict(meeting_id=self.mid), complete=complete)
        self.assertEqual((result['subject'], result['ai']), ('Follow-up', True))
        self.assertEqual(seen['name'], 'followup_email');self.assertIn('followup_email', seen['target']['_prompt_snapshot']['stages'])
        self.assertIn('Release on Friday', seen['messages'][1]['content']);self.assertNotIn('Private remark', seen['messages'][1]['content'])
        with self.assertRaises(ValueError):
            followup_email.generate(self.s, dict(meeting_id=self.mid), complete=lambda *a, **k: dict(subject='x\ny', body='b'))

    def test_draft_is_created_once_then_updated(self):
        body = dict(meeting_id=self.mid, to=['Maria@Example.test', 'maria@example.test'], subject='Follow-up: Release', body='Здравейте,\nРешения.')
        first = followup_email.save_draft(self.s, body)
        self.assertEqual(first['draft_id'], 'd1');self.assertIn('#drafts?compose=md1', first['url'])
        message = email.message_from_bytes(base64.urlsafe_b64decode(self.google.sent[0][0]), policy=email.policy.default)
        self.assertEqual(message['To'], 'maria@example.test');self.assertEqual(message['Subject'], 'Follow-up: Release')
        self.assertIn('Решения.', message.get_content())
        followup_email.save_draft(self.s, body)
        self.assertEqual(self.google.sent[1][1], 'd1');self.assertEqual(len(self.google.drafts), 1)
        self.assertEqual(followup_email.prepare(self.s, dict(meeting_id=self.mid))['draft']['draft_id'], 'd1')

    def test_invalid_recipients_and_subjects_are_refused(self):
        for to in ([], ['not-an-email'], ['a@example.test'] * 51):
            with self.subTest(to=to), self.assertRaises(ValueError):
                followup_email.save_draft(self.s, dict(meeting_id=self.mid, to=to, subject='S', body='B'))
        with self.assertRaises(ValueError):
            followup_email.save_draft(self.s, dict(meeting_id=self.mid, to=['a@example.test'], subject='Bad\r\nBcc: x@example.test', body='B'))
        self.assertEqual(self.google.sent, [])

    def test_prompt_stage_is_editable_and_testable(self):
        self.assertIn('followup_email', [row['id'] for row in self.s.prompts.catalog()['stages']])
        messages, schema = prompt_lab.messages_for('followup_email', 'Обсъдихме бюджета.', 'general')
        self.assertEqual(schema['required'], ['subject', 'body']);self.assertIn('reviewed_meeting_notes', messages[1]['content'])


class GmailDraftScopeTests(unittest.TestCase):
    def client(self, scopes):
        calls = []
        class Store:
            def get(self_):return dict(client_id='c', client_secret='s', refresh_token='r', access_token='a', expires_at=9e12,
                                      account_id='me@example.test', scopes=scopes)
            def set(self_, value):pass
        def request(url, method='GET', payload=None, token=None, form=False):
            calls.append((url, method, payload))
            if method == 'PUT':
                error = CalendarError('gone');error.status = 404;raise error
            return dict(id='new', message=dict(id='m1'))
        tmp = tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / '.google-calendar.json').write_text('{"configured": true, "account_id": "me@example.test"}')
        return GoogleCalendar(Path(tmp.name), store=Store(), request=request), calls

    def test_draft_needs_the_compose_permission(self):
        google, calls = self.client(['https://www.googleapis.com/auth/gmail.readonly'])
        with self.assertRaisesRegex(CalendarError, 'Gmail drafts'):
            google.gmail_draft('cmF3')
        self.assertEqual(calls, []);self.assertFalse(google.status()['capabilities']['gmail_compose'])

    def test_a_sent_or_deleted_draft_is_created_again(self):
        google, calls = self.client([GMAIL_COMPOSE_SCOPE])
        self.assertTrue(google.status()['capabilities']['gmail_compose'])
        self.assertEqual(google.gmail_draft('cmF3', 'old', expected_account='me@example.test')['id'], 'new')
        self.assertEqual([c[1] for c in calls], ['PUT', 'POST']);self.assertTrue(calls[1][0].endswith('/drafts'))
        with self.assertRaises(ValueError):google.gmail_draft('not base64 !')


if __name__ == '__main__':
    unittest.main()
