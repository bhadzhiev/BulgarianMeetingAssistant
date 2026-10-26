'use strict';
const $ = id => document.getElementById(id);
let desktopStatus='';
function disconnectedMessage(){return desktopStatus||(state?.desktop_mode?'Disconnected · check the desktop app':'Disconnected · reopen the launcher');}
let state, selected = null, detail = null, view = 'setup', dirtyTranscript = false, dirtyNotes = false;
let lastFingerprint = '', lastLibrary = '', lastDevices = '', pending = false;
let timingDefault = null;
let liveMeetingId = null, liveSignature = '', lastSpeakers = '', settingsTab = 'recording';
let lastTasks = '', itemEditing = false;
let speakerNaming=false;
let analyticsData = null, trackersData = [];
let notesEditing = false, questionFilter = 'open', questionLimit = 10;
let requestedMeeting=new URLSearchParams(location.search).get('meeting'), initialRouteHandled=false, lastGoogleConnected=false;
const statusNames = {starting:'Starting',recording:'Recording',paused:'Paused',stopping:'Saving',recorded:'Recorded',processing:'Processing',ready:'Ready',error:'Needs attention',interrupted:'Interrupted'};
function el(tag, className, text) { const node = document.createElement(tag); if(className) node.className=className; if(text!==undefined) node.textContent=text; return node; }
function option(text, value) { const node = el('option', '', text); node.value = value; return node; }
// Imported titles often contain the date already; do not show it two times.
function withDate(title, value) { const day = date(value); return title.includes(day) ? title : title + ' · ' + day; }
function time(seconds) { seconds=Math.max(0,Math.floor(seconds||0)); return [Math.floor(seconds/3600),Math.floor(seconds/60)%60,seconds%60].map(x=>String(x).padStart(2,'0')).join(':'); }
function date(value) { return new Date(value).toLocaleDateString(undefined,{month:'short',day:'numeric',year:'numeric'}); }
function error(message) { const target=$('settings-dialog').open?$('settings-error'):$('review-dialog').open?$('review-error'):$('scope-dialog').open?$('scope-error'):$('error'); target.textContent=message; target.hidden=false; }
function clearError() { $('error').hidden=true; $('settings-error').hidden=true; $('review-error').hidden=true; $('scope-error').hidden=true; }
function toast(message) { $('toast').textContent=message; $('toast').hidden=false; setTimeout(()=>$('toast').hidden=true,3000); }
function knownSpeaker(name) { const key=(name||'').trim().toLocaleLowerCase(); return key?(state?.speakers||[]).find(n=>n.toLocaleLowerCase()===key):undefined; }
function speakerTone(name) { let hash=0; for(const c of name.toLocaleLowerCase()) hash=(hash*31+c.codePointAt(0))>>>0; return 'tone-'+(hash%8); }
function initials(name) { return name.split(/\s+/).filter(Boolean).slice(0,2).map(word=>[...word][0].toLocaleUpperCase()).join(''); }
function speakerBadge(target,name) {
 const known=knownSpeaker(name); name=(name||'').trim();
 target.className='speaker-badge'+(known?' '+speakerTone(known):name?' new':' empty');
 target.textContent=known?initials(known):name?'NEW':'?';
 target.title=known?'Known speaker · '+known:name?'New speaker · added to known speakers when you save corrections':'No speaker label';
 return target;
}
function syncSpeakers() {
 const signature=JSON.stringify(state.speakers||[]); if(signature===lastSpeakers) return; lastSpeakers=signature;
 $('known-speakers').replaceChildren(...(state.speakers||[]).map(name=>{const option=document.createElement('option');option.value=name;return option;}));
 if($('settings-dialog').open) renderSpeakerSettings();
 // Re-annotate the open meeting unless that would discard typing.
 if(view==='detail'&&detail&&!hasEdits()) renderDetail();
}
function renderSpeakerLegend() {
 const target=$('speaker-legend'), counts=new Map(); target.replaceChildren();
 for(const s of detail.transcript) { if(!s.speaker) continue; const name=knownSpeaker(s.speaker)||s.speaker.trim(); counts.set(name,(counts.get(name)||0)+1); }
 target.hidden=!counts.size;
 for(const [name,count] of counts) { const chip=el('span','speaker-chip'); chip.append(speakerBadge(el('span'),name),el('span','',name+' · '+count)); target.append(chip); }
}
function renderSpeakerReview(busy) {
 const target=$('speaker-review');target.replaceChildren();
 const hasAudio=detail.files.includes('recording.wav'), names=[...new Set(detail.transcript.map(s=>s.speaker).filter(Boolean))];
 if(!detail.transcript.length)return;
 target.append(el('h3','','Speakers · after recording'));
 const runtime=state.diarization||{}, meta=detail.transcript_metadata?.speaker_alignment;
 const description=el('p','hint',detail.diarization_error?'Speaker separation could not finish · '+detail.diarization_error:
  meta?'Aligned using '+meta.method+'. Speaker boundaries are estimates; listen and confirm names.':
  'Separate voices after the meeting, then listen to a sample and name each speaker. Names are not inferred from the participant list.');target.append(description);
 if(hasAudio&&!runtime.available)target.append(el('p','notice warning',runtime.message||'Speaker model is not installed in this build.'));
 if(hasAudio){const identify=el('button','secondary','Identify speakers after recording');identify.type='button';
  identify.disabled=busy||!runtime.available||names.some(n=>!/^SPEAKER[ _-]?\d+$/i.test(n));
  identify.title=names.some(n=>!/^SPEAKER[ _-]?\d+$/i.test(n))?'Confirmed participant names are kept; speaker separation will not overwrite them.':'';
  identify.onclick=()=>perform(async()=>{if(!(await leaveEdits()))return;await api('/api/meetings/'+detail.id+'/process',{action:'speakers'});await openMeeting(detail.id,true);});target.append(identify);}
 if(!names.length){target.append(el('p','hint',hasAudio?'No speaker labels yet. The transcript remains available.':'Speaker separation needs recorded audio. You can add labels manually.'));return;}
 for(const name of names){
  const sample=detail.transcript.find(s=>s.speaker===name), row=el('div','input-row speaker-review-row'), label=el('strong','',name), listen=el('button','quiet','Listen from '+time(sample.start));listen.type='button';listen.disabled=!hasAudio;
  listen.onclick=()=>{$('audio').currentTime=sample.start;$('audio').play().catch(e=>error(e.message));};
  const input=el('input');input.placeholder='Participant name';input.value=/^SPEAKER[ _-]?\d+$/i.test(name)?'':name;input.maxLength=120;input.setAttribute('list','known-speakers');input.setAttribute('aria-label','Participant name for '+name);input.disabled=busy;input.oninput=()=>{speakerNaming=true;};
  const save=el('button','secondary','Apply name');save.type='button';save.disabled=busy;save.onclick=()=>perform(async()=>{if(dirtyTranscript||dirtyNotes||itemEditing){error('Save other corrections before naming speakers.');return;}if(!input.value.trim()){error('Enter a participant name.');return;}
   detail=await api('/api/meetings/'+detail.id+'/edit',{speaker_name:{speaker:name,name:input.value.trim(),revision:detail.transcript_revision}});speakerNaming=false;lastFingerprint=JSON.stringify(detail);state=await api('/api/state');renderState();renderDetail();toast('Speaker name applied to this meeting');});
  row.append(label,listen,input,save);target.append(row);
 }
}
function renderSpeakerSettings() {
 const list=$('speaker-list'), names=state.speakers||[]; list.replaceChildren();
 if(!names.length) list.append(el('p','hint','No known speakers yet.'));
 for(const name of names) { const chip=el('span','speaker-chip'); const remove=el('button','quiet','✕'); remove.type='button'; remove.setAttribute('aria-label','Remove '+name); remove.onclick=()=>perform(()=>saveSpeakers(names.filter(n=>n!==name))); chip.append(speakerBadge(el('span'),name),el('span','',name),remove); list.append(chip); }
}
async function saveSpeakers(names) { const result=await api('/api/speakers',{speakers:names}); state.speakers=result.speakers; renderSpeakerSettings(); syncSpeakers(); }
async function api(path,body) {
 const response=await fetch(path, body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
 const data=await response.json(); if(!response.ok) throw new Error(data.error || 'Request failed'); return data;
}
async function perform(fn) { clearError(); try { await fn(); } catch(e) { error(e.message); } }
function hasEdits() { return dirtyTranscript || dirtyNotes || itemEditing || speakerNaming; }
// The desktop window (WKWebView) does not show confirm() or prompt(): they return "no" at once. This dialog works everywhere.
function ask(message,{ok='OK',cancel='Cancel',danger=false,value=null}={}) {
 return new Promise(resolve=>{
  const dialog=$('ask-dialog'), input=$('ask-input');
  $('ask-message').textContent=message; $('ask-ok').textContent=ok; $('ask-cancel').textContent=cancel; $('ask-ok').className=danger?'danger':'primary';
  input.hidden=value===null; input.value=value??''; dialog.returnValue='';
  dialog.onclose=()=>{ const yes=dialog.returnValue==='ok'; resolve(value===null?yes:yes?input.value:null); };
  dialog.showModal(); if(value===null) $('ask-ok').focus(); else { input.focus(); input.select(); }
 });
}
$('ask-input').onkeydown=event=>{if(event.key==='Enter'){event.preventDefault();$('ask-dialog').close('ok');}};
async function leaveEdits() { const leave=!hasEdits()||await ask('Leave without saving your corrections?',{ok:'Leave',cancel:'Stay'});if(leave)speakerNaming=false;if(leave&&itemEditing){setItemEditing(false);lastTasks='';}return leave; }
function show(which) { view=which; for(const id of ['setup','recording','detail','tasks','analytics','prepare','find']) $(id).hidden=id!==which; $('open-tasks').classList.toggle('current',which==='tasks'); $('open-analytics').classList.toggle('current',which==='analytics'); $('open-prepare').classList.toggle('current',which==='prepare'); $('open-find').classList.toggle('current',which==='find'); }
function renderLibrary() {
 const query=$('search').value.toLocaleLowerCase();
 const meetings=state.meetings.filter(m=>!query||m.title.toLocaleLowerCase().includes(query));
 // Server searches transcript content on demand; retain the regular status snapshot.
 const filter=$('project-filter').value;
 const rows=(query && window.searchResults ? window.searchResults : meetings).filter(m=>!filter||(filter==='__none__'?!m.project_id:m.project_id===filter));
 const signature=JSON.stringify([rows,selected,view]); if(signature===lastLibrary) return; lastLibrary=signature;
 $('library').replaceChildren();
 if(!rows.length) $('library').append(el('p','empty-library',query||filter?'No matching meetings.':'Your meetings will appear here.'));
 for(const m of rows) { const button=el('button','meeting-item'+(m.id===selected&&view==='detail'?' current':'')); button.append(el('strong','',m.title),el('small','',(m.title.includes(date(m.created))?'':date(m.created)+' · ')+(statusNames[m.status]||m.status))); button.onclick=()=>perform(()=>openMeeting(m.id)); $('library').append(button); }
}
async function openMeeting(id,force=false) {
 if(!force&&!(await leaveEdits())) return;
 if(state.active?.id===id) { selected=id; show('recording'); renderState(); return; }
 selected=id; history.replaceState(null,'','/?meeting='+id); dirtyTranscript=dirtyNotes=false; if(detail?.id!==id){notesEditing=false;questionFilter='open';questionLimit=10;} detail=await api('/api/meetings/'+id); lastFingerprint=JSON.stringify(detail); renderDetail(); show('detail'); renderLibrary();
}
function renderState() {
 syncSpeakers();
 syncProjects();
 const summary=state.task_summary||{open:0,overdue:0};
 // Mentions that wait for a choice come first; then late tasks, then open tasks.
 $('tasks-badge').hidden=!summary.open&&!summary.review; $('tasks-badge').classList.toggle('late',!summary.review&&summary.overdue>0); $('tasks-badge').classList.toggle('review',!!summary.review);
 $('tasks-badge').textContent=summary.review?summary.review:summary.overdue?summary.overdue+' late':summary.open;
 $('tasks-badge').title=summary.review?summary.review+' mentions wait for your review':summary.overdue?summary.overdue+' tasks are late':summary.open+' open tasks';
 $('connection').textContent=desktopStatus|| (state.active?'● Recording workspace':'● Connected to this Mac');
 const signature=JSON.stringify(state.devices);
 if(signature!==lastDevices) { lastDevices=signature; const oldName=$('microphone').selectedOptions[0]?.textContent; $('microphone').replaceChildren(); for(const d of state.devices) { const option=el('option','',d.name); option.value=d.id; $('microphone').append(option); } if(!state.devices.length){const option=el('option','','No microphone available');option.value='';$('microphone').append(option);} else { const preferred=state.devices.find(d=>d.name===oldName)||state.devices.find(d=>/iphone/i.test(d.name)); if(preferred) $('microphone').value=preferred.id; } }
 const backup=$('fallback-microphone'), previousBackup=backup.value, primaryName=$('microphone').selectedOptions[0]?.textContent;
 backup.replaceChildren(option('Retry the selected microphone only',''),...state.devices.filter(d=>d.name!==primaryName).map(d=>option(d.name,d.name)));
 if([...backup.options].some(o=>o.value===previousBackup))backup.value=previousBackup;
 $('start').disabled=!!state.active||!state.devices.length||pending;
 $('check-mic').disabled=!!state.active||!state.devices.length;
 $('setup-meter').value=state.preview_level;
 $('mic-hint').textContent=state.preview_active?'Listening for 10 seconds · nothing is saved':state.device_error||'Test your microphone before recording';
 const s=state.settings;
 $('meeting-title').placeholder=s.auto_title!==false?'Leave blank for an AI-generated title':'Meeting name (optional)';
 $('processing-name').textContent=(s.transcription==='local'?'Local Whisper':'OpenAI cloud')+' · '+(s.summarizer==='none'?'transcript only':s.summarizer==='local'?'local notes':'cloud notes');
 $('privacy-copy').textContent=privacy(s);
 renderTranscriptionTiming();
 if($('settings-dialog').open){renderGoogleStatus();if(calendarConnected()&&!lastGoogleConnected)perform(loadCalendars);}
 lastGoogleConnected=calendarConnected();
 if(state.active) {
  const a=state.active; $('recording-title').textContent=a.title; $('recording-mode').textContent=a.mode==='online'?'ONLINE · MAC AUDIO + MICROPHONE':'IN PERSON · MICROPHONE';
  // A state snapshot can be older than the last live event; the timer never goes back.
  if(lastLive?.meeting_id===a.id){a.duration=Math.max(a.duration||0,lastLive.duration);a.level=lastLive.level;}
  $('recording-status').textContent=statusNames[a.status]||a.status; $('timer').textContent=time(a.duration); $('recording-meter').value=a.level||0;
  if(a.microphone_status&&a.microphone_status!=='connected')$('recording-status').textContent='Microphone unavailable · retrying';
  const enabled=['recording','paused'].includes(a.status); $('pause').disabled=$('stop').disabled=!enabled;
  $('pause').textContent=a.status==='paused'?'▶ Resume':'Ⅱ Pause'; $('recording-indicator').classList.toggle('paused',a.status!=='recording');
  $('recording-help').textContent=a.status==='starting'?'Preparing audio capture. macOS may request recording permission.':a.status==='paused'?'Paused. Audio during the pause is discarded.':a.status==='stopping'?'Finishing audio files. Please keep the app open.':'Audio is being saved continuously on this Mac.';
  if(a.warnings?.length) $('recording-help').textContent+=' '+a.warnings.join(' ');
  if(a.microphone_name)$('recording-help').textContent+=' Input: '+a.microphone_name+'.';
  renderLive(a);
  renderMarkerList($('marker-list'),a.markers||[],false);
  if(view==='setup') { selected=a.id; show('recording'); }
 } else if(view==='recording' && selected) { perform(()=>openMeeting(selected,true)); }
 renderLibrary();
}
const MARKER_LABELS={important:'★ Important',decision:'✓ Decision',check:'? Check later'};
// Recording markers during the meeting, and review shortcuts after it.
function renderMarkerList(target,markers,review) {
 target.replaceChildren();
 for(const marker of [...markers].sort((a,b)=>a.time-b.time)) {
  const row=el('div','marker-row '+marker.kind), when=el(review?'button':'span','marker-time',time(marker.time)+(review?' ▶':''));
  if(review){when.type='button';when.title='Show and play this moment';when.onclick=()=>showSeconds(marker.time);}
  row.append(when,el('span','marker-kind',MARKER_LABELS[marker.kind]||marker.kind));
  if(marker.note) row.append(el('span','marker-note',marker.note));
  if(review){const remove=el('button','quiet','✕');remove.type='button';remove.setAttribute('aria-label','Remove marker');remove.onclick=()=>perform(async()=>{detail=await api('/api/meetings/'+detail.id+'/marker-delete',{id:marker.id});lastFingerprint=JSON.stringify(detail);renderDetail();});row.append(remove);}
  target.append(row);
 }
}
async function addMarker(kind) {
 const note=$('marker-note').value.trim(), result=await api('/api/marker',{kind,note});
 $('marker-note').value=''; if(state.active) state.active.markers=result.markers; renderMarkerList($('marker-list'),result.markers,false); toast(MARKER_LABELS[kind]+' · '+time(result.markers.at(-1).time));
}
for(const button of document.querySelectorAll('[data-marker]')) button.onclick=()=>perform(()=>addMarker(button.dataset.marker));
$('marker-note').onkeydown=event=>{if(event.key==='Enter'){event.preventDefault();perform(()=>addMarker('important'));}};
document.addEventListener('keydown',event=>{
 if(view!=='recording'||!state?.active||event.metaKey||event.ctrlKey||event.altKey||event.target.closest('input,textarea,select,[contenteditable]')) return;
 const kind={'1':'important','2':'decision','3':'check'}[event.key]; if(kind){event.preventDefault();perform(()=>addMarker(kind));}
});
function captionRow(segment, provisional=false, ended=false) {
 const row=el('div','live-segment'+(provisional?' provisional':''));
 row.append(el('span','live-time',time(segment.start)),el('p','',segment.text));
 if(provisional) row.append(el('span','live-provisional',ended?'Unconfirmed draft':'Still speaking…'));
 return row;
}
function renderTranscriptionTiming(reset=false) {
 if(!state)return;
 const s=state.settings, preferred=s.live_transcription===false?'after':'live';
 if(reset||timingDefault!==preferred){$('transcription-timing').value=preferred;timingDefault=preferred;}
 const live=$('transcription-timing').value==='live';
 $('transcription-timing-help').textContent=(live?'Whisper shows draft captions during the meeting. ':'Only audio is saved during the meeting; no live speech model runs. ')+
  (s.auto_process?'After you stop, ':'When you choose Transcribe after saving, ')+
  (s.transcription==='local'?'Whisper transcribes the full saved recording.':'the selected cloud provider transcribes the full saved recording.')+
  ' Any enabled spelling correction runs after final transcription. This choice applies only to this meeting.';
}
$('transcription-timing').onchange=()=>renderTranscriptionTiming();
function renderLive(active) {
 const live=active.live;
 const disabled=active.settings?.live_transcription===false;
 $('live-card').hidden=disabled;
 const final=active.settings?.transcription==='openai'?'the selected cloud provider':'Whisper';
 const next=active.settings?.auto_process===false?'After saving, choose Transcribe to process the full recording with '+final+'.':'After you stop, '+final+' will transcribe the full saved recording.';
 $('recording-transcription-plan').hidden=!disabled;
 $('recording-transcription-plan').textContent='Audio only during this meeting · no live captions. '+next;
 $('recording-next-step').textContent='Keep the app running. '+next+' Any enabled spelling correction follows final transcription.';
 const target=$('live-transcript');
 if(liveMeetingId!==active.id){liveMeetingId=active.id;liveSignature='';target.replaceChildren();}
 let message=disabled?'Live captions are switched off for this meeting.':live?.message||'Preparing local live captions…';
 if(active.status==='paused' && live?.status!=='error') message='Paused · transcript is kept; captions resume with recording.';
 const lag=Math.max(0,(active.duration||0)-(live?.processed_until||0));
 if(active.status==='recording'&&(live?.status==='listening'||live?.status==='transcribing')) message += lag>15?' · Catching up ('+Math.round(lag)+' seconds behind).':' · Updates every few seconds';
 if(live?.error) message += ' '+live.error;
 $('live-status').textContent=message;
 const signature=JSON.stringify([live?.segments,live?.partial,disabled]);
 if(signature===liveSignature)return;
 liveSignature=signature;
 const follow=target.scrollHeight-target.scrollTop-target.clientHeight<70;
 const segments=live?.segments||[];
 // Keep existing committed rows in place; changing partials must never duplicate them.
 for(const partial of target.querySelectorAll('.provisional,.live-empty'))partial.remove();
 while(target.children.length>segments.length)target.lastElementChild.remove();
 for(let i=target.children.length;i<segments.length;i++)target.append(captionRow(segments[i]));
 if(live?.partial)target.append(captionRow(live.partial,true));
 if(!target.children.length)target.append(el('p','live-empty',disabled?'You can transcribe the saved recording later.':'Your words will appear here as you speak.'));
 if(follow)target.scrollTop=target.scrollHeight;
}
function renderSavedDraft(meeting) {
 const target=$('saved-live-draft');target.replaceChildren();
 const live=meeting.live;
 target.hidden=!!meeting.transcript.length||!live;
 if(target.hidden)return;
 target.append(el('h3','','Live draft'),el('p','hint','Saved during recording. Use Transcribe to create the final version.'));
 for(const segment of live.segments||[])target.append(captionRow(segment));
 if(live.partial)target.append(captionRow(live.partial,true,true));
 if(!live.segments?.length&&!live.partial)target.append(el('p','hint',live.message||'No live speech was recognized.'));
}

function privacy(s) { let text=s.transcription==='openai'?'Audio is sent to OpenAI for transcription.'+(s.summarizer==='openai'?' Transcript text is also sent for notes.':''):s.summarizer==='openai'?'Transcription stays local. Transcript text is sent to OpenAI for notes.':'Transcription stays on this Mac. Local text AI uses the configured API endpoint.';if(s.transcript_correction==='openai')text+=' Transcript text is sent to OpenAI for AI correction.';if(s.auto_title&&s.title_provider==='openai')text+=' Transcript excerpts are sent to OpenAI for titles.';if(s.calendar_enabled)text+=' Meeting titles, times and local links are saved in Google Calendar.';return text; }
function switchTab(name) {
 for(const [tab,panel] of [['transcript','transcript-panel'],['outcomes','outcomes-panel'],['notes','notes-panel'],['analytics','meeting-analytics-panel']]) { const yes=tab===name; $(panel).hidden=!yes; $('tab-'+tab).classList.toggle('selected',yes); $('tab-'+tab).setAttribute('aria-selected',String(yes)); }
}
function markTranscript() { dirtyTranscript=true; $('save-transcript').disabled=false; }
function markNotes() { dirtyNotes=true; $('save-notes').disabled=$('save-outcomes').disabled=false; }
function renderDetail() {
 const d=detail, busy=['starting','recording','paused','stopping','processing'].includes(d.status);
 $('detail-title').textContent=d.title; $('detail-date').textContent=date(d.created)+' · '+(d.mode==='online'?'Online meeting':d.mode==='imported'?'Imported transcript':d.mode==='audio'?'Imported audio':'In-person meeting')+(d.duration?' · '+shortDuration(d.duration):''); $('detail-status').textContent=statusNames[d.status]||d.status;
 const titleMessages={pending:'AI title pending',generating:'Generating AI title…',generated:'AI-generated title',waiting:'AI title waiting for a transcript',manual:'',error:'AI title could not be generated'};
 $('title-status').textContent=(titleMessages[d.title_status]||'')+(d.title_error?' · '+d.title_error:'');$('title-status').hidden=!$('title-status').textContent;
 const sync=d.calendar_sync; $('calendar-status').hidden=!sync;$('calendar-status').replaceChildren();
 if(sync){$('calendar-status').append(el('span','',sync.status==='synced'?'Saved in Google Calendar':sync.status==='error'?'Calendar sync needs attention: '+sync.error:'Calendar sync pending…'));if(sync.status==='synced'&&sync.html_link){const url=new URL(sync.html_link);if(url.protocol==='https:'&&['www.google.com','calendar.google.com'].includes(url.hostname)){const link=el('a','',' Open event ↗');link.href=url.href;link.target='_blank';link.rel='noopener noreferrer';$('calendar-status').append(link);}}}
 renderScope(d);
 $('generate-title').disabled=busy||d.title_status==='generating'||(!d.transcript.length&&!d.live?.segments?.length);
 $('sync-calendar').disabled=busy||(!sync&&!state.settings.calendar_enabled);
 $('sync-calendar').textContent=sync?.status==='synced'?'Update calendar event':'Sync to Google Calendar';
 // The status badge already says Ready; the bar is only for progress and extra advice.
 $('cancel-processing').hidden=d.status!=='processing';
 $('cancel-processing').disabled=!!d.processing_cancel_requested;
 $('cancel-processing').textContent=d.processing_cancel_requested?'Cancelling…':'Cancel processing';
 renderProcessingTime();
 const gaps=$('capture-gaps');gaps.replaceChildren();gaps.hidden=!d.input_gaps?.length;
 if(d.input_gaps?.length){gaps.append(el('p','','Microphone audio is missing in these intervals:'));for(const gap of d.input_gaps){const seek=el('button','quiet',time(gap.start)+'–'+time(gap.end??d.duration)+' · Play');seek.onclick=()=>{$('audio').currentTime=gap.start;$('audio').play().catch(e=>error(e.message));};gaps.append(seek);}}
 $('job-progress').textContent=d.progress||''; $('job-progress').hidden=!d.progress||d.progress===statusNames[d.status]||['Imported','Recording saved','Audio imported'].includes(d.progress); $('detail-error').hidden=!d.error; $('detail-error').textContent=d.error||'';
 const prepared=d.files.includes('transcription.wav'), selector=$('audio-source'), sameMeeting=$('audio').dataset.meeting===d.id;
 const source=prepared&&sameMeeting&&selector.value==='transcription.wav'?'transcription.wav':'recording.wav';
 selector.replaceChildren(option('Original recording','recording.wav'),...(prepared?[option('Prepared for transcription','transcription.wav')]:[]));selector.value=source;
 selector.hidden=$('audio-source-label').hidden=!prepared;$('audio').dataset.meeting=d.id;
 const audioURL='/files/'+d.id+'/'+source;
 if(d.files.includes('recording.wav')) { if(!$('audio').src.endsWith(audioURL)) $('audio').src=audioURL; $('audio').hidden=false; $('audio-unavailable').hidden=true; }
 else { $('audio').removeAttribute('src'); $('audio').hidden=true; $('audio-unavailable').hidden=false; }
 $('playback').hidden=d.mode==='imported';
 $('exports').replaceChildren(); $('files-menu').hidden=!d.files.length; for(const name of d.files) { const row=el('div','file-row'), a=el('a','',name==='recording.wav'?'↓ Audio (WAV)':'↓ '+name); a.href='/files/'+d.id+'/'+name; a.download=name; row.append(a); if(name.endsWith('.md')) { const v=el('button','view-file','View'); v.type='button'; v.setAttribute('aria-label','View '+name); v.onclick=()=>perform(()=>openViewer(d.id,name)); row.append(v); } $('exports').append(row); }
 for(const id of ['process','summarize','recover','edit-title','delete-meeting']) $(id).disabled=busy;
 $('correct').disabled=busy||!d.transcript.length; $('correct').hidden=state.settings.transcript_correction==='none'&&!d.transcript_raw;
 const preparation=d.transcript_metadata?.audio_preparation;
 $('audio-preparation-status').hidden=preparation?.profile!=='light';
 $('audio-preparation-status').textContent=preparation?.source==='recording.wav'&&d.mode==='online'?'Light audio preparation used the mixed recording because separate raw tracks were unavailable.':'Transcribed with Light audio preparation. Playback keeps the original unless you select Prepared.';
 const fix=d.transcript_metadata?.correction;
 $('correction-status').hidden=!fix&&!d.correction_error;
 $('correction-status').textContent=d.correction_error?'AI correction failed · the Whisper transcript is shown. '+d.correction_error:fix?'AI corrected '+fix.changed+(fix.changed===1?' segment':' segments')+(fix.rejected?' · '+fix.rejected+' larger changes were refused':'')+'. Marked segments show the original Whisper text; click ↺ to restore it.':'';
 $('correction-status').classList.toggle('warning',!!d.correction_error);
 $('recover').hidden=d.mode==='imported'||d.mode==='audio'||!!d.files.includes('recording.wav')&&!['interrupted','error'].includes(d.status);$('process').hidden=d.mode==='imported';
 $('summarize').disabled=busy||!d.transcript.length; $('summarize').textContent=d.minutes?'Generate new AI notes':'Generate notes';
 $('process').textContent=d.transcript.length?'Transcribe again':'Transcribe';
 placeActions(d);
 $('timestamp-note').textContent=d.transcript_metadata?.timestamps==='approximate chunk boundaries'?'Cloud timestamps mark approximate audio chunks. Click a time to listen.':'Click a timestamp to listen. Correct the text or add a speaker label below.';
 $('transcript').replaceChildren();
 if(!d.transcript.length) $('transcript').append(el('p','empty-content',d.live?.segments?.length?'Your saved live draft is below. The final transcript appears after processing.':busy?'Your transcript will appear here when processing finishes.':'Your recording is saved. Choose Transcribe to turn it into text.'));
 d.transcript.forEach((s,index)=>{ const row=el('div','segment');const seek=el('button','',time(s.start)+' ▶');seek.setAttribute('aria-label','Play from '+time(s.start));seek.onclick=()=>{ $('audio').currentTime=s.start; $('audio').play().catch(e=>error(e.message)); }; const content=el('div');const speaker=el('input','speaker');speaker.placeholder='Speaker (optional)';speaker.value=s.speaker||'';speaker.setAttribute('list','known-speakers');speaker.setAttribute('aria-label','Speaker for segment '+(index+1));speaker.disabled=busy;const badge=el('span');const annotate=()=>{speakerBadge(badge,speaker.value);row.classList.toggle('known-speaker',!!knownSpeaker(speaker.value));};annotate();speaker.oninput=()=>{s.speaker=speaker.value.trim()||null;annotate();renderSpeakerLegend();markTranscript();};const who=el('div','speaker-line');who.append(badge,speaker);const original=d.transcript_raw?.length===d.transcript.length?d.transcript_raw[index]:null;if(original&&original.text!==s.text){row.classList.add('ai-corrected');const restore=el('button','quiet restore-original','AI ↺');restore.title='Restore Whisper text: '+original.text;restore.setAttribute('aria-label','Restore original Whisper text for segment '+(index+1));restore.disabled=busy;restore.onclick=()=>{s.text=original.text;text.value=original.text;row.classList.remove('ai-corrected');restore.remove();markTranscript();};who.append(restore);}const text=el('textarea');text.value=s.text;text.setAttribute('aria-label','Transcript segment '+(index+1));text.disabled=busy;text.rows=Math.max(2,Math.ceil(s.text.length/85));text.oninput=()=>{s.text=text.value;markTranscript();};content.append(who,text);row.append(seek,content);$('transcript').append(row); });
 renderSpeakerLegend();renderSpeakerReview(busy);
 $('detail-markers').hidden=!d.markers?.length; $('detail-markers').replaceChildren();
 if(d.markers?.length){$('detail-markers').append(el('h3','','Moments you marked'));const list=el('div','marker-list');renderMarkerList(list,d.markers,true);$('detail-markers').append(list);}
 $('save-transcript').disabled=true; renderSavedDraft(d); renderNotes(busy); renderMeetingAnalytics(busy);
}
const ACTIONS=['process','correct','summarize','recover','edit-title','generate-title','sync-calendar','delete-meeting'];
// One clear next step is a button; the other actions wait in the More menu.
function placeActions(d) {
 const audio=d.files.includes('recording.wav');
 const primary=!$('recover').hidden&&!audio?'recover':!$('process').hidden&&!d.transcript.length?'process':d.transcript.length&&!d.minutes?'summarize':null;
 for(const id of ACTIONS) { const button=$(id); if(id===primary){button.className='primary';$('primary-action').append(button);} else {button.className=id==='delete-meeting'?'danger-text':'';$('more-actions').append(button);} }
}
function closeMenus(except) { for(const menu of document.querySelectorAll('details.menu[open]')) if(menu!==except) menu.open=false; }
document.addEventListener('click',event=>{closeMenus(event.target.closest('details.menu'));if(event.target.closest('.menu-items button,.menu-items a'))closeMenus();});
document.addEventListener('keydown',event=>{if(event.key==='Escape')closeMenus();});
function stampSeconds(stamp) { const [h,m,sec]=stamp.split(':').map(Number); return h*3600+m*60+sec; }
// Show the transcript at this moment and play it when the meeting has audio.
function showMoment(stamp) {
 const seconds=stampSeconds(stamp); let index=detail.transcript.findIndex(s=>time(s.start)===stamp);
 if(index<0) index=detail.transcript.findIndex(s=>s.end>=seconds);
 switchTab('transcript'); const row=$('transcript').children[index];
 if(row){row.scrollIntoView({block:'center'});row.classList.add('evidence-highlight');setTimeout(()=>row.classList.remove('evidence-highlight'),1800);}
 if(detail.files.includes('recording.wav')){$('audio').currentTime=seconds;$('audio').play().catch(e=>error(e.message));}
}
function showSeconds(seconds) {
 let index=-1; detail.transcript.forEach((segment,i)=>{if(segment.start<=seconds+0.5)index=i;});
 switchTab('transcript'); const row=$('transcript').children[Math.max(0,index)];
 if(row&&detail.transcript.length){row.scrollIntoView({block:'center'});row.classList.add('evidence-highlight');setTimeout(()=>row.classList.remove('evidence-highlight'),1800);}
 if(detail.files.includes('recording.wav')){$('audio').currentTime=seconds;$('audio').play().catch(e=>error(e.message));}
}
function stampButton(stamp) { const button=el('button','quiet stamp',stamp+' ▶'); button.type='button'; button.title='Show this moment in the transcript'; button.onclick=()=>showMoment(stamp); return button; }
// AI notes cite moments as (00:29:46); make them links to the transcript.
function linkedText(target,text) { text.split(/\(?\b(\d{2}:\d{2}:\d{2})\b\)?/).forEach((part,i)=>target.append(i%2?stampButton(part):document.createTextNode(part))); return target; }
const FIELD_TITLES={summary:'Summary',decisions:'Decisions',next_steps:'Agreed next steps',needs_decision:'Questions for your decision',tasks:'Tasks',open_questions:'Unresolved questions',observations:'Private observations'};
const ITEM_FIELDS=Object.keys(FIELD_TITLES).filter(field=>field!=='tasks');
function segmentAt(stamp) { return detail.transcript.find(s=>time(s.start)===stamp); }
let excerptEnd=null;
$('audio').addEventListener('timeupdate',()=>{if(excerptEnd!==null&&$('audio').currentTime>=excerptEnd){$('audio').pause();excerptEnd=null;}});
$('audio').addEventListener('seeking',()=>{if(excerptEnd!==null&&$('audio').currentTime>excerptEnd)excerptEnd=null;});
// Play only the cited segment and stay in the notes; without audio, show it in the transcript.
function playExcerpt(stamp) {
 const segment=segmentAt(stamp);
 if(!segment||!detail.files.includes('recording.wav')) return showMoment(stamp);
 excerptEnd=segment.end; $('audio').currentTime=segment.start; $('audio').play().catch(e=>error(e.message));
}
function sourceBlock(stamp) {
 const box=el('div','note-source');
 if(!stamp) { box.append(el('span','no-source','No source moment')); return box; }
 const audio=detail.files.includes('recording.wav'), play=el('button','quiet stamp',(audio?'▶ ':'')+stamp);
 play.type='button'; play.title=audio?'Play this moment':'Show this moment in the transcript'; play.onclick=()=>playExcerpt(stamp); box.append(play);
 const segment=segmentAt(stamp);
 if(segment) { const quote=el('button','quote',(segment.speaker?segment.speaker+': ':'')+'“'+segment.text+'”'); quote.type='button'; quote.title='Show in the transcript'; quote.onclick=()=>showMoment(stamp); box.append(quote); }
 return box;
}
let notesBase=null;
const NOTE_FIELDS=['summary','decisions','next_steps','needs_decision','tasks','open_questions','observations'];
// Send only the sections that changed, with how they looked before. The server refuses a section that
// someone else changed meanwhile, so an older copy never undoes newer changes.
async function saveMinutes(base) {
 const fields={}, before={};
 for(const field of NOTE_FIELDS) if(JSON.stringify(detail.minutes[field]||[])!==JSON.stringify(base[field]||[])){fields[field]=detail.minutes[field]||[];before[field]=base[field]||[];}
 if(Object.keys(fields).length) detail=await api('/api/meetings/'+selected+'/edit',{minutes_fields:fields,minutes_base:before,minutes_revision:detail.minutes_revision});
 dirtyNotes=false; notesBase=null; lastFingerprint=JSON.stringify(detail); renderDetail();
}
function reviewBadge(item,busy) {
 const checked=item.review==='verified', badge=el('button','review-badge'+(checked?' verified':''),checked?'✓ Checked':'AI suggestion');
 badge.type='button'; badge.disabled=busy||notesEditing;
 badge.title=checked?'You checked this against the source. Click to undo.':'Not checked yet. Click after you check it against the source.';
 badge.onclick=()=>perform(async()=>{const base=structuredClone(detail.minutes),previous=item.review;item.review=checked?'ai':'verified';try{await saveMinutes(base);}catch(e){item.review=previous;throw e;}});
 return badge;
}
function noteSection(minutes,field,title,busy,hint) {
 const section=el('section','note-section'+(field==='observations'?' private-notes':''));
 section.append(el('h3','',title)); if(hint) section.append(el('p','hint',hint));
 const items=minutes[field]=minutes[field]||[];
 if(!notesEditing) {
  if(!items.length) section.append(el('p','empty-note','Nothing recorded.'));
  else { const list=el('ul','note-list'); items.forEach((item,index)=>{ const li=el('li','note-item'+(item.review==='verified'?' verified':'')), meta=el('div','note-meta'), decision=field==='decisions'&&detail.items?.[item.item_id];
   if(decision) meta.append(el('span','decision-status '+decision.status,DECISION_LABELS[decision.status]));
   meta.append(reviewBadge(item,busy),sourceBlock(item.evidence_timestamp)); li.append(linkedText(el('p','note-text'),item.text),meta);
   if(decision&&decision.links.length>1){const also=meetingChips(decision,detail.item_meetings,detail.id);also.prepend(el('span','hint','Also in'));li.append(also);}
   if(field==='decisions'&&item.link&&!item.item_id) li.append(linkCard({meeting_id:detail.id,kind:'decision',field,index,mention:item,text:item.text,candidates:item.link.candidates},detail.item_meetings,detail.items||{}));
   list.append(li); }); section.append(list); }
  return section;
 }
 const list=el('div','item-editors'), stamps=[...new Set(detail.transcript.map(s=>time(s.start)))];
 function draw() { list.replaceChildren(); items.forEach((item,index)=>{
  const row=el('div','task-editor'), area=el('textarea');
  area.value=item.text; area.rows=Math.max(2,Math.ceil(item.text.length/90)); area.disabled=busy; area.setAttribute('aria-label',title+' '+(index+1));
  area.oninput=()=>{item.text=area.value;markNotes();};
  const bottom=el('div','task-bottom'), select=el('select'), remove=el('button','quiet','Remove');
  select.setAttribute('aria-label','Source for '+title+' '+(index+1)); select.disabled=busy; select.append(option('No source moment',''),...stamps.map(stamp=>option(stamp,stamp)));
  select.value=item.evidence_timestamp||''; select.onchange=()=>{item.evidence_timestamp=select.value||null;markNotes();};
  remove.type='button'; remove.disabled=busy; remove.onclick=()=>{items.splice(index,1);markNotes();draw();};
  bottom.append(el('label','','Source'),select,remove); row.append(area,bottom); list.append(row); }); }
 draw();
 // A statement that you write yourself needs no AI check.
 const add=el('button','secondary','＋ Add'); add.type='button'; add.disabled=busy; add.onclick=()=>{items.push({text:'',evidence_timestamp:null,review:'verified'});markNotes();draw();list.lastElementChild?.querySelector('textarea').focus();};
 section.append(list,add); return section;
}
function changeText(field,item) { return field==='tasks'?[item.task,item.owner,item.deadline&&'said: '+item.deadline,item.due_date].filter(Boolean).join(' · '):item.text; }
async function reviewNotes(action,accept) {
 detail=await api('/api/meetings/'+selected+'/notes-review',{action,accept,revision:detail.minutes_proposal.revision});
 lastFingerprint=JSON.stringify(detail); if($('review-dialog').open) $('review-dialog').close(); renderDetail();
}
function openReview() {
 const proposal=detail.minutes_proposal, body=$('review-body'), choices=new Map(); body.replaceChildren(); clearError();
 for(const field of Object.keys(FIELD_TITLES)) {
  const list=proposal.changes.filter(change=>change.field===field); if(!list.length) continue;
  const section=el('section','review-section'); section.append(el('h3','',FIELD_TITLES[field]));
  for(const change of list) {
   const row=el('label','review-change '+change.kind), box=el('input'), main=el('div'), checked=change.current?.review==='verified';
   // Additions and AI-only edits are preselected; removals and edits of checked statements are not.
   box.type='checkbox'; box.checked=change.kind==='added'||change.kind==='changed'&&!checked; choices.set(change.id,box);
   main.append(el('span','change-kind',{added:'New',changed:'Changed',removed:'Not in the new notes'}[change.kind]+(checked?' · you checked the saved version':'')));
   if(change.current) main.append(el(change.kind==='removed'||change.kind==='changed'?'del':'p','',changeText(field,change.current)));
   if(change.proposed) main.append(el('ins','',changeText(field,change.proposed)));
   const stamp=(change.proposed||change.current).evidence_timestamp; if(stamp) main.append(sourceBlock(stamp));
   row.append(box,main); section.append(row);
  }
  body.append(section);
 }
 $('review-apply').onclick=()=>perform(async()=>{await reviewNotes('apply',[...choices].filter(([,box])=>box.checked).map(([id])=>id));toast('Notes updated · the previous version is kept in versions/');});
 $('review-discard').onclick=()=>perform(async()=>{if(!(await ask('Discard the new AI notes? Your saved notes stay as they are.',{ok:'Discard',danger:true})))return;await reviewNotes('discard',[]);toast('New AI notes discarded');});
 $('review-dialog').showModal();
}
$('review-close').onclick=()=>$('review-dialog').close();
function proposalBanner(busy) {
 const proposal=detail.minutes_proposal, count=proposal.changes.length, banner=el('div','notice proposal-banner');
 banner.append(el('span','',count?'New AI notes are ready · '+count+(count===1?' change':' changes')+' to review. Your saved notes have not changed.':'The new AI notes match your saved notes.'));
 const button=el('button','secondary',count?'Review changes':'Dismiss'); button.type='button'; button.disabled=busy||notesEditing;
 button.onclick=count?openReview:()=>perform(()=>reviewNotes('discard',[]));
 banner.append(button); return banner;
}
function taskRow(task,index,busy) {
 if(task.link&&!task.item_id) return linkCard({meeting_id:detail.id,kind:'task',field:'tasks',index,mention:task,text:task.task,candidates:task.link.candidates},detail.item_meetings,detail.items||{});
 // The persistent task holds the current state; the mention holds what this meeting said.
 const item=detail.items?.[task.item_id], current=item||{text:task.task,owner:task.owner,deadline:task.deadline,due_date:task.due_date,status:task.status};
 const today=state.task_summary?.today||new Date().toISOString().slice(0,10), [kind,label]=dueInfo(current,today);
 const row=el('div','tracked-task '+kind), done=el('input'); done.type='checkbox'; done.checked=current.status==='done'; done.disabled=busy; done.setAttribute('aria-label','Mark task as done');
 done.onchange=()=>perform(async()=>{const status=done.checked?'done':'open';if(item)await changeItem(item,{status});else{await api('/api/meetings/'+detail.id+'/task',{index,task:task.task,changes:{status}});await openMeeting(detail.id,true);}});
 const main=el('div','tracked-main'), meta=el('div','tracked-meta'), who=el('span','tracked-owner');
 who.append(speakerBadge(el('span'),current.owner||''),el('span','',current.owner||'No owner'));
 meta.append(reviewBadge(task,busy),who,el('span','due-label '+kind,current.due_date&&current.status!=='done'?label+' · '+current.due_date:label));
 if(current.deadline) meta.append(el('span','hint','Said: '+current.deadline));
 if(task.evidence_timestamp) meta.append(sourceBlock(task.evidence_timestamp));
 main.append(el('p','tracked-text',current.text||'Untitled task'));
 if(item&&item.text!==task.task) main.append(el('p','hint said-here','Said here: '+task.task));
 main.append(meta);
 if(item&&item.links.length>1) { const also=meetingChips(item,detail.item_meetings,detail.id); also.prepend(el('span','hint','Also in')); main.append(also,historyBlock(item,detail.item_meetings)); }
 row.append(done,main); return row;
}
function renderNotes(busy=false) {
 $('notes').replaceChildren();$('outcomes').replaceChildren();
 if(!detail.minutes||busy) notesEditing=false;
 for(const name of ['notes','outcomes']) { $('edit-'+name).hidden=notesEditing||!detail.minutes; $('edit-'+name).disabled=busy; $('save-'+name).hidden=$('cancel-'+name).hidden=!notesEditing; $('save-'+name).disabled=!dirtyNotes; }
 if(!detail.minutes) { for(const id of ['notes','outcomes']) $(id).append(el('p','empty-content','Generate meeting notes to see the decisions, tasks, unresolved questions and next steps.')); return; }
 const minutes=detail.minutes;
 if(detail.minutes_proposal) for(const id of ['notes','outcomes']) $(id).append(proposalBanner(busy));
 $('notes').append(noteSection(minutes,'summary','Summary',busy),noteSection(minutes,'needs_decision','Questions for your decision',busy));
 $('outcomes').append(noteSection(minutes,'decisions','Decisions',busy));
 const section=el('section','note-section');section.append(el('h3','','Tasks'));
 const taskList=el('div');section.append(taskList);
 function drawTasks() { taskList.replaceChildren(); minutes.tasks.forEach((task,index)=>{
  const box=el('div','task-editor'+(task.status==='done'?' done':''));const text=el('textarea');text.value=task.task;text.disabled=busy;text.setAttribute('aria-label','Task '+(index+1));text.oninput=()=>{task.task=text.value;markNotes();};box.append(text);
  const row=el('div','task-row');
  for(const [field,label] of [['owner','Owner'],['deadline','Deadline as said']]){const input=el('input');input.placeholder=label+' · not specified';input.setAttribute('aria-label',label+' for task '+(index+1));input.value=task[field]||'';input.disabled=busy;if(field==='owner'){input.setAttribute('list','known-speakers');input.classList.toggle('known-owner',!!knownSpeaker(input.value));}input.oninput=()=>{task[field]=input.value.trim()||null;if(field==='owner')input.classList.toggle('known-owner',!!knownSpeaker(input.value));markNotes();};row.append(input);}
  const due=el('input');due.type='date';due.value=task.due_date||'';due.disabled=busy;due.setAttribute('aria-label','Due date for task '+(index+1));due.oninput=()=>{task.due_date=due.value||null;markNotes();};row.append(due);box.append(row);
  const bottom=el('div','task-bottom');const doneLabel=el('label','checkbox');const done=el('input');done.type='checkbox';done.checked=task.status==='done';done.disabled=busy;done.onchange=()=>{task.status=done.checked?'done':'open';box.classList.toggle('done',done.checked);markNotes();};doneLabel.append(done,document.createTextNode(' Done'));
  bottom.append(doneLabel,el('label','','Source'));const select=el('select');select.setAttribute('aria-label','Evidence for task '+(index+1));select.disabled=busy;for(const stamp of [...new Set(detail.transcript.map(s=>time(s.start)))]){const option=el('option','',stamp);option.value=stamp;select.append(option);}select.value=task.evidence_timestamp;select.onchange=()=>{task.evidence_timestamp=select.value;markNotes();};
  const remove=el('button','quiet','Remove');remove.disabled=busy;remove.onclick=()=>{minutes.tasks.splice(index,1);markNotes();drawTasks();};bottom.append(select,remove);box.append(bottom);taskList.append(box);}); }
 if(!notesEditing) {
  if(!minutes.tasks.length) taskList.append(el('p','empty-note','No tasks.'));
  minutes.tasks.forEach((task,index)=>taskList.append(taskRow(task,index,busy)));
 } else {
  drawTasks();const add=el('button','secondary','＋ Add task');add.disabled=busy||!detail.transcript.length;add.onclick=()=>{minutes.tasks.push({task:'',owner:null,deadline:null,due_date:null,status:'open',evidence_timestamp:time(detail.transcript[0].start)});markNotes();drawTasks();};section.append(add);
 }
 $('outcomes').append(section,noteSection(minutes,'open_questions','Unresolved questions',busy),noteSection(minutes,'next_steps','Agreed next steps',busy));
 $('notes').append(
  noteSection(minutes,'observations','Private observations',busy,'Only for you. AI interpretation of risks, unrealistic promises and disagreement. Check it against the recording. Not included in the Markdown export.'));
}
function shortDuration(seconds) {
 seconds=Math.max(0,Math.round(seconds||0));const hours=Math.floor(seconds/3600),minutes=Math.floor(seconds/60)%60,rest=seconds%60;
 return (hours?hours+'h ':'')+(minutes||hours?minutes+'m ':'')+rest+'s';
}
function metric(label,value) { const box=el('div','metric');box.append(el('strong','',String(value)),el('span','',label));return box; }
function seekEvidence(item) {
 if(detail.files.includes('recording.wav')) { $('audio').currentTime=item.timestamp||0;$('audio').play().catch(e=>error(e.message));return; }
 switchTab('transcript');const row=$('transcript').children[item.segment_index];if(row){row.scrollIntoView({block:'center'});row.classList.add('evidence-highlight');setTimeout(()=>row.classList.remove('evidence-highlight'),1800);}
}
function speakerStats(target,rows,global=false) {
 target.replaceChildren();if(!rows.length){target.append(el('p','empty-content','No diarized speaker time is available. Imported transcripts only have topic and question analytics.'));return;}
 // Without diarized audio every talk-time number is zero; show only what is known.
 const timed=rows.some(row=>row.talk_seconds>0);
 if(!timed)target.append(el('p','hint','No talk time. Talk time needs a recording with speaker diarization; imported transcripts have none.'));
 for(const row of rows) {
  const box=el('div','speaker-stat'),heading=el('div','speaker-stat-heading'),name=el('div','tracked-owner');
  name.append(speakerBadge(el('span'),row.speaker),el('strong','',row.speaker));if(row.meeting_title)name.append(el('span','hint speaker-meeting','· '+row.meeting_title));heading.append(name);box.append(heading);
  if(timed){heading.append(el('span','',shortDuration(row.talk_seconds)+' · '+row.talk_percent+'%'));const bar=el('div','talk-bar'),fill=el('span');fill.style.width=Math.max(0,Math.min(100,row.talk_percent))+'%';bar.append(fill);box.append(bar);}
  const facts=timed?['Turns: '+row.turns,'Longest turn: '+shortDuration(row.longest_monologue_seconds),'Average turn: '+shortDuration(row.average_turn_seconds),'Questions: '+row.questions]:['Questions: '+row.questions];
  if(global)facts.push('Not marked as answered: '+row.unanswered_questions,'Meetings: '+row.meetings);
  box.append(el('p','speaker-stat-meta',facts.join(' · ')));target.append(box);
 }
}
function renderMeetingAnalytics(busy=false) {
 const data=detail.analytics,target=$('meeting-analytics-content');target.replaceChildren();
 $('reanalyze').disabled=busy||!detail.transcript.length;
 $('diarization-status').hidden=!detail.diarization_error;$('diarization-status').textContent=detail.diarization_error?'Speaker diarization unavailable · '+detail.diarization_error:'';
 $('meeting-analytics-error').hidden=!detail.analytics_error;$('meeting-analytics-error').textContent=detail.analytics_error?'Some analytics need attention · '+detail.analytics_error:'';
 if(!data){target.append(el('p','empty-content',detail.transcript.length?'Choose Reanalyze to build talk-time, topic and question analytics.':'Transcribe or import a meeting to build conversation analytics.'));return;}
 const speakers=el('section','analytics-section'),speakerRows=el('div');speakers.append(el('h3','','Talk time'));if(data.total_speech_seconds)speakers.append(el('p','hint',shortDuration(data.total_speech_seconds)+' of diarized speech. Silence is excluded.'));speakers.append(speakerRows);speakerStats(speakerRows,data.speakers||[]);target.append(speakers);
 const topics=el('section','analytics-section');topics.append(el('h3','','Topic trackers'));
 if(!(data.topics||[]).length){const configure=el('button','secondary','Configure topic trackers');configure.onclick=()=>openSettings('trackers');topics.append(el('p','hint','No topic trackers are configured.'),configure);}
 for(const topic of data.topics||[]) {
  const box=el('div','topic-result'),heading=el('div','speaker-stat-heading');heading.append(el('strong','',topic.name),el('span','',topic.match_count+(topic.match_count===1?' hit':' hits')));box.append(heading);
  for(const hit of topic.matches||[]) {const evidence=el('div','evidence-row'),seek=el('button','quiet evidence-time',time(hit.timestamp)+' ▶');seek.onclick=()=>seekEvidence(hit);const text=el('p','',hit.text);const meta=el('small','',(hit.speaker||'Unknown speaker')+(hit.semantic?' · Local AI semantic match':' · '+(hit.phrases||[]).join(', ')));const main=el('div');main.append(text,meta);evidence.append(seek,main);box.append(evidence);}
  topics.append(box);
 }
 target.append(topics);
 const all=data.questions||[],questions=el('section','analytics-section');
 questions.append(el('h3','','Questions'),el('p','hint',all.length+' detected from wording · '+all.filter(q=>!q.answered).length+' not marked as answered. The app does not detect answers. Tick a question when it was answered.'));
 if(!all.length)questions.append(el('p','empty-content','No questions detected.'));
 else {
  const filters=el('div','segmented question-filters');filters.setAttribute('role','group');filters.setAttribute('aria-label','Filter questions');
  for(const [key,label] of [['open','Not answered'],['answered','Answered'],['all','All']]){const button=el('button',key===questionFilter?'selected':'',label);button.type='button';button.onclick=()=>{questionFilter=key;questionLimit=10;renderMeetingAnalytics(busy);};filters.append(button);}
  questions.append(filters);
 }
 const shown=all.filter(q=>questionFilter==='all'||(questionFilter==='answered')===!!q.answered);
 if(all.length&&!shown.length)questions.append(el('p','empty-content','No questions match this filter.'));
 for(const question of shown.slice(0,questionLimit)) {
  const row=el('div','question-row'+(question.answered?' answered':'')),toggle=el('input');toggle.type='checkbox';toggle.checked=question.answered;toggle.disabled=busy;toggle.setAttribute('aria-label','Mark question as answered');
  toggle.onchange=()=>perform(async()=>{const updated=await api('/api/meetings/'+detail.id+'/question',{id:question.id,text:question.text,answered:toggle.checked});detail.analytics=updated;lastFingerprint=JSON.stringify(detail);renderMeetingAnalytics(false);});
  const main=el('div'),text=el('p','',question.text),meta=el('div','tracked-meta'),seek=el('button','quiet tracked-source',time(question.timestamp)+' ▶');seek.onclick=()=>seekEvidence(question);meta.append(el('span','',question.speaker||'Unknown speaker'),seek);main.append(text,meta);row.append(toggle,main);questions.append(row);
 }
 if(shown.length>questionLimit){const more=el('button','secondary','Show all '+shown.length+' questions');more.type='button';more.onclick=()=>{questionLimit=Infinity;renderMeetingAnalytics(busy);};questions.append(more);}
 target.append(questions);
}
async function loadAnalytics() {
 const params=new URLSearchParams();for(const [key,id] of [['from','analytics-from'],['to','analytics-to'],['speaker','analytics-speaker'],['topic','analytics-topic']]){const value=$(id).value;if(value)params.set(key,value);}
 analyticsData=await api('/api/analytics'+(params.size?'?'+params:''));renderGlobalAnalytics();
}
function renderGlobalAnalytics() {
 const data=analyticsData;if(!data)return;
 for(const [id,values,placeholder] of [['analytics-speaker',data.available_speakers,'All speakers'],['analytics-topic',data.available_topics,'All topics']]) {const select=$(id),current=select.value;select.replaceChildren(option(placeholder,''),...values.map(value=>option(value,value)));select.value=[...select.options].some(option=>option.value===current)?current:'';}
 const speech=data.total_speech_seconds?shortDuration(data.total_speech_seconds):'—';
 $('analytics-summary').textContent=data.meeting_count+(data.meeting_count===1?' meeting':' meetings')+(data.total_speech_seconds?' · '+speech+' diarized speech':'')+' · '+data.questions+' questions · '+data.unanswered_questions+' not marked as answered';
 $('analytics-overview').replaceChildren(metric('Meetings',data.meeting_count),metric('Diarized speech',speech),metric('Questions',data.questions),metric('Not marked as answered',data.unanswered_questions));
 speakerStats($('analytics-speakers'),data.speakers,true);
 $('analytics-topics').replaceChildren();if(!data.topics.length)$('analytics-topics').append(el('p','empty-content','No topic hits match these filters.'));
 for(const topic of data.topics){const box=el('div','metric');box.append(el('strong','',topic.matches),el('span','',topic.name+' · '+topic.meetings+' meetings'));$('analytics-topics').append(box);}
 $('analytics-meetings').replaceChildren();if(!data.meetings.length)$('analytics-meetings').append(el('p','empty-content','No generated analytics match these filters.'));
 for(const meeting of data.meetings){const row=el('div','analytics-meeting'),button=el('button','quiet tracked-source',meeting.title);button.onclick=()=>perform(async()=>{await openMeeting(meeting.id);switchTab('analytics');});row.append(button,el('span','',date(meeting.date)),el('span','',meeting.talk_seconds?shortDuration(meeting.talk_seconds):'No talk time'),el('span','',meeting.questions+' questions · '+meeting.topic_matches+' topic hits'));$('analytics-meetings').append(row);}
}
function renderTrackers() {
 const target=$('tracker-list');target.replaceChildren();if(!trackersData.length)target.append(el('p','empty-content','No topic trackers yet. Add topics such as Бюджет, Продажби or Риск.'));
 trackersData.forEach((tracker,index)=>{const box=el('fieldset','tracker-editor'),name=el('input');name.value=tracker.name;name.placeholder='Topic name, for example Бюджет';name.maxLength=100;name.setAttribute('aria-label','Topic name '+(index+1));name.oninput=()=>tracker.name=name.value;
  const phrases=el('textarea');phrases.value=(tracker.phrases||[]).join('\n');phrases.rows=3;phrases.placeholder='One phrase per line\nбюджет\nразходи';phrases.setAttribute('aria-label','Phrases for topic '+(index+1));phrases.oninput=()=>tracker.phrases=phrases.value.split('\n').map(value=>value.trim()).filter(Boolean);
  const label=el('label','checkbox'),semantic=el('input');semantic.type='checkbox';semantic.checked=!!tracker.semantic_matching;semantic.onchange=()=>tracker.semantic_matching=semantic.checked;label.append(semantic,document.createTextNode(' Also use Local AI semantic matching'));
  const remove=el('button','quiet danger-text','Remove topic');remove.type='button';remove.onclick=()=>{trackersData.splice(index,1);renderTrackers();};box.append(name,phrases,label,remove);target.append(box);});
}
async function saveTrackers() {
 for(const tracker of trackersData)if(!tracker.name.trim()||!tracker.phrases.length)throw new Error('Every topic needs a name and at least one phrase.');
 const result=await api('/api/trackers',{trackers:trackersData});trackersData=result.trackers;state.trackers=result.trackers;renderTrackers();toast('Topic trackers saved · reanalyze meetings to refresh them');
}
function settingsFields() { $('local-model-field').hidden=false;$('cloud-model-field').hidden=$('provider').value!=='openai';$('notes-model-field').hidden=$('summarizer').value!=='openai'&&$('transcript-correction').value!=='openai';$('title-model-field').hidden=$('title-provider').value!=='openai';$('settings-privacy').textContent=privacy({transcription:$('provider').value,summarizer:$('summarizer').value,transcript_correction:$('transcript-correction').value,auto_title:$('auto-title').checked,title_provider:$('title-provider').value,calendar_enabled:$('calendar-enabled').checked});$('title-privacy').textContent=$('title-provider').value==='openai'?'Transcript excerpts are sent to OpenAI for title generation.':'Uses the shared Local AI endpoint and model above.'; }
function fileSize(bytes) { return bytes>=1e9?(bytes/1e9).toFixed(1)+' GB':bytes>=1e6?Math.round(bytes/1e6)+' MB':Math.max(1,Math.round(bytes/1e3))+' KB'; }
function renderBackups(data) {
 $('backup-folder').textContent=data.folder; const list=$('backup-list'); list.replaceChildren();
 if(!data.archives.length) list.append(el('p','empty-content','No archives yet.'));
 for(const archive of data.archives) {
  const row=el('div','backup-row'), main=el('div'), actions=el('div','backup-actions');
  main.append(el('strong','',archive.created?new Date(archive.created).toLocaleString():archive.name),
   el('span','backup-meta '+(archive.verified?'ok':'bad'),fileSize(archive.bytes)+' · '+(archive.verified?'✓ Restore test passed · '+archive.meetings+(archive.meetings===1?' meeting':' meetings'):'✗ '+(archive.error||'Restore test failed'))));
  const reveal=el('button','quiet','Show in Finder'); reveal.type='button'; reveal.onclick=()=>perform(()=>api('/api/backups/reveal',{name:archive.name}));
  const restore=el('button','secondary','Restore'); restore.type='button'; restore.disabled=!archive.verified;
  restore.onclick=()=>perform(async()=>{if(!(await ask('Restore meetings from this archive?\n\nMeetings that this library does not have are added. Existing meetings and your settings do not change.',{ok:'Restore'})))return;
   restore.disabled=true;$('backup-status').textContent='Restoring and checking…';
   try{const result=await api('/api/backups/restore',{name:archive.name});renderBackups(result);$('backup-status').textContent=result.restored.length+' meetings restored · '+result.skipped.length+' already in the library';state=await api('/api/state');renderState();}
   finally{restore.disabled=false;}});
  actions.append(reveal,restore); row.append(main,actions); list.append(row);
 }
}
async function loadBackups() { renderBackups(await api('/api/backups')); }
$('backup-now').onclick=()=>perform(async()=>{const button=$('backup-now');button.disabled=true;$('backup-status').textContent='Archiving and running the restore test… Large libraries take a few minutes.';
 try{const result=await api('/api/backups/create',{});renderBackups(result);$('backup-status').textContent='Archive created and verified · '+result.created.meetings+' meetings'+(result.created.skipped_meetings?.length?' · '+result.created.skipped_meetings.length+' active or processing meetings left out':'');}
 catch(e){$('backup-status').textContent='';throw e;}finally{button.disabled=false;}});
function showSettingsTab(name) {
 settingsTab=name; if(name==='backup') perform(loadBackups); if(name==='projects') renderProjectSettings();
 for(const tab of document.querySelectorAll('.settings-tabs button')) { const yes=tab.dataset.tab===name; tab.classList.toggle('selected',yes); tab.setAttribute('aria-selected',String(yes)); }
 for(const panel of document.querySelectorAll('.settings-panel')) panel.hidden=panel.dataset.tab!==name;
 document.querySelector('.settings-body').scrollTop=0;
}
function inlineMarkdown(text) { return text.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/`([^`]+)`/g,'<code>$1</code>').replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>').replace(/(^|[^*])\*([^*\s][^*]*)\*/g,'$1<em>$2</em>'); }
function renderMarkdown(source) {
 const lines=source.replace(/\r\n?/g,'\n').split('\n'), out=[]; let i=0;
 const cells=line=>line.trim().replace(/^\||\|$/g,'').split('|').map(cell=>inlineMarkdown(cell.trim()));
 while(i<lines.length) {
  const line=lines[i];
  if(!line.trim()) { i++; continue; }
  if(line.startsWith('```')) { const code=[]; i++; while(i<lines.length&&!lines[i].startsWith('```')) code.push(lines[i++]); i++; out.push('<pre><code>'+inlineMarkdown(code.join('\n')).replace(/<\/?(code|strong|em)>/g,'')+'</code></pre>'); continue; }
  const heading=line.match(/^(#{1,6})\s+(.*)$/);
  if(heading) { const level=heading[1].length; out.push(`<h${level}>${inlineMarkdown(heading[2])}</h${level}>`); i++; continue; }
  if(/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) { out.push('<hr>'); i++; continue; }
  if(line.trim().startsWith('|')&&/^\s*\|?[\s:|-]+\|?\s*$/.test(lines[i+1]||'')&&lines[i+1].includes('-')) {
   const head=cells(line); i+=2; const rows=[]; while(i<lines.length&&lines[i].trim().startsWith('|')) rows.push(cells(lines[i++]));
   out.push('<div class="table-wrap"><table><thead><tr>'+head.map(c=>`<th>${c}</th>`).join('')+'</tr></thead><tbody>'+rows.map(r=>'<tr>'+r.map(c=>`<td>${c}</td>`).join('')+'</tr>').join('')+'</tbody></table></div>'); continue;
  }
  const item=/^\s*(?:[-*+]|(\d+)[.)])\s+(.*)$/;
  if(item.test(line)) { const ordered=!!line.match(item)[1], items=[]; while(i<lines.length&&item.test(lines[i])) items.push('<li>'+inlineMarkdown(lines[i++].match(item)[2])+'</li>'); const tag=ordered?'ol':'ul'; out.push(`<${tag}>${items.join('')}</${tag}>`); continue; }
  if(line.startsWith('>')) { const quote=[]; while(i<lines.length&&lines[i].startsWith('>')) quote.push(inlineMarkdown(lines[i++].replace(/^>\s?/,''))); out.push('<blockquote>'+quote.join('<br>')+'</blockquote>'); continue; }
  const para=[]; while(i<lines.length&&lines[i].trim()&&!/^(#{1,6}\s|```|>|\s*(?:[-*+]|\d+[.)])\s|\s*\|)/.test(lines[i])) para.push(inlineMarkdown(lines[i++]));
  if(!para.length) para.push(inlineMarkdown(lines[i++]));
  out.push('<p>'+para.join('<br>')+'</p>');
 }
 return out.join('');
}
async function openViewer(id,name) { const url='/files/'+id+'/'+name; const response=await fetch(url); if(!response.ok) throw new Error('Could not open '+name); $('viewer-title').textContent=name; $('viewer-download').href=url; $('viewer-download').download=name; $('viewer-body').innerHTML=renderMarkdown(await response.text()); $('viewer-body').scrollTop=0; $('viewer-dialog').showModal(); }
$('viewer-close').onclick=()=>$('viewer-dialog').close();
$('viewer-dialog').onclick=event=>{if(event.target===$('viewer-dialog'))$('viewer-dialog').close();};
function openSettings(tab) { if(!state)return; clearError(); const s=state.settings;$('local-ai-base-url').value=s.local_ai_base_url;$('local-ai-model').value=s.local_ai_model;$('local-ai-format').value=s.local_ai_format;$('local-ai-reasoning').value=s.local_ai_reasoning;$('local-ai-max-tokens').value=s.local_ai_max_tokens;$('local-ai-status').textContent='';localModels=[];renderLocalModels();$('provider').value=s.transcription;$('local-model').value=s.local_model;$('audio-preparation').value=s.audio_preparation||'off';$('whisper-vad').checked=s.whisper_vad!==false;$('whisper-vocabulary').value=s.whisper_vocabulary||'';$('cloud-model').value=s.cloud_model;$('summarizer').value=s.summarizer;$('transcript-correction').value=s.transcript_correction||'none';$('llm-model').value=s.llm_model;$('auto-process').checked=s.auto_process;$('live-enabled').checked=s.live_transcription!==false;$('diarization-enabled').checked=s.diarization_enabled!==false;$('diarization-runtime').textContent=state.diarization?.message||'Speaker separation is checked after recording.';$('auto-title').checked=s.auto_title!==false;$('title-provider').value=s.title_provider||'local';$('title-model').value=s.title_model||'gpt-4.1-mini';$('calendar-enabled').checked=!!s.calendar_enabled;$('calendar-id').replaceChildren();const initialCalendar=el('option','',s.calendar_name||'Choose a calendar…');initialCalendar.value=s.calendar_id||'';$('calendar-id').append(initialCalendar);$('api-key').value='';$('forget-key').disabled=!state.api_key_configured;$('key-state').textContent=state.api_key_configured?'· configured':'';settingsFields();renderGoogleStatus();renderSpeakerSettings();trackersData=JSON.parse(JSON.stringify(state.trackers||[]));renderTrackers();$('new-speaker').value='';showSettingsTab(typeof tab==='string'?tab:settingsTab);$('settings-dialog').showModal();if(calendarConnected())perform(loadCalendars); }
function daysBetween(from,to) { return Math.round((Date.parse(to)-Date.parse(from))/86400000); }
function dueInfo(task,today) {
 if(task.status==='done') return ['done','Done'];
 if(!task.due_date) return ['undated','No date'];
 const days=daysBetween(today,task.due_date);
 if(days<0) return ['overdue','Overdue · '+(-days)+(days===-1?' day':' days')];
 if(days===0) return ['today','Due today'];
 return [days<=7?'soon':'later','Due in '+days+(days===1?' day':' days')];
}
let itemKind='task', itemsData={items:[],pending:[],meetings:{}};
const STATUS_FILTERS={task:[['open','Open'],['overdue','Overdue'],['done','Done'],['all','All'],['snoozed','Snoozed'],['dismissed','Dismissed']],decision:[['current','In force'],['proposed','Proposed'],['accepted','Accepted'],['superseded','Replaced'],['all','All'],['snoozed','Snoozed'],['dismissed','Dismissed']]};
const statusFilter={task:'open',decision:'current'};
const DECISION_LABELS={proposed:'Proposed',accepted:'Accepted',superseded:'Replaced'};
const FIELD_LABELS={text:'text',owner:'owner',deadline:'deadline as said',due_date:'due date',status:'status'};
const EVENT_LABELS={created:'Created in',discussed:'Discussed in',duplicate:'Mentioned again in',changed:'Changed',removed:'Removed from',merged:'Merged with another item',superseded:'Replaced in',detached:'Waits for the new notes of'};
function meetingLabel(id,meetings) { const meeting=meetings?.[id]; return meeting?withDate(meeting.title,meeting.date):'a deleted meeting'; }
function meetingChips(item,meetings,except) {
 const box=el('div','item-meetings');
 for(const link of item.links.filter(link=>link.meeting_id!==except).sort((a,b)=>(meetings[a.meeting_id]?.date||'').localeCompare(meetings[b.meeting_id]?.date||''))) {
  const chip=el('button','meeting-chip','↗ '+meetingLabel(link.meeting_id,meetings)+(link.evidence_timestamp?' · '+link.evidence_timestamp:'')); chip.type='button'; chip.title='Open this meeting';
  chip.onclick=()=>perform(async()=>{await openMeeting(link.meeting_id);switchTab('outcomes');}); box.append(chip);
 }
 return box;
}
function historyBlock(item,meetings) {
 const box=el('details','item-history'), list=el('ol'); box.append(el('summary','','History · '+item.history.length));
 for(const event of [...item.history].reverse()) {
  const changes=Object.entries(event.changes||{}).map(([name,[from,to]])=>(FIELD_LABELS[name]||name)+': '+(from??'—')+' → '+(to??'—')).join(' · ');
  // A meeting event belongs to the meeting's date, not to the moment the app processed it.
  const when=event.meeting_id&&meetings?.[event.meeting_id]?meetings[event.meeting_id].date:event.at;
  const entry=el('li'); entry.append(el('span','history-date',new Date(when).toLocaleDateString(undefined,{day:'numeric',month:'short'})),
   el('span','',(EVENT_LABELS[event.event]||event.event)+(event.meeting_id?' '+meetingLabel(event.meeting_id,meetings):'')+(changes?' · '+changes:'')+(event.by==='user'?' · by you':' · AI')));
  list.append(entry);
 }
 box.append(list); return box;
}
async function refreshAfterItemChange() { lastTasks=''; if(view==='tasks') await loadTasks(); else if(view==='prepare') await loadPrepare(); else if(view==='detail'&&selected) await openMeeting(selected,true); state=await api('/api/state'); renderState(); }
async function changeItem(item,changes,finishEdit=false) { await api('/api/items/'+item.id,{text:item.text,revision:item.revision,changes});if(finishEdit)setItemEditing(false);await refreshAfterItemChange(); }
// A new mention that looks like an existing item: the person decides, nothing is linked before that.
function linkCard(entry,meetings,itemsById) {
 const kind=entry.kind, mention=entry.mention, card=el('div','link-card'), head=el('div','link-head');
 head.append(el('span','change-kind','Is this an existing '+kind+'?'),el('span','hint','From '+meetingLabel(entry.meeting_id,meetings)));
 const details=kind==='task'?[mention.owner,mention.deadline&&'said: '+mention.deadline,mention.due_date].filter(Boolean):[];
 card.append(head,el('p','link-text',entry.text+(details.length?' · '+details.join(' · '):'')));
 const resolve=(action,itemId)=>perform(async()=>{await api('/api/meetings/'+entry.meeting_id+'/link',{field:entry.field,index:entry.index,text:entry.text,action,item_id:itemId});await refreshAfterItemChange();toast(action==='new'?'Added as a new '+kind:'Linked · the history shows this meeting');});
 for(const candidate of entry.candidates) {
  const item=itemsById[candidate.item_id]; if(!item) continue;
  const row=el('div','link-candidate'), main=el('div'), actions=el('div','link-actions');
  const facts=kind==='task'?[item.status==='done'?'Done':'Open',item.owner,item.due_date&&'due '+item.due_date]:[DECISION_LABELS[item.status]];
  main.append(el('p','',item.text),el('span','hint',facts.filter(Boolean).join(' · ')+' · '+Math.round(candidate.score*100)+'% similar'),meetingChips(item,meetings));
  const choices=kind==='task'?[['same','Same task · update','primary','Links this meeting. Owner, deadline and due date from the AI fill fields that you did not edit. The status stays.'],['duplicate','Duplicate','secondary','Links this meeting and changes nothing.']]
   :[['same','Same decision','primary','Links this meeting to the decision.'],['replaces','Replaces it','secondary','Saves this as a new decision; the older one becomes replaced.']];
  for(const [action,label,style,title] of choices){const button=el('button',style,label);button.type='button';button.title=title;button.onclick=()=>resolve(action,item.id);actions.append(button);}
  row.append(main,actions); card.append(row);
 }
 const fresh=el('button','quiet','No, it is a new '+kind); fresh.type='button'; fresh.onclick=()=>resolve('new'); card.append(fresh);
 return card;
}
function evidenceBlock(item,meetings){
 const snapshots=item.evidence||[],graphEvidence=(itemsData.graph?.source_evidence||[]).filter(e=>(item.source_evidence||[]).includes(e.id)),box=el('details','item-history');box.append(el('summary','','Sources · '+(snapshots.length+graphEvidence.length)));
 for(const evidence of graphEvidence){const row=el('div','work-evidence'),source=itemsData.graph.sources.find(s=>s.id===evidence.source_id);row.append(el('small','hint','Saved source quote · '+(source?source.provider+' · '+source.external_id:'Unavailable source')+' · revision '+evidence.source_revision.slice(0,12)),el('p','',evidence.quote));box.append(row);}
 for(const evidence of [...snapshots].reverse()){
  const row=el('div','work-evidence'),main=el('div');main.append(el('small','hint',evidence.quote_kind==='meeting_note'?'Saved meeting note · historical wording':'Saved item text · source quote unavailable'),el('p','',evidence.quote));
  const source=el('button','quiet','↗ '+meetingLabel(evidence.source_id,meetings)+(evidence.timestamp?' · '+evidence.timestamp:''));source.type='button';source.disabled=!meetings[evidence.source_id];
  source.onclick=()=>perform(async()=>{await openMeeting(evidence.source_id);switchTab('outcomes');if(evidence.timestamp&&detail.files.includes('recording.wav'))$('audio').currentTime=evidence.timestamp.split(':').reduce((n,v)=>n*60+Number(v),0);toast('Showing the current meeting. This quote is a saved note snapshot.');});
  row.append(main,source);box.append(row);
 }
 return box;
}
function setItemEditing(active,row=null){
 itemEditing=active;
 for(const other of $('task-list').children)other.inert=active&&other!==row;
 for(const node of [...document.querySelectorAll('[data-kind]'),...$('status-filter').querySelectorAll('button'),$('work-project'),$('task-owner')])node.disabled=active;
 if(active&&row)for(const node of row.querySelectorAll('input,button'))node.disabled=true;
}
function itemActions(item,row) {
 const actions=el('div','tracked-actions'), edit=el('button','quiet','Edit'), merge=el('button','quiet','Merge…'), remove=el('button','quiet danger-text','Delete');
 const main=row.querySelector('.tracked-main'), text=main.querySelector('.tracked-text');
 edit.onclick=()=>{if(itemEditing)return;setItemEditing(true,row);const box=el('textarea','tracked-edit'),bar=el('div','tracked-edit-bar'),save=el('button','primary','Save'),cancel=el('button','secondary','Cancel');let owner=null;
  box.value=item.text;box.setAttribute('aria-label','Text');bar.append(save,cancel);
  if(item.kind==='task'){owner=el('input','tracked-owner-input');owner.value=item.owner||'';owner.placeholder='Owner';owner.setAttribute('list','known-speakers');owner.setAttribute('aria-label','Owner');bar.prepend(owner);}
  const close=()=>{setItemEditing(false);box.replaceWith(text);bar.remove();actions.hidden=false;lastTasks='';perform(loadTasks);};
  save.onclick=()=>{const value=box.value.trim();if(!value){box.focus();return;}const changes={};if(value!==item.text)changes.text=value;if(owner&&(owner.value.trim()||null)!==item.owner)changes.owner=owner.value.trim()||null;if(!Object.keys(changes).length){close();return;}save.disabled=true;perform(()=>changeItem(item,changes,true)).finally(()=>save.disabled=false);};
  cancel.onclick=close;box.onkeydown=event=>{if(event.key==='Escape'){event.stopPropagation();close();}if(event.key==='Enter'&&(event.metaKey||event.ctrlKey))save.click();};
  text.replaceWith(box);box.after(bar);actions.hidden=true;box.focus();};
 merge.onclick=()=>{const others=itemsData.items.filter(other=>other.kind===item.kind&&other.id!==item.id);if(!others.length){toast('There is no other '+item.kind+' to merge with');return;}
  if(itemEditing)return;setItemEditing(true,row);
  const bar=el('div','tracked-edit-bar'),select=el('select'),go=el('button','primary','Merge'),cancel=el('button','secondary','Cancel');
  select.setAttribute('aria-label','Merge into');select.append(option('Same as…',''),...others.map(other=>option(other.text.slice(0,100),other.id)));
  go.onclick=()=>{if(!select.value)return;perform(async()=>{await api('/api/items/'+item.id+'/merge',{into:select.value,revision:item.revision,into_revision:itemsData.items.find(other=>other.id===select.value)?.revision});setItemEditing(false);await refreshAfterItemChange();toast('Merged · both histories are kept');});};
  cancel.onclick=()=>{setItemEditing(false);bar.remove();actions.hidden=false;lastTasks='';perform(loadTasks);};bar.append(select,go,cancel);main.append(bar);actions.hidden=true;};
 remove.onclick=()=>perform(async()=>{if(!(await ask('Delete this '+item.kind+' everywhere?\n\n'+item.text+'\n\nIt is removed from the notes of '+item.links.length+(item.links.length===1?' meeting.':' meetings.'),{ok:'Delete',danger:true})))return;await api('/api/items/'+item.id+'/delete',{text:item.text,revision:item.revision});await refreshAfterItemChange();toast('Deleted');});
 const snooze=el('button','quiet',item.snoozed_until?'Unsnooze':'Snooze'),dismiss=el('button','quiet',item.dismissed?'Restore to My Work':'Dismiss');
 snooze.onclick=()=>perform(async()=>{if(item.snoozed_until){await changeItem(item,{snoozed_until:null});return;}const day=new Date();day.setDate(day.getDate()+1);const value=await ask('Snooze in My Work until YYYY-MM-DD. The item status and its sources stay unchanged.',{ok:'Snooze',value:day.toLocaleDateString('en-CA')});if(value!==null)await changeItem(item,{snoozed_until:value});});
 dismiss.onclick=()=>perform(()=>changeItem(item,{dismissed:!item.dismissed}));
 actions.append(edit,snooze,dismiss,merge,remove); return actions;
}
function globalTaskRow(item,today) {
 const [kind,label]=dueInfo(item,today), row=el('div','tracked-task '+kind), done=el('input'), main=el('div','tracked-main'), meta=el('div','tracked-meta'), who=el('span','tracked-owner');
 done.type='checkbox';done.checked=item.status==='done';done.setAttribute('aria-label','Mark task as done');done.onchange=()=>perform(()=>changeItem(item,{status:done.checked?'done':'open'}));
 who.append(speakerBadge(el('span'),item.owner||''),el('span','',item.owner||'No owner'));
 const due=el('input');due.type='date';due.value=item.due_date||'';due.setAttribute('aria-label','Due date');due.onchange=()=>perform(()=>changeItem(item,{due_date:due.value||null}));
 meta.append(who,el('span','due-label '+kind,label),due); if(item.deadline) meta.append(el('span','hint','Said: '+item.deadline));
 main.append(el('p','tracked-text',item.text),meta,meetingChips(item,itemsData.meetings),historyBlock(item,itemsData.meetings),evidenceBlock(item,itemsData.meetings));
 row.append(done,main); row.append(itemActions(item,row)); return row;
}
function decisionRow(item,byId) {
 const row=el('div','tracked-task decision '+item.status), main=el('div','tracked-main'), meta=el('div','tracked-meta');
 meta.append(el('span','decision-status '+item.status,DECISION_LABELS[item.status]));
 if(item.superseded_by&&byId[item.superseded_by]) meta.append(el('span','hint','Replaced by: '+byId[item.superseded_by].text));
 for(const id of item.supersedes||[]) if(byId[id]) meta.append(el('span','hint','Replaces: '+byId[id].text));
 const next={proposed:['accepted','Accept'],accepted:['proposed','Mark as proposed'],superseded:[item.superseded_previous_status==='accepted'?'accepted':'proposed',item.superseded_previous_status==='accepted'?'Restore as accepted':'Restore as proposed']}[item.status];
 const change=el('button','secondary small-action',next[1]);change.type='button';change.onclick=()=>perform(()=>changeItem(item,{status:next[0]}));meta.append(change);
 main.append(el('p','tracked-text',item.text),meta,meetingChips(item,itemsData.meetings),historyBlock(item,itemsData.meetings),evidenceBlock(item,itemsData.meetings));
 row.append(el('span'),main); row.append(itemActions(item,row)); return row;
}
async function loadTasks() { if(itemEditing)return;const fresh=await api('/api/items'); if(itemEditing)return;const signature=JSON.stringify(fresh); if(signature===lastTasks) return; lastTasks=signature; itemsData=fresh; renderTasks(); }
let mailView='needs_reply',mailTimer=null,mailAIWasRunning=false;
async function loadMail(){
 const status=await api('/api/gmail'),ai=await api('/api/gmail/ai');
 $('gmail-ai-status').textContent='Email AI: '+ai.status+(ai.endpoint?' · '+ai.endpoint+' · '+ai.model:'')+(ai.proposal_ids?' · '+ai.proposal_ids.length+' proposals':'')+(ai.error?' · '+ai.error:'');
 $('gmail-ai-cancel').disabled=!ai.running;
 if(mailAIWasRunning&&!ai.running){lastTasks='';await loadTasks();if(ai.proposal_ids?.length)$('work-suggested').open=true;}
 mailAIWasRunning=ai.running;
 $('gmail-status').textContent=(status.connected?'Connected as '+status.account:'Gmail permission not connected')+' · '+status.count+' cached threads · '+status.job.status+(status.sync.last_sync?' · Last page saved '+new Date(status.sync.last_sync*1000).toLocaleString():'')+(status.sync.limited?' · Initial 200-thread limit reached':'')+(status.job.error?' · '+status.job.error:'');
 $('gmail-sync').disabled=!status.connected||status.job.running;$('gmail-cancel').disabled=!status.job.running;
 const accounts=$('gmail-cache-account'),selected=accounts.value;accounts.replaceChildren(...status.cached_accounts.map(a=>option(a,a)));if(status.cached_accounts.includes(selected))accounts.value=selected;
 $('gmail-clear').disabled=status.job.running||!status.cached_accounts.length;
 $('gmail-filters').replaceChildren();
 for(const [value,label] of [['needs_reply','Needs reply'],['waiting','Waiting for'],['all','All cached']]){const b=el('button',mailView===value?'selected':'',label);b.onclick=()=>perform(async()=>{mailView=value;$('gmail-detail').replaceChildren();await loadMail();});$('gmail-filters').append(b);}
 const list=$('gmail-threads');list.replaceChildren();
 if(status.connected){const threads=await api('/api/gmail/threads?view='+mailView);for(const thread of threads){const b=el('button','mail-thread',thread.subject+' · '+thread.sender+' · '+new Date(thread.date).toLocaleDateString());b.onclick=()=>perform(()=>openMail(thread.id));list.append(b);}if(!threads.length)list.append(el('p','hint','No cached threads in this view. Choose Sync / Continue to fetch a page.'));}
 if(mailTimer)clearTimeout(mailTimer);mailTimer=null;
 if((status.job.running||ai.running)&&view==='tasks'&&$('gmail-panel').open)mailTimer=setTimeout(()=>perform(loadMail),2000);
}
async function openMail(key){
 const thread=await api('/api/gmail/thread?id='+encodeURIComponent(key)),box=$('gmail-detail');box.replaceChildren(el('h3','',thread.subject),el('p','hint','Cached '+new Date(thread.fetched_at*1000).toLocaleString()+(thread.partial?' · Only the latest 100 messages are included':'')));
 for(const message of thread.messages){const row=el('details','work-proposal');row.append(el('summary','',message.sender+' · '+new Date(message.date).toLocaleString()),el('p','mail-body',message.body||'No inline text body. Attachments are not fetched.'));
  if(message.body){const b=el('button','secondary small-action','Suggest a task from this message');b.onclick=()=>perform(async()=>{const title=await ask('Task suggestion. Review the source quote in Suggested before accepting.',{ok:'Save suggestion',value:thread.subject});if(title===null)return;await api('/api/gmail/propose',{id:thread.id,revision:thread.revision,message_id:message.id,title});await refreshAfterItemChange();$('work-suggested').open=true;toast('Proposal saved in Suggested · no task was accepted');});row.append(b);const analyze=el('button','secondary small-action','Analyze this message with AI');analyze.onclick=()=>perform(()=>analyzeMail(thread,message));row.append(analyze);}box.append(row);
 }
}
async function analyzeMail(thread,message){
 const body={id:thread.id,revision:thread.revision,message_id:message.id},preview=await api('/api/gmail/ai/preview',body);
 const prompt=preview.cached?'Reuse the saved analysis for this exact message and AI settings? No new AI request will be sent. Existing review states stay unchanged.':'Send this selected email message to the AI endpoint below?\n\nAccount: '+preview.account+'\nSubject: '+preview.subject+'\nSize: '+preview.characters+' characters including sender and subject\nEndpoint: '+preview.endpoint+'\nModel: '+preview.model+'\n\nThis endpoint may be remote. Approval applies only to this message revision and these settings. Proposals require your later Accept/Link.';
 if(!(await ask(prompt,{ok:preview.cached?'Show saved analysis':'Approve and analyze',cancel:'Cancel'})))return;
 const result=await api('/api/gmail/ai/start',{...body,preview_token:preview.preview_token,approved:true});
 mailAIWasRunning=!!result.running;
 if(result.status==='reused'){await refreshAfterItemChange();$('work-suggested').open=true;toast('Saved analysis reused · review state kept');}
 await loadMail();
}
$('gmail-ai-cancel').onclick=()=>perform(async()=>{await api('/api/gmail/ai/cancel',{});await loadMail();});
$('gmail-panel').ontoggle=()=>{if($('gmail-panel').open)perform(loadMail);else if(mailTimer){clearTimeout(mailTimer);mailTimer=null;}};
$('gmail-refresh').onclick=()=>perform(loadMail);
$('gmail-connect').onclick=()=>perform(async()=>{const result=await api('/api/calendar/connect',{capability:'gmail'});$('gmail-auth-link').href=result.authorization_url;$('gmail-auth-link').hidden=false;toast('Approve Gmail read-only access in your browser, then Refresh connection');});
$('gmail-sync').onclick=()=>perform(async()=>{await api('/api/gmail/sync',{});await loadMail();});
$('gmail-cancel').onclick=()=>perform(async()=>{await api('/api/gmail/cancel',{});await loadMail();});
$('gmail-clear').onclick=()=>perform(async()=>{const account=$('gmail-cache-account').value;if(await ask('Clear the local email cache for '+account+'? It can be synced again. WorkItem quotes and archives remain.',{ok:'Clear cache',danger:true})){await api('/api/gmail/clear',{account});$('gmail-detail').replaceChildren();await loadMail();}});
function calendarConnected(google=state?.google){return google?.capabilities?.calendar??!!google?.connected;}

