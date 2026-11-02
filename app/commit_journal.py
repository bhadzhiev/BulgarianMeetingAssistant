"""Durable external intents. Unknown outcomes never grant permission to resend."""
import hashlib
import json
import sqlite3
import uuid
from contextlib import closing
from .work_items import canonical, WorkItemConflict


class CommitJournal:
    def __init__(self,path):
        self.path=path
        with closing(self.connect()) as db:
            db.execute('CREATE TABLE IF NOT EXISTS external_operations (id TEXT PRIMARY KEY, intent TEXT UNIQUE NOT NULL, document TEXT NOT NULL)');db.commit()

    def connect(self):
        return sqlite3.connect(self.path,timeout=10)

    def approve(self,payload):
        required={'resource','resource_revision','source_revision','account_id','repository_id','action','target','title','body'}
        if not isinstance(payload,dict) or set(payload)!=required or payload['action'] not in {'issue','comment'}:
            raise ValueError('Invalid publication preview')
        for field in ('resource','resource_revision','source_revision','account_id','repository_id'):
            if not payload[field]:raise ValueError('Preview needs source, resource and destination identity')
        digest=hashlib.sha256(canonical(payload).encode()).hexdigest()
        with closing(self.connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT document FROM external_operations WHERE intent=?',(digest,)).fetchone()
            if old:return json.loads(old[0])
            for raw, in db.execute('SELECT document FROM external_operations'):
                previous=json.loads(raw)
                if previous['payload']['resource']==payload['resource'] and previous['payload']['action']==payload['action']:
                    raise WorkItemConflict('This resource already has a publication intent. Check its outcome before creating another.')
            operation=dict(id=uuid.uuid4().hex,intent=digest,payload=payload,state='approved',result=None)
            db.execute('INSERT INTO external_operations VALUES (?,?,?)',(operation['id'],digest,canonical(operation)));db.commit();return operation

    def get(self,key):
        with closing(self.connect()) as db:
            row=db.execute('SELECT document FROM external_operations WHERE id=?',(key,)).fetchone()
        if not row:raise ValueError('Unknown publication operation')
        return json.loads(row[0])

    def transition(self,key,expected,state,result=None):
        allowed={('approved','sending'),('sending','unknown'),('sending','created'),('sending','failed'),('unknown','created'),('created','verified')}
        if (expected,state) not in allowed:raise ValueError('Invalid publication transition')
        with closing(self.connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT document FROM external_operations WHERE id=?',(key,)).fetchone()
            if not row:raise ValueError('Unknown publication operation')
            operation=json.loads(row[0])
            if operation['state']!=expected:raise WorkItemConflict('Publication already advanced. Check its result before trying again.')
            operation.update(state=state)
            if result is not None:operation['result']=result
            db.execute('UPDATE external_operations SET document=? WHERE id=?',(canonical(operation),key));db.commit();return operation

    def recover(self):
        """Explicit startup/restore recovery: no network call, no resend authorization."""
        with closing(self.connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            for key,raw in db.execute('SELECT id,document FROM external_operations').fetchall():
                operation=json.loads(raw)
                if operation['state'] in {'approved','sending'}:
                    operation['state']='unknown'
                    db.execute('UPDATE external_operations SET document=? WHERE id=?',(canonical(operation),key))
            db.commit()

    def export(self):
        with closing(self.connect()) as db:
            return [json.loads(raw) for raw, in db.execute('SELECT document FROM external_operations')]

    @staticmethod
    def validate_archive(rows):
        import re
        if not isinstance(rows,list) or len(rows)>100000:raise ValueError('Invalid publication archive')
        for row in rows:
            if not isinstance(row,dict) or not re.fullmatch(r'[a-f0-9]{32}',str(row.get('id',''))) or not isinstance(row.get('payload'),dict):raise ValueError('Invalid publication operation')
            payload=row['payload']
            if set(payload)!={'resource','resource_revision','source_revision','account_id','repository_id','action','target','title','body'} or row.get('intent')!=hashlib.sha256(canonical(payload).encode()).hexdigest() or row.get('state') not in {'approved','sending','unknown','created','verified','failed'}:raise ValueError('Invalid publication intent')
        return rows

    def restore(self,rows):
        self.validate_archive(rows)
        with closing(self.connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            for archived in rows:
                row=dict(archived,state='unknown')
                db.execute('INSERT OR IGNORE INTO external_operations VALUES (?,?,?)',(row['id'],row['intent'],canonical(row)))
            db.commit()
