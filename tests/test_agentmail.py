from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from app.agentmail import AgentMail
from app.service import MeetingService
from app.task_draft import create, preview
from app.task_email import send_agentmail
from app.work_items import WorkItemConflict
from tests.test_calendar import FakeGoogle

PROJECT = Path(__file__).resolve().parents[1]
INBOX = 'test@agentmail.to'
KEY = 'fixture-key'
FIRST = '<mail-1@agentmail.to>'
REPLY = '<mail-2@agentmail.to>'


class MemoryStore:
    value = None

    def get(self):
        return self.value

    def set(self, value):
        self.value = value

    def delete(self):
        self.value = None


class AgentMailTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service = MeetingService(Path(self.temp.name) / 'library', PROJECT, google=FakeGoogle())
        self.addCleanup(self.service.close)
        self.first = dict(inbox_id=INBOX, message_id=FIRST, thread_id='thread',
                          subject='Fwd: Verify pilot', labels=['received'], text='Verify the backup result.')
        self.reply = dict(inbox_id=INBOX, message_id=REPLY, thread_id='thread', in_reply_to=FIRST,
                          subject='Re: Verify pilot', labels=['received'], text='Full message including history',
                          extracted_text='Backup restored. Waiting for reviewer.')
        self.calls = []

        def request(inbox, key, suffix=''):
            self.assertEqual((inbox, key), (INBOX, KEY))
            self.calls.append(suffix)
            if not suffix:
                return dict(inbox_id=INBOX, status='active')
            if suffix.startswith('/messages?'):
                return dict(messages=[self.first, self.reply, dict(self.reply, labels=['spam'])])
            return self.reply if 'mail-2' in suffix else self.first

        self.mail = self.service.agentmail = AgentMail(store=MemoryStore(), request=request)
        self.assertEqual(self.mail.connect(dict(inbox=INBOX, key=KEY)), dict(inbox=INBOX))

    def capture(self, mid, operation, **parameters):
        row = self.mail.detail(mid, INBOX)
        source = dict(provider='agentmail', inbox=INBOX, id=mid, revision=row['revision'])
        draft = preview(self.service, source)
        self.assertFalse(draft['ai_available'])
        self.assertEqual(draft['suggested_title'], 'Verify pilot')
        return dict(source, preview_token=draft['preview_token'], operation_id=operation,
                    title=draft['suggested_title'], details=draft['suggested_details'], **parameters)

    def test_lists_safe_messages_and_pins_source_when_task_is_saved(self):
        self.assertEqual(self.mail.status(), dict(inbox=INBOX))
        self.assertEqual([m['id'] for m in self.mail.listing()['messages']], [FIRST, REPLY])
        self.assertTrue(all('body' not in m for m in self.mail.listing()['messages']))
        request = self.capture(FIRST, 'a' * 32)
        saved = create(self.service, request)
        self.assertEqual(create(self.service, request), saved)
        task = self.service.items.items[saved['item_id']]
        evidence = self.service.items.data['source_evidence'][task['source_evidence'][0]]
        self.assertEqual(evidence['quote'], 'Verify the backup result.')
        self.assertEqual(evidence['locator']['thread_id'], 'thread')
        self.assertEqual(len(self.service.items.items), 1)

    def test_sends_the_reviewed_task_from_the_connected_inbox_with_safe_retries(self):
        task = self.service.create_task(dict(text='Verify pilot', request_id='e' * 32))
        submitted = []

        def send(inbox, key, suffix, *, payload, idempotency_key):
            self.assertEqual((inbox, key, suffix), (INBOX, KEY, '/messages/send'))
            submitted.append((payload, idempotency_key))
            return dict(message_id=FIRST, thread_id='thread')

        self.mail.request = send
        body = dict(inbox=INBOX, item_id=task['id'], to=['Reviewer@Example.test'],
                    subject='Verify pilot', body='Review the result.')
        with self.assertRaisesRegex(ValueError, 'changed'):
            send_agentmail(self.service, dict(body, inbox='another@agentmail.to'))
        with self.assertRaisesRegex(ValueError, 'no longer exists'):
            send_agentmail(self.service, dict(body, item_id='missing'))
        self.assertEqual(submitted, [])
        receipt = send_agentmail(self.service, body)
        self.assertEqual(receipt, dict(inbox=INBOX, to=['reviewer@example.test'],
                                       message_id=FIRST, thread_id='thread'))
        self.assertEqual(send_agentmail(self.service, body), receipt)
        self.assertEqual(submitted[0], submitted[1])
        self.assertEqual(submitted[0][0], dict(to=['reviewer@example.test'],
                                              subject='Verify pilot', text='Review the result.'))
        send_agentmail(self.service, dict(body, body='Edited text.'))
        self.assertNotEqual(submitted[0][1], submitted[2][1])

    def test_reply_updates_existing_task_once_without_changing_its_current_state(self):
        task = self.service.create_task(dict(text='Check the backup', request_id='c' * 32))
        request = self.capture(REPLY, 'b' * 32, target_id=task['id'], target_revision=task['revision'],
                               link_update='Restored. Waiting for reviewer.')
        result = create(self.service, request)
        self.assertEqual(create(self.service, request), result)
        self.assertEqual(result['item_id'], task['id'])
        updated = self.service.items.items[task['id']]
        self.assertEqual((updated['text'], updated['workflow_state']), ('Check the backup', 'todo'))
        updates = [e for e in updated['history'] if e['event'] == 'progress_update']
        self.assertEqual([e['text'] for e in updates], ['Restored. Waiting for reviewer.'])
        saved = self.service.items.data['source_evidence'][updates[0]['evidence_id']]
        self.assertEqual(saved['quote'], self.reply['extracted_text'])

    def test_rejects_stale_and_disconnected_captures(self):
        request = self.capture(FIRST, 'a' * 32)
        self.first['text'] = 'A revised email.'
        self.mail.detail(FIRST, INBOX)
        with self.assertRaises(WorkItemConflict):
            create(self.service, request)
        request = self.capture(FIRST, 'b' * 32)
        self.mail.disconnect()
        with self.assertRaises(ValueError):
            create(self.service, request)
        self.assertEqual(self.service.items.items, {})