let chatSpace='',chatMessage='',chatAccount='',chatTimer=null,chatWasRunning=false;
async function loadChat(){
 const status=await api('/api/chat');
 if(chatAccount!==status.account_id){chatMessage='';chatSpace='';$('chat-detail').replaceChildren();chatAccount=status.account_id;}
 $('chat-status').textContent=(status.connected?'Connected as '+status.account:'Chat permission not connected')+' · '+status.job.status+(status.job.error?' · '+status.job.error:'');
 const spaces=status.connected?await api('/api/chat/spaces'):[],select=$('chat-space');select.replaceChildren(option('Choose a conversation…',''),...spaces.map(s=>option(s.label+' · '+s.type,s.name)));if(spaces.some(s=>s.name===chatSpace))select.value=chatSpace;else chatSpace='';
 const discovery=status.states['']||{};
 $('chat-discover').textContent=discovery.complete?'Refresh spaces':discovery.page?'Load more spaces':'Load spaces';$('chat-discover').disabled=!status.connected||status.job.running;
 $('chat-sync').disabled=$('chat-restart').disabled=!status.connected||!chatSpace||status.job.running;$('chat-cancel').disabled=!status.job.running;
 const cache=$('chat-cache-account'),old=cache.value;cache.replaceChildren(...status.cached_accounts.map(a=>option(a.label+' · '+a.id.slice(0,8),a.id)));if(status.cached_accounts.some(a=>a.id===old))cache.value=old;$('chat-clear').disabled=status.job.running||!status.cached_accounts.length;
 const list=$('chat-messages');list.replaceChildren();
 if(chatSpace){const sync=status.states[chatSpace]||{};list.append(el('p','hint',(sync.last_sync?'Last page saved '+new Date(sync.last_sync*1000).toLocaleString():'No saved page yet')+(sync.limited?' · 200-message limit reached; this is not a full conversation mirror':'')+(discovery.limited?' · Space discovery is limited to 200 conversations':'')));
  const messages=await api('/api/chat/messages?space='+encodeURIComponent(chatSpace));for(const m of messages){const b=el('button','mail-thread',(m.available?m.excerpt||'No plain text available':'Message unavailable/deleted')+' · '+m.sender+' · '+(m.date?new Date(m.date*1000).toLocaleString():m.name));b.onclick=()=>perform(()=>openChatMessage(m.name));list.append(b);}if(!messages.length)list.append(el('p','hint','No cached messages. Sync the selected conversation.'));
 }
 if(chatWasRunning&&!status.job.running){lastTasks='';await loadTasks();if(chatMessage)await openChatMessage(chatMessage);}
 chatWasRunning=status.job.running;
 if(chatTimer)clearTimeout(chatTimer);chatTimer=null;if(status.job.running&&view==='tasks'&&$('chat-panel').open)chatTimer=setTimeout(()=>perform(loadChat),1500);
}
async function openChatMessage(name){
 const m=await api('/api/chat/message?name='+encodeURIComponent(name));chatMessage=name;const box=$('chat-detail');box.replaceChildren(el('h3','',m.sender),el('p','hint',m.name+' · '+(m.thread||'No thread reference')),el('p','hint','Cached '+new Date(m.fetched_at*1000).toLocaleString()),el('p','mail-body',m.available?m.body||'No plain text available. Cards and attachments are not fetched.':'Message unavailable or deleted. Earlier WorkItem source quotes are retained.'));
 const refresh=el('button','secondary small-action','Refresh this message from Chat');refresh.onclick=()=>perform(async()=>{const result=await api('/api/chat/refresh',{name:m.name});chatWasRunning=true;await loadChat();});box.append(refresh);
 if(m.available&&m.body){const b=el('button','secondary small-action','Suggest a task from this message');b.onclick=()=>perform(async()=>{const title=await ask('Task proposal from this Chat message',{ok:'Save suggestion',value:m.body.slice(0,120)});if(title===null)return;await api('/api/chat/propose',{name:m.name,revision:m.revision,title});await refreshAfterItemChange();$('work-suggested').open=true;toast('Chat proposal saved · review it before Accept/Link');});box.append(b);}
}
async function chatAction(path,body={}){const result=await api('/api/chat/'+path,body);chatWasRunning=true;await loadChat();}
$('chat-panel').ontoggle=()=>{if($('chat-panel').open)perform(loadChat);else if(chatTimer){clearTimeout(chatTimer);chatTimer=null;}};
$('chat-connect').onclick=()=>perform(async()=>{const result=await api('/api/calendar/connect',{capability:'chat'});$('chat-auth-link').href=result.authorization_url;$('chat-auth-link').hidden=false;toast('Approve Chat read-only permission in your browser, then Refresh connection');});
$('chat-connection').onclick=()=>perform(loadChat);
$('chat-discover').onclick=()=>perform(()=>chatAction('discover'));
$('chat-space').onchange=()=>{chatSpace=$('chat-space').value;chatMessage='';$('chat-detail').replaceChildren();perform(loadChat);};
$('chat-sync').onclick=()=>perform(()=>chatAction('sync',{space:chatSpace}));
$('chat-restart').onclick=()=>perform(()=>chatAction('sync',{space:chatSpace,restart:true}));
$('chat-cancel').onclick=()=>perform(()=>chatAction('cancel'));
$('chat-clear').onclick=()=>perform(async()=>{const account=$('chat-cache-account').value;if(await ask('Clear this local Chat account cache? Promoted WorkItem source snapshots and archives remain.',{ok:'Clear cache',danger:true})){await api('/api/chat/clear',{account});chatMessage='';$('chat-detail').replaceChildren();await loadChat();}});

