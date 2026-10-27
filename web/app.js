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
let initialRouteHandled=false, lastGoogleConnected=false;
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
function knownSpeaker(name) { const key=(name||'').trim().toLocaleLowerCase();if(/^speaker[ _-]?\d+$/i.test(key))return null; return key?(state?.speakers||[]).find(n=>n.toLocaleLowerCase()===key):undefined; }
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
 if($('settings-dialog').open){ renderSpeakerSettings(); renderPeople(); }
 // Re-annotate the open meeting unless that would discard typing.
 if(view==='detail'&&detail&&!hasEdits()) renderDetail();
}
function renderSpeakerLegend() {
 const target=$('speaker-legend'), counts=new Map(); target.replaceChildren();
 for(const s of detail.transcript) { if(!s.speaker) continue; const name=knownSpeaker(s.speaker)||s.speaker.trim(); counts.set(name,(counts.get(name)||0)+1); }
 target.hidden=!counts.size;
 for(const [name,count] of counts) { const chip=el('span','speaker-chip'); chip.append(speakerBadge(el('span'),name),el('span','',name+' · '+count)); target.append(chip); }
}
// After the meeting: one list of what still needs a person, each with the step that resolves it.
function renderAttention(busy){
 const d=detail,box=$('attention');box.replaceChildren();
 if(busy||!d.transcript.length&&!d.error){box.hidden=true;return;}
 const items=[],minutes=d.minutes||{};
 const add=(tone,text,label,run)=>{const row=el('div','attention-item '+tone),go=el('button','secondary small-action',label);go.type='button';go.onclick=()=>perform(run);row.append(el('i'),el('span','',text),go);items.push(row);};
 const toOutcomes=()=>{switchTab('outcomes');$('outcomes-panel').scrollIntoView({block:'start'});};
 if(d.error)add('bad','Processing stopped: '+d.error,'Show details',async()=>$('detail-error').scrollIntoView({block:'center'}));
 const generic=[...new Set(d.transcript.map(s=>s.speaker).filter(name=>name&&/^SPEAKER[ _-]?\d+$/i.test(name)))];
 if(generic.length)add('warn','Name '+generic.length+(generic.length===1?' speaker':' speakers')+' so tasks and talk time use real names','Name speakers',async()=>{switchTab('transcript');$('speaker-review').scrollIntoView({block:'center'});});
 if(d.minutes_proposal?.changes?.length)add('warn','New AI notes are ready · '+d.minutes_proposal.changes.length+' changes to review','Review changes',async()=>openReview());
 else if(d.notes_need_refresh||d.notes_refresh_error)add('warn',d.notes_refresh_error||'The transcript changed after the notes were made','Update notes',async()=>{switchTab('transcript');$('transcript-refresh-status').scrollIntoView({block:'center'});});
 const links=['tasks','decisions'].reduce((n,field)=>n+(minutes[field]||[]).filter(m=>m.link&&!m.item_id).length,0);
 if(links)add('warn',links+(links===1?' mention looks':' mentions look')+' like existing work · link or keep as new','Check links',async()=>toOutcomes());
 const decisions=(minutes.decisions||[]).filter(m=>m.review!=='verified'&&!m.link).length;
 if(decisions)add('warn','Confirm '+decisions+(decisions===1?' decision':' decisions')+' that the AI proposed','Confirm decisions',async()=>toOutcomes());
 const tasks=(minutes.tasks||[]).filter(t=>t.status!=='done'&&!t.link&&(!t.owner||!t.due_date)).length;
 if(tasks)add('info','Give an owner and a due date to '+tasks+(tasks===1?' task':' tasks'),'Complete tasks',async()=>toOutcomes());
 // Each meeting type asks its own review questions, for example to confirm the hypotheses of an incident.
 for(const section of meetingType(d).sections){if(!section.attention)continue;const count=(minutes[section.key]||[]).filter(m=>m.review!=='verified').length;
  if(count)add('info',section.attention[count===1?0:1].replace('{n}',count),'Open notes',async()=>{switchTab('notes');$('notes-panel').scrollIntoView({block:'start'});});}
 box.hidden=false;
 const head=el('div','attention-head');head.append(el('strong','',items.length?'Needs attention · '+items.length:'Review complete'));
 if(!items.length){
  head.append(el('span','hint',d.minutes?'Speakers, notes, decisions and tasks are checked.':'Generate notes to collect decisions and tasks.'));
  if(d.project_id){const next=el('button','secondary small-action','Prepare the next meeting');next.type='button';next.onclick=()=>perform(()=>openPrepare(d.project_id,d.series_id||''));head.append(next);}
 }
 box.append(head,...items);box.classList.toggle('done',!items.length);
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
  const sample=detail.transcript.find(s=>s.speaker===name), row=el('div','input-row speaker-review-row'), label=el('strong','',name), listen=listenButton(detail.id,sample.start,{label:'Listen from '+time(sample.start),className:'quiet'});
  const input=el('input');input.placeholder='Participant name';input.value=/^SPEAKER[ _-]?\d+$/i.test(name)?'':name;input.maxLength=120;input.setAttribute('list','known-speakers');input.setAttribute('aria-label','Participant name for '+name);input.disabled=busy;input.oninput=()=>{speakerNaming=true;};
  const apply=async value=>{if(dirtyTranscript||dirtyNotes||itemEditing){error('Save other corrections before naming speakers.');return false;}
   detail=await api('/api/meetings/'+detail.id+'/edit',{speaker_name:{speaker:name,name:value,revision:detail.transcript_revision}});speakerNaming=false;lastFingerprint=JSON.stringify(detail);state=await api('/api/state');renderState();renderDetail();return true;};
  const save=el('button','secondary','Apply name');save.type='button';save.disabled=busy;save.onclick=()=>perform(async()=>{if(!input.value.trim()){error('Enter a participant name.');return;}if(await apply(input.value.trim()))toast('Speaker name applied to this meeting');});
  row.append(label,listen,input,save,thisIs(name,busy,apply));target.append(row);
 }
}
// The person that a speaker name belongs to: the same name or one of the person's other names.
function personFor(name) { const key=(name||'').trim().toLocaleLowerCase(); return key?(state.people||[]).find(p=>[p.name,...p.aliases].some(n=>n.toLocaleLowerCase()===key))||null:null; }
// "This is …" links a speaker of this meeting to a person. A numbered speaker takes the person's name;
// a name already given here stays and becomes one of the person's other names, so later meetings link too.
let pendingSpeaker=null;
function thisIs(name,busy,apply) {
 const linked=personFor(name), generic=/^SPEAKER[ _-]?\d+$/i.test(name), select=el('select','this-is');
 select.setAttribute('aria-label','Link '+name+' to a person'); select.disabled=busy; select.title=linked?'Linked to '+linked.name+'. Choose another person to change it.':'Choose the person who speaks here';
 select.append(option(linked?'✓ '+linked.name:'This is…',''),...(state.people||[]).filter(p=>p!==linked).map(p=>option(p.name,p.id)),option('＋ New person…','__new__'));
 select.onchange=()=>perform(async()=>{
  const value=select.value; select.value='';
  if(value==='__new__'){await openPerson(null);if(!generic)$('person-name').value=name;$('person-name').focus();pendingSpeaker={meeting:detail.id,name,generic,apply};return;}
  const person=(state.people||[]).find(p=>p.id===value); if(!person) return;
  if(generic||personFor(name)){if(await apply(person.name))toast(name+' is '+person.name+' in this meeting');return;}
  const result=await api('/api/people/save',Object.assign({},person,{aliases:[...person.aliases,name]}));
  state.people=result.people; renderPeople(); renderDetail(); toast('"'+name+'" is now one of the names of '+person.name);
 });
 return select;
}
function renderSpeakerSettings() {
 const list=$('speaker-list'), names=state.speakers||[]; list.replaceChildren();
 if(!names.length) list.append(el('p','hint','No known speakers yet.'));
 for(const name of names) { const chip=el('span','speaker-chip'); const remove=el('button','quiet','✕'); remove.type='button'; remove.setAttribute('aria-label','Remove '+name); remove.onclick=()=>perform(()=>saveSpeakers(names.filter(n=>n!==name))); chip.append(speakerBadge(el('span'),name),el('span','',name),remove); list.append(chip); }
}
// People: one real person behind names, task owners and a GitHub account. Confirmed by a person only.
function renderPeople(){
 const list=$('people-list');list.replaceChildren();
 for(const person of state.people||[]){
  const row=el('button','person-row');row.type='button';row.append(avatar(person.name),el('strong','',person.name),
   el('span','hint',[person.aliases.length?'Also: '+person.aliases.join(', '):'',person.github?'@'+person.github.login+(person.github.id?'':' · not checked'):''].filter(Boolean).join(' · ')));
  row.onclick=()=>perform(()=>openPerson(person.id));list.append(row);
 }
 if(!(state.people||[]).length)list.append(el('p','hint','No people yet. Add the people you meet often; their known names can stay as speakers above.'));
}
let personEditing=null,personGitHub=null;
const splitList=value=>value.split(',').map(x=>x.trim()).filter(Boolean);
async function openPerson(id){
 if(id)pendingSpeaker=null;
 const person=id?(state.people||[]).find(p=>p.id===id):null;personEditing=person;personGitHub=person?.github||null;
 $('person-title').textContent=person?person.name:'New person';$('person-error').hidden=true;
 $('person-name').value=person?.name||'';$('person-aliases').value=(person?.aliases||[]).join(', ');$('person-emails').value=(person?.emails||[]).join(', ');
 $('person-github').value=person?.github?.login||'';$('person-notes').value=person?.notes||'';$('person-delete').hidden=!person;
 $('person-github-status').textContent=person?.github?(person.github.id?'GitHub ID '+person.github.id+' · a renamed account stays this person':'Not checked on GitHub yet'):'';
 renderPersonIdentities(person);$('person-profile').replaceChildren();
 if(!$('person-dialog').open)$('person-dialog').showModal();
 if(person)renderProfile(await api('/api/people/profile?id='+person.id));
}
function renderProfile(profile){
 const box=$('person-profile');box.replaceChildren(el('h3','','What '+profile.person.name+' said and took on'));
 box.append(el('p','hint',profile.statements+(profile.statements===1?' statement':' statements')+' in '+profile.meetings+(profile.meetings===1?' meeting':' meetings')+', from transcripts where a speaker has one of the names above.'));
 const list=(title,rows,render,empty)=>{const section=el('section','profile-section');section.append(el('h4','',title));if(!rows.length)section.append(el('p','hint',empty));for(const row of rows)section.append(render(row));box.append(section);};
 renderChannelProfile(profile);
 list('Commitments',profile.commitments,task=>el('p','profile-row',task.text+(task.due_date?' · due '+task.due_date:'')+(task.status==='done'?' · done':'')),'No task with an owner that a person confirmed.');
 if(profile.suggested.length)list('Suggested by the AI, not confirmed',profile.suggested,task=>el('p','profile-row muted',task.text),'');
 list('Recent statements',profile.said.slice(0,10),row=>{const line=el('div','profile-said');line.append(listenButton(row.meeting_id,row.start,{label:'',className:'chip-listen'}),el('span','',row.text),el('small','hint',row.meeting_title));return line;},'No transcript uses these names yet.');
 if(profile.person.github)list('Assigned on GitHub (cached)',profile.github,item=>el('p','profile-row',item.repository+' #'+item.number+' · '+item.title+' · '+item.state),'Nothing in the GitHub cache. Sync the GitHub tab to see assigned issues.');
}
$('add-person').onclick=()=>perform(()=>openPerson(null));
$('person-close').onclick=()=>$('person-dialog').close();
$('person-dialog').addEventListener('close',()=>{pendingSpeaker=null;});
$('person-github').oninput=()=>{personGitHub=null;$('person-github-status').textContent=$('person-github').value.trim()?'Check the username on GitHub to keep its stable ID.':'';};
$('person-github-check').onclick=()=>perform(async()=>{const login=$('person-github').value.trim().replace(/^@/,'');if(!login)return;
 try{personGitHub=await api('/api/github/user',{login});$('person-github').value=personGitHub.login;$('person-github-status').textContent='✓ @'+personGitHub.login+' · GitHub ID '+personGitHub.id;}
 catch(e){$('person-github-status').textContent='Could not check: '+e.message+' The username is saved without an ID.';}});
$('person-form').onsubmit=event=>{event.preventDefault();perform(async()=>{
 const login=$('person-github').value.trim().replace(/^@/,'');
 const github=login?(personGitHub&&personGitHub.login.toLowerCase()===login.toLowerCase()?personGitHub:{login,id:null}):null;
 try{const result=await api('/api/people/save',{id:personEditing?.id,revision:personEditing?.revision,name:$('person-name').value,aliases:splitList($('person-aliases').value),emails:splitList($('person-emails').value),github,notes:$('person-notes').value});
  // A person created from "This is …" is linked to that speaker at once.
  const link=pendingSpeaker;pendingSpeaker=null;
  state.people=result.people;renderPeople();$('person-dialog').close();toast('Saved '+result.person.name);
  if(link&&!personEditing&&detail?.id===link.meeting){if(link.generic||!personFor(link.name)){if(await link.apply(result.person.name))toast(link.name+' is '+result.person.name+' in this meeting');}else renderDetail();}}
 catch(e){$('person-error').textContent=e.message;$('person-error').hidden=false;}});};
$('person-delete').onclick=()=>perform(async()=>{if(!personEditing||!(await ask('Delete '+personEditing.name+'? Meetings, tasks and speaker names stay as they are.',{ok:'Delete',danger:true})))return;
 const result=await api('/api/people/delete',{id:personEditing.id,revision:personEditing.revision});state.people=result.people;renderPeople();$('person-dialog').close();});
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
// The active recording stays in reach from every view: status, time, level, a microphone warning,
// Pause/Resume, Stop, and a way back to the live transcript.
function renderRecordingBar(){
 const a=state?.active,bar=$('recording-bar');bar.hidden=!a||view==='recording';if(!a)return;
 const missing=a.microphone_status&&a.microphone_status!=='connected',enabled=['recording','paused'].includes(a.status);
 bar.classList.toggle('paused',a.status!=='recording');bar.classList.toggle('alert',!!missing);
 $('bar-title').textContent=a.title||'Recording';$('bar-status').textContent=statusNames[a.status]||a.status;
 $('bar-timer').textContent=time(a.duration);$('bar-meter').value=a.level||0;
 const warning=missing?'Microphone unavailable · retrying':(a.warnings||[]).join(' ');$('bar-warning').hidden=!warning;$('bar-warning').textContent=warning;
 $('bar-pause').disabled=$('bar-stop').disabled=!enabled;$('bar-pause').textContent=a.status==='paused'?'▶ Resume':'Ⅱ Pause';
}
// Per-viewer conveniences: the last microphone and meeting type. Storage can be unavailable.
function stored(key){try{return localStorage.getItem(key)||'';}catch{return '';}}
function store(key,value){try{localStorage.setItem(key,value);}catch{}}
// Before Start: what the next recording needs, in plain words.
function renderReadiness(){
 if(!state)return;const r=state.readiness||{},online=document.querySelector('input[name=mode]:checked')?.value==='online',box=$('readiness');
 const chip=(ok,label,title)=>{const item=el('span','ready-chip '+(ok===true?'ok':ok===false?'bad':'wait'),label);if(title)item.title=title;return item;};
 const mic=$('microphone').selectedOptions[0]?.textContent;
 const items=[chip(!state.device_error&&!!state.devices.length&&!!$('microphone').value,state.device_error?'Microphone unavailable':state.devices.length?'Mic · '+mic:'No microphone')];
 if(online)items.push(chip(r.system_audio?null:false,r.system_audio?'System audio · macOS asks once':'System audio helper missing','Online meetings record all Mac audio. macOS asks for Screen & System Audio Recording permission on the first use.'));
 if(r.model)items.push(chip(r.model.ready?true:null,r.model.label));
 if(r.disk_free!==undefined){const gb=r.disk_free/1e9;items.push(chip(r.disk_hours>=4?true:r.disk_hours>=1?null:false,'Disk · '+(gb>=10?Math.round(gb):gb.toFixed(1))+' GB free',`About ${Math.floor(r.disk_hours)} hours of recording`));}
 box.replaceChildren(...items);
}
// The choices under More options, in one line, so a closed section still shows what will happen.
function renderRecordMore(){
 const parts=[$('transcription-timing').value==='live'?'Live captions':'Transcribe after recording'];
 if($('record-type').value&&$('record-type').value!=='general')parts.push(typeOf($('record-type').value).label);
 const type=typeOf($('record-type').value),inherited=seriesType($('record-series').value);
 $('record-type-help').textContent=type.description+($('record-series').value&&type.id===inherited?' The default of this series.':'');
 const project=$('record-project').selectedOptions[0];if($('record-project').value&&project)parts.push(project.textContent+($('record-series').value?' · '+$('record-series').selectedOptions[0]?.textContent:''));
 if($('fallback-microphone').value)parts.push('Backup: '+$('fallback-microphone').value);
 parts.push($('processing-name').textContent);$('record-more-summary').textContent=parts.join(' · ');
}
// Library: one place for finding past conversations. Its views keep their own sections and loaders.
const LIBRARY_VIEWS=['conversations','find','analytics'];
// Each view and tab has its own address: Back and Forward work, and a reload keeps the place.
let routing=false,meetingTab='transcript';
function currentRoute(){
 const q=new URLSearchParams();
 if(view==='detail'&&selected){q.set('meeting',selected);if(meetingTab!=='transcript')q.set('tab',meetingTab);}
 else if(view==='tasks'){q.set('view','work');q.set('tab',workTab);}
 else if(view==='projects'){q.set('view','projects');const project=$('workspace-project').value;if(project)q.set('project',project);if(workspaceSection!=='overview')q.set('section',workspaceSection);}
 else if(view==='prepare'){q.set('view','prepare');if(prepareScope.project)q.set('project',prepareScope.project);if(prepareScope.series)q.set('series',prepareScope.series);if(prepareScope.type)q.set('type',prepareScope.type);}
 else if(LIBRARY_VIEWS.includes(view))q.set('view',view);
 const text=q.toString();return text?'/?'+text:'/';
}
// A new view adds a history step; a tab or filter inside the view only updates the address.
function syncRoute(replace=false){
 if(routing)return;const url=currentRoute();
 if(url!==location.pathname+location.search)history[replace?'replaceState':'pushState'](null,'',url);
}
async function applyRoute(){
 const q=new URLSearchParams(location.search),target=q.get('view'),meeting=q.get('meeting');
 routing=true;
 try{
  if(meeting&&/^[a-f0-9]{32}$/.test(meeting)){await openMeeting(meeting);const tab=q.get('tab');if(view==='detail'&&['outcomes','notes','analytics'].includes(tab))switchTab(tab);}
  else if(target==='work'){if(WORK_PANELS[q.get('tab')])workTab=q.get('tab');await $('open-tasks').onclick();}
  else if(target==='projects'){
   const project=q.get('project')||'',select=$('workspace-project');
   if(project&&![...select.options].some(o=>o.value===project))select.append(option(project,project));select.value=project;
   workspaceSection=q.get('section')||'overview';await $('open-projects').onclick();
  }
  else if(target==='prepare')await perform(()=>openPrepare(q.get('project')||'',q.get('series')||'',q.get('type')||''));
  else if(target==='find')await openFind();
  else if(target==='analytics')await $('open-analytics').onclick();
  else if(target==='conversations')await perform(openConversations);
  else if(view!=='setup'&&view!=='recording')await $('new-meeting').onclick();
 }finally{routing=false;syncRoute(true);}
}
window.addEventListener('popstate',()=>perform(applyRoute));
function historyKeys(event){
 const typing=event.target.closest?.('input,textarea,select,[contenteditable]');
 if(typing||!(event.metaKey&&['[',']'].includes(event.key)||event.altKey&&['ArrowLeft','ArrowRight'].includes(event.key)))return;
 event.preventDefault();if(event.key==='['||event.key==='ArrowLeft')history.back();else history.forward();
}
document.addEventListener('keydown',historyKeys);
$('history-back').onclick=()=>history.back();$('history-forward').onclick=()=>history.forward();
function show(which) { view=which; if(LIBRARY_VIEWS.includes(which))store('library-view',which); for(const id of ['setup','recording','detail','tasks','analytics','prepare','find','projects','conversations']) $(id).hidden=id!==which; $('open-tasks').classList.toggle('current',which==='tasks'); $('open-projects').classList.toggle('current',which==='projects'); $('open-conversations').classList.toggle('current',LIBRARY_VIEWS.includes(which));
 $('library-tabs').hidden=!LIBRARY_VIEWS.includes(which);for(const b of $('library-tabs').querySelectorAll('button')){const on=b.dataset.library===which;b.classList.toggle('selected',on);b.setAttribute('aria-selected',String(on));} $('open-analytics').classList.toggle('current',which==='analytics'); $('open-prepare').classList.toggle('current',which==='prepare'); $('open-find').classList.toggle('current',which==='find'); renderRecordingBar(); syncRoute(); }
