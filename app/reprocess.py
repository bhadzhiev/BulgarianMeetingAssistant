"""Explicit, revision-bound reruns. Preview never starts processing."""
import hashlib
import secrets
import time
from .work_items import canonical,WorkItemConflict
from . import meeting_types

ACTIONS={'notes':'summarize','correction':'correct','correction_notes':'correct_summarize','analytics':'reanalyze','audio':'all'}


def candidates(service,body):
    scope=body.get('scope','global')
    if not isinstance(scope,str) or not (scope=='global' or scope.startswith(('type:','meeting:'))):raise ValueError('Choose a meeting scope')
    rows=[]
    with service.lock:
        for meeting in service.library.list():
            if scope.startswith('meeting:') and meeting['id']!=scope[8:]:continue
            if scope.startswith('type:') and meeting_types.of(meeting)['id']!=scope[5:]:continue
            directory=service.library.directory(meeting['id'])
            rows.append(dict(id=meeting['id'],title=meeting['title'],created=meeting['created'],status=meeting['status'],eligible=(directory/'transcript.json').exists() and meeting['id']!=service.active and meeting['id'] not in service.busy,has_audio=(directory/'recording.wav').exists()))
    return dict(meetings=rows)


def revision(service,key):
    meeting=service.library.get(key);directory=service.library.directory(key)
    files={name:hashlib.sha256((directory/name).read_bytes()).hexdigest() if (directory/name).exists() else None for name in ('transcript.json','minutes.json')}
    return hashlib.sha256(canonical(dict(files=files,meeting_type=meeting_types.of(meeting),prompts=service.prompts.catalog()['revision'],settings=service.settings,trackers=service.library.trackers(),speakers=service.library.speakers())).encode()).hexdigest()


def validate(service,keys,action):
    if action not in ACTIONS or not isinstance(keys,list) or not 1<=len(keys)<=20 or len(set(keys))!=len(keys):raise ValueError('Choose 1–20 meetings and an operation')
    settings=service.settings
    if action in {'notes','correction_notes'} and settings['summarizer']=='none':raise ValueError('Choose a notes provider in Settings')
    if action in {'correction','correction_notes'} and settings['transcript_correction']=='none':raise ValueError('Enable transcript correction in Settings')
    providers=[]
    if action in {'notes','correction_notes','audio'} and settings['summarizer']!='none':providers.extend([('Notes',settings['summarizer']),('Consolidation of multipart notes',settings['summarizer'])])
    if (action in {'correction','correction_notes'} or action=='audio' and settings['transcription']!='elevenlabs') and settings['transcript_correction']!='none':providers.append(('Correction',settings['transcript_correction']))
    if action=='audio':providers.append(('Speech recognition',settings['transcription']))
    semantic=any(tracker.get('semantic_matching') for tracker in service.library.trackers())
    providers.append(('Analytics','local' if semantic else 'on_device'))
    if any(provider=='openai' for _,provider in providers) and not service.api_key:raise ValueError('Add an OpenAI key before starting cloud processing')
    if any(provider=='elevenlabs' for _,provider in providers) and not service.elevenlabs_api_key:raise ValueError('Add an ElevenLabs key before starting cloud processing')
    from .local_ai import is_remote
    if any(provider=='local' for _,provider in providers) and is_remote(settings.get('local_ai_base_url')) and not service.local_ai_api_key:
        raise ValueError('Add the API key of the configured API before starting cloud processing')
    for key in keys:
        meeting=service.library.get(key);directory=service.library.directory(key)
        if key==service.active or key in service.busy or meeting.get('title_status')=='generating':raise ValueError('A selected meeting is busy. Try later.')
        if not (directory/'transcript.json').exists():raise ValueError('A saved transcript is required')
        if action=='audio' and not (directory/'recording.wav').exists():raise ValueError('Audio is unavailable. Choose processing from the saved transcript.')
    return [dict(operation=label,provider=provider,destination='ElevenLabs cloud' if provider=='elevenlabs' else 'OpenAI cloud' if provider=='openai' else service.settings.get('local_ai_base_url','') if provider=='local' else 'On this Mac') for label,provider in providers]


def preview(service,body):
    with service.lock:
        keys=body.get('meetings');action=body.get('action');providers=validate(service,keys,action)
        if not hasattr(service,'rerun_previews'):service.rerun_previews={}
        service.rerun_previews={k:v for k,v in service.rerun_previews.items() if v['expires']>time.monotonic()}
        if len(service.rerun_previews)>=100:raise ValueError('Too many pending previews. Close old dialogs and retry later.')
        token=secrets.token_urlsafe(24);job=dict(keys=list(keys),action=action,revisions={key:revision(service,key) for key in keys},expires=time.monotonic()+600)
        service.rerun_previews[token]=job
        return dict(token=token,count=len(keys),providers=providers,uses_audio=action=='audio')


def start(service,body):
    if body.get('approved') is not True:raise ValueError('Approve the displayed operation first')
    with service.lock:
        job=getattr(service,'rerun_previews',{}).get(body.get('token'))
        if not job or job['expires']<=time.monotonic():raise WorkItemConflict('Preview expired or was already used. Review again.')
        validate(service,job['keys'],job['action'])
        if any(revision(service,key)!=value for key,value in job['revisions'].items()):raise WorkItemConflict('Transcript, notes, prompts or settings changed. Review the selection again.')
        del service.rerun_previews[body['token']]
        queued=[];failed=[]
        for key in job['keys']:
            try:
                if job['action']=='audio':service.process(key,'all',preserve_notes=True)
                else:service.process(key,ACTIONS[job['action']])
                queued.append(key)
            except (ValueError,RuntimeError) as error:failed.append(dict(id=key,error=str(error)))
        return dict(queued=queued,failed=failed)