let ghAccount='',ghRepo=0,ghItem=0,ghRepos=[],ghTimer=null,ghWasRunning=false;
async function loadGitHub(){
 const status=await api('/api/github'),connection=status.connection;
 if(ghAccount!==connection.account_id){ghAccount=connection.account_id;ghRepo=0;ghItem=0;$('github-detail').replaceChildren();$('github-repository').value='';}
 $('github-status').textContent=(connection.connected?'Connected as '+connection.login:'GitHub not connected')+' · '+status.job.status+(connection.error?' · '+connection.error:'')+(status.job.error?' · '+status.job.error:'');
 ghRepos=connection.connected?await api('/api/github/repos'):[];const chosen=ghRepos.find(r=>r.full_name.toLowerCase()===$('github-repository').value.trim().toLowerCase());if(chosen)ghRepo=chosen.id;
 $('github-repos').replaceChildren(option('Choose a cached repository…',''),...ghRepos.map(r=>option(r.full_name,String(r.id))));$('github-repos').value=ghRepo?String(ghRepo):'';
 $('github-sync').disabled=$('github-restart').disabled=!connection.connected||status.job.running;$('github-cancel').disabled=!status.job.running;$('github-disconnect').disabled=!connection.connected;
 const cache=$('github-cache-account'),old=cache.value;cache.replaceChildren(...status.cached_accounts.map(a=>option(a.login+' · '+a.id,a.id)));if(status.cached_accounts.some(a=>a.id===old))cache.value=old;$('github-clear').disabled=status.job.running||!status.cached_accounts.length;
 const list=$('github-items');list.replaceChildren();if(ghRepo&&connection.connected){const role=$('github-filter').value,sync=status.states[ghRepo+':'+role]||{};
  list.append(el('p','hint',(sync.last_sync?'Last page saved '+new Date(sync.last_sync*1000).toLocaleString():'This filter has no completed page yet')+(sync.limited?' · 200-result limit reached':'')+(sync.incomplete?' · GitHub reported incomplete search results':'')));
  const records=await api('/api/github/items?repo='+ghRepo+'&filter='+role+'&kind='+$('github-kind').value);for(const r of records){const b=el('button','mail-thread',r.repository+' #'+r.number+' · '+(r.kind==='issue'?'Issue':'PR')+' · '+r.title+' · '+(r.available?r.state:'Unavailable'));b.onclick=()=>perform(()=>openGitHubItem(r.issue_id));list.append(b);}if(!records.length)list.append(el('p','hint','No matches in this cached filter. Sync the selected repository/filter.'));
 }
 if(ghWasRunning&&!status.job.running){lastTasks='';await loadTasks();if(ghItem)await openGitHubItem(ghItem);}ghWasRunning=status.job.running;
 if(ghTimer)clearTimeout(ghTimer);ghTimer=null;if(status.job.running&&view==='tasks'&&$('github-panel').open)ghTimer=setTimeout(()=>perform(loadGitHub),1500);
}
async function openGitHubItem(key){
 const r=await api('/api/github/item?id='+key);ghItem=key;const box=$('github-detail');box.replaceChildren(el('h3','',r.repository+' #'+r.number+' · '+r.title),el('p','hint','GitHub '+(r.kind==='issue'?'issue':'PR')+' state: '+r.state+' · '+(r.available?'Cached '+new Date(r.fetched_at*1000).toLocaleString():'Source unavailable')),el('p','hint','Local task status remains independent.'),el('p','mail-body',r.available?r.body||'No body text. The title can be quoted.':'Access or source unavailable. Historical WorkItem quotes remain.'));
 const link=el('a','','Open on GitHub ↗');link.href=r.url;link.target='_blank';link.rel='noopener noreferrer';box.append(link);
 const refresh=el('button','secondary small-action','Refresh this issue / PR');refresh.onclick=()=>perform(async()=>{await api('/api/github/refresh',{id:key});ghWasRunning=true;await loadGitHub();});box.append(refresh);
 if(r.available){const b=el('button','secondary small-action','Suggest a task from this issue / PR');b.onclick=()=>perform(async()=>{const title=await ask('Task proposal from GitHub. Remote status does not set the task status.',{ok:'Save suggestion',value:r.title});if(title===null)return;await api('/api/github/propose',{id:key,revision:r.revision,title});await refreshAfterItemChange();$('work-suggested').open=true;toast('GitHub proposal saved · review Accept/Link');});box.append(b);}
}
async function githubSync(restart=false){await api('/api/github/sync',{repository:$('github-repository').value.trim(),filter:$('github-filter').value,restart});ghWasRunning=true;await loadGitHub();}
$('github-panel').ontoggle=()=>{if($('github-panel').open)perform(loadGitHub);else if(ghTimer){clearTimeout(ghTimer);ghTimer=null;}};
$('github-connect').onclick=()=>perform(async()=>{const token=$('github-token').value.trim();try{await api('/api/github/connect',{token});await loadGitHub();}finally{$('github-token').value='';}});
$('github-disconnect').onclick=()=>perform(async()=>{await api('/api/github/disconnect',{});await loadGitHub();});
$('github-connection').onclick=()=>perform(loadGitHub);
$('github-sync').onclick=()=>perform(()=>githubSync());$('github-restart').onclick=()=>perform(()=>githubSync(true));
$('github-cancel').onclick=()=>perform(async()=>{await api('/api/github/cancel',{});await loadGitHub();});
$('github-repository').onchange=()=>{ghRepo=ghRepos.find(r=>r.full_name.toLowerCase()===$('github-repository').value.trim().toLowerCase())?.id||0;ghItem=0;$('github-detail').replaceChildren();perform(loadGitHub);};
$('github-repos').onchange=()=>{const repo=ghRepos.find(r=>r.id===Number($('github-repos').value));if(repo){$('github-repository').value=repo.full_name;ghRepo=repo.id;}ghItem=0;$('github-detail').replaceChildren();perform(loadGitHub);};
for(const id of ['github-filter','github-kind'])$(id).onchange=()=>{ghItem=0;$('github-detail').replaceChildren();perform(loadGitHub);};
$('github-clear').onclick=()=>perform(async()=>{if(await ask('Clear the local GitHub cache for the selected account? Promoted source snapshots and archives remain.',{ok:'Clear cache',danger:true})){await api('/api/github/clear',{account:$('github-cache-account').value});ghItem=0;$('github-detail').replaceChildren();await loadGitHub();}});

