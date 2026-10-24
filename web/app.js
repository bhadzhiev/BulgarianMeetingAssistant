'use strict';
const $ = id => document.getElementById(id);
let state, selected = null, detail = null, view = 'setup', dirtyTranscript = false, dirtyNotes = false;
let lastFingerprint = '', lastLibrary = '', lastDevices = '', pending = false;
let liveMeetingId = null, liveSignature = '', lastSpeakers = '', settingsTab = 'recording';
let taskFilter = 'open', tasksData = [], lastTasks = '';
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
function error(message) { const target=$('settings-dialog').open?$('settings-error'):$('error'); target.textContent=message; target.hidden=false; }
function clearError() { $('error').hidden=true; $('settings-error').hidden=true; }
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
function hasEdits() { return dirtyTranscript || dirtyNotes; }
function leaveEdits() { return !hasEdits() || window.confirm('Leave without saving your corrections?'); }
function show(which) { view=which; for(const id of ['setup','recording','detail','tasks','analytics']) $(id).hidden=id!==which; $('open-tasks').classList.toggle('current',which==='tasks'); $('open-analytics').classList.toggle('current',which==='analytics'); }
function renderLibrary() {
 const query=$('search').value.toLocaleLowerCase();
 const meetings=state.meetings.filter(m=>!query||m.title.toLocaleLowerCase().includes(query));
 // Server searches transcript content on demand; retain the regular status snapshot.
 const rows=query && window.searchResults ? window.searchResults : meetings;
 const signature=JSON.stringify([rows,selected,view]); if(signature===lastLibrary) return; lastLibrary=signature;
 $('library').replaceChildren();
 if(!rows.length) $('library').append(el('p','empty-library',query?'No matching meetings.':'Your meetings will appear here.'));
 for(const m of rows) { const button=el('button','meeting-item'+(m.id===selected&&view==='detail'?' current':'')); button.append(el('strong','',m.title),el('small','',(m.title.includes(date(m.created))?'':date(m.created)+' · ')+(statusNames[m.status]||m.status))); button.onclick=()=>perform(()=>openMeeting(m.id)); $('library').append(button); }
}
async function openMeeting(id,force=false) {
 if(!force&&!leaveEdits()) return;
 if(state.active?.id===id) { selected=id; show('recording'); renderState(); return; }
 selected=id; history.replaceState(null,'','/?meeting='+id); dirtyTranscript=dirtyNotes=false; if(detail?.id!==id){notesEditing=false;questionFilter='open';questionLimit=10;} detail=await api('/api/meetings/'+id); lastFingerprint=JSON.stringify(detail); renderDetail(); show('detail'); renderLibrary();
}
function renderState() {
 syncSpeakers();
 const summary=state.task_summary||{open:0,overdue:0};
 $('tasks-badge').hidden=!summary.open; $('tasks-badge').classList.toggle('late',summary.overdue>0);
 $('tasks-badge').textContent=summary.overdue?summary.overdue+' late':summary.open;
 $('connection').textContent=state.active?'● Recording workspace':'● Connected to this Mac';
 const signature=JSON.stringify(state.devices);
 if(signature!==lastDevices) { lastDevices=signature; const old=$('microphone').value; $('microphone').replaceChildren(); for(const d of state.devices) { const option=el('option','',d.name); option.value=d.id; $('microphone').append(option); } if(!state.devices.length){const option=el('option','','No microphone available');option.value='';$('microphone').append(option);} else { const preferred=state.devices.find(d=>String(d.id)===old)||state.devices.find(d=>/iphone/i.test(d.name)); if(preferred) $('microphone').value=preferred.id; } }
 $('start').disabled=!!state.active||!state.devices.length||pending;
 $('check-mic').disabled=!!state.active||!state.devices.length;
 $('setup-meter').value=state.preview_level;
 $('mic-hint').textContent=state.preview_active?'Listening for 10 seconds · nothing is saved':state.device_error||'Test your microphone before recording';
 const s=state.settings;
 $('meeting-title').placeholder=s.auto_title!==false?'Leave blank for an AI-generated title':'Meeting name (optional)';
 $('processing-name').textContent=(s.transcription==='local'?'Local Whisper':'OpenAI cloud')+' · '+(s.summarizer==='none'?'transcript only':s.summarizer==='local'?'local notes':'cloud notes');
 $('privacy-copy').textContent=privacy(s);
 if($('settings-dialog').open){renderGoogleStatus();if(state.google?.connected&&!lastGoogleConnected)perform(loadCalendars);}
 lastGoogleConnected=!!state.google?.connected;
 if(state.active) {
  const a=state.active; $('recording-title').textContent=a.title; $('recording-mode').textContent=a.mode==='online'?'ONLINE · MAC AUDIO + MICROPHONE':'IN PERSON · MICROPHONE';
  $('recording-status').textContent=statusNames[a.status]||a.status; $('timer').textContent=time(a.duration); $('recording-meter').value=a.level||0;
  const enabled=['recording','paused'].includes(a.status); $('pause').disabled=$('stop').disabled=!enabled;
  $('pause').textContent=a.status==='paused'?'▶ Resume':'Ⅱ Pause'; $('recording-indicator').classList.toggle('paused',a.status!=='recording');
  $('recording-help').textContent=a.status==='starting'?'Preparing audio capture. macOS may request recording permission.':a.status==='paused'?'Paused. Audio during the pause is discarded.':a.status==='stopping'?'Finishing audio files. Please keep the app open.':'Audio is being saved continuously on this Mac.';
  renderLive(a);
  if(view==='setup') { selected=a.id; show('recording'); }
 } else if(view==='recording' && selected) { perform(()=>openMeeting(selected,true)); }
 renderLibrary();
}
function captionRow(segment, provisional=false, ended=false) {
 const row=el('div','live-segment'+(provisional?' provisional':''));
 row.append(el('span','live-time',time(segment.start)),el('p','',segment.text));
 if(provisional) row.append(el('span','live-provisional',ended?'Unconfirmed draft':'Still speaking…'));
 return row;
}
function renderLive(active) {
 const live=active.live;
 const disabled=active.settings?.live_transcription===false;
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
 $('detail-title').textContent=d.title; $('detail-date').textContent=date(d.created)+' · '+(d.mode==='online'?'Online meeting':d.mode==='imported'?'Imported transcript':'In-person meeting')+(d.duration?' · '+shortDuration(d.duration):''); $('detail-status').textContent=statusNames[d.status]||d.status;
 const titleMessages={pending:'AI title pending',generating:'Generating AI title…',generated:'AI-generated title',waiting:'AI title waiting for a transcript',manual:'',error:'AI title could not be generated'};
 $('title-status').textContent=(titleMessages[d.title_status]||'')+(d.title_error?' · '+d.title_error:'');$('title-status').hidden=!$('title-status').textContent;
 const sync=d.calendar_sync; $('calendar-status').hidden=!sync;$('calendar-status').replaceChildren();
 if(sync){$('calendar-status').append(el('span','',sync.status==='synced'?'Saved in Google Calendar':sync.status==='error'?'Calendar sync needs attention: '+sync.error:'Calendar sync pending…'));if(sync.status==='synced'&&sync.html_link){const url=new URL(sync.html_link);if(url.protocol==='https:'&&['www.google.com','calendar.google.com'].includes(url.hostname)){const link=el('a','',' Open event ↗');link.href=url.href;link.target='_blank';link.rel='noopener noreferrer';$('calendar-status').append(link);}}}
 $('generate-title').disabled=busy||d.title_status==='generating'||(!d.transcript.length&&!d.live?.segments?.length);
 $('sync-calendar').disabled=busy||(!sync&&!state.settings.calendar_enabled);
 $('sync-calendar').textContent=sync?.status==='synced'?'Update calendar event':'Sync to Google Calendar';
 // The status badge already says Ready; the bar is only for progress and extra advice.
 $('job-progress').textContent=d.progress||''; $('job-progress').hidden=!d.progress||d.progress===statusNames[d.status]||['Imported','Recording saved'].includes(d.progress); $('detail-error').hidden=!d.error; $('detail-error').textContent=d.error||'';
 const audioURL='/files/'+d.id+'/recording.wav';
 if(d.files.includes('recording.wav')) { if(!$('audio').src.endsWith(audioURL)) $('audio').src=audioURL; $('audio').hidden=false; $('audio-unavailable').hidden=true; }
 else { $('audio').removeAttribute('src'); $('audio').hidden=true; $('audio-unavailable').hidden=false; }
 $('playback').hidden=d.mode==='imported';
 $('exports').replaceChildren(); $('files-menu').hidden=!d.files.length; for(const name of d.files) { const row=el('div','file-row'), a=el('a','',name==='recording.wav'?'↓ Audio (WAV)':'↓ '+name); a.href='/files/'+d.id+'/'+name; a.download=name; row.append(a); if(name.endsWith('.md')) { const v=el('button','view-file','View'); v.type='button'; v.setAttribute('aria-label','View '+name); v.onclick=()=>perform(()=>openViewer(d.id,name)); row.append(v); } $('exports').append(row); }
 for(const id of ['process','summarize','recover','edit-title','delete-meeting']) $(id).disabled=busy;
 $('correct').disabled=busy||!d.transcript.length; $('correct').hidden=state.settings.transcript_correction==='none'&&!d.transcript_raw;
 const fix=d.transcript_metadata?.correction;
 $('correction-status').hidden=!fix&&!d.correction_error;
 $('correction-status').textContent=d.correction_error?'AI correction failed · the Whisper transcript is shown. '+d.correction_error:fix?'AI corrected '+fix.changed+(fix.changed===1?' segment':' segments')+(fix.rejected?' · '+fix.rejected+' larger changes were refused':'')+'. Marked segments show the original Whisper text; click ↺ to restore it.':'';
 $('correction-status').classList.toggle('warning',!!d.correction_error);
 $('recover').hidden=d.mode==='imported'||!!d.files.includes('recording.wav')&&!['interrupted','error'].includes(d.status);$('process').hidden=d.mode==='imported';
 $('summarize').disabled=busy||!d.transcript.length;
 $('process').textContent=d.transcript.length?'Transcribe again':'Transcribe';
 placeActions(d);
 $('timestamp-note').textContent=d.transcript_metadata?.timestamps==='approximate chunk boundaries'?'Cloud timestamps mark approximate audio chunks. Click a time to listen.':'Click a timestamp to listen. Correct the text or add a speaker label below.';
 $('transcript').replaceChildren();
 if(!d.transcript.length) $('transcript').append(el('p','empty-content',d.live?.segments?.length?'Your saved live draft is below. The final transcript appears after processing.':busy?'Your transcript will appear here when processing finishes.':'Your recording is saved. Choose Transcribe to turn it into text.'));
 d.transcript.forEach((s,index)=>{ const row=el('div','segment');const seek=el('button','',time(s.start)+' ▶');seek.setAttribute('aria-label','Play from '+time(s.start));seek.onclick=()=>{ $('audio').currentTime=s.start; $('audio').play().catch(e=>error(e.message)); }; const content=el('div');const speaker=el('input','speaker');speaker.placeholder='Speaker (optional)';speaker.value=s.speaker||'';speaker.setAttribute('list','known-speakers');speaker.setAttribute('aria-label','Speaker for segment '+(index+1));speaker.disabled=busy;const badge=el('span');const annotate=()=>{speakerBadge(badge,speaker.value);row.classList.toggle('known-speaker',!!knownSpeaker(speaker.value));};annotate();speaker.oninput=()=>{s.speaker=speaker.value.trim()||null;annotate();renderSpeakerLegend();markTranscript();};const who=el('div','speaker-line');who.append(badge,speaker);const original=d.transcript_raw?.length===d.transcript.length?d.transcript_raw[index]:null;if(original&&original.text!==s.text){row.classList.add('ai-corrected');const restore=el('button','quiet restore-original','AI ↺');restore.title='Restore Whisper text: '+original.text;restore.setAttribute('aria-label','Restore original Whisper text for segment '+(index+1));restore.disabled=busy;restore.onclick=()=>{s.text=original.text;text.value=original.text;row.classList.remove('ai-corrected');restore.remove();markTranscript();};who.append(restore);}const text=el('textarea');text.value=s.text;text.setAttribute('aria-label','Transcript segment '+(index+1));text.disabled=busy;text.rows=Math.max(2,Math.ceil(s.text.length/85));text.oninput=()=>{s.text=text.value;markTranscript();};content.append(who,text);row.append(seek,content);$('transcript').append(row); });
 renderSpeakerLegend();
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
function stampButton(stamp) { const button=el('button','quiet stamp',stamp+' ▶'); button.type='button'; button.title='Show this moment in the transcript'; button.onclick=()=>showMoment(stamp); return button; }
// AI notes cite moments as (00:29:46); make them links to the transcript.
function linkedText(target,text) { text.split(/\(?\b(\d{2}:\d{2}:\d{2})\b\)?/).forEach((part,i)=>target.append(i%2?stampButton(part):document.createTextNode(part))); return target; }
function noteSection(minutes,field,title,busy,hint) {
 const section=el('section','note-section'+(field==='observations'?' private-notes':''));
 section.append(el('h3','',title)); if(hint) section.append(el('p','hint',hint));
 const items=minutes[field]||[];
 if(!notesEditing) {
  if(!items.length) section.append(el('p','empty-note','Nothing recorded.'));
  else { const list=el('ul','note-list'); for(const item of items) list.append(linkedText(el('li'),item)); section.append(list); }
  return section;
 }
 const area=el('textarea');
 area.value=items.join('\n');area.setAttribute('aria-label',title+' · one item per line');area.disabled=busy;area.placeholder='One item per line';
 area.rows=Math.max(3,items.reduce((rows,item)=>rows+Math.ceil((item.length+1)/90),1));
 area.oninput=()=>{minutes[field]=area.value.split('\n').filter(s=>s.trim());area.style.height='auto';area.style.height=area.scrollHeight+2+'px';markNotes();};
 section.append(area); return section;
}
function taskRow(task,index,busy) {
 const today=state.task_summary?.today||new Date().toISOString().slice(0,10), [kind,label]=dueInfo(task,today);
 const row=el('div','tracked-task '+kind), done=el('input'); done.type='checkbox'; done.checked=task.status==='done'; done.disabled=busy; done.setAttribute('aria-label','Mark task as done');
 done.onchange=()=>perform(async()=>{await api('/api/meetings/'+detail.id+'/task',{index,task:task.task,changes:{status:done.checked?'done':'open'}});await openMeeting(detail.id,true);});
 const main=el('div','tracked-main'), meta=el('div','tracked-meta'), who=el('span','tracked-owner');
 who.append(speakerBadge(el('span'),task.owner||''),el('span','',task.owner||'No owner'));
 meta.append(who,el('span','due-label '+kind,task.due_date&&task.status!=='done'?label+' · '+task.due_date:label));
 if(task.deadline) meta.append(el('span','hint','Said: '+task.deadline));
 if(task.evidence_timestamp) meta.append(stampButton(task.evidence_timestamp));
 main.append(el('p','tracked-text',task.task||'Untitled task'),meta); row.append(done,main); return row;
}
function renderNotes(busy=false) {
 $('notes').replaceChildren();$('outcomes').replaceChildren();
 if(!detail.minutes||busy) notesEditing=false;
 for(const name of ['notes','outcomes']) { $('edit-'+name).hidden=notesEditing||!detail.minutes; $('edit-'+name).disabled=busy; $('save-'+name).hidden=$('cancel-'+name).hidden=!notesEditing; $('save-'+name).disabled=!dirtyNotes; }
 if(!detail.minutes) { for(const id of ['notes','outcomes']) $(id).append(el('p','empty-content','Generate meeting notes to see the decisions, tasks, unresolved questions and next steps.')); return; }
 const minutes=detail.minutes;
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
  name.append(speakerBadge(el('span'),row.speaker),el('strong','',row.speaker));heading.append(name);box.append(heading);
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
function showSettingsTab(name) {
 settingsTab=name;
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
function openSettings(tab) { if(!state)return; clearError(); const s=state.settings;$('local-ai-base-url').value=s.local_ai_base_url;$('local-ai-model').value=s.local_ai_model;$('local-ai-format').value=s.local_ai_format;$('local-ai-reasoning').value=s.local_ai_reasoning;$('local-ai-max-tokens').value=s.local_ai_max_tokens;$('local-ai-status').textContent='';$('provider').value=s.transcription;$('local-model').value=s.local_model;$('whisper-vad').checked=s.whisper_vad!==false;$('whisper-vocabulary').value=s.whisper_vocabulary||'';$('cloud-model').value=s.cloud_model;$('summarizer').value=s.summarizer;$('transcript-correction').value=s.transcript_correction||'none';$('llm-model').value=s.llm_model;$('auto-process').checked=s.auto_process;$('live-enabled').checked=s.live_transcription!==false;$('diarization-enabled').checked=s.diarization_enabled!==false;$('auto-title').checked=s.auto_title!==false;$('title-provider').value=s.title_provider||'local';$('title-model').value=s.title_model||'gpt-4.1-mini';$('calendar-enabled').checked=!!s.calendar_enabled;$('calendar-id').replaceChildren();const initialCalendar=el('option','',s.calendar_name||'Choose a calendar…');initialCalendar.value=s.calendar_id||'';$('calendar-id').append(initialCalendar);$('api-key').value='';$('forget-key').disabled=!state.api_key_configured;$('key-state').textContent=state.api_key_configured?'· configured':'';settingsFields();renderGoogleStatus();renderSpeakerSettings();trackersData=JSON.parse(JSON.stringify(state.trackers||[]));renderTrackers();$('new-speaker').value='';showSettingsTab(typeof tab==='string'?tab:settingsTab);$('settings-dialog').showModal();if(state.google?.connected)perform(loadCalendars); }
function daysBetween(from,to) { return Math.round((Date.parse(to)-Date.parse(from))/86400000); }
function dueInfo(task,today) {
 if(task.status==='done') return ['done','Done'];
 if(!task.due_date) return ['undated','No date'];
 const days=daysBetween(today,task.due_date);
 if(days<0) return ['overdue','Overdue · '+(-days)+(days===-1?' day':' days')];
 if(days===0) return ['today','Due today'];
 return [days<=7?'soon':'later','Due in '+days+(days===1?' day':' days')];
}
async function loadTasks() { const fresh=await api('/api/tasks'); const signature=JSON.stringify(fresh); if(signature===lastTasks) return; lastTasks=signature; tasksData=fresh; renderTasks(); }
function renderTasks() {
 const today=state.task_summary?.today||new Date().toISOString().slice(0,10);
 const open=tasksData.filter(t=>t.status==='open'), late=open.filter(t=>t.due_date&&t.due_date<today);
 const week=open.filter(t=>t.due_date&&t.due_date>=today&&daysBetween(today,t.due_date)<=7);
 $('tasks-summary').textContent=open.length+' open · '+late.length+' overdue · '+week.length+' due in the next 7 days';
 const owner=$('task-owner').value, owners=[...new Set(tasksData.map(t=>t.owner).filter(Boolean))].sort((a,b)=>a.localeCompare(b));
 $('task-owner').replaceChildren(option('All owners',''),...owners.map(name=>option(name,name)),option('No owner','__none__'));
 $('task-owner').value=[...$('task-owner').options].some(o=>o.value===owner)?owner:'';
 for(const button of document.querySelectorAll('[data-filter]')) button.classList.toggle('selected',button.dataset.filter===taskFilter);
 const rows=tasksData.filter(t=>taskFilter==='all'||(taskFilter==='done'?t.status==='done':t.status==='open'&&(taskFilter==='open'||t.due_date&&t.due_date<today)))
  .filter(t=>!$('task-owner').value||($('task-owner').value==='__none__'?!t.owner:t.owner===$('task-owner').value))
  .sort((a,b)=>(a.status===b.status?0:a.status==='open'?-1:1)||(a.due_date||'9999').localeCompare(b.due_date||'9999')||b.meeting_date.localeCompare(a.meeting_date));
 $('task-list').replaceChildren();
 if(!rows.length) $('task-list').append(el('p','empty-content',tasksData.length?'No tasks match this filter.':'No tasks yet. Generate notes for a meeting to collect its tasks here.'));
 for(const task of rows) {
  const [kind,label]=dueInfo(task,today);
  const row=el('div','tracked-task '+kind);
  const done=el('input');done.type='checkbox';done.checked=task.status==='done';done.setAttribute('aria-label','Mark task as done');
  done.onchange=()=>perform(()=>updateTask(task,{status:done.checked?'done':'open'}));
  const main=el('div','tracked-main'),text=el('p','tracked-text',task.task);main.append(text);
  const edit=el('button','quiet','Edit'),remove=el('button','quiet danger-text','Delete'),actions=el('div','tracked-actions');actions.append(edit,remove);
  edit.onclick=()=>{const box=el('textarea','tracked-edit');box.value=task.task;box.setAttribute('aria-label','Task text');const save=el('button','primary','Save'),cancel=el('button','secondary','Cancel'),bar=el('div','tracked-edit-bar');bar.append(save,cancel);
   const close=()=>{box.replaceWith(text);bar.remove();actions.hidden=false;};
   save.onclick=()=>{const value=box.value.trim();if(!value){box.focus();return;}if(value===task.task){close();return;}save.disabled=true;perform(()=>updateTask(task,{task:value})).finally(()=>save.disabled=false);};
   cancel.onclick=close;box.onkeydown=event=>{if(event.key==='Escape'){event.stopPropagation();close();}if(event.key==='Enter'&&(event.metaKey||event.ctrlKey))save.click();};
   text.replaceWith(box);box.after(bar);actions.hidden=true;box.focus();};
  remove.onclick=()=>{if(confirm('Delete this task from "'+task.meeting_title+'"?\n\n'+task.task))perform(()=>deleteTask(task));};
  const meta=el('div','tracked-meta');
  const who=el('span','tracked-owner');who.append(speakerBadge(el('span'),task.owner||''),el('span','',task.owner||'No owner'));
  const due=el('input');due.type='date';due.value=task.due_date||'';due.setAttribute('aria-label','Due date');
  due.onchange=()=>perform(()=>updateTask(task,{due_date:due.value||null}));
  meta.append(who,el('span','due-label '+kind,label),due);
  if(task.deadline) meta.append(el('span','hint','Said: '+task.deadline));
  const source=el('button','quiet tracked-source','↗ '+withDate(task.meeting_title,task.meeting_date)+' · '+task.evidence_timestamp);source.title='Open the meeting';
  source.onclick=()=>perform(async()=>{await openMeeting(task.meeting_id);switchTab('outcomes');});
  meta.append(source);main.append(meta);row.append(done,main,actions);$('task-list').append(row);
 }
}
async function deleteTask(task) {
 await api('/api/meetings/'+task.meeting_id+'/delete-task',{index:task.index,task:task.task});
 lastTasks='';await loadTasks();state=await api('/api/state');renderState();toast('Task deleted');
}
async function updateTask(task,changes) {
 await api('/api/meetings/'+task.meeting_id+'/task',{index:task.index,task:task.task,changes});
 lastTasks='';await loadTasks();state=await api('/api/state');renderState();
}
async function poll() { try { state=await api('/api/state');renderState();if(!initialRouteHandled){initialRouteHandled=true;if(requestedMeeting&&/^[a-f0-9]{32}$/.test(requestedMeeting))await perform(()=>openMeeting(requestedMeeting,true));}if(view==='tasks') await loadTasks(); if(view==='detail'&&selected&&!hasEdits()) { const fresh=await api('/api/meetings/'+selected);const fingerprint=JSON.stringify(fresh);if(fingerprint!==lastFingerprint){detail=fresh;lastFingerprint=fingerprint;renderDetail();} } }catch(e){$('connection').textContent='Disconnected · reopen the launcher';}finally{setTimeout(poll,1000);} }
$('open-tasks').onclick=()=>perform(async()=>{if(!leaveEdits())return;dirtyTranscript=dirtyNotes=false;selected=null;history.replaceState(null,'','/');show('tasks');lastTasks='';await loadTasks();renderLibrary();});
$('open-analytics').onclick=()=>perform(async()=>{if(!leaveEdits())return;dirtyTranscript=dirtyNotes=false;selected=null;history.replaceState(null,'','/');show('analytics');await loadAnalytics();renderLibrary();});
$('analytics-apply').onclick=()=>perform(loadAnalytics);
$('analytics-reset').onclick=()=>perform(async()=>{for(const id of ['analytics-from','analytics-to','analytics-speaker','analytics-topic'])$(id).value='';await loadAnalytics();});
for(const button of document.querySelectorAll('[data-filter]')) button.onclick=()=>{taskFilter=button.dataset.filter;renderTasks();};
$('task-owner').onchange=renderTasks;
$('new-meeting').onclick=()=>{if(!leaveEdits())return;dirtyTranscript=dirtyNotes=false;selected=null;history.replaceState(null,'','/');show(state?.active?'recording':'setup');if(state?.active)selected=state.active.id;renderLibrary();};
let searchTimer; $('search').oninput=()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>perform(async()=>{const q=$('search').value.trim();if(q){window.searchResults=await api('/api/search?q='+encodeURIComponent(q));}else window.searchResults=null;lastLibrary='';renderLibrary();}),200);};
for(const radio of document.querySelectorAll('input[name=mode]'))radio.onchange=()=>{$('mode-help').textContent=radio.value==='online'?'Captures audio from all Mac apps plus your microphone. Use headphones to avoid echo. macOS requires Screen & System Audio Recording permission.':'Place your iPhone near the centre of the table, or use your Mac microphone.';};
$('check-mic').onclick=()=>perform(async()=>{await api('/api/check-mic',{device:Number($('microphone').value)});toast('Microphone test started · 10 seconds');});
$('record-form').onsubmit=event=>{event.preventDefault();perform(async()=>{pending=true;$('start').disabled=true;try{const m=await api('/api/start',{title:$('meeting-title').value,mode:document.querySelector('input[name=mode]:checked').value,device:Number($('microphone').value)});selected=m.id;state.active=m;renderState();show('recording');}finally{pending=false;}});};
async function importTranscript(text,filename) {
 const d=await api('/api/import',{text,filename});
 $('import-file').value='';$('import-text').value='';$('import-button').disabled=$('import-paste-button').disabled=true;
 toast('Transcript imported · '+d.transcript.length+' segments');state=await api('/api/state');renderState();await openMeeting(d.id,true);
}
$('import-file').onchange=()=>{$('import-button').disabled=!$('import-file').files.length;};
$('import-button').onclick=()=>perform(async()=>{const file=$('import-file').files[0];if(!file)return;if(file.size>5_000_000)throw new Error('Choose a transcript file of at most 5 MB');$('import-button').disabled=true;try{await importTranscript(await file.text(),file.name);}finally{$('import-button').disabled=!$('import-file').files.length;}});
$('import-text').oninput=()=>{$('import-paste-button').disabled=!$('import-text').value.trim();};
$('import-paste-button').onclick=()=>perform(async()=>{$('import-paste-button').disabled=true;try{await importTranscript($('import-text').value,'');}finally{$('import-paste-button').disabled=!$('import-text').value.trim();}});
$('pause').onclick=()=>perform(()=>api('/api/pause',{paused:state.active.status!=='paused'}));$('stop').onclick=()=>perform(()=>api('/api/stop',{}));
for(const [id,action] of [['process','transcribe'],['summarize','summarize'],['recover','recover'],['correct','correct']])$(id).onclick=()=>perform(async()=>{if(!leaveEdits())return;if(action==='summarize'&&state.settings.summarizer==='none'){openSettings('notes');toast('Choose a meeting-notes provider first');return;}await api('/api/meetings/'+selected+'/process',{action});dirtyNotes=dirtyTranscript=false;toast('Processing queued');await openMeeting(selected,true);});
$('edit-title').onclick=()=>perform(async()=>{const title=window.prompt('Meeting name',detail.title);if(title?.trim()){await api('/api/meetings/'+selected+'/edit',{title});await openMeeting(selected,true);}});
$('save-transcript').onclick=()=>perform(async()=>{detail=await api('/api/meetings/'+selected+'/edit',{transcript:detail.transcript});dirtyTranscript=false;lastFingerprint=JSON.stringify(detail);renderDetail();toast('Transcript corrections saved');});
$('save-notes').onclick=$('save-outcomes').onclick=()=>perform(async()=>{detail=await api('/api/meetings/'+selected+'/edit',{minutes:detail.minutes});dirtyNotes=false;notesEditing=false;lastFingerprint=JSON.stringify(detail);renderDetail();toast('Meeting notes saved');});
for(const name of ['notes','outcomes']) {
 $('edit-'+name).onclick=()=>{notesEditing=true;renderNotes(false);};
 $('cancel-'+name).onclick=()=>perform(async()=>{if(dirtyNotes&&!confirm('Discard your changes to the notes?'))return;notesEditing=false;await openMeeting(selected,true);});
}
$('reanalyze').onclick=()=>perform(async()=>{if(!leaveEdits())return;await api('/api/meetings/'+selected+'/reanalyze',{});dirtyTranscript=dirtyNotes=false;toast('Analytics queued');await openMeeting(selected,true);});
for(const tab of ['transcript','outcomes','notes','analytics']) $('tab-'+tab).onclick=()=>switchTab(tab);
$('settings-open').onclick=()=>openSettings();$('settings-inline').onclick=()=>openSettings('recording');
for(const tab of document.querySelectorAll('.settings-tabs button')) tab.onclick=()=>showSettingsTab(tab.dataset.tab);
// A required field on a hidden tab would block saving without a visible message.
$('settings-save').onclick=event=>{const invalid=$('settings-form').querySelector('input:invalid,select:invalid,textarea:invalid');if(invalid){event.preventDefault();showSettingsTab(invalid.closest('.settings-panel').dataset.tab);invalid.reportValidity();}};$('settings-close').onclick=()=>$('settings-dialog').close();$('provider').onchange=settingsFields;$('summarizer').onchange=()=>{$('llm-model').value=$('summarizer').value==='openai'?'gpt-4.1-mini':'gpt-4.1-mini';settingsFields();};$('transcript-correction').onchange=settingsFields;
$('settings-form').onsubmit=event=>{event.preventDefault();perform(async()=>{const body={local_ai_base_url:$('local-ai-base-url').value.trim(),local_ai_model:$('local-ai-model').value.trim(),local_ai_format:$('local-ai-format').value,local_ai_reasoning:$('local-ai-reasoning').value,local_ai_max_tokens:Number($('local-ai-max-tokens').value),transcription:$('provider').value,local_model:$('local-model').value,whisper_vad:$('whisper-vad').checked,whisper_vocabulary:$('whisper-vocabulary').value.trim(),cloud_model:$('cloud-model').value,summarizer:$('summarizer').value,transcript_correction:$('transcript-correction').value,llm_model:$('llm-model').value,auto_process:$('auto-process').checked,live_transcription:$('live-enabled').checked,diarization_enabled:$('diarization-enabled').checked,auto_title:$('auto-title').checked,title_provider:$('title-provider').value,title_model:$('title-model').value,calendar_enabled:$('calendar-enabled').checked,calendar_id:$('calendar-id').value};if($('api-key').value.trim())body.api_key=$('api-key').value.trim();await api('/api/settings',body);$('api-key').value='';$('settings-dialog').close();toast('Settings saved');state=await api('/api/state');renderState();});};

function renderGoogleStatus() {
 const google=state.google||{};
 $('google-status').textContent=(google.connected?'Signed in as '+google.account:google.sign_in_available?'Not signed in. Sign in with your Google account to add meetings to your calendar.':'Google sign-in is not set up for this app yet. See README → Google Calendar, or use Advanced below.')+(google.error?' · '+google.error:'');
 $('google-connect').disabled=!google.sign_in_available;$('google-connect').textContent=google.connected?'Switch Google account':'Sign in with Google';$('google-disconnect').disabled=!google.connected;
 if(!google.sign_in_available) $('google-advanced').open=true;
 $('refresh-calendars').disabled=!google.connected;
 $('sync-all-meetings').disabled=!state.settings.calendar_enabled||!google.connected;
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
 if(!window.confirm('Delete "'+title+'"?\n\nThe recording, transcript, notes and all other files of this meeting are removed from this Mac. You cannot undo this.')) return;
 const calendar_event=!!detail.calendar_sync?.event_id&&window.confirm('Also delete the Google Calendar event of this meeting?\n\nOK deletes the event. Cancel keeps the event.');
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
poll();

$('load-local-models').onclick=()=>perform(async()=>{const button=$('load-local-models');button.disabled=true;$('local-ai-status').textContent='Connecting…';try{const result=await api('/api/local-ai/models',{base_url:$('local-ai-base-url').value.trim()});$('local-ai-models').replaceChildren(...result.models.map(id=>{const option=document.createElement('option');option.value=id;return option;}));$('local-ai-status').textContent=result.models.length+' models available. Choose a text/chat model above; embedding models cannot generate notes.';if(result.models.length===1)$('local-ai-model').value=result.models[0];}catch(error){$('local-ai-status').textContent='Could not load models. Check the endpoint and server.';throw error;}finally{button.disabled=false;}});
