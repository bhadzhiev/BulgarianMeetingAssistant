"""AgentMail intake and explicit email sends for one connected inbox."""
from collections import OrderedDict
import json
import re
import threading
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .credentials import CredentialStore
from .gmail import _Markdown
from .work_graph import digest, text

API = 'https://api.agentmail.to/v0/inboxes/'
LIST_LIMIT = 50
BODY_LIMIT = 18000
RESPONSE_LIMIT = 4 * 1024 * 1024
HIDDEN_LABELS = {'sent', 'draft', 'spam', 'blocked', 'unauthenticated', 'trash'}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def fetch(inbox, key, suffix='', *, payload=None, idempotency_key=None):
    url = API + quote(inbox, safe='') + suffix
    headers = {'Authorization': 'Bearer ' + key, 'Accept': 'application/json'}
    sending = payload is not None
    if sending:
        headers.update({'Content-Type': 'application/json', 'Idempotency-Key': idempotency_key})
    request = Request(url, data=json.dumps(payload).encode() if sending else None, headers=headers)
    unconfirmed = 'AgentMail did not confirm the send. Retry without changing the email to avoid a duplicate.'
    try:
        with build_opener(NoRedirect()).open(request, timeout=15) as response:
            data = response.read(RESPONSE_LIMIT + 1)
        if len(data) > RESPONSE_LIMIT:
            raise ValueError('AgentMail response exceeds the local size limit')
        result = json.loads(data)
    except HTTPError as error:
        if sending:
            messages = {
                400: 'AgentMail rejected the email. Check the recipient, subject and text.',
                401: 'AgentMail rejected the API key.',
                403: 'AgentMail denied the send. Check the inbox scope and message_send permission.',
                404: 'The AgentMail inbox is unavailable.',
                429: 'AgentMail is rate limiting requests. Try again shortly.',
            }
            raise ValueError(messages.get(error.code, unconfirmed)) from None
        messages = {
            401: 'AgentMail rejected the API key.',
            403: 'AgentMail denied access. Check the key scope and read permissions.',
            404: 'This AgentMail inbox or message is unavailable.',
            429: 'AgentMail is rate limiting requests. Try again shortly.',
        }
        raise ValueError(messages.get(error.code, f'AgentMail returned HTTP {error.code}.')) from None
    except (URLError, TimeoutError):
        raise ValueError(unconfirmed if sending else 'Cannot reach AgentMail. Try again.') from None
    except (ValueError, UnicodeError):
        raise ValueError('AgentMail returned an invalid or oversized response.') from None
    if not isinstance(result, dict):
        raise ValueError('AgentMail returned an invalid response.')
    return result


def short(value, limit):
    return value.strip()[:limit] if isinstance(value, str) else ''


def message(inbox, value, *, body=False):
    if not isinstance(value, dict) or value.get('inbox_id') != inbox:
        raise ValueError('AgentMail returned a message for a different inbox.')
    labels = value.get('labels')
    if not isinstance(labels, list) or any(not isinstance(label, str) for label in labels):
        raise ValueError('AgentMail returned invalid message labels.')
    if HIDDEN_LABELS.intersection(labels):
        return None
    row = dict(id=text(value.get('message_id'), 'AgentMail message ID', 500),
               thread_id=short(value.get('thread_id'), 500),
               subject=short(value.get('subject'), 500) or '(No subject)',
               sender=short(value.get('from'), 500), timestamp=short(value.get('timestamp'), 100))
    if body:
        # Forwarded content belongs to the source. For replies, prefer the provider's newly written part.
        plain = short(value.get('extracted_text'), BODY_LIMIT + 1) if value.get('in_reply_to') else ''
        html = short(value.get('extracted_html'), RESPONSE_LIMIT) if value.get('in_reply_to') else ''
        if not plain and not html:
            plain = short(value.get('text'), BODY_LIMIT + 1)
            html = short(value.get('html'), RESPONSE_LIMIT)
        if not plain and html:
            parser = _Markdown()
            parser.feed(html)
            parser.close()
            plain = parser.text()
        row.update(body=plain[:BODY_LIMIT], truncated=len(plain) > BODY_LIMIT)
        row['revision'] = digest(row)
    return row