let proposalFilter='pending';
async function graphAction(action,body){await api('/api/work/'+action,body);await refreshAfterItemChange();}
function renderWorkGraph(){
 const graph=itemsData.graph||{},today=state.task_summary?.today||new Date().toLocaleDateString('en-CA');
 const sources=Object.fromEntries((graph.sources||[]).map(s=>[s.id,s])),evidence=Object.fromEntries((graph.source_evidence||[]).map(e=>[e.id,e]));
 const filters=$('proposal-filters');filters.replaceChildren();
 for(const value of ['pending','snoozed','dismissed','all']){const b=el('button',proposalFilter===value?'selected':'',value[0].toUpperCase()+value.slice(1));b.onclick=()=>{proposalFilter=value;renderWorkGraph();};filters.append(b);}
 const list=$('proposal-list');list.replaceChildren();
 const proposals=(graph.proposals||[]).filter(p=>proposalFilter==='all'||(proposalFilter==='dismissed'?p.state==='dismissed':p.state==='pending'&&(proposalFilter==='snoozed'?p.snoozed_until>today:!p.snoozed_until||p.snoozed_until<=today)));
 for(const p of proposals){
  const card=el('div','work-proposal'),ev=evidence[p.evidence_id],source=sources[ev?.source_id];
  card.append(el('strong','',p.text),el('p','hint',(p.origin==='gmail_ai'?'AI suggestion · ':'')+p.kind+' · '+p.state+(p.snoozed_until?' · Snoozed until '+p.snoozed_until:'')));
  if(p.fields&&Object.keys(p.fields).length)card.append(el('p','hint',Object.entries(p.fields).map(([name,value])=>(name==='due_date'?'Due date':name==='owner'?'Owner':'Deadline')+': '+value).join(' · ')));
  if(source?.remote?.authority==='github')card.append(el('p','hint','GitHub '+(source.remote.kind==='pull_request'?'PR':'issue')+' state: '+source.remote.state+' · local task status is independent'+(!source.available?' · Source unavailable':'')));
  if(ev){const quote=el('blockquote','',ev.quote);card.append(quote,el('p','hint',(source?source.provider+' · '+source.account+' · '+source.external_id:'Unavailable source')+' · saved revision '+ev.source_revision.slice(0,12)));}
  const actions=el('div','work-actions'),review=(action,extra={})=>graphAction('review',{id:p.id,revision:p.revision,action,...extra});
  const button=(label,run)=>{const b=el('button','secondary small-action',label);b.onclick=()=>perform(run);actions.append(b);};
  if(p.state==='pending'){
   button('Accept',()=>review('accept'));
   const select=el('select');select.setAttribute('aria-label','Link proposal to existing item');select.append(option('Link to existing…',''),...itemsData.items.filter(i=>i.kind===p.kind).map(i=>option(i.text,i.id)));actions.append(select);
   button('Link',async()=>{const target=itemsData.items.find(i=>i.id===select.value);if(!target){toast('Choose an existing item');return;}await review('link',{target_id:target.id,target_revision:target.revision});});
   button(p.snoozed_until?'Unsnooze':'Snooze',async()=>{if(p.snoozed_until)return review('snooze',{snoozed_until:null});const day=new Date();day.setDate(day.getDate()+1);const value=await ask('Snooze proposal until YYYY-MM-DD',{ok:'Snooze',value:day.toLocaleDateString('en-CA')});if(value!==null)await review('snooze',{snoozed_until:value});});
   button('Dismiss',()=>review('dismiss'));
  }else if(p.state==='dismissed')button('Restore',()=>review('restore'));
  if(p.result_id)actions.append(el('span','hint','Item '+p.result_id));
  card.append(actions);list.append(card);
 }
 if(!proposals.length)list.append(el('p','hint','No proposals match this filter.'));
 const questions=$('work-questions');questions.replaceChildren();
 for(const q of itemsData.items.filter(i=>i.kind==='question')){
  const row=el('div','work-proposal');row.append(el('strong','',q.text),el('p','hint',q.status==='answered'?'Answered':'Open'));
  if(q.answer)row.append(el('p','',q.answer));row.append(historyBlock(q,itemsData.meetings),evidenceBlock(q,itemsData.meetings));
  const b=el('button','secondary small-action',q.status==='answered'?'Reopen':'Answer');b.onclick=()=>perform(async()=>{const answer=q.status==='answered'?null:await ask('Answer: '+q.text,{ok:'Save answer',value:''});if(q.status!=='answered'&&answer===null)return;await graphAction('question',{id:q.id,revision:q.revision,answer});});row.append(b);questions.append(row);
 }
 if(!questions.children.length)questions.append(el('p','hint','No questions yet. Add one or accept a question proposal.'));
}
$('new-work-question').onclick=()=>perform(async()=>{const value=await ask('New question',{ok:'Add question',value:''});if(value!==null)await graphAction('question',{text:value});});

