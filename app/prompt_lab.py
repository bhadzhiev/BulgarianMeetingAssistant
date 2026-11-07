"""Isolated prompt previews. Explicit snippets only; never modifies meeting outputs."""
import copy
import json
from pathlib import Path
import secrets
import tempfile
import threading
import time

from . import meeting_types
from .jobs import JobCancelled
from .local_ai import complete_json
from .prompts import STAGES, MAX_TEXT, apply, digest, key_for
from .work_items import WorkItemConflict, canonical

MEETING_STAGES={'meeting_minutes','transcript_correction','meeting_title','topic_matches'}


def context(service,stage,scope):
    key_for(stage,scope)
    if scope!='global' and stage not in MEETING_STAGES:
        raise ValueError('This operation uses global instructions because its sources span meetings')
    if scope.startswith('meeting:'):
        meeting=service.library.get(scope[8:]);return meeting_types.of(meeting),meeting['id']
    kind=scope[5:] if scope.startswith('type:') else 'general'
    template=service.templates.get(kind)
    if kind not in meeting_types.TYPES and not template:raise ValueError('Choose an existing meeting type')
    return meeting_types.definition(kind,template),None


def resolve(service,body):
    stage=body.get('stage');scope=body.get('scope','global');kind,meeting=context(service,stage,scope)
    snapshot=service.prompts.snapshot(kind['id'] if scope!='global' else None,meeting)
    if 'text' in body:
        if type(body.get('revision')) is not int or body['revision']!=snapshot['revision']:
            raise WorkItemConflict('Instructions changed. Reload before previewing this draft.')
        text=body['text']
        if text is not None and (not isinstance(text,str) or not text.strip() or len(text)>MAX_TEXT):raise ValueError('Enter 1–8000 characters, or reset to inherited instructions')
        saved=service.prompts.catalog()['entries'].get(stage+'|'+scope,{})
        mode=body.get('mode',saved.get('mode','append'))
        if mode not in {'append','replace'} or mode=='replace' and (stage!='meeting_minutes' or not scope.startswith('type:')):raise ValueError('Invalid replacement scope')
        if text==saved.get('text') and mode==saved.get('mode','append'):return snapshot,kind
        config=snapshot['stages'][stage];config['layers']=[v for v in config['layers'] if v['scope']!=scope]
        if text is not None:config['layers'].append(dict(scope=scope,text=text.strip(),revision='draft',**({'mode':'replace'} if mode=='replace' else {})))
        effective=[config['default']]
        for layer in config['layers']:
            if layer.get('mode')=='replace':effective=[]
            effective.append(layer['text'])
        config['effective']='\n\n'.join(effective);snapshot['id']=digest({k:v for k,v in snapshot.items() if k!='id'})
    return snapshot,kind


def save(service,body):
    with service.lock:
        context(service,body.get('stage'),body.get('scope','global'))
        service.prompts.save(body.get('stage'),body.get('scope','global'),body.get('text'),body.get('revision'),body.get('mode','append'))
        return service.prompts.catalog()


