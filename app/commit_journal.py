"""Durable external intents. Unknown outcomes never grant permission to resend.

An intent that never reached GitHub (approved, cancelled, failed) or that a person checked
and abandoned no longer holds its resource. Only a live intent keeps the unique intent key.
"""
import datetime as dt
import hashlib
import json
import sqlite3
import uuid
from contextlib import closing
from .work_items import canonical, WorkItemConflict

STATES={'approved','sending','unknown','created','verified','failed','cancelled','abandoned'}
CLOSED={'failed','cancelled','abandoned'}


def _key(operation):
    """The intent column. A closed intent gives its key to a new attempt and keeps its history."""
    return operation['intent']+':'+operation['id'] if operation['state'] in CLOSED else operation['intent']


class CommitJournal:
    def __init__(self,path):
        self.path=path
        with closing(self.connect()) as db:
            db.execute('CREATE TABLE IF NOT EXISTS external_operations (id TEXT PRIMARY KEY, intent TEXT UNIQUE NOT NULL, document TEXT NOT NULL)');db.commit()

    def connect(self):
        return sqlite3.connect(self.path,timeout=10)

    def approve(self,payload):
        required={'resource','resource_revision','source_revision','account_id','repository_id','action','target','title','body'}
        # Assignees and labels are optional; without them, the payload and its digest stay as before.
        if not isinstance(payload,dict) or not required<=set(payload)<=required|{'assignees','labels'} or payload['action'] not in {'issue','comment'}:
            raise ValueError('Invalid publication preview')
        for field in ('resource','resource_revision','source_revision','account_id','repository_id'):
            if not payload[field]:raise ValueError('Preview needs source, resource and destination identity')
        digest=hashlib.sha256(canonical(payload).encode()).hexdigest()
        with closing(self.connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT document FROM external_operations WHERE intent=?',(digest,)).fetchone()
            if old:return json.loads(old[0])
            for key,raw in db.execute('SELECT id,document FROM external_operations').fetchall():
                previous=json.loads(raw)
                if previous['payload']['resource']!=payload['resource'] or previous['payload']['action']!=payload['action'] or previous['state'] in CLOSED:continue
                if previous['state']=='approved':
                    # Never sent: a new preview replaces it.
                    previous['state']='cancelled';db.execute('UPDATE external_operations SET intent=?,document=? WHERE id=?',(_key(previous),canonical(previous),key))
                elif previous['state'] in {'sending','unknown'} or payload['action']=='issue':
                    raise WorkItemConflict('This resource already has a publication. Check its outcome before creating another.')
            operation=dict(id=uuid.uuid4().hex,intent=digest,payload=payload,state='approved',result=None)
            db.execute('INSERT INTO external_operations VALUES (?,?,?)',(operation['id'],digest,canonical(operation)));db.commit();return operation

    def get(self,key):
        with closing(self.connect()) as db:
            row=db.execute('SELECT document FROM external_operations WHERE id=?',(key,)).fetchone()
        if not row:raise ValueError('Unknown publication operation')
        return json.loads(row[0])

    def transition(self,key,expected,state,result=None):
        allowed={('approved','sending'),('approved','cancelled'),('sending','unknown'),('sending','created'),('sending','failed'),('unknown','created'),('unknown','abandoned'),('created','verified')}
        if (expected,state) not in allowed:raise ValueError('Invalid publication transition')
        with closing(self.connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT document FROM external_operations WHERE id=?',(key,)).fetchone()
            if not row:raise ValueError('Unknown publication operation')
            operation=json.loads(row[0])
            if operation['state']!=expected:raise WorkItemConflict('Publication already advanced. Check its result before trying again.')
            operation.update(state=state)
            if result is not None:operation['result']=result
            db.execute('UPDATE external_operations SET intent=?,document=? WHERE id=?',(_key(operation),canonical(operation),key));db.commit();return operation

    def record_check(self,key,matches):
        """Record a complete GitHub lookup for an unknown outcome. A person decides what it means."""
        with closing(self.connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT document FROM external_operations WHERE id=?',(key,)).fetchone()
            if not row:raise ValueError('Unknown publication operation')
            operation=json.loads(row[0])
            if operation['state']!='unknown':return operation
            operation['result']=dict(operation['result'] or {},last_check=dict(at=dt.datetime.now(dt.timezone.utc).isoformat(),matches=matches))
            db.execute('UPDATE external_operations SET document=? WHERE id=?',(canonical(operation),key));db.commit();return operation

    def recover(self):
        """Startup recovery: no network call, no resend authorization. Only a POST that may have left is unknown."""
        with closing(self.connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            for key,raw in db.execute('SELECT id,document FROM external_operations').fetchall():
                operation=json.loads(raw)
                if operation['state']=='sending':
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
            if set(payload)!={'resource','resource_revision','source_revision','account_id','repository_id','action','target','title','body'} or row.get('intent')!=hashlib.sha256(canonical(payload).encode()).hexdigest() or row.get('state') not in STATES:raise ValueError('Invalid publication intent')
        return rows

    def restore(self,rows):
        self.validate_archive(rows)
        with closing(self.connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            for archived in rows:
                # A restored approval is never sent; anything that may have been sent needs a new check.
                row=dict(archived,state='cancelled' if archived['state']=='approved' else archived['state'] if archived['state'] in CLOSED else 'unknown')
                db.execute('INSERT OR IGNORE INTO external_operations VALUES (?,?,?)',(row['id'],_key(row),canonical(row)))
            db.commit()