function renderTasks() {
 if(itemEditing)return;
 renderWorkGraph();
 const today=state.task_summary?.today||new Date().toISOString().slice(0,10), meetings=itemsData.meetings, byId=Object.fromEntries(itemsData.items.map(item=>[item.id,item]));
 const project=$('work-project'), oldProject=project.value;
 project.replaceChildren(option('All projects',''),...(state.projects?.projects||[]).map(p=>option(p.name,p.id)));
 if([...project.options].some(o=>o.value===oldProject))project.value=oldProject;
 const inProject=item=>!project.value||item.links.some(link=>meetings[link.meeting_id]?.project_id===project.value);
 const tasks=itemsData.items.filter(item=>item.kind==='task'&&inProject(item)), decisions=itemsData.items.filter(item=>item.kind==='decision'&&inProject(item));
 const open=tasks.filter(t=>t.status==='open'&&!t.dismissed&&(!t.snoozed_until||t.snoozed_until<=today)), late=open.filter(t=>t.due_date&&t.due_date<today), pending=itemsData.pending.filter(entry=>!project.value||meetings[entry.meeting_id]?.project_id===project.value);
 const accepted=decisions.filter(d=>d.status==='accepted'&&!d.dismissed&&(!d.snoozed_until||d.snoozed_until<=today)).length;
 $('tasks-summary').textContent=open.length+' open task'+(open.length===1?'':'s')+' · '+late.length+' overdue · '+accepted+' accepted decision'+(accepted===1?'':'s')+(pending.length?' · '+pending.length+' to review':'');
 for(const button of document.querySelectorAll('[data-kind]')) { const count=pending.filter(p=>p.kind===button.dataset.kind).length; button.classList.toggle('selected',button.dataset.kind===itemKind); button.textContent=(button.dataset.kind==='task'?'Tasks':'Decisions')+(count?' · '+count+' to review':''); }
 const review=pending.filter(entry=>entry.kind===itemKind); $('link-review').hidden=!review.length; $('link-review').replaceChildren();
 if(review.length) { $('link-review').append(el('h2','',review.length+' to review'),el('p','hint','The AI found mentions that look like existing items. Nothing is linked until you choose.')); for(const entry of review) $('link-review').append(linkCard(entry,meetings,byId)); }
 const filter=statusFilter[itemKind];
 $('status-filter').replaceChildren(...STATUS_FILTERS[itemKind].map(([key,label])=>{const button=el('button',key===filter?'selected':'',label);button.type='button';button.onclick=()=>{statusFilter[itemKind]=key;renderTasks();};return button;}));
 $('task-owner').hidden=itemKind!=='task';
 const owner=$('task-owner').value, owners=[...new Set(tasks.map(t=>t.owner).filter(Boolean))].sort((a,b)=>a.localeCompare(b));
 $('task-owner').replaceChildren(option('All owners',''),...owners.map(name=>option(name,name)),option('No owner','__none__'));
 $('task-owner').value=[...$('task-owner').options].some(o=>o.value===owner)?owner:'';
 const latest=item=>item.links.map(link=>meetings[link.meeting_id]?.date||'').sort().at(-1)||'';
 let rows;
 const personal=item=>filter==='snoozed'?!!item.snoozed_until&&item.snoozed_until>today&&!item.dismissed:filter==='dismissed'?!!item.dismissed:filter==='all'||!item.dismissed&&(!item.snoozed_until||item.snoozed_until<=today);
 if(itemKind==='task') rows=tasks.filter(personal).filter(t=>['all','snoozed','dismissed'].includes(filter)||(filter==='done'?t.status==='done':t.status==='open'&&(filter==='open'||t.due_date&&t.due_date<today)))
  .filter(t=>!$('task-owner').value||($('task-owner').value==='__none__'?!t.owner:t.owner===$('task-owner').value))
  .sort((a,b)=>(a.status===b.status?0:a.status==='open'?-1:1)||(a.due_date||'9999').localeCompare(b.due_date||'9999')||latest(b).localeCompare(latest(a)));
 else rows=decisions.filter(personal).filter(d=>['all','snoozed','dismissed'].includes(filter)||(filter==='current'?d.status==='accepted':d.status===filter)).sort((a,b)=>latest(b).localeCompare(latest(a)));
 $('task-list').replaceChildren();
 const empty=itemKind==='task'?'No tasks yet. Generate notes for a meeting to collect its tasks here.':'No decisions yet. Generate notes for a meeting to collect its decisions here.';
 if(!rows.length) $('task-list').append(el('p','empty-content',(itemKind==='task'?tasks:decisions).length?'Nothing matches this filter.':empty));
 for(const item of rows) $('task-list').append(itemKind==='task'?globalTaskRow(item,today):decisionRow(item,byId));
}
for(const button of document.querySelectorAll('[data-kind]')) button.onclick=()=>{itemKind=button.dataset.kind;renderTasks();};
// Projects group meetings; a series groups the meetings that repeat inside a project.
let lastProjects='', prepareScope={project:'',series:''}, prepareData=null;
const projectList=()=>state?.projects?.projects||[];
const seriesOf=projectId=>(state?.projects?.series||[]).filter(series=>series.project_id===projectId);
function fillProjects(select,value,none,extra=[]) { select.replaceChildren(option(none,''),...projectList().map(p=>option(p.name,p.id)),...extra); select.value=[...select.options].some(o=>o.value===value)?value:''; }
function fillSeries(select,projectId,value,none,extra=[]) { select.replaceChildren(option(none,''),...seriesOf(projectId).map(s=>option(s.name,s.id)),...extra); select.value=[...select.options].some(o=>o.value===value)?value:''; select.disabled=!projectId&&!extra.length; }
function syncProjects() {
 const signature=JSON.stringify(state.projects); if(signature===lastProjects) return; lastProjects=signature;
 fillProjects($('project-filter'),$('project-filter').value,'All projects',projectList().length?[option('No project','__none__')]:[]); $('project-filter').hidden=!projectList().length;
 fillProjects($('record-project'),$('record-project').value,'No project'); fillSeries($('record-series'),$('record-project').value,$('record-series').value,'No series');
 $('record-prepare').disabled=!$('record-project').value;
 if($('settings-dialog').open) renderProjectSettings();
 if(view==='detail'&&detail) renderScope(detail);
}
$('project-filter').onchange=()=>{lastLibrary='';renderLibrary();};
$('record-project').onchange=()=>{fillSeries($('record-series'),$('record-project').value,'','No series');$('record-prepare').disabled=!$('record-project').value;};
$('record-prepare').onclick=()=>perform(()=>openPrepare($('record-project').value,$('record-series').value));
function renderScope(d) {
 const box=$('detail-scope'), project=projectList().find(p=>p.id===d.project_id), series=seriesOf(d.project_id).find(s=>s.id===d.series_id); box.replaceChildren();
 const edit=el('button','quiet scope-chip',project?project.name+(series?' · '+series.name:'')+' ✎':'＋ Add to a project'); edit.type='button'; edit.title='Project and series of this meeting'; edit.onclick=()=>openScopeDialog(d); box.append(edit);
 if(project){const prepare=el('button','quiet scope-chip','Prepare the next meeting ›');prepare.type='button';prepare.onclick=()=>perform(()=>openPrepare(d.project_id,d.series_id||''));box.append(prepare);}
}
function syncScopeSeries(value) {
 const project=$('scope-project').value; $('scope-project-name').hidden=project!=='__new__';
 fillSeries($('scope-series'),project==='__new__'?null:project,value,'No series',project?[option('New series…','__new__')]:[]);
 $('scope-series').disabled=!project; $('scope-series-name').hidden=$('scope-series').value!=='__new__';
}
function openScopeDialog(d) {
 clearError(); fillProjects($('scope-project'),d.project_id,'No project',[option('New project…','__new__')]); syncScopeSeries(d.series_id);
 $('scope-project-name').value=''; $('scope-series-name').value=''; $('scope-dialog').showModal();
}
$('scope-project').onchange=()=>{syncScopeSeries('');if($('scope-project').value==='__new__')$('scope-project-name').focus();};
$('scope-series').onchange=()=>{$('scope-series-name').hidden=$('scope-series').value!=='__new__';if(!$('scope-series-name').hidden)$('scope-series-name').focus();};
$('scope-close').onclick=()=>$('scope-dialog').close();
$('scope-form').onsubmit=event=>{event.preventDefault();perform(async()=>{
 const projectValue=$('scope-project').value, seriesValue=$('scope-series').value;
 const project=!projectValue?null:projectValue==='__new__'?{name:$('scope-project-name').value}:{id:projectValue};
 const series=!projectValue||!seriesValue?null:seriesValue==='__new__'?{name:$('scope-series-name').value}:{id:seriesValue};
 detail=await api('/api/meetings/'+selected+'/scope',{project,series}); lastFingerprint=JSON.stringify(detail);
 state=await api('/api/state'); $('scope-dialog').close(); renderState(); renderDetail(); lastLibrary=''; renderLibrary(); toast('Saved');});};