class AgentMail:
    def __init__(self, *, store=None, request=fetch):
        self.store = store if store is not None else CredentialStore('default', 'agentmail')
        self.request = request
        self.lock = threading.RLock()
        self.messages = OrderedDict()

    def status(self):
        with self.lock:
            current = self.store.get()
            return dict(inbox=current['inbox'] if current else '')

    def connect(self, body):
        inbox = text(body.get('inbox'), 'AgentMail inbox address', 254).lower()
        key = text(body.get('key'), 'AgentMail API key', 1024)
        if not re.fullmatch(r'[a-z0-9_+.-]+@agentmail\.to', inbox):
            raise ValueError('Enter the test inbox address at agentmail.to.')
        if not re.fullmatch(r'[!-~]+', key):
            raise ValueError('Enter a valid AgentMail API key.')
        with self.lock:
            record = self.request(inbox, key)
            if record.get('inbox_id') != inbox or record.get('status') == 'deactivated':
                raise ValueError('Choose an active AgentMail inbox.')
            self.store.set(dict(inbox=inbox, key=key))
            self.messages.clear()
            return dict(inbox=inbox)

    def disconnect(self):
        with self.lock:
            self.store.delete()
            self.messages.clear()
            return dict(inbox='')

    def _connection(self):
        current = self.store.get()
        if not current:
            raise ValueError('Connect an AgentMail inbox first.')
        return current['inbox'], current['key']

    def send(self, expected_inbox, to, subject, body, *, item_ids):
        with self.lock:
            inbox, key = self._connection()
            if expected_inbox != inbox:
                raise ValueError('The connected AgentMail inbox changed. Reopen the email and confirm the sender.')
            payload = dict(to=to, subject=subject, text=body)
            operation = digest([inbox, sorted(item_ids), payload])
            result = self.request(inbox, key, '/messages/send', payload=payload, idempotency_key=operation)
            message_id = short(result.get('message_id'), 500)
            thread_id = short(result.get('thread_id'), 500)
            if not message_id or not thread_id:
                raise ValueError('AgentMail did not confirm the send. Retry without changing the email to avoid a duplicate.')
            return dict(inbox=inbox, to=to, message_id=message_id, thread_id=thread_id)

    def listing(self):
        with self.lock:
            inbox, key = self._connection()
            result = self.request(inbox, key, f'/messages?limit={LIST_LIMIT}')
            rows = result.get('messages')
            if not isinstance(rows, list):
                raise ValueError('AgentMail returned an invalid message list.')
            return dict(inbox=inbox, messages=[row for value in rows[:LIST_LIMIT] if (row := message(inbox, value))])

    def detail(self, message_id, expected_inbox):
        message_id = text(message_id, 'AgentMail message ID', 500)
        with self.lock:
            inbox, key = self._connection()
            if expected_inbox != inbox:
                raise ValueError('The connected AgentMail inbox changed.')
            value = self.request(inbox, key, '/messages/' + quote(message_id, safe=''))
            row = message(inbox, value, body=True)
            if not row:
                self.messages.pop(message_id, None)
                raise ValueError('This AgentMail message is unavailable.')
            if row['id'] != message_id:
                raise ValueError('AgentMail returned a different message.')
            self.messages[message_id] = row
            self.messages.move_to_end(message_id)
            if len(self.messages) > LIST_LIMIT:
                self.messages.popitem(last=False)
            return dict(row, inbox=inbox)

    def source(self, inbox, message_id):
        with self.lock:
            connected, _key = self._connection()
            row = self.messages.get(message_id) if isinstance(message_id, str) else None
            if inbox != connected or not row or not row['body']:
                raise ValueError('Open the AgentMail message again before capturing it.')
            return dict(account=inbox, revision=row['revision'], subject=row['subject'], body=row['body'],
                        locator=dict(thread_id=row['thread_id'], message_id=row['id'],
                                     sender=row['sender'], timestamp=row['timestamp']))