function renderLibrary() {
 const query=$('search').value.toLocaleLowerCase();
 const meetings=state.meetings.filter(m=>!query||m.title.toLocaleLowerCase().includes(query));
 // Server searches transcript content on demand; retain the regular status snapshot.
 const filter=$('project-filter').value;
 const rows=(query && window.searchResults ? window.searchResults : meetings).filter(m=>!filter||(filter==='__none__'?!m.project_id:m.project_id===filter));
 const signature=JSON.stringify([rows,selected,view]); if(signature===lastLibrary) return; lastLibrary=signature;
 $('library').replaceChildren();
 if(!rows.length) $('library').append(el('p','empty-library',query||filter?'No matching meetings.':'Your meetings will appear here.'));
 for(const m of rows.slice(0,5)) { const button=el('button','meeting-item'+(m.id===selected&&view==='detail'?' current':'')); button.append(el('strong','',m.title),el('small','',(m.title.includes(date(m.created))?'':date(m.created)+' · ')+(statusNames[m.status]||m.status))); button.onclick=()=>perform(()=>openMeeting(m.id)); $('library').append(button); }
 const all=el('button','quiet','All meetings in the Library →');all.type='button';all.onclick=()=>perform(openConversations);$('library').append(all);
}
async function openMeeting(id,force=false) {
 if(!force&&!(await leaveEdits())) return;
 if(state.active?.id===id) { selected=id; show('recording'); renderState(); return; }
 selected=id; dirtyTranscript=dirtyNotes=false; if(detail?.id!==id){notesEditing=false;questionFilter='open';questionLimit=10;} detail=await api('/api/meetings/'+id); lastFingerprint=JSON.stringify(detail); renderDetail(); show('detail'); renderLibrary();
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
 if(signature!==lastDevices) { lastDevices=signature; const oldName=$('microphone').selectedOptions[0]?.textContent; $('microphone').replaceChildren(); for(const d of state.devices) { const option=el('option','',d.name); option.value=d.id; $('microphone').append(option); } if(!state.devices.length){const option=el('option','','No microphone available');option.value='';$('microphone').append(option);} else { const saved=stored('record-mic'),preferred=state.devices.find(d=>d.name===oldName)||state.devices.find(d=>d.name===saved)||state.devices.find(d=>/iphone/i.test(d.name)); if(preferred) $('microphone').value=preferred.id; } }
 const backup=$('fallback-microphone'), previousBackup=backup.value, primaryName=$('microphone').selectedOptions[0]?.textContent;
 backup.replaceChildren(option('Retry the selected microphone only',''),...state.devices.filter(d=>d.name!==primaryName).map(d=>option(d.name,d.name)));
 if([...backup.options].some(o=>o.value===previousBackup))backup.value=previousBackup;
 $('start').disabled=!!state.active||!state.devices.length||pending;
 $('check-mic').disabled=!!state.active||!state.devices.length;
 $('setup-meter').value=state.preview_level;
 $('mic-hint').textContent=state.preview_active?'Listening for 10 seconds · nothing is saved':state.device_error||'Test your microphone before recording';
 renderReadiness();renderRecordMore();
 const s=state.settings;
 $('meeting-title').placeholder=s.auto_title!==false?'Leave blank for an AI-generated title':'Meeting name (optional)';
 $('processing-name').textContent=(s.transcription==='parakeet'?'Local Parakeet v3':s.transcription==='local'?'Local Whisper':'OpenAI cloud')+' · '+(s.summarizer==='none'?'transcript only':s.summarizer==='local'?'local notes':'cloud notes');
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
 renderRecordingBar();
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
  (s.transcription==='parakeet'?'Parakeet v3 transcribes the full saved recording.':s.transcription==='local'?'Whisper transcribes the full saved recording.':'the selected cloud provider transcribes the full saved recording.')+
  ' Any enabled spelling correction runs after final transcription. This choice applies only to this meeting.';
}
$('transcription-timing').onchange=()=>renderTranscriptionTiming();
function renderLive(active) {
 const live=active.live;
 const disabled=active.settings?.live_transcription===false;
 $('live-card').hidden=disabled;
 const final=active.settings?.transcription==='parakeet'?'Parakeet v3':active.settings?.transcription==='openai'?'the selected cloud provider':'Whisper';
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
 meetingTab=name;syncRoute(true);
}
function markTranscript() { dirtyTranscript=true; $('save-transcript').disabled=false; $('save-transcript').textContent=refreshNotesAfterEdit?'Save & update notes':'Save corrections'; }
function markNotes() { dirtyNotes=true; $('save-notes').disabled=$('save-outcomes').disabled=false; }
let transcriptEditing=false,refreshNotesAfterEdit=true;
// Group only adjacent segments: a participant returning later starts a new turn.
function transcriptTurns(segments) {
 const turns=[];
 segments.forEach((segment,index)=>{
  const speaker=(segment.speaker||'').trim(), previous=turns[turns.length-1];
  if(previous&&previous.speaker===speaker)previous.segments.push({segment,index});
  else turns.push({speaker,segments:[{segment,index}]});
 });
 return turns;
}
function transcriptElement(index) { return $('transcript').querySelector('[data-segment-index="'+index+'"]'); }
function renderTranscript(d,busy) {
 const target=$('transcript');target.replaceChildren();
 if(!d.transcript.length){target.append(el('p','empty-content',d.live?.segments?.length?'Your saved live draft is below. The final transcript appears after processing.':busy?'Your transcript will appear here when processing finishes.':'Your recording is saved. Choose Transcribe to turn it into text.'));return;}
 const toolbar=el('div','transcript-view-actions'),toggle=el('button','quiet',transcriptEditing?'Read as dialogue':'Edit transcript');toggle.type='button';toggle.setAttribute('aria-pressed',String(transcriptEditing));toggle.onclick=()=>{transcriptEditing=!transcriptEditing;renderTranscript(detail,busy);};toolbar.append(toggle);target.append(toolbar);
 if(transcriptEditing){
 const choice=el('label','transcript-refresh-choice'),check=el('input');check.type='checkbox';check.checked=refreshNotesAfterEdit;check.disabled=busy;check.onchange=()=>{refreshNotesAfterEdit=check.checked;if(dirtyTranscript)markTranscript();};choice.append(check,document.createTextNode(' Update notes and tasks after saving'));toolbar.prepend(choice);
 d.transcript.forEach((s,index)=>{ const row=el('div','segment');row.dataset.segmentIndex=String(index);const seek=listenButton(d.id,s.start); const content=el('div');const speaker=el('input','speaker');speaker.placeholder='Speaker (optional)';speaker.value=s.speaker||'';speaker.setAttribute('list','known-speakers');speaker.setAttribute('aria-label','Speaker for segment '+(index+1));speaker.disabled=busy;const badge=el('span');const annotate=()=>{speakerBadge(badge,speaker.value);row.classList.toggle('known-speaker',!!knownSpeaker(speaker.value));};annotate();speaker.oninput=()=>{s.speaker=speaker.value.trim()||null;annotate();renderSpeakerLegend();markTranscript();};const who=el('div','speaker-line');who.append(badge,speaker);const original=d.transcript_raw?.length===d.transcript.length?d.transcript_raw[index]:null;if(original&&original.text!==s.text){row.classList.add('ai-corrected');const restore=el('button','quiet restore-original','AI ↺');restore.title='Restore original transcription: '+original.text;restore.setAttribute('aria-label','Restore original transcription for segment '+(index+1));restore.disabled=busy;restore.onclick=()=>{s.text=original.text;text.value=original.text;row.classList.remove('ai-corrected');restore.remove();markTranscript();};who.append(restore);}const text=el('textarea');text.value=s.text;text.setAttribute('aria-label','Transcript segment '+(index+1));text.disabled=busy;text.rows=Math.max(2,Math.ceil(s.text.length/85));text.oninput=()=>{s.text=text.value;markTranscript();};content.append(who,text);row.append(seek,content);$('transcript').append(row); });
 return;
 }
 for(const turn of transcriptTurns(d.transcript)) {
  const row=el('article','dialogue-turn'),header=el('div','dialogue-heading'),first=turn.segments[0].segment;
  const seek=listenButton(d.id,first.start,{className:'quiet dialogue-time'});
  header.append(speakerBadge(el('span'),turn.speaker),el('strong','',turn.speaker||'Unidentified speaker'),seek);
  const text=el('p','dialogue-text');
  for(const {segment,index} of turn.segments){if(text.childNodes.length)text.append(document.createTextNode(' '));const fragment=el('span','transcript-fragment',segment.text.trim());fragment.dataset.segmentIndex=String(index);text.append(fragment);}
  row.append(header,text);target.append(row);
 }
}

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
 $('exports').replaceChildren(); $('files-menu').hidden=!d.files.length;
 if(d.minutes){ const row=el('div','file-row'), open=el('button','view-file type-export',meetingType(d).export+' …'); open.type='button'; open.title='The result in the format of this meeting type'; open.onclick=()=>perform(()=>openTypeExport(d.id)); row.append(open); $('exports').append(row); } for(const name of d.files) { const row=el('div','file-row'), a=el('a','',name==='recording.wav'?'↓ Audio (WAV)':'↓ '+name); a.href='/files/'+d.id+'/'+name; a.download=name; row.append(a); if(name.endsWith('.md')) { const v=el('button','view-file','View'); v.type='button'; v.setAttribute('aria-label','View '+name); v.onclick=()=>perform(()=>openViewer(d.id,name)); row.append(v); } $('exports').append(row); }
 for(const id of ['process','summarize','recover','edit-title','delete-meeting']) $(id).disabled=busy;
 $('correct').disabled=busy||!d.transcript.length; $('correct').hidden=state.settings.transcript_correction==='none'&&!d.transcript_raw;
 const preparation=d.transcript_metadata?.audio_preparation;
 $('audio-preparation-status').hidden=preparation?.profile!=='light';
 $('audio-preparation-status').textContent=preparation?.source==='recording.wav'&&d.mode==='online'?'Light audio preparation used the mixed recording because separate raw tracks were unavailable.':'Transcribed with Light audio preparation. Playback keeps the original unless you select Prepared.';
 const fix=d.transcript_metadata?.correction;
 $('correction-status').hidden=!fix&&!d.correction_error;
 $('correction-status').textContent=d.correction_error?'AI correction failed · the original transcript is shown. '+d.correction_error:fix?'AI corrected '+fix.changed+(fix.changed===1?' segment':' segments')+(fix.rejected?' · '+fix.rejected+' larger changes were refused':'')+'. Marked segments show the original transcription; click ↺ to restore it.':'';
 $('correction-status').classList.toggle('warning',!!d.correction_error);
 $('recover').hidden=d.mode==='imported'||d.mode==='audio'||!!d.files.includes('recording.wav')&&!['interrupted','error'].includes(d.status);$('process').hidden=d.mode==='imported';
 $('summarize').disabled=busy||!d.transcript.length; $('summarize').textContent=d.minutes?'Generate new AI notes':'Generate notes';
 $('process').textContent=d.transcript.length?'Transcribe again':'Transcribe';
 placeActions(d);
 $('timestamp-note').textContent=d.transcript_metadata?.timestamps==='approximate chunk boundaries'?'Cloud timestamps mark approximate audio chunks. Click a time to listen.':'Consecutive speech is grouped by participant. Click a time to listen; choose Edit transcript to make corrections.';
 renderTranscript(d,busy);
 renderSpeakerLegend();renderSpeakerReview(busy);renderAttention(busy);
 $('detail-markers').hidden=!d.markers?.length; $('detail-markers').replaceChildren();
 if(d.markers?.length){$('detail-markers').append(el('h3','','Moments you marked'));const list=el('div','marker-list');renderMarkerList(list,d.markers,true);$('detail-markers').append(list);}
 $('save-transcript').disabled=!dirtyTranscript||busy;$('save-transcript').textContent=dirtyTranscript&&refreshNotesAfterEdit?'Save & update notes':'Save corrections';renderTranscriptRefresh(busy); renderSavedDraft(d); renderNotes(busy); renderMeetingAnalytics(busy);
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
// One player for every listen button: the first click plays from the moment, the next click stops it.
// Only one moment plays at a time. In the open meeting it drives the meeting's own player, so the
// player bar shows the same position; elsewhere a hidden player reads the meeting's recording.
const moment={audio:new Audio(),player:null,button:null,render:null,key:'',until:null};
moment.audio.preload='none';
function hasRecording(meetingId){
 if(detail?.id===meetingId)return detail.files.includes('recording.wav');
 return !!(state?.meetings?.find(m=>m.id===meetingId)?.has_audio??itemsData?.meetings?.[meetingId]?.has_audio);
}
function finishMoment(){ if(moment.render)moment.render(false); Object.assign(moment,{player:null,button:null,render:null,key:'',until:null}); }
function stopMoment(){ const player=moment.player; finishMoment(); if(player&&!player.paused)player.pause(); }
function listenButton(meetingId,seconds,{label,until,className='',title}={}){
 const button=el('button','listen '+className),key=meetingId+'@'+seconds+'@'+(until??'');button.type='button';
 const text=label??time(seconds);
 const render=playing=>{button.classList.toggle('playing',playing);button.setAttribute('aria-pressed',String(playing));
  button.replaceChildren(el('span','listen-icon',playing?'■':'▶'),...(text?[el('span','listen-label',text)]:[]));
  button.setAttribute('aria-label',(playing?'Stop playback at ':'Play from ')+time(seconds));button.title=title||(playing?'Stop':'Play from '+time(seconds));};
 render(false);
 if(!meetingId||!hasRecording(meetingId)){button.disabled=true;button.title='This meeting has no recording';return button;}
 // A list that renders again keeps showing the moment that plays.
 if(moment.key===key&&moment.player&&!moment.player.paused){moment.button=button;moment.render=render;render(true);}
 button.onclick=event=>{event.stopPropagation();
  if(moment.button===button){stopMoment();return;}
  stopMoment();
  const player=detail?.id===meetingId&&view==='detail'?$('audio'):moment.audio;
  if(player===moment.audio){const src='/files/'+meetingId+'/recording.wav';if(!player.src.endsWith(src)){player.src=src;player.preload='auto';}}
  Object.assign(moment,{player,button,render,key,until:until??null});render(true);
  const start=()=>{player.currentTime=seconds;player.play().catch(e=>{if(moment.button===button)finishMoment();error('The recording could not play: '+e.message);});};
  if(player.readyState>=1)start();else player.addEventListener('loadedmetadata',start,{once:true});
 };
 return button;
}
function watchPlayer(player){
 // The pause event arrives after a new moment may already play; only a stopped player ends the moment.
 player.addEventListener('pause',()=>{if(moment.player===player&&player.paused)finishMoment();});
 player.addEventListener('ended',()=>{if(moment.player===player)finishMoment();});
 player.addEventListener('timeupdate',()=>{if(moment.player===player&&moment.until!==null&&player.currentTime>=moment.until)player.pause();});
}
watchPlayer(moment.audio);watchPlayer($('audio'));
// Show the transcript at this moment and play it when the meeting has audio.
function showMoment(stamp) {
 const seconds=stampSeconds(stamp); let index=detail.transcript.findIndex(s=>time(s.start)===stamp);
 if(index<0) index=detail.transcript.findIndex(s=>s.end>=seconds);
 switchTab('transcript'); const row=transcriptElement(index);
 if(row){row.scrollIntoView({block:'center'});row.classList.add('evidence-highlight');setTimeout(()=>row.classList.remove('evidence-highlight'),1800);}
 if(detail.files.includes('recording.wav')&&$('audio').paused)$('audio').currentTime=seconds;
}
function showSeconds(seconds) {
 let index=-1; detail.transcript.forEach((segment,i)=>{if(segment.start<=seconds+0.5)index=i;});
 switchTab('transcript'); const row=transcriptElement(Math.max(0,index));
 if(row&&detail.transcript.length){row.scrollIntoView({block:'center'});row.classList.add('evidence-highlight');setTimeout(()=>row.classList.remove('evidence-highlight'),1800);}
 if(detail.files.includes('recording.wav')&&$('audio').paused)$('audio').currentTime=seconds;
}
// A note's time: listen in place, or show the moment in the transcript.
function stampButton(stamp) {
 const box=el('span','stamp-group'),show=el('button','quiet stamp-show','↗');show.type='button';show.title='Show '+stamp+' in the transcript';show.setAttribute('aria-label',show.title);show.onclick=()=>showMoment(stamp);
 box.append(listenButton(detail.id,stampSeconds(stamp),{label:stamp,className:'stamp'}),show);return box;
}
// AI notes cite moments as (00:29:46); make them links to the transcript.
function linkedText(target,text) { text.split(/\(?\b(\d{2}:\d{2}:\d{2})\b\)?/).forEach((part,i)=>target.append(i%2?stampButton(part):document.createTextNode(part))); return target; }
const FIELD_TITLES={summary:'Summary',decisions:'Decisions',next_steps:'Agreed next steps',needs_decision:'Questions for your decision',tasks:'Tasks',open_questions:'Unresolved questions',observations:'Private observations'};
const ITEM_FIELDS=Object.keys(FIELD_TITLES).filter(field=>field!=='tasks');
function segmentAt(stamp) { return detail.transcript.find(s=>time(s.start)===stamp); }
function sourceBlock(stamp) {
 const box=el('div','note-source');
 if(!stamp) { box.append(el('span','no-source','No source moment')); return box; }
 const segment=segmentAt(stamp);
 if(detail.files.includes('recording.wav')){
  // Play only the cited segment and stay in the notes.
  box.append(listenButton(detail.id,segment?segment.start:stampSeconds(stamp),{label:stamp,until:segment?.end,className:'quiet stamp',title:'Play this moment'}));
 }else{const show=el('button','quiet stamp',stamp);show.type='button';show.title='Show this moment in the transcript';show.onclick=()=>showMoment(stamp);box.append(show);}
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
  const section=el('section','review-section'); section.append(el('h3','',meetingType(detail).sections.find(s=>s.key===field)?.title||FIELD_TITLES[field]));
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
function transcriptRefreshBanner(busy) {
 const banner=el('div','notice proposal-banner'),button=el('button','secondary','Update notes & tasks');button.type='button';button.disabled=busy||dirtyTranscript||dirtyNotes||itemEditing;
 banner.append(el('span','',detail.notes_refresh_error|| (busy?'Updating notes and tasks from the corrected transcript…':'The transcript changed. Notes and tasks need to be checked against the corrected text.')));
 button.onclick=()=>perform(async()=>{if(state.settings.summarizer==='none'){openSettings('notes');return;}await api('/api/meetings/'+detail.id+'/process',{action:'summarize'});await openMeeting(detail.id,true);});banner.append(button);return banner;
}
function renderTranscriptRefresh(busy) {
 const target=$('transcript-refresh-status');target.replaceChildren();target.hidden=!(detail.minutes_proposal||detail.notes_need_refresh||detail.notes_refresh_error);
 if(!target.hidden)target.append(detail.minutes_proposal?proposalBanner(busy):transcriptRefreshBanner(busy));
}
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
 // A task, for example a corrective action, becomes a GitHub draft or links to an existing issue.
 if(item) main.append(githubActions({kind:'item',id:item.id},(detail.github_links||[]).filter(l=>l.resource.id===item.id)));
 row.append(done,main); return row;
}
function renderNotes(busy=false) {
 $('notes').replaceChildren();$('outcomes').replaceChildren();
 if(!detail.minutes||busy) notesEditing=false;
 for(const name of ['notes','outcomes']) { $('edit-'+name).hidden=notesEditing||!detail.minutes; $('edit-'+name).disabled=busy; $('save-'+name).hidden=$('cancel-'+name).hidden=!notesEditing; $('save-'+name).disabled=!dirtyNotes; }
 if(!detail.minutes) { for(const id of ['notes','outcomes']) $(id).append(el('p','empty-content','Generate meeting notes to see the decisions, tasks, unresolved questions and next steps.')); return; }
 const minutes=detail.minutes;
 if(detail.minutes_proposal||detail.notes_need_refresh||detail.notes_refresh_error)for(const id of ['notes','outcomes']) $(id).append(detail.minutes_proposal?proposalBanner(busy):transcriptRefreshBanner(busy));
 $('notes').append(noteSection(minutes,'summary','Summary',busy),...typeSections(meetingType(detail),minutes).map(s=>noteSection(minutes,s.key,s.title,busy)),noteSection(minutes,'needs_decision','Questions for your decision',busy));
 $('outcomes').append(noteSection(minutes,'decisions','Decisions',busy));
 const section=el('section','note-section');section.append(el('h3','',meetingType(detail).task_title));
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
 if(detail.files.includes('recording.wav')&&$('audio').paused) $('audio').currentTime=item.timestamp||0;
 switchTab('transcript');const row=transcriptElement(item.segment_index);if(row){row.scrollIntoView({block:'center'});row.classList.add('evidence-highlight');setTimeout(()=>row.classList.remove('evidence-highlight'),1800);}
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
  for(const hit of topic.matches||[]) {const evidence=el('div','evidence-row'),seek=listenButton(detail.id,hit.timestamp||0,{className:'quiet evidence-time'});const text=el('p','',hit.text);const meta=el('small','',(hit.speaker||'Unknown speaker')+(hit.semantic?' · Local AI semantic match':' · '+(hit.phrases||[]).join(', ')));const main=el('div');main.append(text,meta);evidence.append(seek,main);box.append(evidence);}
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
  const main=el('div'),text=el('p','',question.text),meta=el('div','tracked-meta'),seek=listenButton(detail.id,question.timestamp||0,{className:'quiet tracked-source'});meta.append(el('span','',question.speaker||'Unknown speaker'),seek);main.append(text,meta);row.append(toggle,main);questions.append(row);
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
function settingsFields() { const parakeet=$('provider').value==='parakeet';$('parakeet-runtime').hidden=!parakeet;$('parakeet-runtime').textContent=state.parakeet?.message||'Parakeet v3 requires an Apple Silicon build with Parakeet support.'; $('local-model-field').hidden=false;$('cloud-model-field').hidden=$('provider').value!=='openai';$('notes-model-field').hidden=$('summarizer').value!=='openai'&&$('transcript-correction').value!=='openai';$('title-model-field').hidden=$('title-provider').value!=='openai';$('settings-privacy').textContent=privacy({transcription:$('provider').value,summarizer:$('summarizer').value,transcript_correction:$('transcript-correction').value,auto_title:$('auto-title').checked,title_provider:$('title-provider').value,calendar_enabled:$('calendar-enabled').checked});$('title-privacy').textContent=$('title-provider').value==='openai'?'Transcript excerpts are sent to OpenAI for title generation.':'Uses the shared Local AI endpoint and model above.'; }
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
 settingsTab=name; if(name==='backup') perform(loadBackups); if(name==='projects') renderProjectSettings(); if(name==='types') renderTypeSettings();
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
// The result of a meeting in the format of its type. Built from saved notes; nothing is saved as a file.
let viewerUrl=null;
async function openTypeExport(id) {
 const result=await api('/api/meetings/'+id+'/type-export',{});
 if(viewerUrl)URL.revokeObjectURL(viewerUrl); viewerUrl=URL.createObjectURL(new Blob([result.markdown],{type:'text/markdown'}));
 $('viewer-title').textContent=result.title; $('viewer-download').href=viewerUrl; $('viewer-download').download=result.filename;
 $('viewer-body').innerHTML=renderMarkdown(result.markdown); $('viewer-body').prepend(el('p','hint',result.note)); $('viewer-body').scrollTop=0;
 $('viewer-copy').hidden=false; $('viewer-copy').onclick=()=>perform(async()=>{await navigator.clipboard.writeText(result.markdown);toast('Copied · paste it into a chat, an email or a document');});
 $('viewer-dialog').showModal();
}
async function openViewer(id,name) { $('viewer-copy').hidden=true; const url='/files/'+id+'/'+name; const response=await fetch(url); if(!response.ok) throw new Error('Could not open '+name); $('viewer-title').textContent=name; $('viewer-download').href=url; $('viewer-download').download=name; $('viewer-body').innerHTML=renderMarkdown(await response.text()); $('viewer-body').scrollTop=0; $('viewer-dialog').showModal(); }
$('viewer-close').onclick=()=>$('viewer-dialog').close();
$('viewer-dialog').onclick=event=>{if(event.target===$('viewer-dialog'))$('viewer-dialog').close();};
// The fields that Save settings sends. Speakers, topics and projects save with their own buttons.
function settingsValues(){
 const fields=$('settings-form').querySelectorAll('.settings-panel:is([data-tab=recording],[data-tab=notes],[data-tab=calendar]) :is(input:not([type=file]):not([type=button]),select,textarea)');
 return JSON.stringify([...fields].map(f=>f.type==='checkbox'?f.checked:f.value));
}
let settingsOpened='';
async function closeSettings(){
 if(settingsValues()!==settingsOpened&&!(await ask('Discard the changes in Settings? They are not saved.',{ok:'Discard changes',cancel:'Keep editing',danger:true})))return;
 $('settings-dialog').close();
}
function openSettings(tab) { if(!state)return; clearError(); const s=state.settings;$('local-ai-base-url').value=s.local_ai_base_url;$('local-ai-model').value=s.local_ai_model;$('local-ai-format').value=s.local_ai_format;$('local-ai-reasoning').value=s.local_ai_reasoning;$('local-ai-max-tokens').value=s.local_ai_max_tokens;$('local-ai-status').textContent='';localModels=[];renderLocalModels();$('provider').value=s.transcription;$('local-model').value=s.local_model;$('audio-preparation').value=s.audio_preparation||'off';$('whisper-vad').checked=s.whisper_vad!==false;$('whisper-vocabulary').value=s.whisper_vocabulary||'';$('cloud-model').value=s.cloud_model;$('summarizer').value=s.summarizer;$('transcript-correction').value=s.transcript_correction||'none';$('llm-model').value=s.llm_model;$('auto-process').checked=s.auto_process;$('live-enabled').checked=s.live_transcription!==false;$('diarization-enabled').checked=s.diarization_enabled!==false;$('diarization-runtime').textContent=state.diarization?.message||'Speaker separation is checked after recording.';$('auto-title').checked=s.auto_title!==false;$('title-provider').value=s.title_provider||'local';$('title-model').value=s.title_model||'gpt-4.1-mini';$('calendar-enabled').checked=!!s.calendar_enabled;$('calendar-id').replaceChildren();const initialCalendar=el('option','',s.calendar_name||'Choose a calendar…');initialCalendar.value=s.calendar_id||'';$('calendar-id').append(initialCalendar);$('api-key').value='';$('forget-key').disabled=!state.api_key_configured;$('key-state').textContent=state.api_key_configured?'· configured':'';settingsFields();renderGoogleStatus();renderSpeakerSettings();trackersData=JSON.parse(JSON.stringify(state.trackers||[]));renderTrackers();$('new-speaker').value='';showSettingsTab(typeof tab==='string'?tab:settingsTab);$('settings-dialog').showModal();markProfile();renderPeople();settingsOpened=settingsValues();
 // Loading the calendar list can change the calendar field; that is not an edit by the person.
 if(calendarConnected())perform(async()=>{const untouched=settingsValues()===settingsOpened;await loadCalendars();if(untouched)settingsOpened=settingsValues();}); }
function daysBetween(from,to) { return Math.round((Date.parse(to)-Date.parse(from))/86400000); }
function dueInfo(task,today) {
 if(task.status==='done') return ['done','Done'];
 if(!task.due_date) return ['undated','No date'];
 const days=daysBetween(today,task.due_date);
 if(days<0) return ['overdue','Overdue · '+(-days)+(days===-1?' day':' days')];
 if(days===0) return ['today','Due today'];
 return [days<=7?'soon':'later','Due in '+days+(days===1?' day':' days')];
}
let itemKind='task', sourceFilter='', itemsData={items:[],pending:[],meetings:{}};
const STATUS_FILTERS={task:[['open','Open'],['overdue','Overdue'],['done','Done'],['all','All'],['snoozed','Snoozed'],['dismissed','Dismissed']],decision:[['current','In force'],['proposed','Proposed'],['accepted','Accepted'],['superseded','Replaced'],['all','All'],['snoozed','Snoozed'],['dismissed','Dismissed']]};
const statusFilter={task:'open',decision:'current'};
const DECISION_LABELS={proposed:'Proposed',accepted:'Accepted',superseded:'Replaced'};
const FIELD_LABELS={text:'text',owner:'owner',deadline:'deadline as said',due_date:'due date',status:'status'};
const EVENT_LABELS={confirmed:'Owner confirmed',created:'Created in',discussed:'Discussed in',duplicate:'Mentioned again in',changed:'Changed',removed:'Removed from',merged:'Merged with another item',superseded:'Replaced in',detached:'Waits for the new notes of'};
function meetingLabel(id,meetings) { const meeting=meetings?.[id]; return meeting?withDate(meeting.title,meeting.date):'a deleted meeting'; }
function meetingChips(item,meetings,except) {
 const box=el('div','item-meetings');
 for(const link of item.links.filter(link=>link.meeting_id!==except).sort((a,b)=>(meetings[a.meeting_id]?.date||'').localeCompare(meetings[b.meeting_id]?.date||''))) {
  box.append(originChip('meeting',meetingLabel(link.meeting_id,meetings)+(link.evidence_timestamp?' · '+link.evidence_timestamp:''),async()=>{await openMeeting(link.meeting_id);switchTab('outcomes');}));
  if(link.evidence_timestamp)box.append(listenButton(link.meeting_id,stampSeconds(link.evidence_timestamp),{label:'',className:'chip-listen'}));
 }
 return box;
}
// The external sources (Gmail, Chat, GitHub) behind an item, from its saved source quotes.
function itemSources(item){const graph=itemsData.graph||{},ids=new Set(item.source_evidence||[]),evidence=(graph.source_evidence||[]).filter(e=>ids.has(e.id));return [...new Map(evidence.map(e=>[e.source_id,(graph.sources||[]).find(s=>s.id===e.source_id)])).values()].filter(Boolean);}
function sourceLabel(source){return source.remote?.authority==='github_code'?source.remote.repository+' · code':source.remote?.authority==='github'?source.remote.repository+' #'+source.remote.number:'';}
function itemProviders(item){return new Set([...(item.links.length?['meeting']:[]),...itemSources(item).map(s=>s.provider)]);}
function sourceChips(item,meetings){const box=meetingChips(item,meetings);for(const source of itemSources(item))box.append(originChip(source.provider,sourceLabel(source),()=>openSource(source)));return box;}
function historyBlock(item,meetings) {
 const box=el('details','item-history'), list=el('ol'); box.append(el('summary','','History · '+item.history.length));
 for(const event of [...item.history].reverse()) {
  const changes=Object.entries(event.changes||{}).map(([name,[from,to]])=>{if(name==='project_ids'){const label=ids=>ids===null?'Meeting projects':ids.map(id=>projectList().find(p=>p.id===id)?.name||'Removed project').join(', ')||'Unassigned';return 'Projects: '+label(from)+' → '+label(to);}return (FIELD_LABELS[name]||name)+': '+(from??'—')+' → '+(to??'—');}).join(' · ');
  // A meeting event belongs to the meeting's date, not to the moment the app processed it.
  const when=event.meeting_id&&meetings?.[event.meeting_id]?meetings[event.meeting_id].date:event.at;
  const entry=el('li'); entry.append(el('span','history-date',new Date(when).toLocaleDateString(undefined,{day:'numeric',month:'short'})),
   el('span','',(EVENT_LABELS[event.event]||event.event)+(event.meeting_id?' '+meetingLabel(event.meeting_id,meetings):'')+(changes?' · '+changes:'')+(event.by==='user'?' · by you':' · AI')));
  list.append(entry);
 }
 box.append(list); return box;
}
async function refreshAfterItemChange() { lastTasks=''; if(view==='projects'){ itemsData=await api('/api/items'); await loadWorkspace(); } else if(view==='tasks') await loadTasks(); else if(view==='prepare') await loadPrepare(); else if(view==='detail'&&selected) await openMeeting(selected,true); state=await api('/api/state'); renderState(); }
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
  row.append(main,source);if(evidence.timestamp&&meetings[evidence.source_id])row.append(listenButton(evidence.source_id,stampSeconds(evidence.timestamp),{label:'',className:'chip-listen'}));box.append(row);
 }
 return box;
}
function setItemEditing(active,row=null){
 itemEditing=active;
 for(const other of $('task-list').children)other.inert=active&&other!==row;
 for(const node of [...$('work-tabs').querySelectorAll('button'),...$('status-filter').querySelectorAll('button'),$('work-project'),$('task-owner')])node.disabled=active;
 if(active&&row)for(const node of row.querySelectorAll('input,button'))node.disabled=true;
}
function itemActions(item,row) {
 const actions=el('div','tracked-actions'); actions.append(projectAssignment(item)); const edit=el('button','quiet','Edit'), merge=el('button','quiet','Merge…'), remove=el('button','quiet danger-text','Delete');
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
// GitHub, without writing to it: copy a draft, open GitHub prefilled, or link an existing issue on this Mac.
function githubActions(resource,links){
 links=links??(itemsData.github_links||[]).filter(l=>l.resource.kind===resource.kind&&l.resource.id===resource.id);
 const box=el('div','github-actions');
 for(const link of links){
  const chip=el('span','source-chip src-github linked-issue'),open=el('a','',link.repository+' #'+link.number);open.href=link.url;open.target='_blank';open.rel='noopener noreferrer';
  chip.append(el('i'),el('b','',link.kind==='pull_request'?'PR':'Issue'),open);
  if(link.title)chip.append(el('span','',link.title));if(link.state)chip.append(el('span','',link.state));chip.append(el('span','hint',githubVerificationLabel(link)));
  const check=el('button','quiet','Check in GitHub');check.type='button';check.onclick=()=>perform(async()=>{check.disabled=true;try{await api('/api/github/link',{resource,reference:link.url,verify_live:true});await afterGitHubLink(resource);}finally{check.disabled=false;}});chip.append(check);
  const remove=el('button','quiet','✕');remove.type='button';remove.title='Remove this link from Atlanta (GitHub is not changed)';remove.setAttribute('aria-label','Remove link');
  remove.onclick=()=>perform(async()=>{await api('/api/github/unlink',{id:link.id,revision:link.revision});await afterGitHubLink(resource);});chip.append(remove);box.append(chip);
 }
 const menu=el('details','menu github-menu'),items=el('div','menu-items');menu.append(el('summary','','GitHub ▾'),items);
 for(const [label,run] of [['Copy as issue…',()=>openDraft(resource,'issue')],['Copy as comment…',()=>openDraft(resource,'comment')],['Link existing issue or PR…',()=>openLink(resource)]]){
  const b=el('button','',label);b.type='button';b.onclick=()=>{menu.open=false;perform(run);};items.append(b);
 }
 box.append(menu);return box;
}
async function afterGitHubLink(resource){
 if(resource.kind==='attachment'&&$('conversation-reader').open)return openAttachment(resource.id);
 await refreshAfterItemChange();
}
let draftResource=null,draftFormat='issue',draftSequence=0,draftActiveKey='',draftLatest=null;
const draftBuffers=new Map();
function captureDraft(){if(draftActiveKey&&draftBuffers.has(draftActiveKey))draftBuffers.get(draftActiveKey).capture($('github-draft-issue-title').value,$('github-draft-body').value);}
function draftEditNotice(){const buffer=draftBuffers.get(draftActiveKey);$('github-draft-edits').hidden=!buffer?.edited;}
async function openDraft(resource,format){captureDraft();draftResource=resource;draftFormat=format;draftActiveKey='';$('github-draft-repo').replaceChildren();await renderDraft();if(!$('github-draft-dialog').open)$('github-draft-dialog').showModal();}
async function renderDraft(){
 captureDraft();const sequence=++draftSequence,key=JSON.stringify([draftResource,draftFormat]),format=draftFormat;
 if(!draftBuffers.has(key)){if(draftBuffers.size>=20){const clean=[...draftBuffers].find(([,buffer])=>!buffer.edited);if(clean)draftBuffers.delete(clean[0]);}draftBuffers.set(key,new DraftBuffer());}
 const buffer=draftBuffers.get(key);draftActiveKey=key;
 if(buffer.values.body!==undefined){$('github-draft-issue-title').value=buffer.values.title;$('github-draft-body').value=buffer.values.body;}
 else {$('github-draft-issue-title').value='';$('github-draft-body').value='';}
 $('github-draft-copy').disabled=$('github-draft-copy-title').disabled=$('github-draft-review').disabled=true;
 try{
 const draft=await api('/api/github/draft',{resource:draftResource,format,repository:$('github-draft-repo').value||undefined,include_meeting:$('github-draft-meeting').checked,include_speaker:$('github-draft-speaker').checked});
 if(sequence!==draftSequence||key!==draftActiveKey)return;
 // Capture edits made while the request was in flight, before accepting generated fields.
 buffer.capture($('github-draft-issue-title').value,$('github-draft-body').value);
 const values=buffer.accept(draft);draftLatest=draft;
 segmentedChoice($('github-draft-format'),[['issue','Issue draft'],['comment','Comment']],format,value=>{captureDraft();draftFormat=value;perform(renderDraft);});
 const repos=[...new Set([...draft.repositories,...(draft.repository?[draft.repository]:[])])],select=$('github-draft-repo');select.replaceChildren(option(repos.length?'Repository…':'No repository in the project',''),...repos.map(r=>option(r,r)));select.value=draft.repository||'';
 $('github-draft-issue-title').value=values.title;$('github-draft-body').value=values.body;$('github-draft-issue-title').hidden=$('github-draft-title-label').hidden=format!=='issue';
 $('github-draft-notes').textContent=[...draft.notes,draft.assignee?'Assignee suggestion: '+draft.assignee+' (a confirmed owner).':''].filter(Boolean).join(' ');draftEditNotice();updateDraftLink();
 }finally{if(sequence===draftSequence)$('github-draft-copy').disabled=$('github-draft-copy-title').disabled=$('github-draft-review').disabled=false;}
}
function updateDraftLink(){
 const repo=$('github-draft-repo').value,open=$('github-draft-open');open.hidden=draftFormat!=='issue'||!repo;
 if(!open.hidden)open.href='https://github.com/'+repo+'/issues/new?'+new URLSearchParams({title:$('github-draft-issue-title').value,body:$('github-draft-body').value});
}
async function copyText(text){
 try{await navigator.clipboard.writeText(text);}catch{const area=el('textarea');area.value=text;document.body.append(area);area.select();document.execCommand('copy');area.remove();}
 toast('Copied · paste it in GitHub');
}
$('github-draft-close').onclick=()=>{captureDraft();$('github-draft-dialog').close();};
$('github-draft-dialog').addEventListener('close',captureDraft);
for(const id of ['github-draft-meeting','github-draft-speaker','github-draft-repo'])$(id).onchange=()=>{updateDraftLink();perform(renderDraft);};
$('github-draft-body').oninput=$('github-draft-issue-title').oninput=()=>{captureDraft();draftEditNotice();updateDraftLink();};
$('github-draft-copy').onclick=()=>perform(()=>copyText($('github-draft-body').value));
$('github-draft-copy-title').onclick=()=>perform(()=>copyText($('github-draft-issue-title').value));
let linkResource=null,linkCandidates=[];
async function openLink(resource){
 linkResource=resource;$('github-link-error').hidden=true;$('github-link-ref').value='';$('github-link-results').replaceChildren();
 let draft={repositories:[]};try{draft=await api('/api/github/draft',{resource,format:'comment'});}catch{}
 try{linkCandidates=(await api('/api/github/overview?filter=all')).items;}catch{linkCandidates=[];}
 const repos=[...new Set([...draft.repositories,...linkCandidates.map(r=>r.repository)])];
 $('github-link-repo').replaceChildren(option('Any repository',''),...repos.map(r=>option(r,r)));$('github-link-repo').value=draft.repositories[0]||'';
 renderLinkResults();$('github-link-dialog').showModal();$('github-link-ref').focus();
}
function renderLinkResults(){
 const query=$('github-link-ref').value.trim().toLocaleLowerCase(),repo=$('github-link-repo').value,list=$('github-link-results');
 const rows=query&&!/^#?\d+$|github\.com|\/.+#/.test(query)?linkCandidates.filter(r=>(!repo||r.repository===repo)&&(r.title+' #'+r.number).toLocaleLowerCase().includes(query)).slice(0,30):[];
 list.replaceChildren(...rows.map(r=>sourceRow(false,[el('span','row-tag '+(r.kind==='issue'?'issue':'pr'),r.kind==='issue'?'Issue':'PR'),el('span','row-who',r.repository.split('/')[1]),el('strong','row-title','#'+r.number+' '+r.title),el('span','row-when',r.state)],async()=>{$('github-link-ref').value=r.repository+'#'+r.number;renderLinkResults();})));
 list.hidden=!rows.length;
}
$('github-link-ref').oninput=$('github-link-repo').onchange=renderLinkResults;
$('github-link-close').onclick=()=>$('github-link-dialog').close();
$('github-link-form').onsubmit=event=>{event.preventDefault();perform(async()=>{
 try{await api('/api/github/link',{resource:linkResource,reference:$('github-link-ref').value,repository:$('github-link-repo').value});$('github-link-dialog').close();toast('Linked in Atlanta · GitHub is not changed');await afterGitHubLink(linkResource);}
 catch(e){$('github-link-error').textContent=e.message;$('github-link-error').hidden=false;}});};
function globalTaskRow(item,today) {
 const [kind,label]=dueInfo(item,today), row=el('div','tracked-task '+kind), done=el('input'), main=el('div','tracked-main'), meta=el('div','tracked-meta'), who=el('span','tracked-owner');
 done.type='checkbox';done.checked=item.status==='done';done.setAttribute('aria-label','Mark task as done');done.onchange=()=>perform(()=>changeItem(item,{status:done.checked?'done':'open'}));
 who.append(speakerBadge(el('span'),item.owner||''),el('span','',item.owner||'No owner'));
 if(item.owner&&!item.manual?.includes('owner')){const confirm=el('button','quiet small-action owner-confirm','AI suggestion · Confirm');confirm.type='button';confirm.title='A person confirms this owner. Only confirmed owners count as commitments and reach GitHub drafts.';confirm.onclick=()=>perform(()=>changeItem(item,{owner:item.owner}));who.append(confirm);}
 const due=el('input');due.type='date';due.value=item.due_date||'';due.setAttribute('aria-label','Due date');due.onchange=()=>perform(()=>changeItem(item,{due_date:due.value||null}));
 meta.append(who,el('span','due-label '+kind,label),due); if(item.deadline) meta.append(el('span','hint','Said: '+item.deadline));
 main.append(el('p','tracked-text',item.text),meta,sourceChips(item,itemsData.meetings),githubActions({kind:'item',id:item.id}),historyBlock(item,itemsData.meetings),evidenceBlock(item,itemsData.meetings));
 row.append(done,main); row.append(itemActions(item,row)); return row;
}
function decisionRow(item,byId) {
 const row=el('div','tracked-task decision '+item.status), main=el('div','tracked-main'), meta=el('div','tracked-meta');
 meta.append(el('span','decision-status '+item.status,DECISION_LABELS[item.status]));
 if(item.superseded_by&&byId[item.superseded_by]) meta.append(el('span','hint','Replaced by: '+byId[item.superseded_by].text));
 for(const id of item.supersedes||[]) if(byId[id]) meta.append(el('span','hint','Replaces: '+byId[id].text));
 const next={proposed:['accepted','Accept'],accepted:['proposed','Mark as proposed'],superseded:[item.superseded_previous_status==='accepted'?'accepted':'proposed',item.superseded_previous_status==='accepted'?'Restore as accepted':'Restore as proposed']}[item.status];
 const change=el('button','secondary small-action',next[1]);change.type='button';change.onclick=()=>perform(()=>changeItem(item,{status:next[0]}));meta.append(change);
 main.append(el('p','tracked-text',item.text),meta,sourceChips(item,itemsData.meetings),githubActions({kind:'item',id:item.id}),historyBlock(item,itemsData.meetings),evidenceBlock(item,itemsData.meetings));
 row.append(el('span'),main); row.append(itemActions(item,row)); return row;
}
async function loadTasks() { if(itemEditing)return;const fresh=await api('/api/items'); if(itemEditing)return;const signature=JSON.stringify(fresh); if(signature===lastTasks) return; lastTasks=signature; itemsData=fresh; renderTasks(); }
// Source identity: every item, proposal and inbox row names where it came from.
const SOURCES={meeting:['Meeting','src-meeting'],gmail:['Gmail','src-gmail'],google_chat:['Chat','src-chat'],github:['GitHub','src-github']};
function originChip(provider,label,open){
 const chip=el(open?'button':'span','source-chip '+(SOURCES[provider]?.[1]||''));chip.append(el('i'),el('b','',SOURCES[provider]?.[0]||provider));
 if(label)chip.append(el('span','',label));
 if(open){chip.type='button';chip.title='Open the source';chip.onclick=()=>perform(open);}
 return chip;
}
function relTime(ms){
 if(!ms)return '';const minutes=Math.round((Date.now()-ms)/60000);
 if(minutes<1)return 'now';if(minutes<60)return minutes+' min';if(minutes<24*60)return Math.round(minutes/60)+' h';
 const day=new Date(ms);return day.toLocaleDateString(undefined,{day:'numeric',month:'short',...(day.getFullYear()!==new Date().getFullYear()?{year:'numeric'}:{})});
}
function dayLabel(ms){return new Date(ms).toLocaleDateString(undefined,{weekday:'long',day:'numeric',month:'long'});}
// A person in Gmail or Chat: initials on a colour that stays the same for the same name.
function avatar(name){const node=el('span','speaker-badge '+speakerTone(name||'?'),initials(name||'?')||'?');node.title=name||'';return node;}
function personName(from){const match=(from||'').match(/^\s*"?([^"<]+?)"?\s*</);return (match?match[1]:from||'Unknown').trim();}
function jobText(job){return job.running?'Syncing…':{continue:'More to sync',synced:'Up to date',error:'Sync failed',idle:''}[job.status]??job.status;}
// The bar on top of a source: who is connected, what the sync does, and any problem in plain words.
function sourceState(name,connected,parts,problem){
 $(name+'-panel').classList.toggle('disconnected',!connected);
 $(name+'-status').textContent=connected?parts.filter(Boolean).join(' · '):'Not connected';
 $(name+'-notice').hidden=!problem;$(name+'-notice').textContent=problem||'';
}
function sourceRow(selected,cells,onopen){
 const row=el('button','source-row'+(selected?' selected':''));row.type='button';row.setAttribute('role','option');row.setAttribute('aria-selected',String(selected));
 row.append(...cells);row.onclick=()=>perform(onopen);return row;
}
// Arrow keys move through a source list like in a mail client.
function listKeys(list){list.onkeydown=event=>{if(event.key!=='ArrowDown'&&event.key!=='ArrowUp')return;const rows=[...list.querySelectorAll('.source-row')],at=rows.indexOf(document.activeElement),next=rows[Math.max(0,Math.min(rows.length-1,at+(event.key==='ArrowDown'?1:-1)))];if(next){event.preventDefault();next.focus();next.click();}};}
function emptyState(box,text){box.replaceChildren(el('p','source-empty',text));}
function segmentedChoice(box,choices,current,choose){
 box.replaceChildren(...choices.map(([value,label])=>{const b=el('button',value===current?'selected':'',label);b.type='button';b.onclick=()=>choose(value);return b;}));
}
function cacheAccounts(select,button,accounts,running){
 const old=select.value;select.replaceChildren(...accounts.map(([label,value])=>option(label,value)));
 if(accounts.some(a=>a[1]===old))select.value=old;button.disabled=running||!accounts.length;
}
async function openSource(source){
 if(source.remote?.authority==='conversation'){const link=(itemsData.graph?.conversation_links||[]).find(a=>a.source_id===source.id);if(link)return openAttachment(link.id);}
 if(view==='projects'){show('tasks');lastTasks='';await loadTasks();}
 if(source.provider==='gmail'){showWorkTab('gmail');await openMail(source.external_id);}
 else if(source.provider==='google_chat'){chatSpace=source.external_id.split('/messages/')[0];chatMessage=source.external_id;showWorkTab('chat');}
 else if(source.provider==='github'&&source.remote?.authority==='github_code'){
  showWorkTab('github');showGitHubSection('reports');
  try{await openRepoReport(source.remote.report_id);}catch(exc){const box=$('repo-report-detail'),snapshot=(itemsData.graph?.source_revisions||[]).find(r=>r.id===source.current_revision);box.replaceChildren(el('h3','','Saved code evidence'),el('p','hint','The local report is unavailable. Promoted source evidence is kept.'),el('pre','report-source',snapshot?.text||''));const link=reportLink(source.remote.url,'Open code on GitHub');if(link)box.append(link);}
 }
 else if(source.provider==='github'){showWorkTab('github');showGitHubSection('items');await openGitHubItem(Number(source.external_id.split(':')[1]));}
}

let mailView='needs_reply',mailTimer=null,mailAIWasRunning=false,mailThread='',mailThreads=[],mailAutoSynced=false,mailAIStatus={},mailAISeenJob='';
async function loadMail(){
 const status=await api('/api/gmail'),ai=await api('/api/gmail/ai');
 mailAIStatus=ai;
 const aiText=ai.running?'Email AI is reading the approved message'+(ai.model?' with '+ai.model:'')+'…':ai.error?'Email AI: '+ai.error:['complete','reused'].includes(ai.status)?mailAIResultText(ai):'';
 sourceState('gmail',status.connected,[status.account,status.count+' threads',jobText(status.job),status.sync.last_sync&&'updated '+relTime(status.sync.last_sync*1000),status.sync.limited&&'first 200 threads'],status.job.error||aiText);
 $('gmail-ai-cancel').hidden=!ai.running;
 if(!ai.running&&(mailAIWasRunning||(['complete','reused'].includes(ai.status)&&ai.job_id!==mailAISeenJob))){lastTasks='';await loadTasks();if(['complete','reused'].includes(ai.status)){mailAISeenJob=ai.job_id;toast(mailAIResultText(ai));}}
 mailAIWasRunning=ai.running;
 $('gmail-sync').disabled=!status.connected||status.job.running;$('gmail-sync').textContent=status.job.running?'Syncing…':status.job.status==='continue'?'Continue sync':'Sync';
 $('gmail-cancel').disabled=!status.job.running;
 cacheAccounts($('gmail-cache-account'),$('gmail-clear'),status.cached_accounts.map(a=>[a,a]),status.job.running);
 // The first visit after connecting fetches the first page without an extra click.
 if(status.connected&&!status.count&&!status.job.running&&!mailAutoSynced){mailAutoSynced=true;await api('/api/gmail/sync',{});return loadMail();}
 segmentedChoice($('gmail-filters'),[['needs_reply','Needs reply'],['waiting','Waiting for'],['all','All']],mailView,value=>{mailView=value;perform(loadMail);});
 mailThreads=status.connected?await api('/api/gmail/threads?view='+mailView):[];
 renderMailList();renderMailAI();
 if(!mailThread)emptyState($('gmail-detail'),mailThreads.length?'Choose a thread above to read it here.':'');
 if(mailTimer)clearTimeout(mailTimer);mailTimer=null;
 if((status.job.running||ai.running)&&view==='tasks'&&workTab==='gmail')mailTimer=setTimeout(()=>perform(loadMail),2000);
}
function renderMailList(){
 const query=$('gmail-search').value.trim().toLocaleLowerCase(),list=$('gmail-threads');const focused=list.contains(document.activeElement);
 const rows=mailThreads.filter(t=>!query||(t.subject+' '+t.sender).toLocaleLowerCase().includes(query));
 list.replaceChildren(...rows.map(t=>sourceRow(t.id===mailThread,[el('span','row-tag '+t.view,t.view==='waiting'?'Waiting':'Reply'),el('strong','row-who',personName(t.sender)),el('span','row-title',t.subject),el('span','row-when',relTime(t.date))],()=>openMail(t.id))));
 if(focused)list.querySelector('.selected')?.focus();
 if(!rows.length)emptyState(list,mailThreads.length?'No thread matches this filter.':'No threads in this view. Choose Sync to fetch the latest page.');
}
$('gmail-search').oninput=renderMailList;listKeys($('gmail-threads'));
async function openMail(key){
 const thread=await api('/api/gmail/thread?id='+encodeURIComponent(key)),box=$('gmail-detail');mailThread=key;renderMailList();
 const head=el('div','reader-head'),attach=el('button','secondary small-action','Attach to project');attach.type='button';attach.onclick=()=>perform(()=>attachExternal('gmail',thread.id));
 head.append(attach,el('h3','',thread.subject),el('p','hint',thread.messages.length+' messages · cached '+relTime(thread.fetched_at*1000)+(thread.partial?' · only the latest 100 messages':'')));
 const body=el('div','reader-body');
 for(const message of thread.messages){
  const card=el('article','mail-message'+(message.sent?' sent':'')),top=el('div','message-top');card.dataset.threadId=thread.id;card.dataset.messageId=message.id;
  top.append(avatar(personName(message.sender)),el('strong','',personName(message.sender)),el('span','hint',new Date(message.date).toLocaleString(undefined,{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'})));
  if(message.identity)top.append(senderIdentityButton(message.identity,message.sender));
  card.append(top,el('p','message-text',message.body||'No inline text body. Attachments are not fetched.'));
  if(message.body){
   const actions=el('div','message-actions'),suggest=el('button','secondary small-action','Suggest a task'),analyze=el('button','quiet small-action','Analyze with AI');
   suggest.onclick=()=>perform(async()=>{const title=await ask('Task suggestion. Review the source quote in Suggested before accepting.',{ok:'Save suggestion',value:thread.subject});if(title===null)return;await api('/api/gmail/propose',{id:thread.id,revision:thread.revision,message_id:message.id,title});await refreshAfterItemChange();toast('Saved in Suggested · nothing was accepted yet');});
   const status=el('p','hint gmail-message-ai-status');status.hidden=true;status.setAttribute('role','status');
   suggest.type=analyze.type='button';analyze.dataset.messageAi='';
   analyze.onclick=()=>perform(()=>analyzeMail(thread,message,analyze,status));actions.append(suggest,analyze);card.append(actions,status);
  }
  body.append(card);
 }
 box.replaceChildren(head,body);renderMailAI();body.scrollTop=body.scrollHeight;
}
function mailAIResultText(ai){const count=ai.proposal_ids?.length||0;return count?count+' AI suggestions are waiting in Suggested.':'Analysis complete. No supported task commitments were found; no suggestions were created.';}
function renderMailAI(){
 for(const card of $('gmail-detail').querySelectorAll('.mail-message')){
  const button=card.querySelector('[data-message-ai]'),note=card.querySelector('.gmail-message-ai-status');if(!button||!note)continue;
  const selected=card.dataset.threadId===mailAIStatus.thread_id&&card.dataset.messageId===mailAIStatus.message_id;
  button.disabled=!!mailAIStatus.running;button.textContent=selected&&mailAIStatus.running?'Analyzing…':'Analyze with AI';button.setAttribute('aria-busy',String(selected&&!!mailAIStatus.running));
  note.hidden=!selected;if(!selected)continue;
  const complete=['complete','reused'].includes(mailAIStatus.status);
  note.replaceChildren(document.createTextNode(mailAIStatus.running?'Analyzing the approved message…':mailAIStatus.error|| (complete?mailAIResultText(mailAIStatus):mailAIStatus.status||'')));
  if(complete&&mailAIStatus.proposal_ids?.length){const open=el('button','quiet small-action','View suggestions');open.type='button';open.onclick=()=>showWorkTab('suggested');note.append(' ',open);}
 }
}
async function analyzeMail(thread,message,button,note){
 if(button){button.disabled=true;button.textContent='Preparing analysis…';}if(note){note.hidden=false;note.textContent='Preparing the message-specific AI approval…';}
 try{
 const body={id:thread.id,revision:thread.revision,message_id:message.id},preview=await api('/api/gmail/ai/preview',body);
 const prompt=preview.cached?'Reuse the saved analysis for this exact message and AI settings? No new AI request will be sent. Existing review states stay unchanged.':'Send this selected email message to the AI endpoint below?\n\nAccount: '+preview.account+'\nSubject: '+preview.subject+'\nSize: '+preview.characters+' characters including sender and subject\nEndpoint: '+preview.endpoint+'\nModel: '+preview.model+'\nReasoning: '+preview.reasoning+' · Output limit: '+preview.max_tokens+' tokens\n\nThis endpoint may be remote. Approval applies only to this message revision and these settings. Proposals require your later Accept/Link.';
 if(!(await ask(prompt,{ok:preview.cached?'Show saved analysis':'Approve and analyze',cancel:'Cancel'}))){if(note)note.hidden=true;return;}
 const result=await api('/api/gmail/ai/start',{...body,preview_token:preview.preview_token,approved:true});
 mailAIWasRunning=!!result.running;
 if(result.status==='reused'){await refreshAfterItemChange();toast('Saved analysis reused · review state kept');}
 await loadMail();
 }catch(exc){if(note){note.hidden=false;note.textContent=exc.message;}throw exc;}finally{if(button){button.disabled=!!mailAIStatus.running;button.textContent=mailAIStatus.running?'Analyzing…':'Analyze with AI';}}
}
async function gmailConnect(){const result=await api('/api/calendar/connect',{capability:'gmail'});$('gmail-auth-link').href=result.authorization_url;$('gmail-auth-link').hidden=false;toast('Approve Gmail read-only access in your browser, then come back here');}
$('gmail-ai-cancel').onclick=()=>perform(async()=>{await api('/api/gmail/ai/cancel',{});await loadMail();});
$('gmail-refresh').onclick=()=>perform(loadMail);
$('gmail-connect').onclick=$('gmail-connect-again').onclick=()=>perform(gmailConnect);
$('gmail-sync').onclick=()=>perform(async()=>{await api('/api/gmail/sync',{});await loadMail();});
$('gmail-cancel').onclick=()=>perform(async()=>{await api('/api/gmail/cancel',{});await loadMail();});
$('gmail-clear').onclick=()=>perform(async()=>{const account=$('gmail-cache-account').value;if(await ask('Clear the local email cache for '+account+'? It can be synced again. WorkItem quotes and archives remain.',{ok:'Clear cache',danger:true})){await api('/api/gmail/clear',{account});mailThread='';$('gmail-detail').replaceChildren();await loadMail();}});
function calendarConnected(google=state?.google){return google?.capabilities?.calendar??!!google?.connected;}

let chatSpace='',chatMessage='',chatAccount='',chatTimer=null,chatWasRunning=false,chatSpaces=[],chatSelf='',chatDiscovered=false;const chatAutoSynced=new Set();
const CHAT_TYPES={DIRECT_MESSAGE:'Direct',GROUP_CHAT:'Group',SPACE:'Space'};
// Chat does not name the signed-in person. The name that appears in most conversations is almost certainly you.
function guessChatSelf(spaces){const seen={};for(const s of spaces)for(const name of s.participants)seen[name]=(seen[name]||0)+1;const [name,count]=Object.entries(seen).sort((a,b)=>b[1]-a[1])[0]||[];return count>=2?name:'';}
function chatLabel(space){if(!space.label.startsWith('spaces/'))return space.label;const others=space.participants.filter(n=>n!==chatSelf);return others.join(', ')||(space.participants.length?space.participants.join(', '):'Direct message');}
async function chatAction(path,body={}){await api('/api/chat/'+path,body);chatWasRunning=true;await loadChat();}
async function loadChat(){
 const status=await api('/api/chat');
 if(chatAccount!==status.account_id){chatMessage='';chatSpace=chatSpace&&chatAccount===''?chatSpace:'';chatAccount=status.account_id;}
 const discovery=status.states['']||{};
 sourceState('chat',status.connected,[status.account,jobText(status.job),discovery.limited&&'first 200 conversations'],status.job.error);
 chatSpaces=status.connected?await api('/api/chat/spaces'):[];chatSelf=guessChatSelf(chatSpaces);
 $('chat-cancel').disabled=!status.job.running;$('chat-discover').disabled=$('chat-restart').disabled=!status.connected||status.job.running;
 $('chat-discover').textContent=discovery.complete||!discovery.page?'Refresh conversation list':'Load more conversations';
 cacheAccounts($('chat-cache-account'),$('chat-clear'),status.cached_accounts.map(a=>[a.label+' · '+a.id.slice(0,8),a.id]),status.job.running);
 if(status.connected&&!chatSpaces.length&&!status.job.running&&!chatDiscovered){chatDiscovered=true;return chatAction('discover');}
 if(chatSpace&&!chatSpaces.some(s=>s.name===chatSpace))chatSpace='';
 const sync=status.states[chatSpace]||{};
 $('chat-sync').disabled=!status.connected||!chatSpace||status.job.running;$('chat-sync').textContent=status.job.running?'Syncing…':sync.page?'Load older messages':'Sync conversation';
 renderChatList();
 if(chatSpace&&!sync.last_sync&&!status.job.running&&!chatAutoSynced.has(chatSpace)){chatAutoSynced.add(chatSpace);return chatAction('sync',{space:chatSpace});}
 if(chatSpace)await renderConversation(sync);else emptyState($('chat-detail'),chatSpaces.length?'Choose a conversation above to read it here.':'');
 if(chatWasRunning&&!status.job.running){lastTasks='';await loadTasks();}
 chatWasRunning=status.job.running;
 if(chatTimer)clearTimeout(chatTimer);chatTimer=null;if(status.job.running&&view==='tasks'&&workTab==='chat')chatTimer=setTimeout(()=>perform(loadChat),1500);
}
function renderChatList(){
 const query=$('chat-search').value.trim().toLocaleLowerCase(),list=$('chat-spaces');const focused=list.contains(document.activeElement);
 const rows=chatSpaces.filter(s=>!query||chatLabel(s).toLocaleLowerCase().includes(query));
 list.replaceChildren(...rows.map(s=>{const label=chatLabel(s);return sourceRow(s.name===chatSpace,[avatar(label),el('strong','row-who',label),el('span','row-tag',CHAT_TYPES[s.type]||'Chat'),el('span','row-title',s.count?s.count+' messages':'Not synced yet'),el('span','row-when',relTime(s.last*1000))],async()=>{chatSpace=s.name;chatMessage='';await loadChat();});}));
 if(focused)list.querySelector('.selected')?.focus();
 if(!rows.length)emptyState(list,chatSpaces.length?'No conversation matches this filter.':'No conversations yet. Open the ⋯ menu and choose Refresh conversation list.');
}
$('chat-search').oninput=renderChatList;listKeys($('chat-spaces'));
async function renderConversation(sync){
 const space=chatSpaces.find(s=>s.name===chatSpace),messages=await api('/api/chat/conversation?space='+encodeURIComponent(chatSpace)),box=$('chat-detail');
 const head=el('div','reader-head'),attach=el('button','secondary small-action','Attach to project');attach.type='button';attach.disabled=!messages.some(m=>m.available&&m.body);attach.onclick=()=>perform(()=>attachExternal('google_chat',chatSpace));head.append(attach,el('h3','',chatLabel(space)),el('p','hint',[space.participants.join(', '),(sync.last_sync?'synced '+relTime(sync.last_sync*1000):'not synced yet'),sync.limited&&'200-message limit'].filter(Boolean).join(' · ')));
 const body=el('div','reader-body chat-body');let previous=null,day='';
 for(const m of messages){
  const stamp=m.date*1000,today=dayLabel(stamp);
  if(today!==day){day=today;body.append(el('div','chat-day',today));previous=null;}
  const grouped=previous&&previous.sender===m.sender&&stamp-previous.date*1000<5*60000;
  const row=el('div','chat-msg'+(grouped?' grouped':'')+(m.sender===chatSelf?' mine':'')+(m.name===chatMessage?' selected':'')+(m.available?'':' gone'));row.tabIndex=0;row.dataset.name=m.name;
  const text=el('p','message-text',m.available?m.body||'No plain text. Cards and attachments are not fetched.':'This message is unavailable or deleted.');
  if(grouped)row.append(el('span','chat-time',new Date(stamp).toLocaleTimeString(undefined,{hour:'2-digit',minute:'2-digit'})),text);
  else{const top=el('div','message-top');top.append(el('strong','',m.sender),el('span','hint',new Date(stamp).toLocaleTimeString(undefined,{hour:'2-digit',minute:'2-digit'})));const main=el('div');main.append(top,text);row.append(avatar(m.sender),main);}
  row.onclick=()=>{chatMessage=m.name;for(const other of body.querySelectorAll('.chat-msg'))other.classList.toggle('selected',other===row);renderChatActions(m);};
  row.onkeydown=event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();row.click();}};
  if(m.identity)row.append(senderIdentityButton(m.identity,m.sender));
  body.append(row);previous=m;
 }
 if(!messages.length)body.append(el('p','source-empty','No messages in the last 30 days. Choose Sync conversation to check again.'));
 const actions=el('div','reader-actions');
 box.replaceChildren(head,body,actions);renderChatActions(messages.find(m=>m.name===chatMessage));
 const chosen=body.querySelector('.chat-msg.selected');if(chosen)chosen.scrollIntoView({block:'center'});else body.scrollTop=body.scrollHeight;
}
function renderChatActions(m){
 const bar=$('chat-detail').querySelector('.reader-actions');if(!bar)return;
 if(!m){bar.replaceChildren(el('span','hint','Select a message to turn it into a task or to refresh it.'));return;}
 const suggest=el('button','primary small-action','Suggest a task'),refresh=el('button','secondary small-action','Refresh this message');
 suggest.disabled=!m.available||!m.body;
 suggest.onclick=()=>perform(async()=>{const title=await ask('Task proposal from this Chat message',{ok:'Save suggestion',value:m.body.slice(0,120)});if(title===null)return;await api('/api/chat/propose',{name:m.name,revision:m.revision,title});await refreshAfterItemChange();toast('Saved in Suggested · nothing was accepted yet');});
 refresh.onclick=()=>perform(()=>chatAction('refresh',{name:m.name}));
 bar.replaceChildren(el('span','reader-quote',m.sender+': '+(m.body||'').slice(0,90)),suggest,refresh);
}
async function chatConnect(){const result=await api('/api/calendar/connect',{capability:'chat'});$('chat-auth-link').href=result.authorization_url;$('chat-auth-link').hidden=false;toast('Approve Chat read-only permission in your browser, then come back here');}
$('chat-connect').onclick=$('chat-connect-again').onclick=()=>perform(chatConnect);
$('chat-connection').onclick=()=>perform(loadChat);
$('chat-discover').onclick=()=>perform(()=>chatAction('discover'));
$('chat-sync').onclick=()=>perform(()=>chatAction('sync',{space:chatSpace}));
$('chat-restart').onclick=()=>perform(()=>chatAction('sync',{space:chatSpace,restart:true}));
$('chat-cancel').onclick=()=>perform(()=>chatAction('cancel'));
$('chat-clear').onclick=()=>perform(async()=>{const account=$('chat-cache-account').value;if(await ask('Clear this local Chat account cache? Promoted WorkItem source snapshots and archives remain.',{ok:'Clear cache',danger:true})){await api('/api/chat/clear',{account});chatMessage='';chatSpace='';await loadChat();}});

let ghAccount='',ghItem=0,ghTimer=null,ghWasRunning=false,ghFilter='all',ghKind='all',ghItems=[],ghState={};const ghAutoSynced=new Set();
async function loadGitHub(){
 const status=await api('/api/github'),connection=status.connection;
 if(ghAccount!==connection.account_id){ghAccount=connection.account_id;ghItem=0;ghAutoSynced.clear();$('github-detail').replaceChildren();}
 const overview=connection.connected?await api('/api/github/overview?filter='+ghFilter):{items:[],state:{}};ghItems=overview.items;ghState=overview.state;
 sourceState('github',connection.connected,['@'+connection.login,ghItems.length+' open',jobText(status.job),ghState.last_sync&&'updated '+relTime(ghState.last_sync*1000),ghState.limited&&'first 300'],connection.error||status.job.error);
 $('github-sync').disabled=!connection.connected||status.job.running;$('github-sync').textContent=status.job.running?'Syncing…':ghState.complete===false?'Continue sync':'Sync';
 $('github-cancel').disabled=!status.job.running;$('github-disconnect').disabled=!connection.connected;
 cacheAccounts($('github-cache-account'),$('github-clear'),status.cached_accounts.map(a=>[a.login+' · '+a.id,a.id]),status.job.running);
 // Each filter syncs by itself the first time that you open it.
 if(connection.connected&&!ghState.last_sync&&!ghState.count&&!ghState.page&&!status.job.running&&!ghAutoSynced.has(ghFilter)&&!state?.active&&!(state?.meetings||[]).some(m=>m.status==='processing')){ghAutoSynced.add(ghFilter);await api('/api/github/overview/sync',{filter:ghFilter});ghWasRunning=true;return loadGitHub();}
 segmentedChoice($('github-filters'),[['all','All open'],['assigned','Assigned to me'],['created','Created by me'],['mentioned','Mentioning me']],ghFilter,value=>{ghFilter=value;ghItem=0;perform(loadGitHub);});
 renderGitHubKinds();
 const repos=[...new Set(ghItems.map(r=>r.repository))].sort((a,b)=>a.localeCompare(b)),select=$('github-repo-filter'),old=select.value;
 select.replaceChildren(option('All repositories · '+ghItems.length,''),...repos.map(name=>option(name+' · '+ghItems.filter(r=>r.repository===name).length,name)));select.value=repos.includes(old)?old:'';
 renderGitHubList();
 if(!ghItem)emptyState($('github-detail'),ghItems.length?'Choose an issue or a pull request above to read it here.':'');
 if(ghWasRunning&&!status.job.running){lastTasks='';await loadTasks();if(ghItem)await openGitHubItem(ghItem);}ghWasRunning=status.job.running;
 if(ghTimer)clearTimeout(ghTimer);ghTimer=null;if(status.job.running&&view==='tasks'&&workTab==='github')ghTimer=setTimeout(()=>perform(loadGitHub),1500);
}
function renderGitHubKinds(){segmentedChoice($('github-kinds'),[['all','All'],['issue','Issues'],['pull_request','PRs']],ghKind,value=>{ghKind=value;renderGitHubKinds();renderGitHubList();});}
function renderGitHubList(){
 const query=$('github-search').value.trim().toLocaleLowerCase(),repo=$('github-repo-filter').value,list=$('github-items');const focused=list.contains(document.activeElement);
 const rows=ghItems.filter(r=>(ghKind==='all'||r.kind===ghKind)&&(!repo||r.repository===repo)&&(!query||(r.title+' #'+r.number).toLocaleLowerCase().includes(query)));
 list.replaceChildren(...rows.map(r=>sourceRow(r.issue_id===ghItem,[el('span','row-tag '+(r.kind==='issue'?'issue':'pr'),r.kind==='issue'?'Issue':'PR'),el('span','row-who',r.repository.split('/')[1]),el('strong','row-title','#'+r.number+' '+r.title),el('span','row-when',relTime(Date.parse(r.updated)))],()=>openGitHubItem(r.issue_id))));
 if(focused)list.querySelector('.selected')?.focus();
 if(!rows.length)emptyState(list,ghItems.length?'No item matches this filter.':ghState.last_sync?'Nothing open here. Good news.':'Syncing the open items…');
}
$('github-search').oninput=$('github-repo-filter').onchange=renderGitHubList;listKeys($('github-items'));
async function openGitHubItem(key){
 const r=await api('/api/github/item?id='+key);ghItem=key;renderGitHubList();
 const head=el('div','reader-head'),title=el('h3','',r.title),meta=el('p','hint',r.repository+' #'+r.number+' · '+(r.kind==='issue'?'Issue':'Pull request')+' · '+r.state+' · '+(r.available?'cached '+relTime(r.fetched_at*1000):'source unavailable'));head.append(title,meta);
 const body=el('div','reader-body');body.append(el('p','message-text',r.available?r.body||'No description.':'Access or source unavailable. Historical WorkItem quotes remain.'));
 const actions=el('div','reader-actions'),suggest=el('button','primary small-action','Suggest a task'),refresh=el('button','secondary small-action','Refresh'),link=el('a','secondary small-action button-link','Open on GitHub ↗');
 link.href=r.url;link.target='_blank';link.rel='noopener noreferrer';suggest.disabled=!r.available;
 suggest.onclick=()=>perform(async()=>{const value=await ask('Task proposal from GitHub. The GitHub status does not set the task status.',{ok:'Save suggestion',value:r.title});if(value===null)return;await api('/api/github/propose',{id:key,revision:r.revision,title:value});await refreshAfterItemChange();toast('Saved in Suggested · nothing was accepted yet');});
 refresh.onclick=()=>perform(async()=>{await api('/api/github/refresh',{id:key});ghWasRunning=true;await loadGitHub();});
 actions.append(el('span','reader-quote','Local task status stays independent of GitHub.'),suggest,refresh,link);
 const linked=await api('/api/github/links?'+new URLSearchParams({repository:r.repository,number:String(r.number)}));
 if(linked.length){const box=el('div','linked-in-atlanta');box.append(el('h4','','Linked in Atlanta · on this Mac'));for(const l of linked)box.append(el('p','profile-row',(l.resource_kind==='deleted'?'':l.resource_kind+' · ')+l.resource_text));body.prepend(box);}
 $('github-detail').replaceChildren(head,body,actions);
}
$('github-connect').onclick=()=>perform(async()=>{const token=$('github-token').value.trim();try{await api('/api/github/connect',{token});await loadGitHub();await loadRepoReports();}finally{$('github-token').value='';}});
$('github-disconnect').onclick=()=>perform(async()=>{if(!(await ask('Remove the GitHub token from this Mac? The token stays valid on GitHub until you revoke it there.',{ok:'Disconnect',danger:true})))return;await api('/api/github/disconnect',{});await loadGitHub();repoReport=null;repoReportId='';$('repo-report-detail').replaceChildren();});
$('github-connection').onclick=()=>perform(loadGitHub);
$('github-sync').onclick=()=>perform(async()=>{await api('/api/github/overview/sync',{filter:ghFilter});ghWasRunning=true;await loadGitHub();});
$('github-cancel').onclick=()=>perform(async()=>{await api('/api/github/cancel',{});await loadGitHub();});
$('github-clear').onclick=()=>perform(async()=>{if(await ask('Clear the local GitHub cache for the selected account? Promoted source snapshots and archives remain.',{ok:'Clear cache',danger:true})){await api('/api/github/clear',{account:$('github-cache-account').value});ghItem=0;$('github-detail').replaceChildren();await loadGitHub();}});

let ghSection='items',repoTimer=null,repoAccount='',repoReportId='',repoReport=null,repoJob={},repoLoadSequence=0;
function showGitHubSection(section){
 ghSection=section;$('github-open-items').hidden=section!=='items';$('repo-reports').hidden=section!=='reports';
 $('github-show-items').classList.toggle('selected',section==='items');$('github-show-reports').classList.toggle('selected',section==='reports');
 if(section==='reports')perform(loadRepoReports);
}
$('github-show-items').onclick=()=>showGitHubSection('items');$('github-show-reports').onclick=()=>showGitHubSection('reports');
function reportLink(url,label){
 try{const parsed=new URL(url);if(parsed.protocol!=='https:'||parsed.hostname!=='github.com'||parsed.username||parsed.password)return null;
 const a=el('a','',label);a.href=parsed.href;a.target='_blank';a.rel='noopener noreferrer';return a;}catch{return null;}
}
async function loadRepoReports(){
 const sequence=++repoLoadSequence;
 if(repoTimer)clearTimeout(repoTimer);repoTimer=null;
 const connection=(await api('/api/github')).connection;
 if(!connection.connected){$('report-job-status').textContent='Connect GitHub to collect or open reports.';$('repo-report-detail').replaceChildren();return;}
 const data=await api('/api/github/reports');if(sequence!==repoLoadSequence)return;repoJob=data.job;
 if(repoAccount!==data.account){repoAccount=data.account;repoReport=null;if(!data.reports.some(r=>r.id===repoReportId))repoReportId='';}
 if(!$('report-start').value){$('report-start').value=data.defaults.start;$('report-end').value=data.defaults.end;}
 const repos=[...new Set(ghItems.map(i=>i.repository))];$('report-repositories').replaceChildren(...repos.map(name=>option(name,name)));
 if(!data.reports.some(r=>r.id===repoReportId))repoReportId=data.reports[0]?.id||'';
 $('report-list').replaceChildren(option('Choose a saved report',''),...data.reports.map(r=>option(r.repository+' · '+r.branch+' · '+r.period.start+' → '+r.period.end+' · '+r.status,r.id)));$('report-list').value=repoReportId;
 $('report-collect').disabled=!!data.job.running;$('report-cancel').hidden=!data.job.running;
 $('report-job-status').textContent=data.error||data.job.error||data.job.status||'';
 if(repoReportId){const selectedId=repoReportId,detail=await api('/api/github/reports/detail?id='+encodeURIComponent(selectedId));if(sequence!==repoLoadSequence||selectedId!==repoReportId)return;repoReport=detail;renderRepoReport();}
 else $('repo-report-detail').replaceChildren(el('p','empty-content','Choose a repository and period to collect its changes. Collection does not send code to AI.'));
 if(data.job.running&&view==='tasks'&&workTab==='github'&&ghSection==='reports')repoTimer=setTimeout(()=>perform(loadRepoReports),1500);
}
async function openRepoReport(id){const sequence=++repoLoadSequence;repoReportId=id;$('report-list').value=id;if(!id){repoReport=null;$('repo-report-detail').replaceChildren();return;}const detail=await api('/api/github/reports/detail?id='+encodeURIComponent(id));if(sequence!==repoLoadSequence||id!==repoReportId)return;repoReport=detail;renderRepoReport();}
$('report-list').onchange=()=>perform(()=>openRepoReport($('report-list').value));
$('report-clear-all').onclick=()=>perform(async()=>{if(await ask('Delete all local repository reports, cached diffs and AI results for every cached account? Promoted WorkItem quotes and existing archives remain.',{ok:'Clear reports',danger:true})){await api('/api/github/reports/clear',{confirmed:true});repoReportId='';repoReport=null;$('repo-report-detail').replaceChildren();toast('Local repository reports cleared');}});
$('report-cancel').onclick=()=>perform(async()=>{await api('/api/github/reports/cancel',{});await loadRepoReports();});
$('repo-report-form').onsubmit=event=>{event.preventDefault();perform(async()=>{const result=await api('/api/github/reports/collect',{repository:$('report-repository').value.trim(),branch:$('report-branch').value.trim(),start:$('report-start').value,end:$('report-end').value});repoReportId=result.report_id;await loadRepoReports();});};
async function analyzeRepoReport(){
 const id=repoReport.id,preview=await api('/api/github/reports/preview',{id}),t=preview.target;
 const approved=await ask('Send this repository snapshot to AI?\n'+repoReport.repository+' · '+repoReport.branch+'\n'+repoReport.period.start+' → '+repoReport.period.end+'\nEndpoint: '+t.local_ai_base_url+'\nModel: '+t.local_ai_model+' · reasoning: '+t.local_ai_reasoning+' · output: '+t.local_ai_max_tokens+'\n'+preview.parts+' parts · '+preview.characters+' characters'+(preview.omitted_parts?' · '+preview.omitted_parts+' parts excluded by the AI limit':'')+(preview.partial?'\nCollection is partial; check the coverage below.':'')+'\nCode, PR descriptions and diff context will be sent. Suggestions require review. No GitHub writes.',{ok:'Approve & analyze',cancel:'Cancel'});
 if(!approved)return;
 await api('/api/github/reports/analyze',{id,preview_token:preview.preview_token,approved:true});await loadRepoReports();
}
function reportFindings(parts){
 const combined=new Map();
 for(const finding of Object.values(parts).flat()){
  const key=finding.kind+'|'+finding.certainty+'|'+finding.text.trim().toLocaleLowerCase().replace(/\s+/g,' '),existing=combined.get(key);
  if(!existing){combined.set(key,{...finding,evidence:[...finding.evidence]});continue;}
  for(const ref of finding.evidence)if(existing.evidence.length<3&&!existing.evidence.some(r=>r.id===ref.id&&r.quote===ref.quote))existing.evidence.push(ref);
 }
 return [...combined.values()];
}
function renderRepoReport(){
 const r=repoReport,box=$('repo-report-detail');box.replaceChildren();if(!r)return;
 const busy=!!repoJob.running,head=el('div','card-heading');head.append(el('h3','',r.repository+' · '+r.branch));
 const remove=el('button','quiet danger-text','Delete report');remove.type='button';remove.disabled=busy;remove.onclick=()=>perform(async()=>{if(await ask('Delete this local report and its cached code? Promoted WorkItem quotes and existing archives remain.',{ok:'Delete report',danger:true})){await api('/api/github/reports/delete',{id:r.id});repoReportId='';await loadRepoReports();}});head.append(remove);box.append(head);
 box.append(el('p','hint',r.period.start+' → '+r.period.end+' · Europe/Sofia · '+r.status));
 if(r.head){const link=reportLink('https://github.com/'+r.repository+'/commit/'+r.head,'Pinned branch head '+r.head.slice(0,8));if(link)box.append(link);}
 if(r.error)box.append(el('p','notice',r.error));
 const actions=el('div','work-actions');
 if(!r.collection_complete){const resume=el('button','secondary','Continue collection');resume.type='button';resume.disabled=busy;resume.onclick=()=>perform(async()=>{await api('/api/github/reports/collect',{id:r.id});await loadRepoReports();});actions.append(resume);}
 else {const ai=el('button','primary',r.analysis?.complete?'Analyze / use cached result':'Analyze with AI');ai.type='button';ai.disabled=busy||!r.evidence.length;ai.onclick=()=>perform(analyzeRepoReport);actions.append(ai);}
 const suggested=el('button','quiet','View suggestions');suggested.type='button';suggested.onclick=()=>showWorkTab('suggested');actions.append(suggested);box.append(actions);
 const coverage=el('details','report-coverage'),omitted=r.coverage?.omitted||[],warnings=r.coverage?.warnings||[];
 const count=Object.values(r.changes||{}).filter(c=>!c.skipped).length,partial=omitted.length||warnings.length||r.evidence.length>80;
 coverage.append(el('summary','',(partial?'Partial coverage':'Collected coverage')+' · '+count+' logical changes · '+(r.coverage?.files||0)+' files · '+r.evidence.length+' evidence parts'));
 coverage.append(el('p','hint','PRs use merge time; other commits use committer time. Historic push times and complete branch history are not reconstructed. File context is bounded. CI and deployment status are not collected; AI findings are not proof of completed work.'));
 if(r.evidence.length>80)coverage.append(el('p','notice','AI reads the first 80 parts. '+(r.evidence.length-80)+' collected parts are excluded from analysis.'));
 for(const text of warnings)coverage.append(el('p','notice',text));
 for(const entry of omitted)coverage.append(el('p','hint',entry.change+' · '+entry.file+' · '+entry.reason));box.append(coverage);
 const association=el('div','work-actions'),meeting=el('select');meeting.setAttribute('aria-label','Link report to a meeting');meeting.append(option('No linked meeting',''),...(state.meetings||[]).map(m=>option(m.title,m.id)));meeting.value=r.meeting_id||'';
 const linkMeeting=el('button','secondary','Link meeting');linkMeeting.type='button';linkMeeting.disabled=busy;linkMeeting.onclick=()=>perform(async()=>{repoReport=await api('/api/github/reports/associate',{id:r.id,meeting_id:meeting.value||null});renderRepoReport();});association.append(meeting,linkMeeting);
 if(r.meeting_id){const open=el('button','quiet','Open linked meeting');open.type='button';open.onclick=()=>perform(()=>openMeeting(r.meeting_id));association.append(open);}box.append(association);
 if(r.related_items?.length){const related=el('section','report-findings');related.append(el('h4','','Related work (same repository or linked meeting)'));for(const item of r.related_items)related.append(el('p','hint',item.kind+' · '+item.status+' · '+item.text));const open=el('button','quiet','Open My Work');open.type='button';open.onclick=()=>{sourceFilter='';showWorkTab('task');};related.append(open);box.append(related);}
 if(r.analysis){box.append(el('p','hint','AI interpretation · '+r.analysis.target.local_ai_model+' · '+r.analysis.target.local_ai_base_url+' · '+Object.keys(r.analysis.parts).length+' parts completed. Check conclusions against their source.'));
  const findings=reportFindings(r.analysis.parts);
  const groups={change:'What changed',impact:'Practical effect',risk:'Risks and uncertainties',verification:'Checks to make',follow_up:'Suggested follow-ups'};
  if(!findings.length)box.append(el('p','empty-note',r.analysis.complete?'Analysis complete. No supported findings were returned.':'No completed analysis parts yet.'));
  for(const [kind,title] of Object.entries(groups)){
   const rows=findings.filter(f=>f.kind===kind);if(!rows.length)continue;const section=el('section','report-findings');section.append(el('h4','',title));
   for(const f of rows){const card=el('article','report-finding');card.append(el('p','',f.text),el('span','hint','AI · '+(f.certainty==='inference'?'inference':'source-based observation')));
    for(const ref of f.evidence){const ev=r.evidence.find(e=>e.id===ref.id);if(!ev)continue;const quote=el('blockquote','',ref.quote),source=reportLink(ev.url,ev.filename||ev.kind);card.append(quote);if(source)card.append(source);}
    const suggest=el('button','secondary small-action','Suggest a task');suggest.type='button';suggest.disabled=busy;suggest.onclick=()=>perform(async()=>{await api('/api/github/reports/propose',{id:r.id,finding_id:f.id});await refreshAfterItemChange();toast('Saved in Suggested · no task status changed');});card.append(suggest);section.append(card);
   }box.append(section);
  }
 }
 const sources=el('details','report-sources');sources.append(el('summary','','Collected evidence · '+r.evidence.length));
 for(const ev of r.evidence){const entry=el('details');entry.append(el('summary','',ev.filename||ev.kind),el('pre','report-source',ev.text));const link=reportLink(ev.url,'Open on GitHub');if(link)entry.append(link);sources.append(entry);}box.append(sources);
}

let proposalFilter='pending';
async function graphAction(action,body){await api('/api/work/'+action,body);await refreshAfterItemChange();}
function renderWorkGraph(){
 const graph=itemsData.graph||{},today=state.task_summary?.today||new Date().toLocaleDateString('en-CA');
 const sources=Object.fromEntries((graph.sources||[]).map(s=>[s.id,s])),evidence=Object.fromEntries((graph.source_evidence||[]).map(e=>[e.id,e]));
 const filters=$('proposal-filters');filters.replaceChildren();
 for(const value of ['pending','snoozed','dismissed','all']){const b=el('button',proposalFilter===value?'selected':'',value[0].toUpperCase()+value.slice(1));b.onclick=()=>{proposalFilter=value;renderWorkGraph();};filters.append(b);}
 const list=$('proposal-list');list.replaceChildren();
 const waiting=(graph.proposals||[]).filter(p=>p.state==='pending'&&(!p.snoozed_until||p.snoozed_until<=today)).length;$('work-tabs').querySelector('[data-work-tab=suggested]').textContent='Suggested'+(waiting?' · '+waiting:'');
 const proposals=(graph.proposals||[]).filter(p=>proposalFilter==='all'||(proposalFilter==='dismissed'?p.state==='dismissed':p.state==='pending'&&(proposalFilter==='snoozed'?p.snoozed_until>today:!p.snoozed_until||p.snoozed_until<=today)));
 for(const p of proposals){
  const card=el('div','work-proposal'),ev=evidence[p.evidence_id],source=sources[ev?.source_id];
  const top=el('div','proposal-top');top.append(source?originChip(source.provider,sourceLabel(source),()=>openSource(source)):originChip('','Unavailable source'),el('span','hint',(['gmail_ai','repo_ai'].includes(p.origin)?'AI suggestion · ':'')+p.kind+' · '+p.state+(p.snoozed_until?' · snoozed until '+p.snoozed_until:'')));
  card.append(top,el('strong','proposal-text',p.text));
  if(p.fields&&Object.keys(p.fields).length)card.append(el('p','hint',Object.entries(p.fields).map(([name,value])=>(name==='due_date'?'Due date':name==='owner'?'Owner':'Deadline')+': '+value).join(' · ')));
  if(source?.remote?.authority==='github')card.append(el('p','hint','GitHub '+(source.remote.kind==='pull_request'?'PR':'issue')+' state: '+source.remote.state+' · local task status is independent'+(!source.available?' · Source unavailable':'')));
  if(ev){const quote=el('blockquote','',ev.quote);card.append(quote,el('p','hint',(source?source.account:'Unavailable source')+' · saved revision '+ev.source_revision.slice(0,12)));}
  const actions=el('div','work-actions'),review=(action,extra={})=>graphAction('review',{id:p.id,revision:p.revision,action,...extra});
  const button=(label,run)=>{const b=el('button','secondary small-action',label);b.onclick=()=>perform(run);actions.append(b);};
  if(p.state==='pending'){
   button('Accept',()=>review('accept'));actions.lastChild.className='primary small-action';
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
  const b=el('button','secondary small-action',q.status==='answered'?'Reopen':'Answer');b.onclick=()=>perform(async()=>{const answer=q.status==='answered'?null:await ask('Answer: '+q.text,{ok:'Save answer',value:''});if(q.status!=='answered'&&answer===null)return;await graphAction('question',{id:q.id,revision:q.revision,answer});});row.append(b,projectAssignment(q),githubActions({kind:'item',id:q.id}));questions.append(row);
 }
 if(!questions.children.length)questions.append(el('p','hint','No questions yet. Add one or accept a question proposal.'));
}
$('new-work-question').onclick=()=>perform(async()=>{const value=await ask('New question',{ok:'Add question',value:''});if(value!==null)await graphAction('question',{text:value});});

function renderTasks() {
 if(itemEditing)return;
 renderWorkGraph();
 const today=state.task_summary?.today||new Date().toISOString().slice(0,10), meetings=itemsData.meetings, byId=Object.fromEntries(itemsData.items.map(item=>[item.id,item]));
 const project=$('work-project'), oldProject=project.value;
 project.replaceChildren(option('All projects',''),option('Unassigned','__none__'),...(state.projects?.projects||[]).map(p=>option(p.name,p.id)));
 if([...project.options].some(o=>o.value===oldProject))project.value=oldProject;
 const inProject=item=>!project.value||(project.value==='__none__'?!item.effective_project_ids?.length:item.effective_project_ids?.includes(project.value));
 const tasks=itemsData.items.filter(item=>item.kind==='task'&&inProject(item)), decisions=itemsData.items.filter(item=>item.kind==='decision'&&inProject(item));
 const open=tasks.filter(t=>t.status==='open'&&!t.dismissed&&(!t.snoozed_until||t.snoozed_until<=today)), late=open.filter(t=>t.due_date&&t.due_date<today), pending=itemsData.pending.filter(entry=>!project.value||meetings[entry.meeting_id]?.project_id===project.value);
 const accepted=decisions.filter(d=>d.status==='accepted'&&!d.dismissed&&(!d.snoozed_until||d.snoozed_until<=today)).length;
 $('tasks-summary').textContent=open.length+' open task'+(open.length===1?'':'s')+' · '+late.length+' overdue · '+accepted+' accepted decision'+(accepted===1?'':'s')+(pending.length?' · '+pending.length+' to review':'');
 for(const button of document.querySelectorAll('[data-kind]')) { const count=pending.filter(p=>p.kind===button.dataset.kind).length; button.textContent=(button.dataset.kind==='task'?'Tasks':'Decisions')+(count?' · '+count+' to review':''); }
 const review=pending.filter(entry=>entry.kind===itemKind); $('link-review').hidden=!review.length; $('link-review').replaceChildren();
 if(review.length) { $('link-review').append(el('h2','',review.length+' to review'),el('p','hint','The AI found mentions that look like existing items. Nothing is linked until you choose.')); for(const entry of review) $('link-review').append(linkCard(entry,meetings,byId)); }
 const filter=statusFilter[itemKind];
 $('status-filter').replaceChildren(...STATUS_FILTERS[itemKind].map(([key,label])=>{const button=el('button',key===filter?'selected':'',label);button.type='button';button.onclick=()=>{statusFilter[itemKind]=key;renderTasks();};return button;}));
 segmentedChoice($('source-filter'),[['','All sources'],['meeting','Meetings'],['gmail','Gmail'],['google_chat','Chat'],['github','GitHub']],sourceFilter,value=>{sourceFilter=value;renderTasks();});
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
 if(sourceFilter)rows=rows.filter(item=>itemProviders(item).has(sourceFilter));
 $('task-list').replaceChildren();
 const empty=itemKind==='task'?'No tasks yet. Generate notes for a meeting to collect its tasks here.':'No decisions yet. Generate notes for a meeting to collect its decisions here.';
 if(!rows.length) $('task-list').append(el('p','empty-content',(itemKind==='task'?tasks:decisions).length?'Nothing matches this filter.':empty));
 for(const item of rows) $('task-list').append(itemKind==='task'?globalTaskRow(item,today):decisionRow(item,byId));
}
// My Work shows one section at a time. Tasks and Decisions share one panel; each source loads when its tab opens.
const WORK_PANELS={task:'items-panel',decision:'items-panel',suggested:'work-suggested',questions:'questions-panel',gmail:'gmail-panel',chat:'chat-panel',github:'github-panel'};
let workTab='task';try{workTab=WORK_PANELS[localStorage.getItem('work-tab')]?localStorage.getItem('work-tab'):'task';}catch{}
function showWorkTab(tab){
 workTab=tab;syncRoute(true);try{localStorage.setItem('work-tab',tab);}catch{}
 for(const button of $('work-tabs').querySelectorAll('button')){const current=button.dataset.workTab===tab;button.classList.toggle('selected',current);button.setAttribute('aria-selected',String(current));}
 for(const id of new Set(Object.values(WORK_PANELS)))$(id).hidden=id!==WORK_PANELS[tab];
 for(const timer of [mailTimer,chatTimer,ghTimer,repoTimer])if(timer)clearTimeout(timer);mailTimer=chatTimer=ghTimer=repoTimer=null;
 if(tab==='task'||tab==='decision'){itemKind=tab;renderTasks();}
 else if(tab==='gmail')perform(loadMail);else if(tab==='chat')perform(loadChat);else if(tab==='github')perform(async()=>{await loadGitHub();showGitHubSection(ghSection);});
}
for(const button of $('work-tabs').querySelectorAll('button')) button.onclick=()=>showWorkTab(button.dataset.workTab);
// Projects group meetings; a series groups the meetings that repeat inside a project.
let lastProjects='', prepareScope={project:'',series:'',type:''}, prepareData=null;
const projectList=()=>state?.projects?.projects||[];
const seriesOf=projectId=>(state?.projects?.series||[]).filter(series=>series.project_id===projectId);
// Meeting types: the purpose of a meeting adds sections to its notes and changes Prepare me.
const typeList=()=>state?.meeting_types||[];
const typeOf=id=>typeList().find(t=>t.id===id)||typeList()[0]||{id:'general',label:'General',description:'',task_title:'Tasks',export:'Meeting summary',sections:[]};
// A meeting with an own template uses its own copy of the template, even after the template changes.
function meetingType(d) {
 const template=d?.meeting_template; if(!template) return typeOf(d?.meeting_type);
 return {id:d.meeting_type,label:template.label,description:template.description||'',task_title:'Tasks',export:template.label+' summary',custom:true,
  sections:template.sections.map((s,i)=>({key:'custom_'+(i+1),title:s.title,attention:s.review?['Check {n} item in '+s.title,'Check {n} items in '+s.title]:null}))};
}
const seriesType=id=>(state?.projects?.series||[]).find(s=>s.id===id)?.type||'general';
function fillTypes(select,value,extra=[]) {
 const group=(label,types)=>{const box=el('optgroup');box.label=label;box.append(...types.map(t=>option(t.label,t.id)));return box;}, own=typeList().filter(t=>t.custom);
 select.replaceChildren(group('Built-in',typeList().filter(t=>!t.custom)),...(own.length?[group('Your templates',own)]:[]),...extra);
 select.value=[...select.options].some(o=>o.value===value)?value:'general';
}
// The sections of every type are note fields, so editing, review and saving treat them like the summary.
let lastTypes='';
function registerTypes() {
 for(const [key,title] of [...typeList().filter(t=>!t.custom).flatMap(t=>t.sections.map(s=>[s.key,s.title])),['custom_1','Section 1'],['custom_2','Section 2'],['custom_3','Section 3']])
  if(!(key in FIELD_TITLES)){FIELD_TITLES[key]=title;ITEM_FIELDS.push(key);NOTE_FIELDS.push(key);}
 const signature=JSON.stringify(typeList()); if(signature===lastTypes) return; lastTypes=signature;
 fillTypes($('record-type'),$('record-type').value||seriesType($('record-series').value)); if($('settings-dialog').open) renderTypeSettings();
}
// The sections of this meeting's type, and sections of an earlier type that still hold notes.
function typeSections(type,minutes) {
 const own=type.sections, other=[...typeList().filter(t=>!t.custom).flatMap(t=>t.sections),...['custom_1','custom_2','custom_3'].map(key=>({key,title:FIELD_TITLES[key]}))].filter(s=>!own.some(o=>o.key===s.key)&&(minutes[s.key]||[]).length);
 return [...own,...other.filter((s,i)=>other.findIndex(o=>o.key===s.key)===i)];
}
function fillProjects(select,value,none,extra=[]) { select.replaceChildren(option(none,''),...projectList().map(p=>option(p.name,p.id)),...extra); select.value=[...select.options].some(o=>o.value===value)?value:''; }
function fillSeries(select,projectId,value,none,extra=[]) { select.replaceChildren(option(none,''),...seriesOf(projectId).map(s=>option(s.name,s.id)),...extra); select.value=[...select.options].some(o=>o.value===value)?value:''; select.disabled=!projectId&&!extra.length; }
function syncProjects() {
 registerTypes();
 const signature=JSON.stringify(state.projects); if(signature===lastProjects) return; lastProjects=signature;
 fillProjects($('project-filter'),$('project-filter').value,'All projects',projectList().length?[option('No project','__none__')]:[]); $('project-filter').hidden=!projectList().length;
 fillProjects($('record-project'),$('record-project').value,'No project'); fillSeries($('record-series'),$('record-project').value,$('record-series').value,'No series');
 $('record-prepare').disabled=!$('record-project').value;
 if($('settings-dialog').open) renderProjectSettings();
 if(view==='detail'&&detail) renderScope(detail);
}
$('project-filter').onchange=()=>{lastLibrary='';renderLibrary();};
$('record-project').onchange=()=>{fillSeries($('record-series'),$('record-project').value,'','No series');$('record-prepare').disabled=!$('record-project').value;$('record-type').value=seriesType('');renderRecordMore();};
// A series brings its default type; the person can still choose another one for this meeting.
$('record-series').onchange=()=>{$('record-type').value=seriesType($('record-series').value);renderRecordMore();};
$('record-prepare').onclick=()=>perform(()=>openPrepare($('record-project').value,$('record-series').value,$('record-type').value));
function renderScope(d) {
 const box=$('detail-scope'), project=projectList().find(p=>p.id===d.project_id), series=seriesOf(d.project_id).find(s=>s.id===d.series_id); box.replaceChildren();
 const edit=el('button','quiet scope-chip',project?project.name+(series?' · '+series.name:'')+' ✎':'＋ Add to a project'); edit.type='button'; edit.title='Project and series of this meeting'; edit.onclick=()=>openScopeDialog(d); box.append(edit);
 const type=el('select','scope-chip scope-type'); type.setAttribute('aria-label','Meeting type'); type.title='Meeting type · changes the notes sections and Prepare me'; fillTypes(type,d.meeting_type||'general',d.meeting_template&&!typeList().some(t=>t.id===d.meeting_type)?[option(d.meeting_template.label+' · deleted template',d.meeting_type)]:[]);
 type.onchange=()=>perform(async()=>{const value=type.value;detail=await api('/api/meetings/'+d.id+'/type',{meeting_type:value});lastFingerprint=JSON.stringify(detail);renderDetail();
  // Saved notes stay; new notes for the type become a proposal that the person reviews.
  if(detail.minutes&&!['starting','recording','paused','stopping','processing'].includes(detail.status)&&await ask('Make new notes for the type "'+typeOf(value).label+'"?\n\nYour saved notes stay as they are. You review each change before it is applied.',{ok:'Make new notes'})){
   if(state.settings.summarizer==='none'){openSettings('notes');return;} await api('/api/meetings/'+d.id+'/process',{action:'summarize'}); await openMeeting(d.id,true);
  } else toast('Meeting type saved');});
 box.append(type);
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
// Settings → Meeting types: the built-in types, read-only, and your own templates.
function renderTypeSettings() {
 const list=$('type-list'); list.replaceChildren();
 for(const type of typeList()){
  const row=el(type.custom?'button':'div','type-row'+(type.custom?' own':''));if(type.custom){row.type='button';row.onclick=()=>openTemplate(type.template);}
  row.append(el('strong','',type.label+(type.custom?'':' · built-in')),el('span','hint',type.description),el('span','type-sections',type.sections.length?type.sections.map(s=>s.title).join(' · '):'Common notes only'));
  list.append(row);
 }
}
let templateEditing=null;
function openTemplate(template) {
 templateEditing=template||null; $('template-error').hidden=true; $('template-title').textContent=template?template.label:'New template';
 $('template-label').value=template?.label||''; $('template-description').value=template?.description||''; $('template-delete').hidden=!template;
 $('template-prepare').replaceChildren(...typeList().filter(t=>!t.custom).map(t=>option(t.label,t.id))); $('template-prepare').value=template?.prepare||'general';
 const sections=template?.sections||[];
 $('template-sections').replaceChildren(...[0,1,2].map(i=>{const box=el('fieldset','template-section'),s=sections[i]||{};box.append(el('legend','','Section '+(i+1)+(i?' (optional)':'')));
  const title=el('input');title.className='template-section-title';title.maxLength=60;title.placeholder=['For example Options','For example Trade-offs','For example Follow-ups'][i];title.value=s.title||'';title.setAttribute('aria-label','Title of section '+(i+1));
  const instruction=el('input');instruction.className='template-section-instruction';instruction.maxLength=300;instruction.placeholder='What the AI writes here, for example: the options that were compared';instruction.value=s.instruction||'';instruction.setAttribute('aria-label','Instruction for section '+(i+1));
  const review=el('label','checkbox'),box2=el('input');box2.type='checkbox';box2.className='template-section-review';box2.checked=!!s.review;review.append(box2,document.createTextNode(' Ask me to check these items after the meeting'));
  box.append(title,instruction,review);return box;}));
 if(!$('template-dialog').open)$('template-dialog').showModal(); $('template-label').focus();
}
$('add-template').onclick=()=>openTemplate(null);
$('template-close').onclick=()=>$('template-dialog').close();
$('template-form').onsubmit=event=>{event.preventDefault();perform(async()=>{
 const sections=[...$('template-sections').querySelectorAll('.template-section')].map(box=>({title:box.querySelector('.template-section-title').value.trim(),instruction:box.querySelector('.template-section-instruction').value.trim(),review:box.querySelector('.template-section-review').checked})).filter(s=>s.title||s.instruction);
 try{const result=await api('/api/templates/save',{id:templateEditing?.id,revision:templateEditing?.revision,label:$('template-label').value,description:$('template-description').value,prepare:$('template-prepare').value,sections});
  state.meeting_types=result.meeting_types;registerTypes();renderTypeSettings();$('template-dialog').close();toast('Saved '+result.template.label);}
 catch(e){$('template-error').textContent=e.message;$('template-error').hidden=false;}});};
$('template-delete').onclick=()=>perform(async()=>{if(!templateEditing||!(await ask('Delete the template "'+templateEditing.label+'"?\n\nSaved meetings keep their notes and their copy of the template. Series that use it become General.',{ok:'Delete',danger:true})))return;
 const result=await api('/api/templates/delete',{id:templateEditing.id,revision:templateEditing.revision});state.meeting_types=result.meeting_types;state.projects=result.projects;lastProjects='';registerTypes();syncProjects();renderTypeSettings();$('template-dialog').close();toast('Template deleted');});
function renderProjectSettings() {
 const list=$('project-list'); list.replaceChildren();
 if(!projectList().length) list.append(el('p','empty-content','No projects yet. Open a saved meeting and choose ＋ Add to a project.'));
 const row=(kind,entry)=>{const line=el('div','scope-entry '+kind),rename=el('button','quiet','Rename'),remove=el('button','quiet danger-text','Delete');rename.type=remove.type='button';
  line.append(el(kind==='projects'?'strong':'span','',entry.name),rename,remove);
  const change=async body=>{state.projects=(await api('/api/projects/change',Object.assign({kind,id:entry.id},body))).projects;lastProjects='';syncProjects();renderProjectSettings();};
  if(kind==='series'){const type=el('select');type.setAttribute('aria-label','Default meeting type of '+entry.name);type.title='New meetings of this series start with this type';fillTypes(type,entry.type||'general');
   type.onchange=()=>perform(async()=>{await change({action:'type',name:type.value});toast('New meetings of "'+entry.name+'" start as '+typeOf(type.value).label);});line.insertBefore(type,rename);}
  rename.onclick=()=>perform(async()=>{const name=await ask('New name',{value:entry.name,ok:'Rename'});if(name?.trim()&&name.trim()!==entry.name)await change({action:'rename',name});});
  remove.onclick=()=>perform(async()=>{if(await ask('Delete "'+entry.name+'"'+(kind==='projects'?' and its series':'')+'?\n\nMeetings stay; they only leave this group.',{ok:'Delete',danger:true}))await change({action:'delete'});});
  return line;};
 for(const project of projectList()) { const box=el('div','project-entry'); box.append(row('projects',project),...seriesOf(project.id).map(series=>row('series',series))); list.append(box); }
}
function sourceListen(source){return source?.meeting_id&&source.timestamp?listenButton(source.meeting_id,stampSeconds(source.timestamp),{label:'',className:'chip-listen'}):'';}
function sourceChip(source) {
 const chip=el('button','meeting-chip','↗ '+withDate(source.meeting_title,source.meeting_date)+(source.timestamp?' · '+source.timestamp:'')); chip.type='button'; chip.title='Open the meeting at this moment';
 chip.onclick=()=>perform(async()=>{await openMeeting(source.meeting_id);if(source.timestamp&&detail.transcript.length)showMoment(source.timestamp);else switchTab('outcomes');});
 return chip;
}
async function openPrepare(projectId,seriesId,kind) {
 if(!(await leaveEdits())) return; dirtyTranscript=dirtyNotes=false; selected=null; show('prepare');
 prepareScope={project:projectId||prepareScope.project||projectList()[0]?.id||'',series:projectId?seriesId||'':prepareScope.series,type:kind||''};
 renderLibrary(); await loadPrepare();
}
async function loadPrepare() {
 syncRoute(true);
 fillProjects($('prepare-project'),prepareScope.project,'Choose a project'); fillSeries($('prepare-series'),prepareScope.project,prepareScope.series,'All meetings of the project');
 $('prepare-empty').hidden=!!projectList().length; $('prepare-content').hidden=true;
 if(!prepareScope.project){$('prepare-summary').textContent='Choose a project or a series.';return;}
 const query=prepareScope.series?{series:prepareScope.series}:{project:prepareScope.project};if(prepareScope.type)query.type=prepareScope.type;
 prepareData=await api('/api/prepare?'+new URLSearchParams(query));
 const picker=$('prepare-type');picker.replaceChildren(option('Choose the upcoming meeting type…',''),...(state.meeting_types||[]).map(t=>option(t.label,t.id)));picker.value=prepareData.requires_type?'':prepareScope.type||prepareData.meeting_type;
 if(prepareData.requires_type){$('prepare-summary').textContent='This project contains different meeting types. Choose the upcoming meeting before preparing its agenda.';return;}
 renderPrepare(prepareData);
}
$('prepare-project').onchange=()=>{prepareScope={project:$('prepare-project').value,series:'',type:''};perform(loadPrepare);};
$('prepare-series').onchange=()=>{prepareScope.series=$('prepare-series').value;prepareScope.type='';perform(loadPrepare);};
$('open-prepare').onclick=()=>perform(()=>openPrepare());
$('copy-agenda').onclick=()=>perform(async()=>{await navigator.clipboard.writeText(prepareData.markdown);toast('Agenda copied · paste it into the invitation or a chat');});
function renderPrepare(data) {
 const last=data.meetings.at(-1);
 const type=typeOf(data.meeting_type), label=type.id==='general'?'':' · '+type.label;
 $('prepare-summary').textContent=data.meetings.length?data.title+label+' · '+data.meetings.length+(data.meetings.length===1?' meeting':' meetings')+' · last: '+withDate(last.title,last.date):data.title+label+' · no meetings yet';
 $('prepare-content').hidden=false;
 const sources=list=>{const box=el('div','item-meetings');for(const source of list.filter(Boolean))box.append(sourceChip(source),sourceListen(source));return box;};
 $('prepare-sections-card').hidden=!data.sections?.length;
 $('prepare-sections').replaceChildren(...(data.sections||[]).map(section=>{const box=el('section','note-section');box.append(el('h3','',section.title),...section.items.map(entry=>{const row=el('div','prepare-question');row.append(el('p','',entry.text),sources([entry.source]));return row;}));return box;}));
 $('prepare-tasks-title').textContent=type.id==='incident'?'Open corrective actions':type.id==='daily'?'Open tasks by person':'Open tasks';
 $('prepare-agenda').replaceChildren(...data.agenda.map(entry=>{const item=el('li');item.append(el('span','agenda-title',entry.title));if(entry.sources.length)item.append(sources(entry.sources));return item;}));
 const today=state.task_summary?.today||new Date().toISOString().slice(0,10);
 $('prepare-tasks').replaceChildren(...(data.tasks.length?data.tasks.map(task=>{
  const [kind,label]=dueInfo(Object.assign({status:'open'},task),today), row=el('div','tracked-task '+kind), done=el('input'), main=el('div','tracked-main'), meta=el('div','tracked-meta'), who=el('span','tracked-owner');
  done.type='checkbox'; done.setAttribute('aria-label','Mark task as done'); done.onchange=()=>perform(()=>changeItem({id:task.item_id,text:task.text},{status:'done'}));
  who.append(speakerBadge(el('span'),task.owner||''),el('span','',task.owner||'No owner')); meta.append(who,el('span','due-label '+kind,task.due_date?label+' · '+task.due_date:label));
  if(task.deadline) meta.append(el('span','hint','Said: '+task.deadline));
  if(task.stalled) meta.append(el('span','hint','No change for '+task.idle_days+' days'));
  main.append(el('p','tracked-text',task.text),meta,sources([task.source])); row.append(done,main); return row;}):[el('p','empty-content','No open tasks.')]));
 // A daily goes person by person, so its tasks are grouped by owner.
 if(type.id==='daily'&&data.tasks.length){const rows=[...$('prepare-tasks').children],groups=new Map();data.tasks.forEach((task,i)=>{const owner=task.owner||'No owner';if(!groups.has(owner))groups.set(owner,[]);groups.get(owner).push(rows[i]);});
  $('prepare-tasks').replaceChildren(...[...groups].sort(([a],[b])=>(a==='No owner')-(b==='No owner')||a.localeCompare(b)).flatMap(([owner,list])=>[el('h3','prepare-owner',owner+' · '+list.length),...list]));}
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
 const sources=el('div','item-meetings'); sources.append(sourceChip(result),sourceListen(result)); row.append(sources); return row;
}
async function openFind(query) {
 if(!(await leaveEdits())) return; dirtyTranscript=dirtyNotes=false; selected=null; show('find'); renderLibrary();
 fillProjects($('find-project'),$('find-project').value,'All projects');
 $('find-kinds').replaceChildren(...FIND_KINDS.map(([key,label])=>{const button=el('button',key===findKind?'selected':'',label);button.type='button';button.onclick=()=>{findKind=key;openFind($('find-query').value);};return button;}));
 if(query!==undefined) $('find-query').value=query;
 $('find-query').focus(); if($('find-query').value.trim()) perform(runFind);
}
let findSequence=0;
async function runFind() {
 const query=$('find-query').value.trim(),sequence=++findSequence; $('find-results').replaceChildren(); if(!query) return;
 const results=await api('/api/find?'+new URLSearchParams({q:query,kind:findKind,project:$('find-project').value}));
 // A slower answer to an earlier search must not replace the newer results.
 if(sequence!==findSequence)return;
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
 const list=entries=>{const wrap=el('div');for(const entry of entries){const row=el('div','prepare-question'),chips=el('div','item-meetings');chips.append(sourceChip(entry),sourceListen(entry));row.append(el('p','',entry.text),chips);wrap.append(row);}return wrap;};
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
   for(const number of full.ai.cited){const chip=sourceChip(full.sources[number-1]);chip.textContent='['+number+'] '+chip.textContent;cites.append(chip,sourceListen(full.sources[number-1]));}written.append(cites);}
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
// Profiles fill the form; nothing changes until Save settings.
const PROFILES={
 fast:{provider:'local','local-model':'large-v3-turbo','live-enabled':false,'transcript-correction':'none','diarization-enabled':false,'whisper-vad':true},
 balanced:{provider:'local','local-model':'large-v3-turbo','live-enabled':true,'transcript-correction':'none','diarization-enabled':true,'whisper-vad':true},
 best:{provider:'local','local-model':'large-v3','live-enabled':true,'transcript-correction':'local','diarization-enabled':true,'whisper-vad':true},
};
const CLOUD_FIELDS=['provider','summarizer','transcript-correction','title-provider'];
function applyProfile(name){
 if(name==='private'){for(const id of CLOUD_FIELDS)if($(id).value==='openai')$(id).value='local';}
 else for(const [id,value] of Object.entries(PROFILES[name]))$(id)[typeof value==='boolean'?'checked':'value']=value;
 if(name==='fast'&&/qwen3\.5/i.test($('local-ai-model').value))$('local-ai-reasoning').value='none';
 settingsFields();markProfile();toast('Profile filled in. Save settings to apply.');
}
function markProfile(){
 const fits=name=>name==='private'?CLOUD_FIELDS.every(id=>$(id).value!=='openai'):Object.entries(PROFILES[name]).every(([id,value])=>(typeof value==='boolean'?$(id).checked:$(id).value)===value);
 for(const b of document.querySelectorAll('.profile'))b.classList.toggle('selected',fits(b.dataset.profile));
}
for(const b of document.querySelectorAll('.profile'))b.onclick=()=>applyProfile(b.dataset.profile);
$('settings-form').addEventListener('change',markProfile);
function showAdvanced(on){$('settings-advanced').checked=on;$('settings-form').classList.toggle('simple',!on);store('settings-advanced',on?'1':'');}
$('settings-advanced').onchange=()=>showAdvanced($('settings-advanced').checked);
showAdvanced(stored('settings-advanced')==='1');

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
  if(!initialRouteHandled){initialRouteHandled=true;await perform(applyRoute);}
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
 if(!$('recording-bar').hidden){$('bar-timer').textContent=$('timer').textContent;$('bar-meter').value=values.level||0;}
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
$('open-tasks').onclick=()=>perform(async()=>{if(!(await leaveEdits()))return;dirtyTranscript=dirtyNotes=false;selected=null;show('tasks');lastTasks='';await loadTasks();showWorkTab(workTab);renderLibrary();});
$('open-analytics').onclick=()=>perform(async()=>{if(!(await leaveEdits()))return;dirtyTranscript=dirtyNotes=false;selected=null;show('analytics');await loadAnalytics();renderLibrary();});
$('analytics-apply').onclick=()=>perform(loadAnalytics);
$('analytics-reset').onclick=()=>perform(async()=>{for(const id of ['analytics-from','analytics-to','analytics-speaker','analytics-topic'])$(id).value='';await loadAnalytics();});
$('work-project').onchange=()=>renderTasks();
$('task-owner').onchange=renderTasks;
// Transcript rows grow with their text instead of showing an inner scroll bar.
document.addEventListener('input',event=>{const area=event.target;if(area.matches?.('.segment textarea')){area.style.height='auto';area.style.height=area.scrollHeight+2+'px';}});
$('new-meeting').onclick=async()=>{if(!(await leaveEdits()))return;dirtyTranscript=dirtyNotes=false;selected=null;show(state?.active?'recording':'setup');if(state?.active)selected=state.active.id;else renderTranscriptionTiming(true);renderLibrary();};
let searchTimer; $('search').oninput=()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>perform(async()=>{const q=$('search').value.trim();if(q){window.searchResults=await api('/api/search?q='+encodeURIComponent(q));}else window.searchResults=null;lastLibrary='';renderLibrary();}),200);};
$('record-form').addEventListener('change',()=>{renderReadiness();renderRecordMore();});
{const mode=document.querySelector(`input[name=mode][value="${stored('record-mode')}"]`);if(mode)mode.checked=true;}
for(const radio of document.querySelectorAll('input[name=mode]'))radio.onchange=()=>{$('mode-help').textContent=radio.value==='online'?'Captures audio from all Mac apps plus your microphone. Use headphones to avoid echo. macOS requires Screen & System Audio Recording permission.':'Place your iPhone near the centre of the table, or use your Mac microphone.';};
// A remembered meeting type shows its own help text.
document.querySelector('input[name=mode]:checked')?.onchange?.();
$('check-mic').onclick=()=>perform(async()=>{await api('/api/check-mic',{device:Number($('microphone').value),device_name:$('microphone').selectedOptions[0]?.textContent});toast('Microphone test started · 10 seconds');});
$('microphone').onchange=()=>renderState();
$('record-form').onsubmit=event=>{event.preventDefault();perform(async()=>{pending=true;$('start').disabled=true;store('record-mode',document.querySelector('input[name=mode]:checked').value);store('record-mic',$('microphone').selectedOptions[0]?.textContent||'');try{const m=await api('/api/start',{title:$('meeting-title').value,mode:document.querySelector('input[name=mode]:checked').value,device:Number($('microphone').value),device_name:$('microphone').selectedOptions[0]?.textContent,fallback_device_name:$('fallback-microphone').value,transcription_timing:$('transcription-timing').value,project_id:$('record-project').value||null,series_id:$('record-series').value||null,meeting_type:$('record-type').value||null});selected=m.id;state.active=m;renderState();show('recording');}finally{pending=false;}});};
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
$('pause').onclick=$('bar-pause').onclick=()=>perform(()=>api('/api/pause',{paused:state.active.status!=='paused'}));$('stop').onclick=()=>perform(()=>api('/api/stop',{}));
// The bar is always on screen, so its Stop asks first; the recording view's Stop is the deliberate one.
$('bar-stop').onclick=()=>perform(async()=>{if(await ask('Stop and save “'+(state.active?.title||'this recording')+'”?',{ok:'Stop & save',cancel:'Keep recording'}))await api('/api/stop',{});});
$('bar-open').onclick=()=>perform(async()=>{if(!state.active||!(await leaveEdits()))return;dirtyTranscript=dirtyNotes=false;selected=state.active.id;show('recording');renderState();});
for(const [id,action] of [['process','transcribe'],['summarize','summarize'],['recover','recover'],['correct','correct']])$(id).onclick=()=>perform(async()=>{if(!(await leaveEdits()))return;if(action==='summarize'&&state.settings.summarizer==='none'){openSettings('notes');toast('Choose a meeting-notes provider first');return;}await api('/api/meetings/'+selected+'/process',{action});dirtyNotes=dirtyTranscript=false;toast('Processing queued');await openMeeting(selected,true);});
$('edit-title').onclick=()=>perform(async()=>{const title=await ask('Meeting name',{value:detail.title,ok:'Rename'});if(title?.trim()){await api('/api/meetings/'+selected+'/edit',{title});await openMeeting(selected,true);}});
$('save-transcript').onclick=()=>perform(async()=>{if(dirtyNotes||itemEditing||speakerNaming){error('Save other edits before updating the transcript.');return;}detail=await api('/api/meetings/'+selected+'/edit',{transcript:detail.transcript,transcript_revision:detail.transcript_revision,refresh_notes:refreshNotesAfterEdit});dirtyTranscript=false;transcriptEditing=false;lastFingerprint=JSON.stringify(detail);renderDetail();toast(detail.notes_refresh_error?'Transcript saved. Notes update needs attention.':detail.status==='processing'?'Transcript saved · updating notes and tasks':'Transcript corrections saved');});
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
$('settings-save').onclick=event=>{const invalid=$('settings-form').querySelector('input:invalid,select:invalid,textarea:invalid');if(invalid){event.preventDefault();if(invalid.closest('.advanced-setting'))showAdvanced(true);showSettingsTab(invalid.closest('.settings-panel').dataset.tab);invalid.reportValidity();}};$('settings-close').onclick=()=>perform(closeSettings);
$('settings-dialog').addEventListener('cancel',event=>{event.preventDefault();perform(closeSettings);});$('provider').onchange=settingsFields;$('summarizer').onchange=()=>{$('llm-model').value=$('summarizer').value==='openai'?'gpt-4.1-mini':'gpt-4.1-mini';settingsFields();};$('transcript-correction').onchange=settingsFields;
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
 dirtyTranscript=dirtyNotes=false;detail=null;selected=null;
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


let workspaceData=null, workspaceSection='overview', workspaceSequence=0;
function projectAssignment(item){
 const box=el('details','project-assignment'), names=(item.effective_project_ids||[]).map(id=>projectList().find(p=>p.id===id)?.name).filter(Boolean);
 box.append(el('summary','',names.length?names.join(' · '):'Assign to project'));
 const hint=el('p','hint',Object.hasOwn(item,'project_ids')?'Manual assignment · preserved during sync':'Inherited from linked meetings');box.append(hint);
 const choices=[];
 for(const project of projectList()){
  const label=el('label','project-choice'),check=el('input');check.type='checkbox';check.checked=(item.effective_project_ids||[]).includes(project.id);label.append(check,document.createTextNode(project.name));box.append(label);choices.push([project.id,check]);
 }
 const save=el('button','secondary small-action','Save projects'),inherit=el('button','quiet','Use meeting projects');save.type=inherit.type='button';
 save.onclick=()=>perform(()=>graphAction('project',{id:item.id,revision:item.revision,project_ids:choices.filter(([,check])=>check.checked).map(([id])=>id)}));
 inherit.onclick=()=>perform(()=>graphAction('project',{id:item.id,revision:item.revision,project_ids:null}));box.append(save,inherit);return box;
}
// Saved links between work items build the project trace. A person makes each link; none is inferred.
const RELATION_LABELS={implements:['implements','is implemented by'],derives_from:['comes from','leads to'],supports:['supports','is supported by'],same_as:['is the same as','is the same as']};
function relationLinks(item){
 const box=el('div','relation-links'),data=workspaceData,names=id=>data?.items.find(i=>i.id===id)?.text;
 for(const edge of data?.timeline?.relationships||[]){
  if(edge.from_id!==item.id&&edge.to_id!==item.id)continue;
  const outgoing=edge.from_id===item.id,other=names(outgoing?edge.to_id:edge.from_id);
  if(other)box.append(el('p','relation-line',(RELATION_LABELS[edge.kind]?.[outgoing?0:1]||edge.kind)+' · '+other));
 }
 const others=(data?.items||[]).filter(i=>i.id!==item.id&&['task','decision','question'].includes(i.kind));
 if(!others.length)return box;
 const add=el('details','relation-add'),kind=el('select'),target=el('select'),save=el('button','secondary small-action','Save link');
 add.append(el('summary','','Link to another item'));
 kind.setAttribute('aria-label','Link type');target.setAttribute('aria-label','Linked item');save.type='button';
 kind.append(option('This item implements…','implements'),option('This item comes from…','derives_from'),option('This item supports…','supports'),option('This item is the same as…','same_as'));
 if(item.kind!=='task')kind.value='derives_from';
 target.append(...others.map(o=>option((o.kind==='task'?'Task':o.kind==='decision'?'Decision':'Question')+' · '+o.text.slice(0,90),o.id)));
 const preferred=others.find(o=>item.kind==='task'?o.kind==='decision':o.kind==='question');if(preferred)target.value=preferred.id;
 save.onclick=()=>perform(async()=>{const to=others.find(o=>o.id===target.value);await graphAction('relate',{from_id:item.id,to_id:to.id,kind:kind.value,from_revision:item.revision,to_revision:to.revision});toast('Link saved · it appears in the project trace');});
 add.append(kind,target,save);box.append(add);return box;
}
const TRACE_STAGES=[['conversation','Conversation'],['decision','Decision'],['task','Task'],['github','Issue / PR'],['code','Code change']];
const TRACE_SOURCE={meeting:'src-meeting',excerpt:'src-meeting',gmail:'src-gmail',google_chat:'src-chat',issue:'src-github',pull_request:'src-github',code:'src-github'};
function traceNode(node){
 const kinds={meeting:'Meeting',excerpt:'Excerpt',gmail:'Gmail',google_chat:'Chat',issue:'Issue',pull_request:'PR',code:'Code',decision:'Decision',task:'Task',question:'Question'};
 const url=node.ref.url,button=el(url?'a':'button','trace-node '+(TRACE_SOURCE[node.kind]||''));
 if(url){button.href=url;button.target='_blank';button.rel='noopener noreferrer';}else button.type='button';
 button.append(el('i'),el('b','',kinds[node.kind]||node.kind),el('span','trace-label',node.label));
 const meta=[node.status&&(STATUS_LABELS[node.status]||node.status),node.ref.timestamp,node.ref.state,node.date&&new Date(node.date).toLocaleDateString(undefined,{day:'numeric',month:'short'})].filter(Boolean);
 if(meta.length)button.append(el('small','',meta.join(' · ')));
 if(!url)button.onclick=()=>perform(async()=>{
  const ref=node.ref;
  if(ref.attachment_id)return openAttachment(ref.attachment_id);
  if(ref.meeting_id){await openMeeting(ref.meeting_id);if(ref.timestamp)showSeconds(ref.timestamp.split(':').reduce((n,v)=>n*60+Number(v),0));return;}
  if(ref.source_id){const source=(workspaceData.graph.sources||[]).find(s=>s.id===ref.source_id);if(source)return openSource(source);}
  if(ref.item_id){const item=workspaceData.items.find(i=>i.id===ref.item_id);show('tasks');lastTasks='';await loadTasks();showWorkTab(item?.kind==='question'?'questions':item?.kind||'task');}
 });
 return button;
}
function traceListen(node){
 const ref=node.ref;if(!ref.meeting_id)return '';
 const start=ref.start??(ref.timestamp?stampSeconds(ref.timestamp):0);
 return listenButton(ref.meeting_id,start,{label:'',until:ref.end??null,className:'chip-listen',title:ref.end!=null?'Play the excerpt':'Play from '+time(start)});
}
function traceStep(node){const step=el('div','trace-step');step.append(traceNode(node),traceListen(node));return step;}
function traceCard(chain){
 const card=el('article','trace-card'),grid=el('div','trace-grid');
 for(const [stage,title] of TRACE_STAGES){
  const column=el('div','trace-stage'+(chain.stages[stage].length?'':' empty'));column.append(el('h4','',title));
  for(const node of chain.stages[stage].slice(0,6))column.append(traceStep(node));
  if(chain.stages[stage].length>6)column.append(el('p','hint','+'+(chain.stages[stage].length-6)+' more'));
  if(!chain.stages[stage].length)column.append(el('p','trace-missing',stage==='task'&&chain.stages.decision.length?'Link a task to this decision':stage==='code'&&chain.stages.github.some(n=>n.kind==='pull_request')?'No repository report has this PR':'—'));
  grid.append(column);
 }
 card.append(grid);return card;
}
let timelineView='chains';
function renderTimeline(box,data){
 const timeline=data.timeline||{events:[],chains:[]},switcher=el('div','segmented');
 segmentedChoice(switcher,[['chains','Trace'],['events','Events']],timelineView,value=>{timelineView=value;renderWorkspace();});
 box.append(el('h2','','Project timeline'),switcher);
 if(timelineView==='chains'){
  box.append(el('p','hint','Each row follows saved links: the conversation where it started, the decision, the tasks that implement it, their GitHub issue or PR, and the merged code change. Use “Link to another item” on a decision or task to connect them. Nothing is guessed from similar text or dates.'));
  for(const chain of timeline.chains||[])box.append(traceCard(chain));
  if(!(timeline.chains||[]).length)box.append(el('p','empty-content','No decisions or tasks in this project yet.'));
  return;
 }
 box.append(el('p','hint','Dates belong to the recorded events. Work item text and status describe their current state.'));
 let day='';
 for(const event of timeline.events||[]){
  const when=new Date(event.at),label=when.toLocaleDateString(undefined,{weekday:'long',day:'numeric',month:'long',year:'numeric'});
  if(label!==day){day=label;box.append(el('h3','timeline-day',label));}
  const row=el('article','timeline-event'),kind=event.kind==='code'?'code':event.kind;
  row.append(el('span','timeline-time',when.toLocaleTimeString(undefined,{hour:'2-digit',minute:'2-digit'})),traceStep(eventNode(event,kind)));
  if(event.event)row.append(el('span','hint',TIMELINE_EVENTS[event.event]||event.event.replace(/_/g,' ')));
  box.append(row);
 }
 if(!(timeline.events||[]).length)box.append(el('p','empty-content','No events yet.'));
}
const TIMELINE_EVENTS={confirmed:'Owner confirmed',created:'Created',discussed:'Discussed',duplicate:'Mentioned again',changed:'Changed',removed:'Removed from a meeting',merged:'Merged',superseded:'Replaced',detached:'Waits for new notes',projects_changed:'Projects changed',source_linked:'Source linked',answered:'Answered',reopened:'Reopened'};
function eventNode(event,kind){
 const ref=event.url?{url:event.url,report_id:event.report_id}:event.attachment_id?{attachment_id:event.attachment_id,...(event.meeting_id?{meeting_id:event.meeting_id,start:event.start,end:event.end}:{})}:event.source_id?{source_id:event.source_id}:event.item_id?{item_id:event.item_id}:{meeting_id:event.meeting_id};
 return {kind,label:event.text,status:event.status,ref};
}
// The GitHub repositories of a project: drafts and links offer them first. One repository can serve several projects.
function repositoryEditor(project){
 const box=el('section','project-repos'),chips=el('div','item-meetings'),repos=[...(project.repositories||[])];
 box.append(el('h3','','GitHub repositories'),chips);
 const draw=()=>{chips.replaceChildren(...repos.map(name=>{const chip=el('span','source-chip src-github'),remove=el('button','quiet','✕');remove.type='button';remove.setAttribute('aria-label','Remove '+name);
  remove.onclick=()=>{repos.splice(repos.indexOf(name),1);draw();save.disabled=false;};chip.append(el('i'),el('b','',name),remove);return chip;}));if(!repos.length)chips.append(el('span','hint','No repository yet.'));};
 const row=el('div','work-actions'),input=el('input'),add=el('button','secondary','Add'),save=el('button','primary','Save repositories'),list=el('datalist');
 list.id='repo-choices-'+project.id;input.setAttribute('list',list.id);input.placeholder='owner/name';input.setAttribute('aria-label','Repository');add.type=save.type='button';save.disabled=true;
 add.onclick=()=>{const name=input.value.trim();if(name&&!repos.some(r=>r.toLowerCase()===name.toLowerCase())){repos.push(name);draw();save.disabled=false;}input.value='';};
 input.onkeydown=event=>{if(event.key==='Enter'){event.preventDefault();add.click();}};
 save.onclick=()=>perform(async()=>{await api('/api/projects/repositories',{id:project.id,repositories:repos});toast('Repositories saved');await loadWorkspace();});
 api('/api/github/repos').then(rows=>list.replaceChildren(...rows.map(r=>option(r.full_name,r.full_name)))).catch(()=>{});
 row.append(input,list,add,save);box.append(row);draw();return box;
}
async function loadWorkspace(){
 const sequence=++workspaceSequence,key=$('workspace-project').value;
 const fresh=await api('/api/projects/workspace?id='+encodeURIComponent(key));if(sequence!==workspaceSequence||view!=='projects')return;
 workspaceData=fresh;state.projects={...state.projects,projects:fresh.projects.filter(p=>p.id!=='__none__').map(({id,name})=>({id,name}))};
 fillProjects($('workspace-project'),fresh.project_id,'All projects',[option('Unassigned','__none__')]);renderWorkspace();syncRoute(true);
}
function renderWorkspace(){
 const data=workspaceData;if(!data)return;
 const cards=$('workspace-cards');cards.replaceChildren();
 for(const project of data.projects){const b=el('button','project-card'+(data.project_id===project.id?' selected':''));b.append(el('strong','',project.name),el('span','hint',project.meetings+' meetings · '+project.open_tasks+' open tasks · '+project.open_questions+' questions · '+(project.linked_conversations||0)+' linked conversations'));b.onclick=()=>perform(async()=>{$('workspace-project').value=project.id;await loadWorkspace();});cards.append(b);}
 for(const b of $('workspace-tabs').querySelectorAll('button')){b.classList.toggle('selected',b.dataset.section===workspaceSection);b.setAttribute('aria-selected',String(b.dataset.section===workspaceSection));}
 const box=$('workspace-content');box.replaceChildren();
 const today=state.task_summary?.today||new Date().toLocaleDateString('en-CA');
 const visible=data.items.filter(i=>!i.dismissed&&(!i.snoozed_until||i.snoozed_until<=today));
 const kinds={task:'Tasks',decision:'Decisions',question:'Questions'};
 function itemCard(item){
  const card=el('article','workspace-item');card.append(el('strong','',item.text),el('p','hint',item.kind+' · '+item.status+(item.owner?' · '+item.owner:'')),projectAssignment(item));
  if(item.answer)card.append(el('p','',item.answer));card.append(sourceChips(item,itemsData.meetings),githubActions({kind:'item',id:item.id}),relationLinks(item),evidenceBlock(item,itemsData.meetings));
  const open=el('button','quiet','Open in My Work');open.onclick=()=>perform(async()=>{show('tasks');lastTasks='';await loadTasks();$('work-project').value=data.project_id;renderTasks();showWorkTab(item.kind==='question'?'questions':item.kind);});card.append(open);return card;
 }
 if(workspaceSection==='overview'){
  box.append(el('h2','',data.projects.find(p=>p.id===data.project_id)?.name||'All projects'));
  box.append(el('p','hint','One work item can belong to several projects. Manual assignments take priority over linked meeting projects. Source states and saved quotes remain unchanged.'));
  const current=data.projects.find(p=>p.id===data.project_id);if(current&&current.id!=='__none__')box.append(repositoryEditor(current));
  for(const [kind,title] of Object.entries(kinds)){
   const rows=visible.filter(i=>i.kind===kind&&(kind==='task'?i.status==='open':kind==='question'?i.status==='open':i.status==='accepted'));
   box.append(el('h3','',title+' · '+rows.length));for(const item of rows.slice(0,5))box.append(itemCard(item));
  }
 }else if(workspaceSection==='meetings'){
  box.append(el('h2','','Meetings · '+data.meetings.length));
  for(const meeting of data.meetings){const row=el('article','workspace-item'),open=el('button','quiet',meeting.title);open.onclick=()=>perform(()=>openMeeting(meeting.id));row.append(open,el('p','hint',date(meeting.started_at||meeting.created)+' · '+(statusNames[meeting.status]||meeting.status)));
   const assign=el('select');assign.setAttribute('aria-label','Project for '+meeting.title);fillProjects(assign,meeting.project_id||'','No project');const save=el('button','secondary small-action','Move meeting');save.onclick=()=>perform(async()=>{await api('/api/meetings/'+meeting.id+'/scope',{project:assign.value?{id:assign.value}:null,series:assign.value===meeting.project_id&&meeting.series_id?{id:meeting.series_id}:null});state=await api('/api/state');lastTasks='';itemsData=await api('/api/items');renderState();await loadWorkspace();});row.append(assign,save);box.append(row);}
 }else if(workspaceSection==='conversations'){
  box.append(el('h2','','Project conversations'),el('p','hint','Whole meetings, pinned excerpts and locally cached external conversations. Source snapshots do not imply a task or commitment.'));
  for(const meeting of data.meetings){const open=el('button','quiet',meeting.title);open.onclick=()=>perform(()=>openMeeting(meeting.id));box.append(open);}
  for(const conversation of data.conversations||[])box.append(attachmentCard(conversation));
 }else if(workspaceSection==='timeline'){
  renderTimeline(box,data);
 }else if(workspaceSection==='sources'){
  const evs=new Set(data.items.flatMap(i=>i.source_evidence||[])),ids=new Set((data.graph.source_evidence||[]).filter(e=>evs.has(e.id)).map(e=>e.source_id));
  box.append(el('h2','','Sources linked through project work'),el('p','hint','Accept or link a proposal in My Work, then assign its item to a project. This view keeps the original source and its evidence.'));
  for(const source of data.graph.sources||[])if(ids.has(source.id)){const row=el('article','workspace-item');row.append(originChip(source.provider,sourceLabel(source),()=>openSource(source)),el('p','hint',source.available?'Available':'Saved evidence · source unavailable'));box.append(row);}
 }else {const rows=visible.filter(i=>i.kind===workspaceSection);box.append(el('h2','',kinds[workspaceSection]+' · '+rows.length));for(const item of rows)box.append(itemCard(item));}
 if(box.children.length<2)box.append(el('p','hint','Nothing assigned here yet.'));
}
$('open-projects').onclick=()=>perform(async()=>{if(!(await leaveEdits()))return;dirtyTranscript=dirtyNotes=false;selected=null;show('projects');itemsData=await api('/api/items');await loadWorkspace();});
$('workspace-project').onchange=()=>perform(loadWorkspace);
$('workspace-refresh').onclick=()=>perform(async()=>{itemsData=await api('/api/items');await loadWorkspace();});
$('workspace-new').onclick=()=>perform(async()=>{const name=await ask('New project name',{ok:'Create project',value:''});if(name===null)return;const created=await api('/api/projects/create',{name});state.projects=created.projects;lastProjects='';syncProjects();fillProjects($('workspace-project'),created.id,'All projects',[option('Unassigned','__none__')]);await loadWorkspace();});
for(const b of $('workspace-tabs').querySelectorAll('button'))b.onclick=()=>{workspaceSection=b.dataset.section;renderWorkspace();syncRoute(true);};

const CONVERSATION_LABELS={meeting:'Meeting',excerpt:'Transcript excerpt',gmail:'Gmail',google_chat:'Google Chat',attached:'Saved snapshot'};
let conversationPage=null,conversationOffset=0,conversationSequence=0;
const selectedConversations=new Map();
function syncConversationFilters(){
 fillProjects($('conversation-project'),$('conversation-project').value,'All projects',[option('Unassigned','__none__')]);
 fillSeries($('conversation-series'),$('conversation-project').value,$('conversation-series').value,'All series');
 fillProjects($('conversation-bulk-project'),$('conversation-bulk-project').value,'No project');
 fillSeries($('conversation-bulk-series'),$('conversation-bulk-project').value,$('conversation-bulk-series').value,'Keep series when project stays the same');
}
async function openConversations(){
 if(!(await leaveEdits()))return;dirtyTranscript=dirtyNotes=false;selected=null;show('conversations');syncConversationFilters();await loadConversations();renderLibrary();
}
async function loadConversations(){
 const sequence=++conversationSequence,query=new URLSearchParams({q:$('conversation-query').value,source:$('conversation-source').value,project:$('conversation-project').value,series:$('conversation-series').value,participant:$('conversation-participant').value,from:$('conversation-from').value,to:$('conversation-to').value,offset:String(conversationOffset)});
 const result=await api('/api/conversations?'+query);if(sequence!==conversationSequence||view!=='conversations')return;
 conversationPage=result;const select=$('conversation-participant'),old=select.value,names=result.participants;
 select.replaceChildren(option('All participants',''),...names.map(name=>option(name,name)),...(old&&!names.includes(old)?[option(old,old)]:[]));select.value=old;
 $('conversation-notices').textContent=result.notices.join(' ')+(result.rows.some(row=>['gmail','google_chat'].includes(row.provider))?' External conversations show the locally cached messages only. Attachments and full remote history are not fetched.':'');
 renderConversations();
}
function conversationProjectChoices(ids=[]){
 const box=el('div','conversation-project-choices'),choices=[];
 for(const p of projectList()){const label=el('label','project-choice'),check=el('input');check.type='checkbox';check.checked=ids.includes(p.id);label.append(check,document.createTextNode(p.name));box.append(label);choices.push([p.id,check]);}
 return {box,value:()=>choices.filter(([,check])=>check.checked).map(([id])=>id)};
}
function attachmentCard(row){
 const card=el('article','workspace-item'),open=el('button','quiet',row.title);open.onclick=()=>perform(()=>openAttachment(row.id));card.append(open,el('p','hint',(CONVERSATION_LABELS[row.kind]||row.kind)+' · '+new Date(row.date).toLocaleString()+(row.partial?' · cached conversation snapshot':'')));return card;
}
function renderConversations(){
 if(!conversationPage)return;const result=conversationPage,list=$('conversation-list');list.replaceChildren();
 $('conversation-select-page').disabled=!result.rows.some(row=>row.provider==='meeting');
 $('conversation-count').textContent=result.total+' conversations · '+(result.total?result.offset+1:0)+'–'+Math.min(result.offset+result.rows.length,result.total);
 $('conversation-selection').textContent=selectedConversations.size+' meetings selected';$('conversation-move').disabled=!selectedConversations.size;$('conversation-move').closest('.conversation-bulk').hidden=!selectedConversations.size;
 $('conversation-prev').disabled=!result.offset;$('conversation-next').disabled=result.offset+result.rows.length>=result.total;
 for(const row of result.rows){
  const card=el('article','conversation-card'),main=el('div','conversation-main'),open=el('button','quiet conversation-title',row.title);open.type='button';
  open.onclick=()=>perform(async()=>{if(row.provider==='meeting')return openMeeting(row.external_id);if(row.provider==='attached')return openAttachment(row.external_id);show('tasks');lastTasks='';await loadTasks();if(row.provider==='gmail'){showWorkTab('gmail');await openMail(row.external_id);}else{chatSpace=row.external_id;showWorkTab('chat');}});
  main.append(open,el('p','hint',(CONVERSATION_LABELS[row.provider]||row.provider)+' · '+new Date(row.date).toLocaleString()+(row.status?' · '+(statusNames[row.status]||row.status):'')),el('p','hint',(row.participants||[]).join(', ')));
  const names=(row.project_ids||[]).map(id=>projectList().find(p=>p.id===id)?.name).filter(Boolean);main.append(el('p','hint',names.length?names.join(' · '):'Unassigned'));
  if(row.excerpt_projects?.length)main.append(el('p','hint','Contains project excerpts: '+row.excerpt_projects.map(id=>projectList().find(p=>p.id===id)?.name).filter(Boolean).join(', ')));
  if(row.provider==='meeting'){
   const check=el('input');check.type='checkbox';check.checked=selectedConversations.has(row.external_id);check.setAttribute('aria-label','Select '+row.title);
   check.onchange=()=>{if(check.checked){if(selectedConversations.size>=200){check.checked=false;toast('Select up to 200 meetings');return;}selectedConversations.set(row.external_id,{id:row.external_id,revision:row.scope_revision});}else selectedConversations.delete(row.external_id);$('conversation-selection').textContent=selectedConversations.size+' meetings selected';$('conversation-move').disabled=!selectedConversations.size;$('conversation-move').closest('.conversation-bulk').hidden=!selectedConversations.size;};card.append(check);
  }else if(row.provider!=='attached'){
   const details=el('details','project-assignment'),choices=conversationProjectChoices(row.project_ids),save=el('button','secondary small-action','Attach conversation');details.append(el('summary','','Attach to projects'),choices.box);save.type='button';save.onclick=()=>perform(async()=>{const saved=await api('/api/conversations/attach',{provider:row.provider,external_id:row.external_id,account:row.account,revision:row.revision,attachment_revision:row.attachment_revision,project_ids:choices.value()});await loadConversations();await openAttachment(saved.id);});details.append(save);main.append(details);
  }
  card.append(main);list.append(card);
 }
 if(!result.rows.length)list.append(el('p','empty-content','No conversations match these filters.'));
}
// A whole email thread or Chat conversation can join a project before any task exists.
async function attachExternal(provider,id){
 const row=await api('/api/conversations/external?provider='+provider+'&id='+encodeURIComponent(id)),box=$('conversation-reader-body');
 const choices=conversationProjectChoices(row.project_ids),save=el('button','primary','Save project links');
 box.replaceChildren(el('h2','',row.title),el('p','hint',(CONVERSATION_LABELS[provider]||provider)+' · '+row.participants.join(', ')),
  el('p','hint','Atlanta saves a snapshot of the cached '+(provider==='gmail'?'messages of this thread':'messages of this conversation')+' with the project. No task is created and no AI request is sent. A later sync does not change the snapshot; attach again to save the new version.'),choices.box,save);
 if(!projectList().length)box.append(el('p','notice','Create a project in Projects first.'));
 save.onclick=()=>perform(async()=>{const ids=choices.value();if(!ids.length){toast('Choose at least one project');return;}const saved=await api('/api/conversations/attach',{provider,external_id:row.external_id,account:row.account,revision:row.revision,attachment_revision:row.attachment_revision,project_ids:ids});toast('Attached to '+ids.length+(ids.length===1?' project':' projects'));await openAttachment(saved.id);});
 if(!$('conversation-reader').open)$('conversation-reader').showModal();
}
async function openAttachment(id){
 const row=await api('/api/conversations/attachment?id='+encodeURIComponent(id)),box=$('conversation-reader-body');box.replaceChildren(el('h2','',row.title),el('p','hint',(CONVERSATION_LABELS[row.kind]||row.kind)+' · saved '+new Date(row.created).toLocaleString()));
 if(row.kind!=='excerpt')box.append(el('p','hint','Saved local snapshot. It does not update automatically and current remote state is not checked.'));
 if(row.partial)box.append(el('p','notice','This is a snapshot of cached text, not the full remote conversation.'));
 if(row.stale)box.append(el('p','notice','The original transcript or source revision has changed or is unavailable. This saved quotation is preserved.'));
 box.append(el('pre','conversation-snapshot',row.text));const choices=conversationProjectChoices(row.project_ids),save=el('button','secondary','Save project links');box.append(choices.box,save);
 save.onclick=()=>perform(async()=>{await api('/api/conversations/projects',{id:row.id,revision:row.revision,project_ids:choices.value()});if(view==='conversations')await loadConversations();if(view==='projects')await loadWorkspace();await openAttachment(row.id);});
 if(row.kind==='excerpt'){const jump=el('button','quiet','Open original meeting at '+time(row.locator.start));jump.onclick=()=>perform(async()=>{$('conversation-reader').close();await openMeeting(row.locator.meeting_id);showSeconds(row.locator.start);if(row.stale)toast('Saved excerpt differs from the current transcript');});box.append(jump,listenButton(row.locator.meeting_id,row.locator.start,{label:'Listen to the excerpt',until:row.locator.end,className:'secondary'}));
  box.append(githubActions({kind:'attachment',id:row.id},await api('/api/github/links?kind=attachment&id='+encodeURIComponent(row.id))));}
 if(!$('conversation-reader').open)$('conversation-reader').showModal();
}
$('conversation-reader-close').onclick=()=>$('conversation-reader').close();
// A moment that plays from the reader stops with it.
$('conversation-reader').addEventListener('close',()=>{if(moment.player===moment.audio)stopMoment();});
$('open-conversations').onclick=()=>{const last=stored('library-view');if(last==='find')$('open-find').click();else if(last==='analytics')$('open-analytics').click();else perform(openConversations);};
for(const b of $('library-tabs').querySelectorAll('button'))b.onclick=()=>b.dataset.library==='conversations'?perform(openConversations):$('open-'+b.dataset.library).click();
// Prepare me belongs to a project: it opens for the project on screen.
$('workspace-prepare').onclick=()=>perform(()=>openPrepare(['','__none__'].includes($('workspace-project').value)?'':$('workspace-project').value,''));
$('conversation-filters').onsubmit=event=>{event.preventDefault();conversationOffset=0;selectedConversations.clear();perform(loadConversations);};
$('conversation-project').onchange=()=>fillSeries($('conversation-series'),$('conversation-project').value,'','All series');
$('conversation-bulk-project').onchange=()=>fillSeries($('conversation-bulk-series'),$('conversation-bulk-project').value,'','Keep series when project stays the same');
$('conversation-reset').onclick=()=>{for(const id of ['conversation-query','conversation-project','conversation-series','conversation-participant','conversation-from','conversation-to'])$(id).value='';$('conversation-source').value='meeting';syncConversationFilters();conversationOffset=0;selectedConversations.clear();perform(loadConversations);};
$('conversation-select-page').onclick=()=>{for(const row of conversationPage?.rows||[])if(row.provider==='meeting'&&selectedConversations.size<200)selectedConversations.set(row.external_id,{id:row.external_id,revision:row.scope_revision});renderConversations();};
$('conversation-clear').onclick=()=>{selectedConversations.clear();renderConversations();};
$('conversation-prev').onclick=()=>{conversationOffset=Math.max(0,conversationOffset-50);perform(loadConversations);};
$('conversation-next').onclick=()=>{conversationOffset+=50;perform(loadConversations);};
$('conversation-move').onclick=()=>perform(async()=>{if(!selectedConversations.size)return;const project=$('conversation-bulk-project').value;if(!(await ask('Move '+selectedConversations.size+' meetings to '+(projectList().find(p=>p.id===project)?.name||'No project')+'? Manual work item assignments stay unchanged.',{ok:'Move meetings'})))return;await api('/api/conversations/bulk',{meetings:[...selectedConversations.values()],project_id:project||null,series_id:$('conversation-bulk-series').value||null});selectedConversations.clear();state=await api('/api/state');lastLibrary='';renderState();syncConversationFilters();await loadConversations();});
function openExcerpt(){
 if(hasEdits()){error('Save transcript corrections before selecting an excerpt.');return;}
 if(!detail?.transcript?.length){error('Finish transcription before selecting an excerpt.');return;}
 const turns=transcriptTurns(detail.transcript),first=$('excerpt-first'),last=$('excerpt-last');first.replaceChildren();last.replaceChildren();
 for(const turn of turns){const start=turn.segments[0],end=turn.segments.at(-1),label=time(start.segment.start)+' · '+(turn.speaker||'Speaker')+' · '+turn.segments.map(s=>s.segment.text).join(' ').slice(0,90);first.append(option(label,String(start.index)));last.append(option(label,String(end.index)));}
 last.value=String(turns[0].segments.at(-1).index);$('excerpt-from').value=time(detail.transcript[0].start);$('excerpt-to').value=time(Math.ceil(detail.transcript.at(-1).end));fillProjects($('excerpt-project'),detail.project_id||'','Choose a project');$('excerpt-error').hidden=true;$('excerpt-dialog').showModal();
}
$('save-excerpt').onclick=openExcerpt;
$('excerpt-first').onchange=()=>{if(Number($('excerpt-last').value)<Number($('excerpt-first').value)){const first=Number($('excerpt-first').value),turn=transcriptTurns(detail.transcript).find(t=>t.segments[0].index===first);$('excerpt-last').value=String(turn.segments.at(-1).index);}};
$('excerpt-mode').onchange=()=>{$('excerpt-times').hidden=$('excerpt-mode').value!=='range';$('excerpt-turns').hidden=$('excerpt-mode').value==='range';};
$('excerpt-cancel').onclick=()=>$('excerpt-dialog').close();
$('excerpt-form').onsubmit=async event=>{event.preventDefault();$('excerpt-error').hidden=true;const button=event.submitter;button.disabled=true;try{const body={provider:'excerpt',meeting_id:detail.id,transcript_revision:detail.transcript_revision,first:Number($('excerpt-first').value),last:Number($('excerpt-last').value),project_ids:[$('excerpt-project').value]};if($('excerpt-mode').value==='range'){const seconds=value=>{if(!/^\d{2,}:\d{2}:\d{2}$/.test(value)||value.split(':').slice(1).some(n=>Number(n)>59))throw new Error('Use HH:MM:SS for the time range');return value.split(':').reduce((n,v)=>n*60+Number(v),0);};body.range=[seconds($('excerpt-from').value),seconds($('excerpt-to').value)];}const saved=await api('/api/conversations/attach',body);$('excerpt-dialog').close();await openAttachment(saved.id);}catch(exc){$('excerpt-error').textContent=exc.message;$('excerpt-error').hidden=false;}finally{button.disabled=false;}};

$('prepare-type').onchange=()=>{prepareScope.type=$('prepare-type').value;perform(loadPrepare);};
function githubVerificationLabel(link){
 const checked=link.checked_at?' · last live check '+new Date(link.checked_at).toLocaleString():'';
 if(link.verification==='github')return 'Checked in GitHub'+checked;
 if(link.verification==='cached'){const cached=link.cached_at?(typeof link.cached_at==='number'?new Date(link.cached_at*1000):new Date(link.cached_at)).toLocaleString():'';return 'Found in local cache'+(cached?' · cached '+cached:'')+checked;}
 if(link.verification==='offline')return 'Not checked · offline or unavailable'+checked;
 return 'Verification source unknown · check again';
}
$('github-draft-review').onclick=()=>{
 captureDraft();const buffer=draftBuffers.get(draftActiveKey);if(!buffer)return;
 $('draft-review-current').textContent=buffer.values.title+'\n\n'+buffer.values.body;
 $('draft-review-generated').textContent=buffer.generated.title+'\n\n'+buffer.generated.body;
 $('draft-review-dialog').showModal();
};
$('draft-review-cancel').onclick=()=>$('draft-review-dialog').close();
$('draft-review-apply').onclick=()=>{const buffer=draftBuffers.get(draftActiveKey);if(!buffer)return;const next=buffer.reset();$('github-draft-issue-title').value=next.title;$('github-draft-body').value=next.body;draftEditNotice();updateDraftLink();$('draft-review-dialog').close();};
let channelContext=null;
function senderIdentityButton(identity,label){
 const b=el('button','quiet sender-person',identity.person_name?'✓ '+identity.person_name:'Link sender to person…');b.type='button';b.disabled=!identity.available;
 b.onclick=event=>{event.stopPropagation();perform(async()=>{if(identity.person_id)return openPerson(identity.person_id);channelContext=identity;$('channel-person-context').textContent=(identity.provider==='gmail'?'Gmail':'Google Chat')+' · '+label+' · '+identity.account;
 $('channel-person-select').replaceChildren(option('Choose a person',''),...(state.people||[]).map(p=>option(p.name,p.id)));$('channel-person-error').hidden=true;$('channel-person-dialog').showModal();});};return b;
}
$('channel-person-cancel').onclick=()=>$('channel-person-dialog').close();
$('channel-person-new').onclick=()=>perform(async()=>{$('channel-person-dialog').close();await openPerson(null);});
$('channel-person-confirm').onclick=async()=>{
 const person=(state.people||[]).find(p=>p.id===$('channel-person-select').value);if(!person){$('channel-person-error').textContent='Choose a person first.';$('channel-person-error').hidden=false;return;}
 const context=channelContext;$('channel-person-confirm').disabled=true;
 try{const result=await api('/api/people/channel',{...context,person_id:person.id,revision:person.revision});state.people=result.people;renderPeople();if(context!==channelContext)return;$('channel-person-dialog').close();if(context.provider==='gmail')await openMail(context.thread_id);else await loadChat();toast('Sender identity confirmed');}
 catch(e){$('channel-person-error').textContent=e.message;$('channel-person-error').hidden=false;}
 finally{$('channel-person-confirm').disabled=false;}
};
function renderPersonIdentities(person){
 const box=$('person-identities');box.replaceChildren();if(!person)return;
 for(const identity of person.identities||[]){const row=el('div','identity-row'),remove=el('button','quiet','Remove identity');remove.type='button';row.append(el('span','hint',(identity.provider==='gmail'?'Gmail':'Google Chat')+' · '+identity.external_id+' · '+identity.account));
  remove.onclick=()=>perform(async()=>{const text=identity.provider==='gmail'?'Remove this confirmed email and its channel links from '+person.name+'?':'Remove this confirmed Chat identity from '+person.name+'?';if(!(await ask(text,{ok:'Remove identity'})))return;const result=await api('/api/people/channel/remove',{person_id:person.id,revision:person.revision,identity});state.people=result.people;renderPeople();await openPerson(person.id);});row.append(remove);box.append(row);
 }
}
function renderChannelProfile(profile){
 const channels=profile.channels;if(!channels)return;const box=$('person-profile');box.append(el('p','hint',channels.coverage));
 for(const [key,label] of [['email','Email messages'],['chat','Chat messages']]){const section=el('section','profile-section');section.append(el('h4','',label+' · '+channels[key].length));for(const message of channels[key]){const row=el('div','profile-said'),open=el('button','quiet','Open cached source');row.append(el('p','',message.text),el('small','hint',message.title+' · '+message.account+' · '+new Date(message.date*1000).toLocaleString()));open.type='button';open.onclick=()=>perform(async()=>{const status=await api(message.provider==='gmail'?'/api/gmail':'/api/chat');if((message.provider==='gmail'?status.account:status.account_id)!==message.account)throw new Error('Connect '+message.account+' to open its source. The cached quotation is shown here.');$('person-dialog').close();show('tasks');lastTasks='';await loadTasks();if(message.provider==='gmail'){showWorkTab('gmail');await openMail(message.thread_id);}else{chatSpace=message.space;chatMessage=message.name;showWorkTab('chat');}});row.append(open);section.append(row);}box.append(section);}
}