function renderProjectSettings() {
 const list=$('project-list'); list.replaceChildren();
 if(!projectList().length) list.append(el('p','empty-content','No projects yet. Open a saved meeting and choose ＋ Add to a project.'));
 const row=(kind,entry)=>{const line=el('div','scope-entry '+kind),rename=el('button','quiet','Rename'),remove=el('button','quiet danger-text','Delete');rename.type=remove.type='button';
  line.append(el(kind==='projects'?'strong':'span','',entry.name),rename,remove);
  const change=async body=>{state.projects=(await api('/api/projects/change',Object.assign({kind,id:entry.id},body))).projects;lastProjects='';syncProjects();renderProjectSettings();};
  rename.onclick=()=>perform(async()=>{const name=await ask('New name',{value:entry.name,ok:'Rename'});if(name?.trim()&&name.trim()!==entry.name)await change({action:'rename',name});});
  remove.onclick=()=>perform(async()=>{if(await ask('Delete "'+entry.name+'"'+(kind==='projects'?' and its series':'')+'?\n\nMeetings stay; they only leave this group.',{ok:'Delete',danger:true}))await change({action:'delete'});});
  return line;};
 for(const project of projectList()) { const box=el('div','project-entry'); box.append(row('projects',project),...seriesOf(project.id).map(series=>row('series',series))); list.append(box); }
}
function sourceChip(source) {
 const chip=el('button','meeting-chip','↗ '+withDate(source.meeting_title,source.meeting_date)+(source.timestamp?' · '+source.timestamp:'')); chip.type='button'; chip.title='Open the meeting at this moment';
 chip.onclick=()=>perform(async()=>{await openMeeting(source.meeting_id);if(source.timestamp&&detail.transcript.length)showMoment(source.timestamp);else switchTab('outcomes');});
 return chip;
}
async function openPrepare(projectId,seriesId) {
 if(!(await leaveEdits())) return; dirtyTranscript=dirtyNotes=false; selected=null; history.replaceState(null,'','/'); show('prepare');
 prepareScope={project:projectId||prepareScope.project||projectList()[0]?.id||'',series:projectId?seriesId||'':prepareScope.series};
 renderLibrary(); await loadPrepare();
}
async function loadPrepare() {
 fillProjects($('prepare-project'),prepareScope.project,'Choose a project'); fillSeries($('prepare-series'),prepareScope.project,prepareScope.series,'All meetings of the project');
 $('prepare-empty').hidden=!!projectList().length; $('prepare-content').hidden=true;
 if(!prepareScope.project){$('prepare-summary').textContent='Choose a project or a series.';return;}
 prepareData=await api('/api/prepare?'+new URLSearchParams(prepareScope.series?{series:prepareScope.series}:{project:prepareScope.project})); renderPrepare(prepareData);
}
$('prepare-project').onchange=()=>{prepareScope={project:$('prepare-project').value,series:''};perform(loadPrepare);};
$('prepare-series').onchange=()=>{prepareScope.series=$('prepare-series').value;perform(loadPrepare);};
$('open-prepare').onclick=()=>perform(()=>openPrepare());
$('copy-agenda').onclick=()=>perform(async()=>{await navigator.clipboard.writeText(prepareData.markdown);toast('Agenda copied · paste it into the invitation or a chat');});
function renderPrepare(data) {
 const last=data.meetings.at(-1);
 $('prepare-summary').textContent=data.meetings.length?data.title+' · '+data.meetings.length+(data.meetings.length===1?' meeting':' meetings')+' · last: '+withDate(last.title,last.date):data.title+' · no meetings yet';
 $('prepare-content').hidden=!data.meetings.length;
 const sources=list=>{const box=el('div','item-meetings');for(const source of list.filter(Boolean))box.append(sourceChip(source));return box;};
 $('prepare-agenda').replaceChildren(...data.agenda.map(entry=>{const item=el('li');item.append(el('span','agenda-title',entry.title));if(entry.sources.length)item.append(sources(entry.sources));return item;}));
 const today=state.task_summary?.today||new Date().toISOString().slice(0,10);
 $('prepare-tasks').replaceChildren(...(data.tasks.length?data.tasks.map(task=>{
  const [kind,label]=dueInfo(Object.assign({status:'open'},task),today), row=el('div','tracked-task '+kind), done=el('input'), main=el('div','tracked-main'), meta=el('div','tracked-meta'), who=el('span','tracked-owner');
  done.type='checkbox'; done.setAttribute('aria-label','Mark task as done'); done.onchange=()=>perform(()=>changeItem({id:task.item_id,text:task.text},{status:'done'}));
  who.append(speakerBadge(el('span'),task.owner||''),el('span','',task.owner||'No owner')); meta.append(who,el('span','due-label '+kind,task.due_date?label+' · '+task.due_date:label));
  if(task.deadline) meta.append(el('span','hint','Said: '+task.deadline));
  main.append(el('p','tracked-text',task.text),meta,sources([task.source])); row.append(done,main); return row;}):[el('p','empty-content','No open tasks.')]));
 $('prepare-questions').replaceChildren(...(data.questions.length?data.questions.map(question=>{
  const row=el('div','prepare-question'); row.append(el('span','change-kind',question.kind==='decide'?'Needs a decision':'Open question'),el('p','',question.text),sources([question.source]));
  if(question.maybe_answered_by){row.classList.add('maybe-answered');row.append(el('p','hint','A later decision may answer it: '+question.maybe_answered_by.text),sources([question.maybe_answered_by.source]));}
  return row;}):[el('p','empty-content','No open questions in the last meetings.')]));
 $('prepare-decisions').replaceChildren(...(data.decisions.length?data.decisions.map(decision=>{const row=el('div','prepare-question');row.append(el('p','',decision.text),sources([decision.source]));return row;}):[el('p','empty-content','No accepted decisions yet. Accept decisions in Tasks & decisions.')]));
 $('prepare-proposed').replaceChildren();
 if(data.proposed.length){const box=el('details','item-history');box.append(el('summary','','Not confirmed yet · '+data.proposed.length));for(const decision of data.proposed){const row=el('div','prepare-question');row.append(el('p','',decision.text),sources([decision.source]));box.append(row);}$('prepare-proposed').append(box);}
}
// Search returns passages; "Answer from sources" writes an answer only from them.
const FIND_KINDS=[['','All'],['decisions','Decisions'],['tasks','Tasks'],['notes','Notes'],['transcript','Transcript']];
const RESULT_GROUPS=[['Decisions',['decision']],['Tasks',['task']],['Notes',['summary','next_step','question','observation','marker']],['Transcript',['transcript','draft']],['Meetings',['meeting']]];
const RESULT_LABELS={decision:'Decision',task:'Task',summary:'Summary',next_step:'Next step',question:'Question',observation:'Private observation',marker:'Marker',transcript:'Transcript',draft:'Live draft',meeting:'Meeting'};
const STATUS_LABELS={accepted:'Accepted',proposed:'Proposed',superseded:'Replaced',open:'Open',done:'Done',pending:'Waits for review'};
let findKind='';
function highlighted(snippet) { const box=el('p','result-text'); snippet.split(/(\x02[^\x03]*\x03)/).forEach(part=>box.append(part.startsWith('\x02')?el('mark','',part.slice(1,-1)):document.createTextNode(part))); return box; }
function resultRow(result) {
 const row=el('div','result-row '+result.kind), head=el('div','result-head');
 head.append(el('span','change-kind',RESULT_LABELS[result.kind]||result.kind));
 if(result.status) head.append(el('span','decision-status '+result.status,STATUS_LABELS[result.status]||result.status));
 if(result.speaker) head.append(el('span','hint',result.speaker));
 row.append(head,highlighted(result.snippet));
 const sources=el('div','item-meetings'); sources.append(sourceChip(result)); row.append(sources); return row;
}
async function openFind(query) {
 if(!(await leaveEdits())) return; dirtyTranscript=dirtyNotes=false; selected=null; history.replaceState(null,'','/'); show('find'); renderLibrary();
 fillProjects($('find-project'),$('find-project').value,'All projects');
 $('find-kinds').replaceChildren(...FIND_KINDS.map(([key,label])=>{const button=el('button',key===findKind?'selected':'',label);button.type='button';button.onclick=()=>{findKind=key;openFind($('find-query').value);};return button;}));
 if(query!==undefined) $('find-query').value=query;
 $('find-query').focus(); if($('find-query').value.trim()) perform(runFind);
}
async function runFind() {
 const query=$('find-query').value.trim(); $('find-results').replaceChildren(); if(!query) return;
 const results=await api('/api/find?'+new URLSearchParams({q:query,kind:findKind,project:$('find-project').value}));
 if(!results.length){$('find-results').append(el('p','empty-content card','Nothing matches. Try fewer or other words.'));return;}
 for(const [title,kinds] of RESULT_GROUPS) { const rows=results.filter(r=>kinds.includes(r.kind)); if(!rows.length) continue;
  const card=el('div','card result-group'); card.append(el('h2','',title+' · '+rows.length),...rows.map(resultRow)); $('find-results').append(card); }
}
let askController=null;
// The check for confirmed decisions and the passages come at once; the written answer can take minutes.
async function runAsk() {
 const question=$('find-query').value.trim(); if(!question) return;
 askController?.abort(); const controller=askController=new AbortController();
 const box=$('find-answer'), project=$('find-project').value; box.hidden=false; box.replaceChildren(el('p','hint','Searching…'));
 const result=await api('/api/ask',{question,project,ai:false});
 box.replaceChildren(el('p','eyebrow','ANSWER FROM YOUR MEETINGS'),el('h2','',result.question));
 const list=entries=>{const wrap=el('div');for(const entry of entries){const row=el('div','prepare-question'),chips=el('div','item-meetings');chips.append(sourceChip(entry));row.append(el('p','',entry.text),chips);wrap.append(row);}return wrap;};
 if(result.decision_question) {
  const status=el('div','decision-check '+(result.confirmed.length?'ok':'none'));
  status.append(el('strong','',result.confirmed.length?'✓ Confirmed decision found':'No confirmed decision found'));
  box.append(status); if(result.confirmed.length) box.append(list(result.confirmed));
  if(result.proposed.length) box.append(el('p','hint','Proposed or waiting for review, not confirmed:'),list(result.proposed));
 }
 const written=el('div','ai-answer'); box.append(written); await runFind();
 if(!result.sources.length){written.append(el('p','hint','Nothing in your meetings matches this question.'));return;}
 if(result.provider==='none'){written.append(el('p','hint','Choose a notes provider in Settings → Notes & AI to get a written answer. The passages below are the sources.'));return;}
 const waiting=el('p','hint'), stop=el('button','quiet','Stop waiting'), started=Date.now(); stop.type='button'; stop.onclick=()=>controller.abort();
 const tick=()=>{waiting.textContent='Writing the answer from '+result.sources.length+' passages · '+Math.round((Date.now()-started)/1000)+' s. A local model can take several minutes.';};
 tick(); const timer=setInterval(tick,1000); written.append(waiting,stop);
 try {
  const response=await fetch('/api/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question,project}),signal:controller.signal});
  const full=await response.json(); if(!response.ok) throw new Error(full.error||'Request failed');
  written.replaceChildren();
  if(full.ai?.found){written.append(el('p','',full.ai.answer));const cites=el('div','item-meetings');cites.append(el('span','hint','Sources'));
   for(const number of full.ai.cited){const chip=sourceChip(full.sources[number-1]);chip.textContent='['+number+'] '+chip.textContent;cites.append(chip);}written.append(cites);}
  else if(full.ai) written.append(el('p','hint','The found passages do not answer this question.'));
  else if(full.ai_error) written.append(el('p','notice warning','No written answer: '+full.ai_error));
 } catch(e) {
  if(e.name!=='AbortError') throw e;
  written.replaceChildren(el('p','hint','You stopped waiting. The model server may still finish this request before it starts the next one.'));
 } finally { clearInterval(timer); }
}

function renderProcessingTime(){
 if(!detail||view!=='detail')return;
 const d=detail, active=d.status==='processing', now=Date.now()/1000;
 const elapsed=active&&d.processing_started_at?Math.max(0,now-d.processing_started_at):d.processing_elapsed||0;
 const timings=Object.entries(d.processing_timings||{}).map(([name,seconds])=>name+': '+time(seconds));
 $('processing-time').hidden=!d.processing_stage;
 $('processing-time').textContent=d.processing_stage+' · '+time(elapsed)+(active&&d.processing_stage_started_at?' · this stage '+time(Math.max(0,now-d.processing_stage_started_at)):'')+(timings.length?' · '+timings.join(' · '):'');
}
setInterval(()=>{if(!document.hidden)renderProcessingTime();},1000);
window.addEventListener('desktop-status',event=>{desktopStatus=String(event.detail||'');$('connection').textContent=desktopStatus;error(desktopStatus);});
$('cancel-processing').onclick=()=>perform(async()=>{await api('/api/meetings/'+selected+'/cancel',{});toast('Cancellation requested');await openMeeting(selected,true);});
$('fast-profile').onclick=()=>{$('provider').value='local';$('local-model').value='large-v3-turbo';$('live-enabled').checked=false;$('transcript-correction').value='none';$('diarization-enabled').checked=false;if(/qwen3\.5/i.test($('local-ai-model').value))$('local-ai-reasoning').value='none';settingsFields();toast('Faster settings selected. Save settings to apply.');};

$('find-form').onsubmit=event=>{event.preventDefault();$('find-answer').hidden=true;perform(runFind);};
$('find-ask').onclick=()=>perform(runAsk);
$('find-project').onchange=()=>perform(runFind);
$('open-find').onclick=()=>openFind();
$('search').onkeydown=event=>{if(event.key==='Enter'&&$('search').value.trim()){event.preventDefault();openFind($('search').value.trim());}};
// The server says when something changed; the tab loads data only then, and not at all while it is hidden.
let events=null, refreshing=false, refreshPending=false, pendingChanged=[];
// changed is the list of meetings that changed, or null for "anything may have changed".
async function refresh(changed) {
 if(refreshing){refreshPending=true;pendingChanged=pendingChanged===null||changed===null?null:[...pendingChanged,...changed];return;}
 refreshing=true;
 try {
  state=await api('/api/state'); renderState();
  if(!initialRouteHandled){initialRouteHandled=true;if(requestedMeeting&&/^[a-f0-9]{32}$/.test(requestedMeeting))await perform(()=>openMeeting(requestedMeeting,true));}
  if(view==='tasks') await loadTasks();
  if(view==='detail'&&selected&&!hasEdits()&&(!changed||changed.includes(selected))) {
   const fresh=await api('/api/meetings/'+selected); const fingerprint=JSON.stringify(fresh);
   if(fingerprint!==lastFingerprint){detail=fresh;lastFingerprint=fingerprint;if(notesEditing)notesBase=structuredClone(fresh.minutes);renderDetail();}
  }
 } catch(e) { $('connection').textContent=disconnectedMessage(); }
 finally { refreshing=false; if(refreshPending){const next=pendingChanged;refreshPending=false;pendingChanged=[];refresh(next);} }
}
let lastLive=null;
function showLive(values) {
 if(values.preview_level!==undefined){$('setup-meter').value=values.preview_level;return;}
 lastLive=values;
 if(!state?.active||state.active.id!==values.meeting_id) return;
 state.active.duration=Math.max(state.active.duration||0,values.duration); state.active.level=values.level;
 $('timer').textContent=time(state.active.duration); $('recording-meter').value=values.level||0;
}
function listen() {
 if(events||document.hidden) return;
 events=new EventSource('/api/events');
 events.addEventListener('hello',()=>refresh(null));
 events.addEventListener('state',event=>refresh(JSON.parse(event.data).changed));
 events.addEventListener('live',event=>showLive(JSON.parse(event.data)));
 events.onerror=()=>{ $('connection').textContent=disconnectedMessage(); };
}
document.addEventListener('visibilitychange',()=>{ if(document.hidden){events?.close();events=null;} else listen(); });
// The microphone list is scanned only while the new-meeting form is visible.
setInterval(()=>{ if(view!=='setup'||document.hidden||!state) return;
 api('/api/devices').then(result=>{if(JSON.stringify(result.devices)!==JSON.stringify(state.devices)||result.device_error!==state.device_error){state.devices=result.devices;state.device_error=result.device_error;renderState();}}).catch(()=>{}); },3000);
$('open-tasks').onclick=()=>perform(async()=>{if(!(await leaveEdits()))return;dirtyTranscript=dirtyNotes=false;selected=null;history.replaceState(null,'','/');show('tasks');lastTasks='';await loadTasks();renderLibrary();});
$('open-analytics').onclick=()=>perform(async()=>{if(!(await leaveEdits()))return;dirtyTranscript=dirtyNotes=false;selected=null;history.replaceState(null,'','/');show('analytics');await loadAnalytics();renderLibrary();});
$('analytics-apply').onclick=()=>perform(loadAnalytics);
$('analytics-reset').onclick=()=>perform(async()=>{for(const id of ['analytics-from','analytics-to','analytics-speaker','analytics-topic'])$(id).value='';await loadAnalytics();});
$('work-project').onchange=()=>renderTasks();
$('task-owner').onchange=renderTasks;
$('new-meeting').onclick=async()=>{if(!(await leaveEdits()))return;dirtyTranscript=dirtyNotes=false;selected=null;history.replaceState(null,'','/');show(state?.active?'recording':'setup');if(state?.active)selected=state.active.id;else renderTranscriptionTiming(true);renderLibrary();};
let searchTimer; $('search').oninput=()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>perform(async()=>{const q=$('search').value.trim();if(q){window.searchResults=await api('/api/search?q='+encodeURIComponent(q));}else window.searchResults=null;lastLibrary='';renderLibrary();}),200);};
for(const radio of document.querySelectorAll('input[name=mode]'))radio.onchange=()=>{$('mode-help').textContent=radio.value==='online'?'Captures audio from all Mac apps plus your microphone. Use headphones to avoid echo. macOS requires Screen & System Audio Recording permission.':'Place your iPhone near the centre of the table, or use your Mac microphone.';};
$('check-mic').onclick=()=>perform(async()=>{await api('/api/check-mic',{device:Number($('microphone').value),device_name:$('microphone').selectedOptions[0]?.textContent});toast('Microphone test started · 10 seconds');});
$('microphone').onchange=()=>renderState();
$('record-form').onsubmit=event=>{event.preventDefault();perform(async()=>{pending=true;$('start').disabled=true;try{const m=await api('/api/start',{title:$('meeting-title').value,mode:document.querySelector('input[name=mode]:checked').value,device:Number($('microphone').value),device_name:$('microphone').selectedOptions[0]?.textContent,fallback_device_name:$('fallback-microphone').value,transcription_timing:$('transcription-timing').value,project_id:$('record-project').value||null,series_id:$('record-series').value||null});selected=m.id;state.active=m;renderState();show('recording');}finally{pending=false;}});};
async function importTranscript(text,filename) {
 const d=await api('/api/import',{text,filename});
 $('import-file').value='';$('import-text').value='';$('import-button').disabled=$('import-paste-button').disabled=true;
 toast('Transcript imported · '+d.transcript.length+' segments');state=await api('/api/state');renderState();await openMeeting(d.id,true);
}
$('import-file').onchange=()=>{$('import-button').disabled=!$('import-file').files.length;};
const AUDIO_FILE=/\.(m4a|mp3|wav|aac|ogg|opus|flac|webm|mp4|mov|caf|aiff?|amr|3gp)$/i;
// XMLHttpRequest reports upload progress; a long phone recording takes a while to send.
function uploadAudio(file) {
 return new Promise((resolve,reject)=>{
  const xhr=new XMLHttpRequest(); xhr.open('POST','/api/import-audio');
  xhr.setRequestHeader('Content-Type','application/octet-stream'); xhr.setRequestHeader('X-Filename',encodeURIComponent(file.name)); xhr.setRequestHeader('X-Last-Modified',String(file.lastModified||''));
  xhr.upload.onprogress=event=>{if(event.lengthComputable)$('import-button').textContent=event.loaded<event.total?'Uploading '+Math.floor(100*event.loaded/event.total)+'%':'Converting audio…';};
  xhr.onload=()=>{let data;try{data=JSON.parse(xhr.responseText);}catch{data={error:'The import failed.'};}xhr.status===200?resolve(data):reject(new Error(data.error||'The import failed.'));};
  xhr.onerror=()=>reject(new Error('The upload stopped. Check that the app is still running, then try again.'));
  xhr.send(file);
 });
}
$('import-button').onclick=()=>perform(async()=>{const file=$('import-file').files[0];if(!file)return;$('import-button').disabled=true;
 try{
  if(AUDIO_FILE.test(file.name)){const d=await uploadAudio(file);$('import-file').value='';toast('Audio imported · '+shortDuration(d.duration));state=await api('/api/state');renderState();await openMeeting(d.id,true);return;}
  if(file.size>5_000_000)throw new Error('Choose a transcript file of at most 5 MB');
  await importTranscript(await file.text(),file.name);
 }finally{$('import-button').textContent='Import file';$('import-button').disabled=!$('import-file').files.length;}});
