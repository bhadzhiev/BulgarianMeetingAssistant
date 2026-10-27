"""Confirmed channel identities over existing local caches. No network calls or voice guesses."""
from contextlib import closing
import copy
import json

from .work_items import WorkItemConflict


def sender(service, provider, account, record):
    key=record.get('sender','') if provider=='gmail' else record.get('sender_id','')
    person=service.people.match_channel(provider,account,key)
    return dict(provider=provider,account=account,person_id=person['id'] if person else None,
                person_name=person['name'] if person else None,available=bool(key))


def gmail_thread(service, key):
    account=service.gmail._account();row=copy.deepcopy(service.gmail.detail(key,expected_account=account))
    for message in row['messages']:
        message['identity']=dict(sender(service,'gmail',account,message),thread_id=key,message_id=message['id'],source_revision=row['revision'])
    return row


def chat_conversation(service, space):
    account=service.chat._account();rows=copy.deepcopy(service.chat.conversation(space))
    if service.chat._account()!=account:raise WorkItemConflict('The Chat account changed. Reopen the conversation.')
    for message in rows:message['identity']=dict(sender(service,'google_chat',account,message),name=message['name'],source_revision=message['revision'])
    return rows


def confirm(service, body):
    provider=body.get('provider');account=body.get('account')
    if not isinstance(account,str) or not account:raise ValueError('Reopen the sender before confirming its identity')
    with service.lock,service.people.lock:
        if provider=='gmail':
            thread=service.gmail.detail(body.get('thread_id'),expected_account=account)
            if body.get('source_revision')!=thread.get('revision'):raise WorkItemConflict('The email changed. Reopen it before confirming a sender.')
            message=next((m for m in thread['messages'] if m['id']==body.get('message_id')),None)
            if not message:raise ValueError('This email message is no longer cached')
            key=message['sender']
        elif provider=='google_chat':
            message=service.chat.detail(body.get('name'),expected_account=account)
            if body.get('source_revision')!=message.get('revision'):raise WorkItemConflict('The Chat message changed. Reopen it before confirming a sender.')
            key=message.get('sender_id')
            if not key:raise ValueError('Refresh Chat to get this sender’s stable identity')
        else:raise ValueError('Choose a supported channel')
        person=service.people.confirm_channel(body.get('person_id'),body.get('revision'),provider,account,key)
        return dict(person=person,people=service.people.list())


def remove(service, body):
    with service.lock,service.people.lock:
        person=service.people.get(body.get('person_id'))
        if not person or type(body.get('revision')) is not int or person['revision']!=body['revision']:raise WorkItemConflict('This person changed. Reopen its profile.')
        identity=body.get('identity')
        if identity not in person.get('identities',[]):raise ValueError('This confirmed identity no longer exists')
        value=copy.deepcopy(person)
        if identity['provider']=='gmail':
            value['identities']=[i for i in value['identities'] if not (i['provider']=='gmail' and i['external_id']==identity['external_id'])]
            value['emails']=[email for email in value['emails'] if email!=identity['external_id']]
        else:value['identities'].remove(identity)
        saved=service.people.save(value)
        return dict(person=saved,people=service.people.list())


def profile(service, person):
    email_rows=[];chat_rows=[];person_id=person['id']
    with closing(service.gmail.connect()) as db:
        for account,document in db.execute('SELECT account,document FROM threads ORDER BY date DESC LIMIT 1000'):
            try:thread=json.loads(document)
            except (ValueError,TypeError):continue
            if not isinstance(thread,dict) or not isinstance(thread.get('messages'),list):continue
            for message in thread['messages']:
                if not isinstance(message,dict) or type(message.get('date')) not in (int,float):continue
                matched=service.people.match_channel('gmail',account,message.get('sender',''))
                if matched and matched['id']==person_id:
                    email_rows.append(dict(provider='gmail',account=account,thread_id=thread['id'],message_id=message['id'],title=thread['subject'],text=message.get('body','')[:1000],date=message['date']/1000))
    with closing(service.chat.connect()) as db:
        for account,document in db.execute('SELECT account,document FROM messages ORDER BY date DESC LIMIT 1000'):
            try:message=json.loads(document)
            except (ValueError,TypeError):continue
            if not isinstance(message,dict) or type(message.get('date')) not in (int,float):continue
            matched=service.people.match_channel('google_chat',account,message.get('sender_id',''))
            if matched and matched['id']==person_id:
                chat_rows.append(dict(provider='google_chat',account=account,space=message['space'],name=message['name'],title=message.get('sender',''),text=message.get('body','')[:1000],date=message['date']))
    return dict(email=sorted(email_rows,key=lambda m:m['date'],reverse=True)[:50],chat=sorted(chat_rows,key=lambda m:m['date'],reverse=True)[:50],coverage='Latest 1000 cached email threads and 1000 Chat messages; up to 50 matching messages per channel. Exact confirmed emails or channel IDs only.')