def messages_for(stage,snippet,kind,settings=None,speakers=()):
    """Use production task contracts with a synthetic single source for previews."""
    from meeting_assistant import llm_prompt,minutes_schema
    from . import correction,task_draft,gmail_ai,repo_reports,search
    if stage=='meeting_minutes':return [dict(role='user',content=llm_prompt('[00:00:00] '+snippet,meeting_type=kind))],minutes_schema(meeting_types.sections(kind))
    if stage=='transcript_correction':return [dict(role='system',content=correction.system_prompt(settings or {},speakers)),dict(role='user',content=canonical([dict(id=0,text=snippet)]))],correction.schema(1)
    if stage=='meeting_title':
        from .meeting_automation import TITLE_SYSTEM
        return [dict(role='system',content=TITLE_SYSTEM),dict(role='user',content=snippet)],dict(type='object',additionalProperties=False,required=['title'],properties=dict(title=dict(type='string')))
    if stage=='task_draft':return [dict(role='system',content=task_draft.SYSTEM),dict(role='user',content=canonical(dict(untrusted_source=dict(body=snippet))))],task_draft.SCHEMA
    if stage=='followup_email':
        from . import followup_email
        notes=dict(meeting_title='Test meeting',meeting_date='',summary=[snippet],decisions=[],tasks=[],next_steps=[])
        return [dict(role='system',content=followup_email.SYSTEM),dict(role='user',content=canonical(dict(reviewed_meeting_notes=notes)))],followup_email.SCHEMA
    if stage=='email_commitments':return [dict(role='system',content=gmail_ai.SYSTEM),dict(role='user',content=canonical(dict(untrusted_email=dict(body=snippet))))],gmail_ai.SCHEMA
    if stage in {'repository_changes','repository_summary'}:
        suffix='\nProduce one overall report across these changes; prioritize consequences, risks and follow-ups, without repeating each file.' if stage=='repository_summary' else ''
        return [dict(role='system',content=repo_reports.SYSTEM+suffix),dict(role='user',content=canonical(dict(untrusted_repository_evidence=[dict(id='preview',text=snippet)])))],repo_reports.SCHEMA
    if stage=='meeting_answer':
        sources=[dict(kind='transcript',meeting_title='Test excerpt',timestamp='00:00:00',meeting_date='',text=snippet)]
        return [dict(role='user',content=search.answer_prompt('Какво е обсъдено в този откъс?',sources))],search.ANSWER_SCHEMA
    return [dict(role='system',content='Match transcript segments to a discussion topic. Return only relevant segment IDs; do not infer IDs that are absent.'),dict(role='user',content='Topic: Next actions\nPhrases: []\nTranscript:\n[0] '+snippet)],dict(type='object',additionalProperties=False,required=['matches'],properties=dict(matches=dict(type='array',items=dict(type='integer'))))


def preview(service,body):
    stage=body.get('stage');snapshot,kind=resolve(service,body)
    snippet=body.get('snippet','')
    if not isinstance(snippet,str) or not snippet.strip() or len(snippet)>4000:raise ValueError('Enter a test excerpt of 1–4000 characters')
    # The lab deliberately uses the saved Notes & AI destination for every stage.
    # It is shown before approval; production stages retain their own providers.
    target=service.repo_reports.target();target['_prompt_snapshot']=snapshot
    messages,schema=messages_for(stage,snippet,kind,service.settings,service.library.speakers())
    target['prompt_test']=dict(stage=stage,messages=messages,schema=schema,snippet=snippet)
    token=digest(dict(target=target,nonce=service.prompts.nonce))
    full=apply(target,messages,stage)+[dict(role='user',content='Return only one JSON object matching this schema: '+json.dumps(schema,ensure_ascii=False))]
    return dict(preview_token=token,revision=snapshot['revision'],target=target,messages=full,schema=schema,effective=snapshot['stages'][stage])


def generate(settings,key=''):
    data=settings['prompt_test'];stage=data['stage'];snippet=data['snippet']
    result=complete_json(settings,data['messages'],data['schema'],stage,timeout=120,api_key=key)
    # Apply the same semantic checks where a single test source makes them meaningful.
    if stage=='transcript_correction':
        from .correction import accept
        if set(result)!={'segments'} or len(result['segments'])!=1 or result['segments'][0].get('id')!=0 or not accept(snippet,result['segments'][0].get('text')):raise ValueError('Correction failed the production preservation checks')
    elif stage=='meeting_minutes':
        from meeting_assistant import validate_minutes,TranscriptSegment
        validate_minutes(result,[TranscriptSegment(start=0,end=1,text=snippet)])
    elif stage=='email_commitments':
        from .gmail_ai import validate_result
        validate_result(result,dict(body=snippet,message_id='preview'))
    elif stage in {'repository_changes','repository_summary'}:
        from .repo_reports import validate_findings
        validate_findings(result,[dict(id='preview',text=snippet)])
    elif stage=='meeting_title':
        if set(result)!={'title'} or not isinstance(result['title'],str) or not 3<=len(result['title'].strip())<=100 or any(ord(c)<32 for c in result['title']):raise ValueError('Invalid title')
    elif stage=='task_draft':
        from .task_draft import draft_fields
        draft_fields(result)
    elif stage=='followup_email':
        from .followup_email import clean
        clean(result)
    elif stage=='topic_matches':
        if set(result)!={'matches'} or not isinstance(result['matches'],list) or any(type(v) is not int or v!=0 for v in result['matches']):raise ValueError('Invalid segment IDs')
    elif stage=='meeting_answer':
        if set(result)!={'found','answer','sources'} or type(result['found']) is not bool or not isinstance(result['answer'],str) or not isinstance(result['sources'],list) or any(type(v) is not int or v!=1 for v in result['sources']) or result['found'] and not result['sources']:raise ValueError('Answer has no valid source citations')
    return dict(result=result)