$('import-text').oninput=()=>{$('import-paste-button').disabled=!$('import-text').value.trim();};
$('import-paste-button').onclick=()=>perform(async()=>{$('import-paste-button').disabled=true;try{await importTranscript($('import-text').value,'');}finally{$('import-paste-button').disabled=!$('import-text').value.trim();}});
$('pause').onclick=()=>perform(()=>api('/api/pause',{paused:state.active.status!=='paused'}));$('stop').onclick=()=>perform(()=>api('/api/stop',{}));
for(const [id,action] of [['process','transcribe'],['summarize','summarize'],['recover','recover'],['correct','correct']])$(id).onclick=()=>perform(async()=>{if(!(await leaveEdits()))return;if(action==='summarize'&&state.settings.summarizer==='none'){openSettings('notes');toast('Choose a meeting-notes provider first');return;}await api('/api/meetings/'+selected+'/process',{action});dirtyNotes=dirtyTranscript=false;toast('Processing queued');await openMeeting(selected,true);});
$('edit-title').onclick=()=>perform(async()=>{const title=await ask('Meeting name',{value:detail.title,ok:'Rename'});if(title?.trim()){await api('/api/meetings/'+selected+'/edit',{title});await openMeeting(selected,true);}});
$('save-transcript').onclick=()=>perform(async()=>{detail=await api('/api/meetings/'+selected+'/edit',{transcript:detail.transcript});dirtyTranscript=false;lastFingerprint=JSON.stringify(detail);renderDetail();toast('Transcript corrections saved');});
$('save-notes').onclick=$('save-outcomes').onclick=()=>perform(async()=>{for(const field of ITEM_FIELDS)detail.minutes[field]=(detail.minutes[field]||[]).filter(item=>item.text.trim());notesEditing=false;try{await saveMinutes(notesBase);}catch(e){notesEditing=true;throw e;}toast('Meeting notes saved');});
for(const name of ['notes','outcomes']) {
 $('edit-'+name).onclick=()=>{notesBase=structuredClone(detail.minutes);notesEditing=true;renderNotes(false);};
 $('cancel-'+name).onclick=()=>perform(async()=>{if(dirtyNotes&&!(await ask('Discard your changes to the notes?',{ok:'Discard',danger:true})))return;notesEditing=false;await openMeeting(selected,true);});
}
$('reanalyze').onclick=()=>perform(async()=>{if(!(await leaveEdits()))return;await api('/api/meetings/'+selected+'/reanalyze',{});dirtyTranscript=dirtyNotes=false;toast('Analytics queued');await openMeeting(selected,true);});
for(const tab of ['transcript','outcomes','notes','analytics']) $('tab-'+tab).onclick=()=>switchTab(tab);
$('settings-open').onclick=()=>openSettings();$('settings-inline').onclick=()=>openSettings('recording');
for(const tab of document.querySelectorAll('.settings-tabs button')) tab.onclick=()=>showSettingsTab(tab.dataset.tab);
// A required field on a hidden tab would block saving without a visible message.
$('settings-save').onclick=event=>{const invalid=$('settings-form').querySelector('input:invalid,select:invalid,textarea:invalid');if(invalid){event.preventDefault();showSettingsTab(invalid.closest('.settings-panel').dataset.tab);invalid.reportValidity();}};$('settings-close').onclick=()=>$('settings-dialog').close();$('provider').onchange=settingsFields;$('summarizer').onchange=()=>{$('llm-model').value=$('summarizer').value==='openai'?'gpt-4.1-mini':'gpt-4.1-mini';settingsFields();};$('transcript-correction').onchange=settingsFields;
$('settings-form').onsubmit=event=>{event.preventDefault();perform(async()=>{const body={local_ai_base_url:$('local-ai-base-url').value.trim(),local_ai_model:$('local-ai-model').value.trim(),local_ai_format:$('local-ai-format').value,local_ai_reasoning:$('local-ai-reasoning').value,local_ai_max_tokens:Number($('local-ai-max-tokens').value),transcription:$('provider').value,local_model:$('local-model').value,audio_preparation:$('audio-preparation').value,whisper_vad:$('whisper-vad').checked,whisper_vocabulary:$('whisper-vocabulary').value.trim(),cloud_model:$('cloud-model').value,summarizer:$('summarizer').value,transcript_correction:$('transcript-correction').value,llm_model:$('llm-model').value,auto_process:$('auto-process').checked,live_transcription:$('live-enabled').checked,diarization_enabled:$('diarization-enabled').checked,auto_title:$('auto-title').checked,title_provider:$('title-provider').value,title_model:$('title-model').value,calendar_enabled:$('calendar-enabled').checked,calendar_id:$('calendar-id').value};if($('api-key').value.trim())body.api_key=$('api-key').value.trim();await api('/api/settings',body);$('api-key').value='';$('settings-dialog').close();toast('Settings saved');state=await api('/api/state');renderState();});};

function renderGoogleStatus() {
 const google=state.google||{};
 $('google-status').textContent=(google.connected?'Signed in as '+google.account:google.sign_in_available?'Not signed in. Sign in with your Google account to add meetings to your calendar.':'Google sign-in is not set up for this app yet. See README → Google Calendar, or use Advanced below.')+(google.error?' · '+google.error:'');
 $('google-connect').disabled=!google.sign_in_available;$('google-connect').textContent=google.connected?(calendarConnected(google)?'Switch Google account':'Connect Calendar permission'):'Sign in with Google';$('google-disconnect').disabled=!google.connected;
 if(!google.sign_in_available) $('google-advanced').open=true;
 $('refresh-calendars').disabled=!calendarConnected(google);
 $('sync-all-meetings').disabled=!state.settings.calendar_enabled||!calendarConnected(google);
}
async function loadCalendars() {
 const selected=$('calendar-id').value||state.settings.calendar_id;
 const calendars=await api('/api/calendar/calendars');$('calendar-id').replaceChildren();
 const empty=el('option','','Choose a calendar…');empty.value='';$('calendar-id').append(empty);
 for(const calendar of calendars){const option=el('option','',calendar.name+(calendar.primary?' · primary':''));option.value=calendar.id;$('calendar-id').append(option);}
 // After first sign-in, suggest the primary calendar.
 $('calendar-id').value=selected||calendars.find(c=>c.primary)?.id||'';
}
$('google-client-file').onchange=()=>perform(async()=>{const file=$('google-client-file').files[0];if(!file)return;if(file.size>50000)throw new Error('Choose a Google Desktop OAuth client JSON file.');const credentials=JSON.parse(await file.text());await api('/api/calendar/credentials',{credentials});$('google-client-file').value='';state=await api('/api/state');renderGoogleStatus();toast('OAuth client saved in macOS Keychain · you can sign in now');});
$('google-connect').onclick=()=>perform(async()=>{const result=await api('/api/calendar/connect',{});$('google-auth-link').href=result.authorization_url;$('google-auth-link').hidden=false;toast('Continue Google sign-in in your browser');});
$('google-disconnect').onclick=()=>perform(async()=>{await api('/api/calendar/disconnect',{});state=await api('/api/state');renderGoogleStatus();$('google-auth-link').hidden=true;toast('Signed out of Google');});
$('refresh-calendars').onclick=()=>perform(loadCalendars);
$('add-speaker').onclick=()=>perform(async()=>{const name=$('new-speaker').value.trim();if(!name)return;await saveSpeakers([...(state.speakers||[]),name]);$('new-speaker').value='';$('new-speaker').focus();});
$('new-speaker').onkeydown=event=>{if(event.key==='Enter'){event.preventDefault();$('add-speaker').click();}};
$('add-tracker').onclick=()=>{trackersData.push({id:'',name:'',phrases:[],semantic_matching:false});renderTrackers();$('tracker-list').lastElementChild.querySelector('input').focus();};
$('save-trackers').onclick=()=>perform(saveTrackers);
$('delete-meeting').onclick=()=>perform(async()=>{
 const id=selected, title=detail.title;
 if(!(await ask('Delete "'+title+'"?\n\nThe recording, transcript, notes and all other files of this meeting are removed from this Mac. You cannot undo this.',{ok:'Delete meeting',danger:true}))) return;
 const calendar_event=!!detail.calendar_sync?.event_id&&await ask('Also delete the Google Calendar event of this meeting?',{ok:'Delete event',cancel:'Keep event',danger:true});
 await api('/api/meetings/'+id+'/delete',{calendar_event});
 $('audio').pause();$('audio').removeAttribute('src');
 dirtyTranscript=dirtyNotes=false;detail=null;selected=null;history.replaceState(null,'','/');
 if(window.searchResults) window.searchResults=window.searchResults.filter(m=>m.id!==id);
 show(state?.active?'recording':'setup');if(state?.active)selected=state.active.id;
 state=await api('/api/state');lastLibrary='';renderState();toast('Meeting deleted');
});
$('sync-all-meetings').onclick=()=>perform(async()=>{const result=await api('/api/calendar/sync-all',{});toast(result.queued+' saved meetings queued for calendar sync');});
$('auto-title').onchange=$('calendar-enabled').onchange=settingsFields;
$('title-provider').onchange=()=>{$('title-model').value=$('title-provider').value==='openai'?'gpt-4.1-mini':'gpt-4.1-mini';settingsFields();};
$('generate-title').onclick=()=>perform(async()=>{await api('/api/meetings/'+selected+'/title',{});toast('AI title queued');await openMeeting(selected,true);});
$('sync-calendar').onclick=()=>perform(async()=>{await api('/api/meetings/'+selected+'/calendar',{});toast('Calendar sync queued');await openMeeting(selected,true);});
$('forget-key').onclick=()=>perform(async()=>{await api('/api/settings',{api_key:''});state.api_key_configured=false;$('key-state').textContent='';$('forget-key').disabled=true;toast('API key removed from app memory');});
window.addEventListener('beforeunload',event=>{if(state?.active||hasEdits()){event.preventDefault();event.returnValue='';}});
listen();

// A visible list: the desktop window (WKWebView) shows datalist suggestions poorly or not at all.
let localModels=[];
function renderLocalModels() {
 const current=$('local-ai-model').value.trim();
 $('local-ai-model-list').replaceChildren(...localModels.map(id=>{
  const button=el('button','model-option'+(id===current?' selected':''),id); button.type='button'; button.setAttribute('role','listitem'); button.setAttribute('aria-pressed',String(id===current));
  if(/embed/i.test(id)) button.append(el('span','model-tag','embedding'));
  button.onclick=()=>{$('local-ai-model').value=id;renderLocalModels();$('local-ai-status').textContent='Selected '+id+'. Save settings to use it.';};
  return button;}));
}
$('local-ai-model').addEventListener('input',renderLocalModels);
$('load-local-models').onclick=()=>perform(async()=>{const button=$('load-local-models');button.disabled=true;$('local-ai-status').textContent='Connecting…';try{const result=await api('/api/local-ai/models',{base_url:$('local-ai-base-url').value.trim()});$('local-ai-models').replaceChildren(...result.models.map(id=>{const option=document.createElement('option');option.value=id;return option;}));localModels=result.models;$('local-ai-status').textContent=result.models.length+' models available. Click one to use it; embedding models cannot generate notes.';if(result.models.length===1)$('local-ai-model').value=result.models[0];renderLocalModels();}catch(error){$('local-ai-status').textContent='Could not load models. Check the endpoint and server.';throw error;}finally{button.disabled=false;}});

$('audio-source').onchange=()=>{if(!detail)return;const audio=$('audio'),position=audio.currentTime,playing=!audio.paused;audio.src='/files/'+detail.id+'/'+$('audio-source').value;audio.currentTime=position;if(playing)audio.play().catch(e=>error(e.message));};