class PromptLab:
    def __init__(self,service,runner=None):
        self.service,self.runner=service,runner;self.lock=threading.RLock();self.event=threading.Event();self.thread=None;self.job={}
    def start(self,body):
        current=preview(self.service,body)
        if body.get('approved') is not True or body.get('preview_token')!=current['preview_token']:raise WorkItemConflict('Approve the current snippet, instructions and AI destination first')
        with self.lock:
            if self.thread and self.thread.is_alive():raise ValueError('Finish or cancel the current prompt test')
            self.event.clear();run=secrets.token_hex(16);self.job=dict(id=run,running=True,status='Testing instructions',error=None,started_at=time.time())
            self.thread=threading.Thread(target=self._run,args=(copy.deepcopy(current),),daemon=True,name='prompt-test');self.thread.start();return dict(self.job)
    def is_set(self):return bool(self.event.is_set() or self.service.closed.is_set() or self.service.active or self.service.busy)
    def _run(self,current):
        acquired=False
        try:
            if self.is_set() or not self.service.processing_slot.acquire(blocking=False):raise ValueError('Wait until recording or processing finishes before testing')
            acquired=True
            from .worker import ProcessingWorker
            with tempfile.TemporaryDirectory(prefix='.prompt-test-',dir=self.service.library.root) as tmp:
                output=(self.runner or ProcessingWorker(self.service.project)).run('prompt_test',Path(tmp),current['target'],lambda _:None,self.service.api_key if current['target']['provider']=='openai' else '',cancel=self)
            if self.is_set():raise JobCancelled()
            with self.lock:self.job.update(output,status='Test complete · no meeting changed')
        except JobCancelled:
            with self.lock:self.job.update(status='Cancelled')
        except Exception as exc:
            message=str(exc)
            if self.service.api_key:message=message.replace(self.service.api_key,'[redacted]')
            with self.lock:self.job.update(status='Failed',error=message)
        finally:
            if acquired:self.service.processing_slot.release()
            with self.lock:self.job['running']=False
    def status(self,key):
        with self.lock:
            if key!=self.job.get('id'):raise ValueError('This prompt test is no longer available')
            return copy.deepcopy(self.job)
    def stop(self,key):
        with self.lock:
            if key!=self.job.get('id'):raise ValueError('This prompt test is no longer available')
            self.event.set();return dict(self.job)
    def close(self):
        self.event.set()
        if self.thread:self.thread.join(timeout=2)


def catalog(service):
    result=service.prompts.catalog()
    result['types']=meeting_types.public(service.templates.list())
    result['meeting_type_prompts']={}
    for kind in result['types']:
        instruction=meeting_types.prompt(meeting_types.definition(kind['id'],service.templates.get(kind['id'])))
        global_text=result['entries'].get('meeting_minutes|global',{}).get('text')
        result['meeting_type_prompts'][kind['id']]='\n\n'.join(text for text in [STAGES['meeting_minutes'][1],global_text,instruction] if text)
    result['meetings']=[dict(id=m['id'],title=m['title']) for m in service.library.list()]
    result['meeting_stages']=sorted(MEETING_STAGES)
    result['builtin_templates']={key:dict(label=value['label']+' copy',description=value['description'],prepare=key,
        sections=[dict(title=s['title'],instruction=s['instruction'],review=bool(s['attention'])) for s in value['sections']]) for key,value in meeting_types.TYPES.items()}
    return result
