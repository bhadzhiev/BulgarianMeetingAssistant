'use strict';
const $ = id => document.getElementById(id);
const readers=AtlantaUX.requests(),editorDirty=AtlantaUX.dirtyRegistry();
let meetingLoadSequence=0,detailChangedWhileEditing=false;
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
// Reusable components: a button is always type="button"; actionBtn wires it into perform; emptyNote is the standard empty-state line.
function btn(className, label, onclick, title) { const b = el('button', className, label); b.type='button'; if(title) b.title=title; if(onclick) b.onclick=onclick; return b; }
function actionBtn(className, label, fn, title) { return btn(className, label, () => perform(fn), title); }
function openMeetingBtn(title, id, className='quiet') { return btn(className, title, () => perform(() => openMeeting(id)), 'Open the meeting'); }
function emptyNote(text) { return el('p', 'hint empty-note', text); }
// Inline SVG icons on a 24px grid in the nav-icon style: 2px stroke, currentColor, no fill.
const ICON_PATHS={close:'M6 6l12 12M18 6L6 18',calendar:'M4 6h16v14H4zM4 10h16M8 3v5M16 3v5',mail:'M4 6h16v12H4zM4 7l8 6 8-6',prev:'M15 5l-7 7 7 7',next:'M9 5l7 7-7 7',jump:'M5 12h14m0 0-5-5m5 5-5 5',external:'M7 17 17 7M9 7h8v8',download:'M12 4v11m0 0-4-4m4 4 4-4M5 20h14',restore:'M4 10h9a5 5 0 0 1 0 10h-3M4 10l4-4M4 10l4 4',edit:'M4 20l1-4L16.5 4.5a2.1 2.1 0 0 1 3 3L8 19l-4 1z',gear:'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M19.1 4.9 17 7M7 17l-2.1 2.1',sparkle:'M12 3l2 6 6 2-6 2-2 6-2-6-6-2 6-2z',star:'M12 4l2.4 4.9 5.4.8-3.9 3.8.9 5.4-4.8-2.5-4.8 2.5.9-5.4L4.2 9.7l5.4-.8z',check:'M5 13l4 4 10-10',mic:'M12 3a3 3 0 0 1 3 3v5a3 3 0 0 1-6 0V6a3 3 0 0 1 3-3zM5 11a7 7 0 0 0 14 0M12 18v3',screen:'M4 5h16a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1zM9 20h6M12 16v4'};
function icon(name){const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('aria-hidden','true');svg.classList.add('icon');const path=document.createElementNS('http://www.w3.org/2000/svg','path');path.setAttribute('d',ICON_PATHS[name]||ICON_PATHS.sparkle);svg.append(path);return svg;}
function option(text, value) { const node = el('option', '', text); node.value = value; return node; }
// People for an owner choice: my team first, then the others. Each group is in alphabetical order.
function inTeam(person,day=AtlantaUX.iso(new Date())){return (person.team||[]).some(p=>p.start<=day&&(!p.end||day<p.end));}
function peopleByTeam(people=state.people||[]){const byName=(a,b)=>a.name.localeCompare(b.name,'bg',{sensitivity:'base'});
 return {team:people.filter(p=>inTeam(p)).sort(byName),others:people.filter(p=>!inTeam(p)).sort(byName)};}
function personOptions(people){const {team,others}=peopleByTeam(people);if(!team.length)return others.map(p=>option(p.name,p.id));
 const group=(label,rows)=>{const node=el('optgroup');node.label=label;node.append(...rows.map(p=>option(p.name,p.id)));return node;};
 return [group('My team',team),...(others.length?[group('Others',others)]:[])];}
// Imported titles often contain the date already; do not show it two times.
function withDate(title, value) { const day = date(value); return title.includes(day) ? title : title + ' · ' + day; }
function time(seconds) { seconds=Math.max(0,Math.floor(seconds||0)); return [Math.floor(seconds/3600),Math.floor(seconds/60)%60,seconds%60].map(x=>String(x).padStart(2,'0')).join(':'); }
function date(value) { return AtlantaUX.date(value); }
function dateTime(value){return AtlantaUX.dateTime(value);}
function showError(target,message){
 const previous=document.activeElement,close=btn('dismiss-error','×',null,'Dismiss error');close.setAttribute('aria-label','Dismiss error');
 close.onclick=()=>{target.hidden=true;if(previous?.isConnected&&!previous.disabled)previous.focus();};
 target.classList.add('dismissible-error');target.replaceChildren(el('span','error-message',message),close);target.hidden=false;
}
function error(message) {const dialog=[...document.querySelectorAll('dialog[open]')].at(-1);let target=dialog?.querySelector('[role=alert],.dialog-error');if(dialog&&!target){target=el('p','notice dialog-error');target.setAttribute('role','alert');dialog.prepend(target);}target=target||$('error');showError(target,message);target.scrollIntoView({block:'nearest'});}
function clearError() {for(const node of [$('error'),...document.querySelectorAll('dialog [role=alert],dialog .dialog-error')])node.hidden=true;}
let toastTimer=null;
function toast(message) { clearTimeout(toastTimer); $('toast').textContent=message; $('toast').hidden=false; toastTimer=setTimeout(()=>$('toast').hidden=true,3000); }
// A change that finishes or hides an item is saved at once; Undo stays available for a few seconds.
function undoToast(message,undo){
 const box=$('toast'),button=btn('','Undo');clearTimeout(toastTimer);
 box.replaceChildren(document.createTextNode(message+' · '),button);box.hidden=false;
 button.onclick=()=>{clearTimeout(toastTimer);box.hidden=true;undo();};toastTimer=setTimeout(()=>box.hidden=true,8000);
}
function participantLabel(name){if(!name)return 'Unidentified participant';const match=/^SPEAKER[ _-]?(\d+)$/i.exec(name);return match?'Participant '+(Number(match[1])+1):knownSpeaker(name)||name;}
function knownSpeaker(name) { const person=personFor(name);if(person)return person.name;if(Array.isArray(state?.people))return null;const key=(name||'').trim().toLocaleLowerCase();if(/^speaker[ _-]?\d+$/i.test(key))return null; return key?(state?.speakers||[]).find(n=>n.toLocaleLowerCase()===key):undefined; }
function speakerTone(name) { let hash=0; for(const c of name.toLocaleLowerCase()) hash=(hash*31+c.codePointAt(0))>>>0; return 'tone-'+(hash%8); }
function initials(name) { return name.split(/\s+/).filter(Boolean).slice(0,2).map(word=>[...word][0].toLocaleUpperCase()).join(''); }
function speakerBadge(target,name) {
 const known=knownSpeaker(name); name=(name||'').trim();if(/^SPEAKER[ _-]?\d+$/i.test(name))name='';
 target.className='speaker-badge'+(known?' '+speakerTone(known):name?' new':' empty');
 target.textContent=known?initials(known):name?'NEW':'?';
 target.title=known?'Person · '+known:name?'Participant · added to People when you save a name':'Unidentified participant';
 return target;
}
function syncSpeakers() {
 const signature=JSON.stringify([state.speakers||[],state.people||[]]); if(signature===lastSpeakers) return; lastSpeakers=signature;
 {const {team,others}=peopleByTeam(),names=[...team,...others].map(p=>p.name),known=new Set(names.map(n=>n.toLowerCase()));
 $('known-speakers').replaceChildren(...[...names,...(state.speakers||[]).filter(n=>!known.has(String(n).toLowerCase()))].map(name=>{const option=document.createElement('option');option.value=name;return option;}));}
 if($('settings-dialog').open){ renderSpeakerSettings(); renderPeople(); }
 // Re-annotate the open meeting unless that would discard typing.
 if(view==='detail'&&detail&&!hasEdits()) renderDetail();
}
function renderSpeakerLegend() {
 const target=$('speaker-legend'), counts=new Map(); target.replaceChildren();
 for(const s of detail.transcript) { if(!s.speaker) continue; const name=knownSpeaker(s.speaker)||s.speaker.trim(); counts.set(name,(counts.get(name)||0)+1); }
 target.hidden=!counts.size;
 for(const [name,count] of counts) { const chip=el('span','speaker-chip'); chip.append(speakerBadge(el('span'),name),el('span','',participantLabel(name)+' · '+count)); target.append(chip); }
}
// After the meeting: one list of what still needs a person, each with the step that resolves it.
function renderAttention(busy){
 const d=detail,box=$('attention');box.replaceChildren();
 if(busy||!d.transcript.length&&!d.error){box.hidden=true;return;}
 const items=[],minutes=d.minutes||{};
 const add=(tone,text,label,run)=>{const row=el('div','attention-item '+tone),go=btn('secondary small-action',label);go.onclick=()=>perform(run);row.append(el('i'),el('span','',text),go);items.push(row);};
 const toOutcomes=()=>{switchTab('outcomes');$('outcomes-panel').scrollIntoView({block:'start'});};
 if(d.error)add('bad','Processing stopped: '+d.error,'Show details',async()=>$('detail-error').scrollIntoView({block:'center'}));
 const generic=[...new Set(d.transcript.map(s=>s.speaker).filter(name=>name&&/^SPEAKER[ _-]?\d+$/i.test(name)))];
 const voiced=generic.filter(name=>d.voice_suggestions?.[name]).length;
 if(generic.length)add('warn','Name '+generic.length+(generic.length===1?' speaker':' speakers')+' so tasks and talk time use real names'+(voiced?' · '+voiced+' voice '+(voiced===1?'suggestion':'suggestions'):''),'Name speakers',async()=>{switchTab('transcript');$('speaker-review-container').open=true;$('speaker-review').scrollIntoView({block:'center'});});
 if(d.minutes_proposal?.changes?.length)add('warn','New AI notes are ready · '+d.minutes_proposal.changes.length+' changes to review','Review changes',async()=>openReview());
 else if(d.notes_need_refresh||d.notes_refresh_error)add('warn',d.notes_refresh_error||'The transcript changed after the notes were made','Review update',async()=>{switchTab('transcript');$('primary-action').scrollIntoView({block:'center'});});
 if(d.task_matching?.status==='needs_permission'&&state.settings?.meeting_task_ai)add('warn',d.task_matching.reason||'Task matching needs your permission for the notes API','Allow and match now',async()=>{
  const host=apiHost(state.settings.local_ai_base_url);
  const approved=await ask('Allow task context for '+host+' and match the notes of this meeting now? Titles, owners, states, due dates, expected results and up to 2 updates of at most 30 similar existing tasks are sent to this API. Proposed and hidden tasks, email and chat text are never sent.',{ok:'Allow and match',cancel:'Cancel'});
  if(approved===null)return;
  await api('/api/task-matching/allow',{id:d.id});toast('Permission saved for '+host+' · matching runs in the background');});
 const links=(state.settings?.meeting_task_ai?['tasks','decisions']:['decisions']).reduce((n,field)=>n+(minutes[field]||[]).filter(m=>m.link&&!m.item_id).length,0);
 if(links)add('warn',links+(links===1?' mention looks':' mentions look')+' like existing work · link or keep as new','Check links',async()=>toOutcomes());
 // The same state as the decision badges, so the count and the list agree.
 const decisionStates=AtlantaTasks.meetingGroups(minutes.decisions||[]).map(group=>group.task).filter(m=>!m.link).map(m=>{const item=d.items?.[m.item_id];return item?decisionState(item).cls:m.review==='verified'?'accepted':'proposed';});
 const proposedDecisions=decisionStates.filter(s=>s==='proposed').length,recheckDecisions=decisionStates.filter(s=>s==='recheck').length;
 if((proposedDecisions||recheckDecisions)&&state.settings?.meeting_task_ai)add('warn',[proposedDecisions&&'Accept '+AtlantaUX.count(proposedDecisions,'decision')+' that the AI proposed',recheckDecisions&&'Check '+AtlantaUX.count(recheckDecisions,'accepted decision')+' again after a change'].filter(Boolean).join(' · '),'Review decisions',async()=>toOutcomes());
 const tasks=AtlantaTasks.meetingGroups(minutes.tasks||[]).map(group=>group.task).filter(t=>!d.items?.[t.item_id]?.dismissed&&t.status!=='done'&&!t.link&&(!t.owner||!t.due_date)).length;
 if(tasks&&state.settings?.meeting_task_ai)add('info','Give an owner and a due date to '+tasks+(tasks===1?' task':' tasks'),'Add owners and dates',async()=>toOutcomes());
 // Each meeting type asks its own review questions, for example to confirm the hypotheses of an incident.
 for(const section of meetingType(d).sections){if(!section.attention)continue;const count=(minutes[section.key]||[]).filter(m=>m.review!=='verified').length;
  if(count)add('info',section.attention[count===1?0:1].replace('{n}',count),'Open notes',async()=>{switchTab('notes');$('notes-panel').scrollIntoView({block:'start'});});}
 box.hidden=false;
 const head=el('div','attention-head');head.append(el('strong','',items.length?'Needs attention · '+items.length:'No outstanding flags'));
 if(!items.length){
  head.append(el('span','hint',d.minutes?'No automatic checks are flagged. Review AI statements against their source.':'Generate notes to collect decisions and tasks.'));
  if(d.project_id){const next=actionBtn('secondary small-action','Prepare the next meeting',()=>openPrepare(d.project_id,d.series_id||''));head.append(next);}
 }
 box.append(head,...items);box.classList.toggle('done',!items.length);
}
function renderSpeakerReview(busy) {
 const target=$('speaker-review');target.replaceChildren();$('speaker-review-count').textContent=AtlantaUX.count(new Set(detail.transcript.map(s=>s.speaker).filter(Boolean)).size,'participant');
 const hasAudio=detail.files.includes('recording.wav'), names=[...new Set(detail.transcript.map(s=>s.speaker).filter(Boolean))];
 if(!detail.transcript.length)return;
 target.append(el('h3','','Participants · after recording'));
 const runtime=state.diarization||{}, meta=detail.transcript_metadata?.speaker_alignment;
 const description=el('p','hint',detail.diarization_error?'Speaker separation could not finish · '+detail.diarization_error:
  meta?'Aligned using '+meta.method+'. Speaker boundaries are estimates; listen and confirm names.':
  'Separate voices after the meeting, then listen to a sample and name each speaker. Names are not inferred from the participant list.');target.append(description);
 if(hasAudio&&!runtime.available)target.append(el('p','notice warning',runtime.message||'Speaker model is not installed in this build.'));
 if(hasAudio){const identify=btn('secondary','Identify speakers after recording');
  identify.disabled=busy||!runtime.available||names.some(n=>!/^SPEAKER[ _-]?\d+$/i.test(n));
  identify.title=names.some(n=>!/^SPEAKER[ _-]?\d+$/i.test(n))?'Confirmed participant names are kept; speaker separation will not overwrite them.':'';
  identify.onclick=()=>perform(async()=>{if(!(await leaveEdits()))return;await api('/api/meetings/'+detail.id+'/process',{action:'speakers'});await openMeeting(detail.id,true);});target.append(identify);}
 if(!names.length){target.append(el('p','hint',hasAudio?'No speaker labels yet. The transcript remains available.':'Speaker separation needs recorded audio. You can add labels manually.'));return;}
 for(const name of names){
  const sample=detail.transcript.find(s=>s.speaker===name), row=el('div','input-row speaker-review-row'), label=el('strong','',participantLabel(name)), listen=listenButton(detail.id,sample.start,{label:'Listen from '+time(sample.start),className:'quiet'});
  const apply=async value=>{if(dirtyTranscript||dirtyNotes||itemEditing){error('Save other corrections before naming speakers.');return false;}
   detail=await api('/api/meetings/'+detail.id+'/edit',{speaker_name:{speaker:name,name:value,revision:detail.transcript_revision}});speakerNaming=false;lastFingerprint=JSON.stringify(detail);state=await api('/api/state');renderState();renderDetail();return true;};
  row.append(label,listen,thisIs(name,busy,apply));target.append(row);
  // A voice suggestion is only a hint: listen first, and nothing changes until a person applies it.
  const voice=detail.voice_suggestions?.[name];
  if(voice){const hint=el('p','hint voice-hint','Sounds like '+voice.name+' from '+AtlantaUX.count(voice.meetings,'earlier meeting')+' · similarity '+voice.similarity.toFixed(2)+' '),use=el('button','secondary small-action','Use '+voice.name);
   use.type='button';use.disabled=busy;use.onclick=()=>perform(async()=>{if(await apply(voice.name))toast('Speaker name applied to this meeting');});hint.append(use);target.append(hint);}
 }
}
// The person that a speaker name belongs to: the same name or one of the person's other names.
function personFor(name) { const key=(name||'').trim().toLocaleLowerCase();if(!key||/^SPEAKER[ _-]?\d+$/i.test(key))return null;const matches=(state.people||[]).filter(p=>[p.name,...p.aliases].some(n=>n.toLocaleLowerCase()===key));return matches.length===1?matches[0]:null; }
// "This is …" links a speaker of this meeting to a person. A numbered speaker takes the person's name;
// changing a participant affects this meeting only. Global aliases are edited in People.
let pendingSpeaker=null;
function thisIs(name,busy,apply) {
 const linked=personFor(name), generic=/^SPEAKER[ _-]?\d+$/i.test(name), select=el('select','this-is');
 select.setAttribute('aria-label','Link '+participantLabel(name)+' to a person'); select.disabled=busy; select.title=linked?'Linked to '+linked.name+'. Choose another person to change it.':'Choose the person who speaks here';
 select.append(option(linked?'✓ '+linked.name:'This is…',''),...(state.people||[]).filter(p=>p!==linked).map(p=>option(p.name,p.id)),option('＋ New person…','__new__'));
 select.onchange=()=>perform(async()=>{
  const value=select.value; select.value='';
  if(value==='__new__'){await openPerson(null);if(!generic)$('person-name').value=name;$('person-name').focus();pendingSpeaker={meeting:detail.id,name,generic,apply};return;}
  const person=(state.people||[]).find(p=>p.id===value); if(!person) return;
  if(await apply(person.name))toast('Participant linked to '+person.name+' in this meeting');
 });
 return select;
}
function renderVoiceStatus(){
 const voice=state.voices||{},available=state.diarization?.available;
 $('voice-status').textContent=!available?'Voice learning needs the speaker model, which this build does not include.':voice.running?'Learning voices · '+voice.done+' of '+AtlantaUX.count(voice.total,'meeting'):voice.total?'Learned voices from '+AtlantaUX.count(voice.done-voice.failed,'meeting')+(voice.failed?' · '+voice.failed+' failed, see backend.log':''):'';
 $('learn-voices').disabled=!available||voice.running;
}
function renderSpeakerSettings() {
 renderVoiceStatus();
 const notice=$('people-migration'),report=state.people_migration||{};
 notice.hidden=!report.error&&!report.unresolved?.length;
 notice.textContent=report.error||((report.unresolved||[]).length?'These old participant names need review: '+report.unresolved.join(', ')+'. Review their People profiles and choose the person in each meeting.':'');
}
// People: one real person behind names, task owners and a GitHub account. Confirmed by a person only.
// The row shows the one most useful identity: the GitHub account, else a second name, else an email. The profile shows the rest.
function personIdentity(person){
 const github=person.github?'@'+person.github.login+(person.github.id?'':' · not checked'):'',aliases=person.aliases||[],emails=person.emails||[];
 const first=github||(aliases[0]?'Also '+aliases[0]:'')||emails[0]||'',more=(github?aliases.length+emails.length:aliases.length?aliases.length-1+emails.length:Math.max(0,emails.length-1));
 return first+(more?' · +'+more:'');
}
function renderPeople(){
 const list=$('people-list');list.replaceChildren();
 for(const person of state.people||[]){
  const row=btn('person-row');row.append(avatar(person.name),el('strong','',person.name),
   el('span','hint',personIdentity(person)));
  row.onclick=()=>perform(()=>openPerson(person.id));list.append(row);
 }
 if(!(state.people||[]).length)list.append(el('p','hint','No people yet. Add a person here or name a participant in a meeting. The same profile is used for tasks and connected sources.'));
}
let personEditing=null,personGitHub=null,personSequence=0;
const splitList=value=>value.split(',').map(x=>x.trim()).filter(Boolean);
async function openPerson(id){
 const sequence=++personSequence;
 if(id)pendingSpeaker=null;
 const person=id?(state.people||[]).find(p=>p.id===id):null;personEditing=person;personGitHub=person?.github||null;
 $('person-title').textContent=person?person.name:'New person';$('person-error').hidden=true;
 $('person-name').value=person?.name||'';$('person-aliases').value=(person?.aliases||[]).join(', ');$('person-emails').value=(person?.emails||[]).join(', ');
 $('person-github').value=person?.github?.login||'';$('person-notes').value=person?.notes||'';$('person-delete').hidden=!person;
 $('person-github-status').textContent=person?.github?(person.github.id?'GitHub ID '+person.github.id+' · a renamed account stays this person':'Not checked on GitHub yet'):'';
 renderPersonIdentities(person);$('person-profile').replaceChildren();
 if(!$('person-dialog').open)$('person-dialog').showModal();
 if(person){const profile=await api('/api/people/profile?id='+person.id);if(sequence===personSequence&&$('person-dialog').open&&personEditing?.id===person.id)renderProfile(profile);}
}
function renderProfile(profile){
 const box=$('person-profile');box.replaceChildren(el('h3','','What '+profile.person.name+' said and took on'));
 if(profile.voice_samples?.length)box.append(el('p','hint','Voice profile · samples from '+AtlantaUX.count(profile.voice_samples.length,'meeting')+' on this Mac. Matching only suggests a person; you confirm it.'));
 box.append(el('p','hint',profile.statements+(profile.statements===1?' statement':' statements')+' in '+profile.meetings+(profile.meetings===1?' meeting':' meetings')+', from transcripts where a speaker has one of the names above.'));
 const list=(title,rows,render,empty)=>{const section=el('section','profile-section');section.append(el('h4','',title));if(!rows.length)section.append(el('p','hint',empty));for(const row of rows)section.append(render(row));box.append(section);};
 renderChannelProfile(profile);
 list('Commitments',profile.commitments,task=>el('p','profile-row',task.text+(task.due_date?' · due '+date(task.due_date):'')+(task.status==='done'?' · done':'')),'No task with an owner that a person confirmed.');
 if(profile.shared?.length)list('Also working on (shared tasks)',profile.shared,task=>el('p','profile-row',task.text+(task.due_date?' · due '+date(task.due_date):'')+(task.status==='done'?' · done':'')),'');
 if(profile.suggested.length)list('Suggested by the AI, not confirmed',profile.suggested,task=>el('p','profile-row muted',task.text),'');
 list('Recent statements',profile.said.slice(0,10),row=>{const line=el('div','profile-said');line.append(listenButton(row.meeting_id,row.start,{label:'',className:'chip-listen'}),el('span','',row.text),el('small','hint',row.meeting_title));return line;},'No transcript uses these names yet.');
 if(profile.person.github)list('Assigned on GitHub (cached)',profile.github,item=>el('p','profile-row',item.repository+' #'+item.number+' · '+item.title+' · '+item.state),'Nothing in the GitHub cache. Sync the GitHub tab to see assigned issues.');
}
$('learn-voices').onclick=()=>perform(async()=>{const job=await api('/api/voices/learn',{});state.voices=job;renderSpeakerSettings();toast(job.total?'Learning voices from '+AtlantaUX.count(job.total,'meeting'):'Every saved meeting already has voice prints');});
$('add-person').onclick=()=>perform(()=>openPerson(null));
$('person-close').onclick=()=>$('person-dialog').close();
$('person-dialog').addEventListener('close',()=>{++personSequence;pendingSpeaker=null;});
$('person-github').oninput=()=>{personGitHub=null;$('person-github-status').textContent=$('person-github').value.trim()?'Check the username on GitHub to keep its stable ID.':'';};
$('person-github-check').onclick=()=>perform(async()=>{
 const login=$('person-github').value.trim().replace(/^@/,''),sequence=personSequence;if(!login)return;
 const current=()=>sequence===personSequence&&$('person-dialog').open&&$('person-github').value.trim().replace(/^@/,'')===login;
 try{const found=await api('/api/github/user',{login});if(!current())return;personGitHub=found;$('person-github').value=found.login;$('person-github-status').textContent='✓ @'+found.login+' · GitHub ID '+found.id;}
 catch(e){if(current())$('person-github-status').textContent='Could not check: '+e.message+' The username is saved without an ID.';}
});
$('person-form').onsubmit=event=>{event.preventDefault();return perform(async()=>{
 const login=$('person-github').value.trim().replace(/^@/,'');
 const github=login?(personGitHub&&personGitHub.login.toLowerCase()===login.toLowerCase()?personGitHub:{login,id:null}):null;
 try{const result=await api('/api/people/save',{id:personEditing?.id,revision:personEditing?.revision,name:$('person-name').value,aliases:splitList($('person-aliases').value),emails:splitList($('person-emails').value),github,notes:$('person-notes').value});
  // A person created from "This is …" is linked to that speaker at once.
  const link=pendingSpeaker;pendingSpeaker=null;
  state.people=result.people;state.speakers=result.speakers||state.speakers;renderPeople();syncSpeakers();$('person-dialog').close();toast('Saved '+result.person.name);
  if(link&&!personEditing&&detail?.id===link.meeting){if(link.generic||!personFor(link.name)){if(await link.apply(result.person.name))toast(link.name+' is '+result.person.name+' in this meeting');}else renderDetail();}}
 catch(e){showError($('person-error'),e.message);}});};
$('person-delete').onclick=()=>perform(async()=>{if(!personEditing||!(await ask('Delete '+personEditing.name+'? Meetings, tasks and speaker names stay as they are.',{ok:'Delete',danger:true})))return;
 const result=await api('/api/people/delete',{id:personEditing.id,revision:personEditing.revision});state.people=result.people;state.speakers=result.speakers||state.speakers;renderPeople();syncSpeakers();$('person-dialog').close();});

async function readApiResponse(response){
 const text=await response.text();let data;
 const sessionMessage='Your Atlanta session is no longer valid. Open Atlanta again using its launcher. Your saved work is kept.';
 const fail=message=>{const failure=new Error(message);failure.status=response.status;throw failure;};
 try{data=JSON.parse(text);}catch{
  if(response.status===401||response.status===403)fail(sessionMessage);
  fail(response.ok?'The local server returned an unreadable response. Try again.':'The local server could not complete the request (HTTP '+response.status+'). Try again.');
 }
 if(!response.ok){if(response.status===403&&/Invalid app session or origin|Open the app using its launcher/i.test(data?.error||''))fail(sessionMessage);fail(typeof data?.error==='string'?data.error:'Request failed (HTTP '+response.status+')');}
 return data;
}
async function api(path,body) {
 // A save outside perform() (a select, a checkbox) also shows that it runs.
 if(body!==undefined)beginActivity('Saving');
 // Only a save that the server accepted counts for the check mark. A refused save counts as a failure,
 // also when the caller catches the error and shows it in a form.
 let ok=false;
 try{
  const response=await fetch(path, body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const data=await readApiResponse(response);ok=true;
  // A correction of a term in a task or decision offers that term for the vocabulary.
  if(data&&Array.isArray(data.vocabulary_suggestions)&&data.vocabulary_suggestions.length)offerVocabulary(data.vocabulary_suggestions);
  return data;
 }finally{if(body!==undefined){if(ok)actionWrites++;else actionFailures++;endActivity();}}
}
// The desktop window (WKWebView) ignores target=_blank links. The backend opens them in the default browser.
document.addEventListener('click',event=>{
 const link=event.target.closest?.('a[target="_blank"]');
 if(!link||event.defaultPrevented||event.button!==0||!link.href.startsWith('https://'))return;
 event.preventDefault();perform(()=>api('/api/open-external',{url:link.href}));
});
// A pressed control shows that its action runs, and a saved change shows a check mark.
// The capture listener runs before the control's own handler, so perform() sees the control.
let actionTrigger=null,actionWrites=0,actionFailures=0,runningActions=0,activityTimer=null;
const busyTriggers=new WeakSet(),BUSY_DELAY=250,DONE_TIME=1500;
for(const type of ['click','change','submit'])document.addEventListener(type,event=>{
 const node=type==='submit'?event.submitter||event.target.querySelector?.('[type=submit]'):event.target.closest?.('button,select,input');
 actionTrigger=node||null;setTimeout(()=>{if(actionTrigger===node)actionTrigger=null;});
},true);
let activityLabel='';
// The name of a pressed control, in its own words, for the activity status.
function actionLabel(trigger){
 if(!trigger)return '';
 const text=String((trigger.matches('button,[type=submit]')&&trigger.textContent)||'').replace(/\s+/g,' ').replace(/[✓…]/g,'').trim();
 return (text||trigger.getAttribute?.('aria-label')||trigger.title||'').slice(0,60);
}
// One status line: an action that a person started wins; otherwise a background job of a meeting shows.
let foregroundShown=false,backgroundJob=null;
function paintActivity(){
 const status=$('activity-status'),text=foregroundShown?(activityLabel||'Working')+' · in progress…':backgroundJob?backgroundJob.text:'';
 status.textContent=text;status.hidden=!text;status.classList?.toggle('background',!foregroundShown&&!!backgroundJob);status.classList?.toggle('failed',!foregroundShown&&backgroundJob?.tone==='failed');
 status.title=!foregroundShown&&backgroundJob?'Show the background jobs':'';
 try{if(text){if(status.showPopover&&!status.matches(':popover-open'))status.showPopover();}else if(status.hidePopover&&status.matches(':popover-open'))status.hidePopover();}catch{}
}
// A dialog that opens later covers the status line in the top layer. Showing the popover again puts it above the dialog.
function raiseActivity(){const status=$('activity-status');try{if(status.matches(':popover-open')){status.hidePopover();status.showPopover();}}catch{}}
function showActivity(){activityTimer=null;if(!runningActions)return;$('activity').hidden=false;foregroundShown=true;paintActivity();}
function beginActivity(label){
 if(!runningActions)activityLabel=label||'';else if(label&&!activityLabel)activityLabel=label;
 runningActions++;if(!activityTimer&&$('activity').hidden)activityTimer=setTimeout(showActivity,BUSY_DELAY);
}
function endActivity(){
 runningActions--;if(runningActions)return;
 clearTimeout(activityTimer);activityTimer=null;$('activity').hidden=true;activityLabel='';foregroundShown=false;paintActivity();
}
// A long step inside an action names itself, for example "Importing transcript".
function activityStep(label){activityLabel=label;if(foregroundShown)paintActivity();}
// Processing after a recording or an import runs on the server: its current step and the meeting show here.
if(typeof document.getElementById==='function'&&document.getElementById('activity-status'))document.getElementById('activity-status').addEventListener('click',()=>{if(!foregroundShown&&backgroundJob)perform(backgroundJob.open);});
// Background jobs come from one registry on the server (/api/jobs): meetings, 1:1 AI and GitHub, the prompt test,
// email AI and repository reports. It is the single source of their state: queued, running, completed, failed, cancelled.
// The status line sums them up; a click opens the list. A failure stays there until it is dismissed.
let jobsData={jobs:[],summary:{}},jobsTimer=null,jobsLoading=null;
function refreshJobs(){
 if(jobsLoading)return jobsLoading;
 jobsLoading=(async()=>{
  try{jobsData=await api('/api/jobs');}catch{}finally{jobsLoading=null;}
  renderBackgroundActivity();clearTimeout(jobsTimer);jobsTimer=null;
  if(jobsData.summary?.running||jobsData.summary?.queued)jobsTimer=setTimeout(refreshJobs,2000);
 })();return jobsLoading;
}
function backgroundJobText(job){return job.label+(job.phase&&!job.label.includes(job.phase)&&!['running','queued'].includes(job.phase.toLowerCase())?' · '+job.phase:'')+(job.progress&&job.progress.total>1?' · '+job.progress.done+' of '+job.progress.total:'');}
function jobsSummary(){
 const sum=jobsData.summary||{},active=(sum.running||0)+(sum.queued||0),failed=sum.failed||0,list=jobsData.jobs||[];
 if(!active&&!failed)return null;
 // One running job and no failure: its own words. Otherwise the counts; a failure is never hidden by a success.
 if(active===1&&!failed)return {text:backgroundJobText(list.find(j=>['running','queued'].includes(j.state))),tone:'running'};
 return {text:[active&&AtlantaUX.count(active,'job')+' running',failed&&AtlantaUX.count(failed,'job')+' failed'].filter(Boolean).join(' · '),tone:failed?'failed':'running'};
}
function renderBackgroundActivity(){
 const summary=jobsSummary();
 backgroundJob=summary?{text:summary.text,tone:summary.tone,open:()=>toggleJobsPanel(true)}:null;
 paintActivity();if($('jobs-panel')?.matches?.(':popover-open'))renderJobsPanel();
}
function openJob(job){
 const t=job.target||{};toggleJobsPanel(false);
 if(t.view==='meeting')return openMeeting(t.id);
 if(t.view==='team')return openTeamReview(t.id);
 if(t.view==='settings'){if(!$('settings-dialog').open)openSettings(t.id);showSettingsTab(t.id);return;}
 if(t.view==='work'){workTab=t.id==='github-reports'?'github':t.id;return $('open-tasks').onclick().then(()=>{if(t.id==='github-reports'){showGitHubSection('reports');return loadRepoReports();}});}
}
const JOB_STATES={queued:'Queued',running:'Running',completed:'Completed',failed:'Failed',cancelled:'Cancelled'};
function renderJobsPanel(){
 const panel=$('jobs-panel');panel.replaceChildren(el('h2','','Background jobs'));
 const jobs=jobsData.jobs||[];if(!jobs.length){panel.append(el('p','hint','No background jobs.'));return;}
 for(const job of jobs){
  const row=el('div','job-row job-'+job.state),head=el('div','job-head');
  head.append(el('span','job-state',JOB_STATES[job.state]||job.state),el('strong','',job.label));row.append(head);
  const phase=job.phase&&!job.label.includes(job.phase)&&job.phase.toLowerCase()!==job.state?job.phase:'';if(phase||job.progress)row.append(el('p','hint',[phase,job.progress&&job.progress.total>1&&job.progress.done+' of '+job.progress.total].filter(Boolean).join(' · ')));
  if(job.error)row.append(el('p','error',job.error));
  const actions=el('div','action-group');actions.append(actionBtn('quiet small-action','Open',()=>openJob(job)));
  if(['failed','completed','cancelled'].includes(job.state))actions.append(actionBtn('quiet small-action','Dismiss',async()=>{jobsData=await api('/api/jobs/dismiss',{id:job.id});renderBackgroundActivity();}));
  row.append(actions);panel.append(row);
 }
}
function toggleJobsPanel(open){
 const panel=$('jobs-panel');if(!panel?.showPopover)return;
 try{if(open&&!panel.matches(':popover-open')){renderJobsPanel();panel.showPopover();}else if(!open&&panel.matches(':popover-open'))panel.hidePopover();}catch{}
}
async function perform(fn) {
 // Nested and later calls do not take the control of the first press.
 const trigger=actionTrigger;actionTrigger=null;
 const button=trigger?.matches('button,[type=submit]')?trigger:null;
 // A second press of the same button waits for the first action. Selects and checkboxes always apply.
 if(button&&busyTriggers.has(button))return;
 if(trigger)busyTriggers.add(trigger);
 const writes=actionWrites,failures=actionFailures;let failed=false;
 beginActivity(actionLabel(trigger));
 const busy=trigger&&setTimeout(()=>{trigger.classList.add('is-busy');trigger.setAttribute('aria-busy','true');},BUSY_DELAY);
 clearError();
 try { await fn(); } catch(e) { failed=true; error(e.message); }
 finally {
  endActivity();
  if(trigger){clearTimeout(busy);busyTriggers.delete(trigger);trigger.classList.remove('is-busy');trigger.removeAttribute('aria-busy');}
  // A button that saved or started something confirms it in place, also when the action was fast.
  if(button&&!failed&&actionFailures===failures&&actionWrites!==writes&&button.isConnected&&button.getClientRects().length){
   button.classList.add('is-done');setTimeout(()=>button.classList.remove('is-done'),DONE_TIME);
  }
 }
}
function hasEdits() { return dirtyTranscript || dirtyNotes || itemEditing || speakerNaming || editorDirty.has(); }
// What a person would lose, in their words, so the question says what it is about.
const EDITOR_NAMES={'task-draft':'task draft','task-panel':'task changes','meeting-review':'review edit','inline-edit':'note edit',
 'project-repositories':'project links','team-review':'1:1 review edit','team-notes':'conversation notes','team-agreements':'actions and goals','team-previous':'states of the last 1:1','type-prompt':'meeting-type instructions','ai-prompts':'AI instructions','turn-speaker':'speaker change'};
function unsavedNames(){
 const names=[dirtyTranscript&&'transcript corrections',dirtyNotes&&'notes changes',itemEditing&&'task changes',speakerNaming&&'speaker name',
  ...editorDirty.keys().map(key=>key.startsWith('dialog:')?'changes in the open window':EDITOR_NAMES[key]||'changes')];
 return [...new Set(names.filter(Boolean))];
}
// The desktop window (WKWebView) does not show confirm() or prompt(): they return "no" at once. This dialog works everywhere.
let askQueue=Promise.resolve();
// With extra, a third button answers 'extra'.
function ask(message,{ok='OK',cancel='Cancel',danger=false,value=null,extra=null}={}) {
 const open=()=>new Promise(resolve=>{
  const dialog=$('ask-dialog'), input=$('ask-input');
  $('ask-message').textContent=message; $('ask-ok').textContent=ok; $('ask-cancel').textContent=cancel; $('ask-ok').className=danger?'danger':'primary';
  $('ask-extra').hidden=!extra; $('ask-extra').textContent=extra||'';
  input.hidden=value===null; input.value=value??''; dialog.returnValue='';
  dialog.onclose=()=>{ if(extra&&dialog.returnValue==='extra'){resolve('extra');return;} const yes=dialog.returnValue==='ok'; resolve(value===null?yes:yes?input.value:null); };
  dialog.showModal(); if(value===null) $(danger?'ask-cancel':'ask-ok').focus(); else { input.focus(); input.select(); }
 });
 const answer=askQueue.then(open,open);askQueue=answer.then(()=>{},()=>{});return answer;
}
$('ask-input').onkeydown=event=>{if(event.key==='Enter'){event.preventDefault();$('ask-dialog').close('ok');}};
let taskDraftPending=false,taskEvidenceTarget=null,taskPanelSequence=0;
function renderTaskEvidenceContext(){const box=$('task-evidence-context');box.replaceChildren();box.hidden=!taskEvidenceTarget;if(!taskEvidenceTarget)return;box.append(el('strong','','Link evidence to: '+taskEvidenceTarget.text.slice(0,160)),el('p','hint','Select a transcript passage or open a source and choose Suggest a task. The editor will link it to this task.'));const cancel=btn('quiet','Cancel linking');cancel.onclick=()=>{taskEvidenceTarget=null;renderTaskEvidenceContext();};box.append(cancel);}
async function suggestTask(button,source){
 if(taskDraftPending){toast('Finish the current task draft first');return;}
 if(taskEvidenceTarget&&source.provider!=='manual')source={...source,link_only:true,capture_target:taskEvidenceTarget.id};
 taskDraftPending=true;button.disabled=true;
 try{itemsData=await api('/api/items');const preview=await api('/api/task-draft/preview',source);return await editTaskDraft(source,preview);}
 finally{taskDraftPending=false;button.disabled=false;}
}
function editTaskDraft(source,preview){
 return new Promise(resolve=>{
  const dialog=$('task-draft-dialog'),area=$('task-draft-text'),submit=$('task-draft-save'),cancel=$('task-draft-cancel'),generate=$('task-draft-generate'),note=$('task-draft-error'),status=$('task-draft-status'),project=$('task-draft-project'),keep=$('task-draft-keep');
  let createdTaskId=null,submitted=null,jobId='',poll=null,generating=false,preparing=false,saving=false,closed=false,operation=crypto.randomUUID().replaceAll('-','');
  const extra=$('task-draft-details'),criterion=$('task-draft-criterion'),link=$('task-draft-link');
  const owner=$('task-draft-owner'),due=$('task-draft-due');owner.value=source.capture_owner||'';due.value=source.capture_due_date||'';
  extra.value=criterion.value='';link.replaceChildren(option(source.link_only?'Choose an existing task…':'Create a new task',source.link_only?'__choose__':''),...itemsData.items.filter(i=>i.kind==='task'&&i.acceptance_state!=='proposed'&&i.id!==source.proposal_item_id).map(i=>option(i.text,i.id)));link.value=source.capture_target&&itemsData.items.some(i=>i.id===source.capture_target&&i.acceptance_state!=='proposed')?source.capture_target:source.link_only?'__choose__':'';
  const sourceKey=JSON.stringify(source),cacheKey='atlanta-task-draft';
  area.value='';area.disabled=false;keep.checked=false;note.hidden=true;status.textContent='Review the source, generate a draft or write it yourself.';
  $('task-draft-source').textContent=preview.source_excerpt||'';const target=preview.target;
  if(preview.ai_available===false){note.textContent=preview.ai_unavailable_reason;note.hidden=false;}
  $('task-draft-target').textContent=preview.ai_available===false?preview.ai_unavailable_reason:'AI: '+target.local_ai_model+' · '+target.local_ai_base_url+' · '+preview.characters+' source characters';
  fillProjects(project,Object.hasOwn(source,'capture_project_id')?source.capture_project_id:contextProject(),'No project');
  try{const cached=JSON.parse(localStorage.getItem(cacheKey)||'null');if(cached&&Date.now()-cached.at<86400000&&cached.source===sourceKey){area.value=cached.text;extra.value=cached.details||'';criterion.value=cached.completion_criteria||'';owner.value=cached.owner||'';due.value=cached.due_date||'';project.value=cached.project||'';keep.checked=true;status.textContent='Recovered draft from this Mac. Review it against the current source.';}else if(cached&&Date.now()-cached.at>=86400000)localStorage.removeItem(cacheKey);}catch{}
  function persist(){if(keep.checked){store(cacheKey,JSON.stringify({at:Date.now(),source:sourceKey,text:area.value,details:extra.value,completion_criteria:criterion.value,owner:owner.value,due_date:due.value,project:project.value}));}else{try{localStorage.removeItem(cacheKey);}catch{}}}
  function controls(){submit.textContent=link.value?'Link evidence':'Create task';submit.disabled=saving||generating||link.value==='__choose__'||(!link.value&&!area.value.trim());owner.disabled=due.disabled=extra.disabled=criterion.disabled=!!link.value||saving||generating;link.disabled=saving||generating;area.disabled=!!link.value||saving||generating;generate.disabled=!!link.value||saving||generating||preparing||preview.ai_available===false;cancel.disabled=saving;area.disabled=!!link.value||saving||generating;project.disabled=saving||!!link.value;}
  owner.oninput=due.onchange=extra.oninput=criterion.oninput=()=>{editorDirty.set('task-draft',true);persist();};link.onchange=()=>{editorDirty.set('task-draft',true);controls();};
  area.oninput=()=>{area.setCustomValidity('');editorDirty.set('task-draft',true);persist();controls();};project.onchange=()=>{editorDirty.set('task-draft',true);persist();};keep.onchange=persist;
  async function stop(){closed=true;if(poll)clearTimeout(poll);if(jobId&&generating){try{await api('/api/task-draft/cancel',{id:jobId});}catch{}}}
  async function discard(){if(saving)return;if(editorDirty.keys().includes('task-draft')&&!keep.checked&&!(await ask('Discard this task draft?',{ok:'Discard',cancel:'Keep editing'})))return;await stop();if(!keep.checked){try{localStorage.removeItem(cacheKey);}catch{}}dialog.close();}
  dialog.oncancel=event=>{event.preventDefault();discard();};dialog.onclose=()=>{stop();editorDirty.clear('task-draft');resolve(createdTaskId);};cancel.onclick=discard;
  generate.onclick=()=>perform(async()=>{
   if(preparing||generating||saving||closed)return;preparing=true;controls();
   try{
   if(area.value.trim()&&!(await ask('Replace the current draft with a new AI draft?',{ok:'Replace draft'})))return;
   // An error here shows in this dialog: the page behind the dialog is not in view.
   let current;try{current=await api('/api/task-draft/preview',source);}catch(e){if(!closed){showError(note,e.message);status.textContent='The draft could not start.';}return;}if(closed)return;
   if(current.ai_available===false){preview=current;note.textContent=current.ai_unavailable_reason;note.hidden=false;return;}
   if(!(await ask('Send the selected source to '+current.target.local_ai_model+' at '+current.target.local_ai_base_url+'? '+current.characters+' characters. The result stays an editable draft.',{ok:'Generate draft'})))return;
   if(closed)return;preview=current;generating=true;note.hidden=true;status.textContent='Generating draft… You can cancel this operation.';controls();
   try{
    const job=await api('/api/task-draft/start',{...source,preview_token:preview.preview_token,approved:true});jobId=job.id;
    if(closed){await api('/api/task-draft/cancel',{id:jobId});return;}
    const check=async()=>{if(closed)return;try{const job=await api('/api/task-draft/status?id='+encodeURIComponent(jobId));if(closed)return;status.textContent=job.status+' · '+Math.max(0,Math.floor(Date.now()/1000-job.started_at))+' s';if(job.running){poll=setTimeout(check,700);return;}generating=false;if(job.error){showError(note,job.error+' You can still write the task manually.');}else if(job.text){area.value=job.text;extra.value=job.details||'';criterion.value=job.completion_criteria||'';editorDirty.set('task-draft',true);persist();}controls();area.focus();}catch(e){generating=false;showError(note,e.message);controls();}};
    await check();
   }catch(e){generating=false;showError(note,e.message);status.textContent='Generation failed. Write the task manually or try again.';controls();}
   }finally{preparing=false;controls();}
  });
  submit.onclick=async()=>{
   if(!link.value&&!area.value.trim()){area.setCustomValidity('Enter task text');area.reportValidity();return;}
   if(!validDates(dialog))return;
   saving=true;note.hidden=true;controls();
   try{
    const payload={...source,preview_token:preview.preview_token,operation_id:operation,title:area.value.trim()||'Link source evidence',details:extra.value,completion_criteria:criterion.value,owner:owner.value.trim()||null,due_date:due.value||null,target_id:link.value||null,target_revision:itemsData.items.find(i=>i.id===link.value)?.revision,project_ids:project.value?[project.value]:[]};
    if(submitted&&JSON.stringify(submitted)!==JSON.stringify(payload))throw new Error('Previous result uncertain. Retry unchanged or check My Work.');submitted=payload;
    const created=await api('/api/task-draft/create',payload);
    try{localStorage.removeItem(cacheKey);}catch{}createdTaskId=created.item_id;editorDirty.clear('task-draft');dialog.close();
    if(taskEvidenceTarget){taskEvidenceTarget=null;renderTaskEvidenceContext();}
    showCreatedTask(created.item_id,!!link.value);
    try{await refreshAfterItemChange();revealTask(created.item_id);}catch(e){error('Task created. The list could not refresh. Use Open task or Refresh; do not create it again.');}
   }catch(e){if(e.status>=400&&e.status<500)submitted=null;showError(note,e.message);}
   finally{saving=false;controls();}
  };
  dialog.querySelector('form').onsubmit=event=>event.preventDefault();
  controls();dialog.showModal();area.focus();
 });
}
// A new task is never hidden: My Work clears the filters that hide it, then scrolls to it.
function revealTask(id){
 if(view!=='tasks'||itemKind!=='task'||!itemsData)return;
 const item=itemsData.items.find(i=>i.id===id);if(!item||item.acceptance_state==='proposed')return;
 if(!taskVisibleRows.some(i=>i.id===id)){resetTaskFilters({all:true});toast('Filters cleared to show the new task');}
 const row=[...$('task-list').querySelectorAll('[data-item-id]')].find(node=>node.dataset.itemId===id);if(!row)return;
 row.scrollIntoView({block:'center'});row.classList.add('just-created');setTimeout(()=>row.classList.remove('just-created'),2500);
}
// One offer at a time: "Add linkin.eu (heard as Link in Elo) to the vocabulary?" Nothing changes without Add.
// The offer has its own box, so the toast of the save does not hide it.
let vocabularyOffers=[];
function offerVocabulary(rows){
 for(const r of rows)if(!vocabularyOffers.some(o=>o.term===r.term&&o.variant===r.variant))vocabularyOffers.push(r);
 let box=document.getElementById('vocabulary-offer');
 if(box&&!box.hidden)return;
 if(!box){box=el('div','vocabulary-offer');box.id='vocabulary-offer';box.setAttribute('role','status');document.body.append(box);}
 const row=vocabularyOffers[0];if(!row){box.hidden=true;return;}
 const add=el('button','primary small-action','Add to vocabulary'),skip=el('button','secondary small-action','Not now');add.type=skip.type='button';
 const next=()=>{vocabularyOffers.shift();box.hidden=true;offerVocabulary([]);};
 add.onclick=()=>perform(async()=>{await api('/api/vocabulary/add',{term:row.term,variant:row.variant});next();toast('Added to the vocabulary. The next transcription uses it.');});
 skip.onclick=next;
 box.replaceChildren(el('span','','Add “'+row.term+'”'+(row.variant?' (heard as “'+row.variant+'”)':'')+' to the vocabulary?'),add,skip);box.hidden=false;
}
function showCreatedTask(id,linked=false){const box=$('toast');box.replaceChildren(document.createTextNode(linked?'Evidence linked. ':'Task created. '));const open=el('button','quiet','Open task');open.onclick=()=>perform(()=>openTaskPanel(id));box.append(open);box.hidden=false;setTimeout(()=>{if(box.contains(open))box.hidden=true;},15000);}
function contextProject(){if(view==='projects'){const key=$('workspace-project').value;return key&&key!=='__none__'?key:'';}return view==='detail'?detail?.project_id||'':$('record-project').value||'';}
async function askDate(message,initial){let current=AtlantaUX.display(initial);for(;;){const value=await ask(message,{ok:'Apply date',value:current});if(value===null)return null;const iso=AtlantaUX.inputISO(value);if(iso)return iso;current=value;message='Enter a valid date as dd.mm.yyyy.';}}
async function leaveEdits() {
 if(editorDirty.keys().some(key=>key==='saving'||key.startsWith('dialog-save:'))){toast('Wait for the current save to finish');return false;}
 const edited=hasEdits();
 if(edited&&!(await ask('Leave without saving the '+unsavedNames().join(', ')+'?',{ok:'Leave without saving',cancel:'Stay'})))return false;
 // Navigation checks hasEdits() again after loading. Discard both the edits and
 // their flags now; typing after this point must still block a late response.
 if(dirtyTranscript&&detail&&transcriptBaseline)detail.transcript=structuredClone(transcriptBaseline);
 if(dirtyNotes&&detail&&notesBase)detail.minutes=structuredClone(notesBase);
 dirtyTranscript=dirtyNotes=false;transcriptEditing=notesEditing=false;
 transcriptBaseline=notesBase=null;speakerNaming=false;
 for(const key of editorDirty.keys())editorDirty.clear(key);
 teamDrafts={};
 if(itemEditing){setItemEditing(false);lastTasks='';}
 if(edited&&view==='detail'&&detail)renderDetail();
 editorHeartbeat();return true;
}
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
 const mode=document.querySelector('input[name=mode]:checked')?.value;
 const parts=[mode==='online'?'Online · Mac audio + mic':'In person',$('transcription-timing').value==='live'?'Live captions':'After recording'];
 const type=typeOf($('record-type').value),inherited=seriesType($('record-series').value);
 $('record-type-help').textContent=type.description+($('record-series').value&&type.id===inherited?' The default of this series.':'');
 $('record-series-summary').textContent=$('record-series').value?'Series: '+$('record-series').selectedOptions[0]?.textContent:'Series and preparation';
 if($('fallback-microphone').value)parts.push('Backup: '+$('fallback-microphone').value);
 parts.push($('processing-name').textContent);$('record-more-summary').textContent=parts.join(' · ');
}
// Library: one place for finding past conversations. Its views keep their own sections and loaders.
const LIBRARY_VIEWS=['conversations','calendar','find','analytics'];
// Each view and tab has its own address: Back and Forward work, and a reload keeps the place.
let routing=false,meetingTab='transcript';
function currentRoute(){
 const q=new URLSearchParams();
 if(view==='detail'&&selected){q.set('meeting',selected);if(meetingTab!=='transcript')q.set('tab',meetingTab);}
 else if(view==='tasks'){q.set('view','work');q.set('tab',workTab);if(workTab==='gmail'&&mailThread)q.set('source',mailThread);if(workTab==='chat'&&chatSpace)q.set('source',chatSpace);if(workTab==='github'){if(ghSection==='reports'){q.set('section','reports');if(repoReportId)q.set('report',repoReportId);}else if(ghItem)q.set('source',String(ghItem));}}
 else if(view==='projects'){q.set('view','projects');const project=$('workspace-project').value;if(project)q.set('project',project);if(workspaceSection!=='overview')q.set('section',workspaceSection);if(workspaceSection==='work'&&workspaceWorkKind)q.set('kind',workspaceWorkKind);}
 else if(view==='team'){q.set('view','team');if(teamReviewId)q.set('review',teamReviewId);else if(teamTab!=='members')q.set('tab',teamTab);}
 else if(view==='prepare'){q.set('view','prepare');if(prepareScope.project)q.set('project',prepareScope.project);if(prepareScope.series)q.set('series',prepareScope.series);if(prepareScope.type)q.set('type',prepareScope.type);}
 else if(view==='importing')q.set('view','importing');
 else if(view==='calendar'){q.set('view','calendar');q.set('day',calendarDay);if($('calendar-project').value)q.set('project',$('calendar-project').value);}
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
  if(meeting&&/^[a-f0-9]{32}$/.test(meeting)){
   try{await openMeeting(meeting);}catch(e){if(e.status!==404)throw e;await openConversations();error('This meeting is no longer on this Mac. It may have been deleted.');return;}
   const tab=q.get('tab');if(view==='detail'&&['review','outcomes','notes','team','analytics'].includes(tab))switchTab(tab);}
  else if(target==='work'){if(q.get('tab')==='suggested')await openTaskInbox();else{if(WORK_PANELS[q.get('tab')])workTab=q.get('tab');await $('open-tasks').onclick();}const source=q.get('source');if(workTab==='gmail'&&source)await openMail(source);else if(workTab==='chat'&&source){chatSpace=source;await loadChat();}else if(workTab==='github'){if(q.get('section')==='reports'){showGitHubSection('reports');if(q.get('report'))await openRepoReport(q.get('report'));}else if(source&&/^\d+$/.test(source))await openGitHubItem(Number(source));}}
  else if(target==='projects'){
   const project=q.get('project')||'',select=$('workspace-project');
   if(project&&![...select.options].some(o=>o.value===project))select.append(option(project,project));select.value=project;
   workspaceSection=q.get('section')||'overview';workspaceWorkKind=['task','decision','question'].includes(q.get('kind'))?q.get('kind'):'';await $('open-projects').onclick();
  }
  else if(target==='team'){const review=q.get('review');if(review&&/^[a-f0-9]{12}$/.test(review))await openTeamReview(review);else await openTeam(q.get('tab')==='reviews'?'reviews':'members');}
  else if(target==='prepare')await perform(()=>openPrepare(q.get('project')||'',q.get('series')||'',q.get('type')||''));
  else if(target==='importing')await openImport();
  else if(target==='calendar')await openCalendar(q.get('day'),q.get('project')||'');
  else if(target==='find')await openFind();
  else if(target==='analytics')await $('open-analytics').onclick();
  else if(target==='conversations')await perform(openConversations);
  else if(view!=='setup'&&view!=='recording')await $('new-meeting').onclick();
  // The first screen is shown without show(); its header joins the top bar like every other view.
  else syncPageHeader(view);
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
// App-wide shortcuts in the macOS slots: Cmd+N new meeting, Cmd+, settings, Cmd+F find.
// Browsers keep Cmd+N for a new window, so there Cmd+Option+N is the form that reaches the page.
// Option changes event.key on macOS (Option+N is a dead key), so match the physical key.
function appKeys(event){
 if(event.ctrlKey||event.shiftKey||!event.metaKey||document.querySelector('dialog[open]'))return;
 if(event.code==='KeyN'){event.preventDefault();perform(()=>$('new-meeting').onclick());}
 else if(event.code==='Comma'&&!event.altKey){event.preventDefault();openSettings();}
 else if(event.code==='KeyF'&&!event.altKey){event.preventDefault();if(view==='find'){$('find-query').focus();$('find-query').select();}else perform(()=>openFind());}
}
document.addEventListener('keydown',appKeys);
// The app's WKWebView has no Safari token in its user agent; browsers do.
$('new-meeting').title=!/Safari\//.test(navigator.userAgent)?'New meeting (⌘N)':'New meeting (⌥⌘N)';
$('settings-open').title='Settings (⌘,)';
$('open-find').title='Search (⌘F)';
// Move the existing heading and action, preserving handlers and field identities.
let mountedPageHeader=null;
function syncPageHeader(which){
 if(mountedPageHeader?.view===which)return;
 if(mountedPageHeader){const {heading,home,action,actionHome}=mountedPageHeader;home.prepend(heading);if(action)actionHome.append(action);mountedPageHeader=null;}
 const slot=$('page-header');slot.replaceChildren();
 const compact=['setup','importing','prepare','tasks','team','projects',...LIBRARY_VIEWS].includes(which),home=$(which),heading=compact?home.querySelector('.heading'):null;
 slot.hidden=!heading;document.querySelector('main').classList.toggle('compact-header',!!heading);
 if(!heading)return;
 const action=which==='projects'?$('workspace-new'):LIBRARY_VIEWS.includes(which)?$('header-import'):null,actionHome=action?.parentElement;
 slot.append(heading);if(action)heading.append(action);mountedPageHeader={view:which,heading,home,action,actionHome};
}
function setConnection(message){const node=$('connection');node.textContent=message;node.title=message;node.setAttribute('aria-label',message);node.dataset.status=/disconnected|stopped|failed/i.test(message)?'error':/recording/i.test(message)?'recording':/connecting/i.test(message)?'pending':'connected';}
function show(which) {const changed=view!==which;if(changed)readers.invalidate();view=which; if(LIBRARY_VIEWS.includes(which))store('library-view',which); for(const id of ['setup','recording','detail','tasks','team','analytics','prepare','find','projects','conversations','calendar','importing']) $(id).hidden=id!==which; $('open-tasks').classList.toggle('current',which==='tasks'); $('open-team').classList.toggle('current',which==='team'); $('open-projects').classList.toggle('current',which==='projects'); $('open-conversations').classList.toggle('current',LIBRARY_VIEWS.includes(which));
 syncPageHeader(which);for(const [id,on] of [['open-tasks',which==='tasks'],['open-team',which==='team'],['open-projects',which==='projects'],['open-conversations',LIBRARY_VIEWS.includes(which)]]){if(on)$(id).setAttribute('aria-current','page');else $(id).removeAttribute('aria-current');}if(LIBRARY_VIEWS.includes(which))$(which).prepend($('library-tabs'));$('library-tabs').hidden=!LIBRARY_VIEWS.includes(which);for(const b of $('library-tabs').querySelectorAll('button')){const on=b.dataset.library===which;b.classList.toggle('selected',on);b.setAttribute('aria-selected',String(on));} $('open-analytics').classList.toggle('current',which==='analytics'); $('open-prepare').classList.toggle('current',which==='prepare'); $('open-find').classList.toggle('current',which==='find'); renderRecordingBar();if(changed)window.scrollTo(0,0); syncRoute(); }
function renderLibrary() {
 const query='';
 const meetings=state.meetings;
 // Server searches transcript content on demand; retain the regular status snapshot.
 const filter=$('project-filter').value;
 const rows=(query && window.searchResults ? window.searchResults : meetings).filter(m=>!filter||(filter==='__none__'?!m.project_id:m.project_id===filter));
 const signature=JSON.stringify([rows,selected,view]); if(signature===lastLibrary) return; lastLibrary=signature;
 $('library').replaceChildren();
 $('library').classList.toggle('empty',!rows.length);if(!rows.length) $('library').append(el('p','empty-library',query||filter?'No matching meetings.':'No recent meetings.'));
 for(const m of rows.slice(0,5)) { const button=el('button','meeting-item'+(m.id===selected&&view==='detail'?' current':'')); button.append(el('strong','',m.title),el('small','',(m.title.includes(date(m.created))?'':date(m.created)+' · ')+(statusNames[m.status]||m.status))); button.onclick=()=>perform(()=>openMeeting(m.id)); $('library').append(button); }
 const all=btn('quiet library-all','All meetings →');all.title='Open every meeting in the Library';all.onclick=()=>perform(openConversations);if(meetings.length)$('library').append(all);
}
async function openMeeting(id,force=false) {
 const sequence=++meetingLoadSequence;
 if(!force&&!(await leaveEdits()))return false;
 if($('task-panel')?.open)$('task-panel').close();
 if(sequence!==meetingLoadSequence)return false;
 const request=readers.start('meeting');
 if(state.active?.id===id){selected=id;show('recording');renderState();return true;}
 const fresh=await api('/api/meetings/'+id);
 if(sequence!==meetingLoadSequence||!readers.current(request)||(!force&&hasEdits()))return false;
 if(detail?.id!==id){notesEditing=false;questionFilter='open';questionLimit=10;if(!routing)meetingTab=fresh.minutes?'outcomes':'transcript';}
 selected=id;detail=fresh;dirtyTranscript=dirtyNotes=false;detailChangedWhileEditing=false;
 lastFingerprint=JSON.stringify(fresh);renderDetail();show('detail');switchTab(meetingTab);renderLibrary();return true;
}
function renderState() {
 // The meetings changed: the job registry gives the new state of their processing.
 if(typeof refreshJobs==='function')refreshJobs();
 const metadataErrors=Object.values(state.storage_errors||{});$('metadata-warning').hidden=!metadataErrors.length&&!state.settings_error;$('metadata-warning-text').textContent=[state.settings_error,...metadataErrors].filter(Boolean).join('\n');
 // A settings error leads to Settings; a store error leads to Backup.
 $('metadata-recover').textContent=metadataErrors.length?'Open Backup settings':'Open Settings';
 syncSpeakers();
 if($('settings-dialog').open)renderVoiceStatus();
 syncProjects();
 const summary=state.task_summary||{open:0,overdue:0};
 // Mentions that wait for a choice come first; then source suggestions, late tasks, then open tasks.
 $('tasks-badge').hidden=!summary.open&&!summary.review&&!summary.suggested; $('tasks-badge').classList.toggle('late',!summary.review&&!summary.suggested&&summary.overdue>0); $('tasks-badge').classList.toggle('review',!!(summary.review||summary.suggested));
 $('tasks-badge').textContent=summary.review?summary.review:summary.suggested?summary.suggested:summary.overdue?summary.overdue+' late':summary.open;
 $('tasks-badge').title=summary.review?AtlantaUX.count(summary.review,'mention')+(summary.review===1?' waits':' wait')+' for your review':summary.suggested?AtlantaUX.count(summary.suggested,'source suggestion')+(summary.suggested===1?' waits':' wait')+' for a decision':summary.overdue?AtlantaUX.count(summary.overdue,'task')+(summary.overdue===1?' is':' are')+' late':AtlantaUX.count(summary.open,'open task');
 setConnection(desktopStatus|| (state.active?'● Recording workspace':'● Connected to this Mac'));
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
 $('processing-name').textContent=(s.transcription==='parakeet_sherpa'?'Local Parakeet + vocabulary':s.transcription==='parakeet'?'Local Parakeet v3':s.transcription==='local'?'Local Whisper':s.transcription==='elevenlabs'?'ElevenLabs Scribe v3':'OpenAI cloud')+' · '+(s.summarizer==='none'?'transcript only':s.summarizer==='local'?'notes via configured API':'cloud notes');
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
 renderCaptureSetup();
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
  if(review){const remove=btn('quiet');remove.append(icon('close'));remove.setAttribute('aria-label','Remove marker');remove.onclick=()=>perform(async()=>{detail=await api('/api/meetings/'+detail.id+'/marker-delete',{id:marker.id});lastFingerprint=JSON.stringify(detail);renderDetail();});row.append(remove);}
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
  (s.transcription.startsWith('parakeet')?'Parakeet v3 transcribes the full saved recording.':s.transcription==='local'?'Whisper transcribes the full saved recording.':'the selected cloud provider transcribes the full saved recording.')+
  ' Any enabled spelling correction runs after final transcription. This choice applies only to this meeting.';
}
$('transcription-timing').onchange=()=>renderTranscriptionTiming();
function renderLive(active) {
 const live=active.live;
 const disabled=active.settings?.live_transcription===false;
 $('live-card').hidden=disabled;
 const final=active.settings?.transcription?.startsWith('parakeet')?'Parakeet v3':['openai','elevenlabs'].includes(active.settings?.transcription)?'the selected cloud provider':'Whisper';
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

// Outside this Mac and its local network, so meeting text leaves them. Mirrors app/local_ai.is_remote.
function remoteAPI(url){let host='';try{host=new URL(url).hostname.toLowerCase().replace(/^\[|\]$/g,'');}catch{return false;}
 if(!host||host==='localhost'||host.endsWith('.local')||host==='::1')return false;
 const v4=host.split('.').map(Number);if(v4.length===4&&v4.every(n=>Number.isInteger(n)&&n>=0&&n<=255))return !(v4[0]===127||v4[0]===10||v4[0]===192&&v4[1]===168||v4[0]===172&&v4[1]>=16&&v4[1]<=31||v4[0]===169&&v4[1]===254);
 return !/^(fc|fd|fe80)/.test(host);}
function apiHost(url){try{return new URL(url).host;}catch{return url;}}
function privacy(s) { let text=s.transcription==='elevenlabs'?'Audio and vocabulary terms are sent to ElevenLabs for Scribe v3 transcription.'+(s.summarizer==='openai'?' Transcript text is sent to OpenAI for notes.':''):s.transcription==='openai'?'Audio is sent to OpenAI for transcription.'+(s.summarizer==='openai'?' Transcript text is also sent for notes.':''):s.summarizer==='openai'?'Transcription stays local. Transcript text is sent to OpenAI for notes.':'Transcription stays on this Mac. Notes use the configured API.';if(s.transcript_correction==='openai')text+=s.transcription==='elevenlabs'?' Transcript text is sent to OpenAI only when you run AI correction.':' Transcript text is sent to OpenAI for AI correction.';if(s.auto_title&&s.title_provider==='openai')text+=' Transcript excerpts are sent to OpenAI for titles.';if(remoteAPI(s.local_ai_base_url)){const host=apiHost(s.local_ai_base_url),uses=[s.summarizer==='local'&&'notes',s.transcript_correction==='local'&&s.transcription!=='elevenlabs'&&'AI correction',s.auto_title&&s.title_provider==='local'&&'titles'].filter(Boolean);if(uses.length)text+=' Transcript text is sent to '+host+' for '+uses.join(', ')+'.';text=text.replace(' Notes use the configured API.','');}
 // Task matching adds the context of similar existing tasks, only with the permission for this address.
 if(s.meeting_task_ai&&s.summarizer==='local'&&remoteAPI(s.local_ai_base_url)&&s.task_matching_target===s.local_ai_base_url)text+=' Titles and short updates of similar existing tasks are sent to '+apiHost(s.local_ai_base_url)+' for task matching.';
 if(s.calendar_enabled)text+=' Meeting titles, times and local links are saved in Google Calendar.';return text; }
function switchTab(name) {
 for(const [tab,panel] of [['review','review-panel'],['transcript','transcript-panel'],['outcomes','outcomes-panel'],['notes','notes-panel'],['team','team-analysis-panel'],['analytics','meeting-analytics-panel']]) { const yes=tab===name; $(panel).hidden=!yes; $('tab-'+tab).classList.toggle('selected',yes); $('tab-'+tab).setAttribute('aria-selected',String(yes)); }
 meetingTab=name;syncRoute(true);
 if(detail&&view==='detail')placeActions(detail);
 if(name==='review')perform(openMeetingReview);
}
function markTranscript() { dirtyTranscript=true; $('save-transcript').disabled=false; $('save-transcript').textContent='Save corrections'; }
async function withEditorSave(container,save){if(!validDates(container))return;editorDirty.set('saving',true);container.inert=true;try{return await save();}finally{container.inert=false;editorDirty.clear('saving');editorHeartbeat();}}
function validDates(container){const bad=[...container.querySelectorAll('[data-date-display]')].find(input=>input.getClientRects().length&&!input.checkValidity());if(bad){bad.reportValidity();bad.focus();return false;}return true;}
function markNotes() { dirtyNotes=true; $('save-notes').disabled=$('save-outcomes').disabled=false; }
let transcriptEditing=false,refreshNotesAfterEdit=true,transcriptBaseline=null;
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
 const target=$('transcript');target.replaceChildren();if(transcriptEditing&&!dirtyTranscript)transcriptBaseline=structuredClone(d.transcript);
 $('edit-transcript').disabled=busy||!d.transcript.length;$('save-transcript').hidden=!transcriptEditing;$('save-transcript').disabled=!dirtyTranscript||busy;$('save-excerpt').hidden=true;
 $('transcript-heading').textContent='Transcript · '+AtlantaUX.count(d.transcript.length,'segment')+' · '+AtlantaUX.count(new Set(d.transcript.map(v=>v.speaker).filter(Boolean)).size,'participant');
 if(!d.transcript.length){target.append(emptyNote(d.live?.segments?.length?'Your saved live draft is below. The final transcript appears after processing.':busy?'Your transcript will appear here when processing finishes.':'Your recording is saved. Choose Transcribe to turn it into text.'));return;}
 $('edit-transcript').disabled=busy||!d.transcript.length;$('edit-transcript').textContent=transcriptEditing?'Cancel editing':'Edit transcript';$('edit-transcript').setAttribute('aria-pressed',String(transcriptEditing));$('save-transcript').hidden=!transcriptEditing;
 const toolbar=el('div','transcript-view-actions');if(transcriptEditing)target.append(toolbar);
 if(transcriptEditing){
 toolbar.append(el('p','hint','After saving, choose whether to update notes and tasks from the corrected text.'));
 d.transcript.forEach((s,index)=>{ const row=el('div','segment');row.dataset.segmentIndex=String(index);const seek=listenButton(d.id,s.start); const content=el('div');const speaker=el('input','speaker');speaker.placeholder='Speaker (optional)';speaker.value=s.speaker||'';speaker.setAttribute('list','known-speakers');speaker.setAttribute('aria-label','Speaker for segment '+(index+1));speaker.disabled=busy;const badge=el('span');const annotate=()=>{speakerBadge(badge,speaker.value);row.classList.toggle('known-speaker',!!knownSpeaker(speaker.value));};annotate();speaker.oninput=()=>{s.speaker=speaker.value.trim()||null;annotate();renderSpeakerLegend();markTranscript();};const who=el('div','speaker-line');who.append(badge,speaker);const original=d.transcript_raw?.length===d.transcript.length?d.transcript_raw[index]:null;if(original&&original.text!==s.text){row.classList.add('ai-corrected');const restore=btn('quiet restore-original');restore.append(icon('restore'),document.createTextNode('AI'));restore.title='Restore original transcription: '+original.text;restore.setAttribute('aria-label','Restore original transcription for segment '+(index+1));restore.disabled=busy;restore.onclick=()=>{s.text=original.text;text.value=original.text;row.classList.remove('ai-corrected');restore.remove();markTranscript();};who.append(restore);}const text=el('textarea');text.value=s.text;text.setAttribute('aria-label','Transcript segment '+(index+1));text.disabled=busy;text.rows=Math.max(2,Math.ceil(s.text.length/85));text.oninput=()=>{s.text=text.value;markTranscript();};content.append(who,text,transcriptSegmentTools(d,index,text,busy));row.append(seek,content);$('transcript').append(row); });
 return;
 }
 for(const turn of transcriptTurns(d.transcript)) {
  const row=el('article','dialogue-turn'+(!turn.speaker||/^SPEAKER[ _-]?\d+$/i.test(turn.speaker)?' uncertain':'')),header=el('div','dialogue-heading'),first=turn.segments[0].segment;
  const seek=listenButton(d.id,first.start,{className:'quiet dialogue-time'});
  const speakerChoice=btn('quiet dialogue-speaker',participantLabel(turn.speaker));speakerChoice.disabled=busy;speakerChoice.title='Change speaker for this turn only';speakerChoice.setAttribute('aria-label','Change speaker at '+time(first.start));
  speakerChoice.onclick=()=>openTurnSpeakerEditor(d,turn,row,speakerChoice,busy);
  header.append(speakerBadge(el('span'),turn.speaker),speakerChoice,seek);
  const text=el('p','dialogue-text');
  for(const {segment,index} of turn.segments){if(text.childNodes.length)text.append(document.createTextNode(' '));const fragment=el('span','transcript-fragment',segment.text.trim());fragment.dataset.segmentIndex=String(index);text.append(fragment);}
  row.append(header,text);target.append(row);
 }
}

function transcriptSegmentTools(d,index,textarea,busy){
 const tools=el('div','segment-tools'),split=el('button','quiet small-action','Split at cursor'),merge=el('button','quiet small-action','Merge with next');split.type=merge.type='button';split.disabled=busy;merge.disabled=busy||index>=d.transcript.length-1;
 split.onclick=()=>perform(async()=>{const segment=d.transcript[index],cursor=textarea.selectionStart;if(cursor<=0||cursor>=segment.text.length)throw new Error('Place the cursor inside the text before splitting.');const value=await ask('Exact audio boundary for the split (HH:MM:SS). Listen first; the time must be inside this segment.',{ok:'Split segment',value:time((segment.start+segment.end)/2)});if(value===null)return;if(!/^\d{2,}:\d{2}:\d{2}$/.test(value)||value.split(':').slice(1).some(n=>Number(n)>59))throw new Error('Use HH:MM:SS.');const at=stampSeconds(value);if(!(segment.start<at&&at<segment.end))throw new Error('Choose a time strictly inside the segment.');d.transcript.splice(index,1,{...segment,end:at,text:segment.text.slice(0,cursor).trim()},{...segment,start:at,text:segment.text.slice(cursor).trim()});markTranscript();renderTranscript(d,busy);});
 merge.onclick=()=>perform(async()=>{const first=d.transcript[index],next=d.transcript[index+1];if(!next)return;if(first.speaker!==next.speaker&&!(await ask('Merge both segments under '+(first.speaker||'Unidentified speaker')+'? Confirm the voice by listening first.',{ok:'Merge and keep this speaker'})))return;d.transcript.splice(index,2,{...first,end:Math.max(first.end,next.end),text:first.text.trim()+' '+next.text.trim()});markTranscript();renderTranscript(d,busy);});
 tools.append(split,merge);return tools;
}
function renderDetail() {
 syncReviewPanel();
 $('detail-refresh-notice').hidden=!detailChangedWhileEditing;
 const d=detail, busy=['starting','recording','paused','stopping','processing'].includes(d.status);
 $('meeting-add-task').disabled=busy;
 $('detail-title').textContent=d.title;$('detail-title').title=d.title; $('detail-date').textContent=date(d.created)+' · '+(d.mode==='online'?'Online meeting':d.mode==='imported'?'Imported transcript':d.mode==='audio'?'Imported audio':'In-person meeting')+(d.duration?' · '+shortDuration(d.duration):''); $('detail-status').textContent=d.status==='ready'?(d.notes_need_refresh?'Notes need update':d.minutes_proposal?'Review notes':d.minutes?'Ready for review':'Transcript ready'):statusNames[d.status]||d.status;
 const titleMessages={pending:'AI title pending',generating:'Generating AI title…',generated:'AI-generated title',waiting:'AI title waiting for a transcript',manual:'',error:'AI title could not be generated'};
 const titleNote=d.title_status==='generated'&&!d.title_error;if(titleNote)$('detail-date').textContent+=' · AI title';
 $('title-status').textContent=titleNote?'':(titleMessages[d.title_status]||'')+(d.title_error?' · '+d.title_error:'');$('title-status').hidden=!$('title-status').textContent;
 const sync=d.calendar_sync; $('calendar-status').hidden=!sync;$('calendar-status').replaceChildren();
 if(sync){$('calendar-status').append(el('span','',sync.status==='synced'?'Saved in Google Calendar':sync.status==='error'?'Calendar sync needs attention: '+sync.error:'Calendar sync pending…'));if(sync.status==='synced'&&sync.html_link){const url=new URL(sync.html_link);if(url.protocol==='https:'&&['www.google.com','calendar.google.com'].includes(url.hostname)){const link=el('a','',' Open event ');link.append(icon('external'));link.href=url.href;link.target='_blank';link.rel='noopener noreferrer';$('calendar-status').append(link);}}}
 renderScope(d);
 $('generate-title').disabled=busy||d.title_status==='generating'||(!d.transcript.length&&!d.live?.segments?.length);
 $('sync-calendar').disabled=busy||(!sync&&!state.settings.calendar_enabled);
 $('sync-calendar').textContent=sync?.status==='synced'?'Update calendar event':'Sync to Google Calendar';
 $('followup-email').hidden=!d.minutes;$('followup-email').disabled=busy||!!d.notes_need_refresh;
 $('followup-email').title=d.notes_need_refresh?'Update or review the notes first: they changed after your review.':'';
 // An open draft keeps its text; it only says that its source changed.
 if($('followup-dialog').open&&followupEmailMeeting===d.id&&d.notes_need_refresh)followupEmailStatus('The notes changed after this draft was made. Update the notes, then check this text before you save it.',true);
 // The status badge already says Ready; the bar is only for progress and extra advice.
 $('cancel-processing').hidden=d.status!=='processing';
 $('cancel-processing').disabled=!!d.processing_cancel_requested;
 $('cancel-processing').textContent=d.processing_cancel_requested?'Cancelling…':'Cancel processing';
 renderProcessingTime();
 const gaps=$('capture-gaps');gaps.replaceChildren();gaps.hidden=!d.input_gaps?.length;
 if(d.input_gaps?.length){gaps.append(el('p','','Microphone audio is missing in these intervals:'));for(const gap of d.input_gaps){const seek=el('button','quiet',time(gap.start)+'–'+time(gap.end??d.duration)+' · Play');seek.onclick=()=>{$('audio').currentTime=gap.start;$('audio').play().catch(e=>error(e.message));};gaps.append(seek);}}
 $('job-progress').textContent=d.progress||''; $('job-progress').hidden=!busy||!d.progress||d.progress===statusNames[d.status]||['Imported','Recording saved','Audio imported'].includes(d.progress); $('detail-error').hidden=!d.error; $('detail-error').textContent=d.error||'';
 const prepared=d.files.includes('transcription.wav'), selector=$('audio-source'), sameMeeting=$('audio').dataset.meeting===d.id;
 const source=prepared&&sameMeeting&&selector.value==='transcription.wav'?'transcription.wav':'recording.wav';
 selector.replaceChildren(option('Original recording','recording.wav'),...(prepared?[option('Prepared for transcription','transcription.wav')]:[]));selector.value=source;
 selector.hidden=$('audio-source-label').hidden=!prepared;$('audio').dataset.meeting=d.id;
 const audioURL='/files/'+d.id+'/'+source;
 if(d.files.includes('recording.wav')) { if(!$('audio').src.endsWith(audioURL)) $('audio').src=audioURL; $('audio').hidden=false; $('audio-unavailable').hidden=true; }
 else { $('audio').removeAttribute('src'); $('audio').hidden=true; $('audio-unavailable').hidden=false; }
 $('playback').hidden=d.mode==='imported';
 $('exports').replaceChildren(); $('files-menu').hidden=!d.files.length;
 if(d.minutes){ const row=el('div','file-row'), open=el('button','view-file type-export',meetingType(d).export+' …'); open.type='button'; open.title='The result in the format of this meeting type'; open.onclick=()=>perform(()=>openTypeExport(d.id)); row.append(open); $('exports').append(row); } for(const name of d.files) { const row=el('div','file-row'), a=el('a','');a.append(icon('download'),document.createTextNode(name==='recording.wav'?'Audio (WAV)':name)); a.href='/files/'+d.id+'/'+name; a.download=name; row.append(a); if(name.endsWith('.md')) { const v=el('button','view-file','View'); v.type='button'; v.setAttribute('aria-label','View '+name); v.onclick=()=>perform(()=>openViewer(d.id,name)); row.append(v); } $('exports').append(row); }
 for(const id of ['process','summarize','recover','edit-title','delete-meeting']) $(id).disabled=busy;
 $('correct').disabled=busy||!d.transcript.length; $('correct').hidden=state.settings.transcript_correction==='none'&&!d.transcript_raw;
 const preparation=d.transcript_metadata?.audio_preparation;
 $('audio-preparation-status').hidden=preparation?.profile!=='light';
 $('audio-preparation-status').textContent=preparation?.source==='recording.wav'&&d.mode==='online'?'Light audio preparation used the mixed recording because separate raw tracks were unavailable.':'Transcribed with Light audio preparation. Playback keeps the original unless you select Prepared.';
 const fix=d.transcript_metadata?.correction;
 $('correction-status').hidden=!fix&&!d.correction_error;
 $('correction-status').textContent=d.correction_error?'AI correction failed · the original transcript is shown. '+d.correction_error:fix?'AI corrected '+fix.changed+(fix.changed===1?' segment':' segments')+(fix.rejected?' · '+fix.rejected+' larger changes were refused':'')+'. Marked segments show the original transcription; the restore button brings it back.':'';
 $('correction-status').classList.toggle('warning',!!d.correction_error);
 $('recover').hidden=d.mode==='imported'||d.mode==='audio'||!!d.files.includes('recording.wav')&&!['interrupted','error'].includes(d.status);$('process').hidden=d.mode==='imported';
 $('summarize').disabled=busy||!d.transcript.length; $('summarize').textContent=d.notes_need_refresh||d.notes_refresh_error?'Update notes & tasks':d.minutes?'Generate new AI notes':'Generate notes';
 $('process').textContent=d.transcript.length?'Transcribe again':'Transcribe';
 placeActions(d);
 $('timestamp-note').hidden=!transcriptEditing;
 $('timestamp-note').textContent=d.transcript_metadata?.timestamps==='approximate chunk boundaries'?'Cloud timestamps mark approximate audio chunks. Click a time to listen.':'Consecutive speech is grouped by participant. Click a time to listen; choose Edit transcript to make corrections.';
 renderTranscript(d,busy);
 renderSpeakerLegend();renderSpeakerReview(busy);renderAttention(busy);
 $('detail-markers').hidden=!d.markers?.length; $('detail-markers').replaceChildren();
 if(d.markers?.length){$('detail-markers').append(el('h3','','Moments you marked'));const list=el('div','marker-list');renderMarkerList(list,d.markers,true);$('detail-markers').append(list);}
 $('save-transcript').disabled=!dirtyTranscript||busy;$('save-transcript').textContent='Save corrections';renderTranscriptRefresh(busy); renderSavedDraft(d); renderNotes(busy); renderTeamAnalysis(busy); renderMeetingAnalytics(busy);
}
const ACTIONS=['process','correct','summarize','recover','edit-title','generate-title','sync-calendar','followup-email','delete-meeting'];
// One clear next step is a button; the other actions wait in the More menu.
function placeActions(d) {
 const action=$('review-primary');action.hidden=!d.minutes_proposal&&(!d.minutes||d.notes_need_refresh||d.notes_refresh_error);action.textContent=d.minutes_proposal?'Review updated notes':'Review decisions and tasks';action.disabled=d.status==='processing';
 if(!d.minutes_proposal&&meetingTab==='review')action.hidden=true;
 const audio=d.files.includes('recording.wav');
 const primary=d.minutes_proposal?null:!$('recover').hidden&&!audio?'recover':!$('process').hidden&&!d.transcript.length?'process':d.transcript.length&&(d.notes_need_refresh||d.notes_refresh_error)?'summarize':d.transcript.length&&!d.minutes?'summarize':null;
 for(const id of ACTIONS) { const button=$(id); if(id===primary){button.className=action.hidden?'primary':'secondary';$('primary-action').append(button);} else {button.className=id==='delete-meeting'?'danger-text':'';$('more-actions').append(button);} }
}
// Floating menus: the "…" menus of meetings, rows, sources, projects and tasks. One menu is open at a time.
// A click outside, a choice or Escape closes it; Escape returns the focus to its trigger.
// Accordions (Filters, Participants, Sources, Audio options) are other details elements and stay as they are.
const FLOATING_MENUS='details.menu,details.task-more';
function openMenus(){return [...document.querySelectorAll(FLOATING_MENUS)].filter(menu=>menu.open);}
function closeMenus(except) { for(const menu of openMenus()) if(menu!==except&&!(except&&menu.contains(except))) menu.open=false; }
document.addEventListener('click',event=>{closeMenus(event.target.closest?.(FLOATING_MENUS));if(event.target.closest?.('.menu-items button,.menu-items a,.task-more>.tracked-actions>button'))closeMenus();});
document.addEventListener('keydown',event=>{
 if(event.key!=='Escape')return;const open=openMenus();if(!open.length)return;
 // The menu closes first; the dialog around it stays open until the next Escape.
 event.preventDefault();const last=open.at(-1);closeMenus();last.querySelector(':scope>summary')?.focus();
});
// A menu opens below its trigger. Without room below it opens above, and it moves left or right to stay in the window.
function placeMenu(menu){
 const pop=[...menu.children].find(node=>node.matches('.menu-items,.tracked-actions'));if(!pop)return;
 pop.style.top=pop.style.bottom=pop.style.transform=pop.style.maxHeight=pop.style.overflowY='';
 if(getComputedStyle(pop).position!=='absolute')return;
 const edge=8,trigger=menu.querySelector(':scope>summary').getBoundingClientRect();let box=pop.getBoundingClientRect();
 if(box.bottom>innerHeight-edge){
  const above=trigger.top-edge-6,below=innerHeight-edge-trigger.bottom-6;
  if(above>below){pop.style.top='auto';pop.style.bottom='calc(100% + 6px)';if(box.height>above){pop.style.maxHeight=Math.floor(above)+'px';pop.style.overflowY='auto';}}
  else{pop.style.maxHeight=Math.floor(Math.max(below,120))+'px';pop.style.overflowY='auto';}
 }
 box=pop.getBoundingClientRect();
 const shift=box.right>innerWidth-edge?innerWidth-edge-box.right:box.left<edge?edge-box.left:0;
 if(shift)pop.style.transform='translateX('+Math.round(shift)+'px)';
}
document.addEventListener('toggle',event=>{const menu=event.target;if(!menu.matches?.(FLOATING_MENUS)||!menu.open)return;closeMenus(menu);placeMenu(menu);},true);
if(typeof window!=='undefined'&&typeof window.addEventListener==='function')window.addEventListener('resize',()=>{for(const menu of openMenus())placeMenu(menu);});
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
 const button=btn('listen '+className),key=meetingId+'@'+seconds+'@'+(until??'');
 const text=label??time(seconds);
 const render=playing=>{button.classList.toggle('playing',playing);button.setAttribute('aria-pressed',String(playing));
  button.replaceChildren(el('span','listen-icon',playing?'■':'▶'),...(text?[el('span','listen-label',text)]:[]));
  button.setAttribute('aria-label',(playing?'Stop playback at ':'Play from ')+time(seconds));button.title=title||(playing?'Stop':'Play from '+time(seconds));};
 render(false);
 if(!meetingId||!hasRecording(meetingId)){button.disabled=true;button.title='This meeting has no recording';if(!text)button.hidden=true;return button;}
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
 const box=el('span','stamp-group'),show=btn('quiet stamp-show');show.append(icon('jump'));show.title='Show '+stamp+' in the transcript';show.setAttribute('aria-label',show.title);show.onclick=()=>showMoment(stamp);
 const segment=segmentAt(stamp);box.append(listenButton(detail.id,segment?segment.start:stampSeconds(stamp),{label:stamp,until:segment?.end,className:'stamp'}),show);return box;
}
// AI notes cite moments as (00:29:46); make them links to the transcript.
function linkedText(target,text) { text.split(/\(?\b(\d{2}:\d{2}:\d{2})\b\)?/).forEach((part,i)=>target.append(i%2?stampButton(part):document.createTextNode(part))); return target; }
const FIELD_TITLES={summary:'Summary',decisions:'Decisions',updates:'Updates on work in progress',next_steps:'Agreed next steps',needs_decision:'Questions for your decision',tasks:'Tasks',open_questions:'Unresolved questions',observations:'Private observations',discussion:'Discussion'};
// A discussion topic holds its points, so it is no list of statements like the other fields.
const ITEM_FIELDS=Object.keys(FIELD_TITLES).filter(field=>!['tasks','discussion'].includes(field));
// Notes cite a segment's start in whole seconds, and the previous segment often still runs then.
// So a segment that starts in that second wins; more of them form one span.
function segmentAt(stamp) {
 const seconds=stampSeconds(stamp); let rows=detail.transcript.filter(s=>Math.floor(s.start)===seconds);
 if(!rows.length) rows=detail.transcript.filter(s=>s.start<=seconds&&seconds<s.end).slice(0,1);
 if(!rows.length) return null;
 const speakers=new Set(rows.map(s=>s.speaker||''));
 return {start:rows[0].start,end:rows.at(-1).end,text:rows.map(s=>s.text.trim()).join(' '),speaker:speakers.size===1?rows[0].speaker:''};
}
function sourceBlock(stamp) {
 const box=el('div','note-source');
 if(!stamp) { box.append(el('span','no-source','No source moment')); return box; }
 const segment=segmentAt(stamp);
 if(detail.files.includes('recording.wav')){
  // Play only the cited segment and stay in the notes.
  box.append(listenButton(detail.id,segment?segment.start:stampSeconds(stamp),{label:stamp,until:segment?.end,className:'quiet stamp',title:'Play this moment'}));
 }else{const show=btn('quiet stamp',stamp);show.title='Show this moment in the transcript';show.onclick=()=>showMoment(stamp);box.append(show);}
 if(segment) { const quote=el('button','quote',(segment.speaker?segment.speaker+': ':'')+'“'+segment.text+'”'); quote.type='button'; quote.title='Show in the transcript'; quote.onclick=()=>showMoment(stamp); box.append(quote); }
 return box;
}
let notesBase=null;
const NOTE_FIELDS=['summary','decisions','updates','next_steps','needs_decision','tasks','open_questions','observations','discussion'];
// Send only the sections that changed, with how they looked before. The server refuses a section that
// someone else changed meanwhile, so an older copy never undoes newer changes.
async function saveMinutes(base) {
 const fields={}, before={};
 for(const field of NOTE_FIELDS) if(JSON.stringify(detail.minutes[field]||[])!==JSON.stringify(base[field]||[])){fields[field]=detail.minutes[field]||[];before[field]=base[field]||[];}
 if(Object.keys(fields).length) detail=await api('/api/meetings/'+selected+'/edit',{minutes_fields:fields,minutes_base:before,minutes_revision:detail.minutes_revision});
 dirtyNotes=false;detailChangedWhileEditing=false; notesBase=null; lastFingerprint=JSON.stringify(detail); renderDetail();
}
function reviewBadge(item,busy) {
 const checked=item.review==='verified', badge=el('button','review-badge'+(checked?' verified':''),checked?'✓ Checked':'AI suggestion');
 badge.type='button'; badge.disabled=busy||notesEditing;
 badge.title=checked?'You checked this against the source. Click to undo.':'Not checked yet. Click after you check it against the source.';
 badge.onclick=()=>perform(async()=>{const base=structuredClone(detail.minutes),previous=item.review;item.review=checked?'ai':'verified';try{await saveMinutes(base);}catch(e){item.review=previous;throw e;}});
 return badge;
}
// Edit or delete one statement of the saved notes without the full notes editor.
function noteButtons(items,index,textNode,busy,title){
 const item=items[index],edit=el('button','quiet small-action','Edit'),remove=el('button','quiet small-action danger-text','Delete');edit.type=remove.type='button';edit.disabled=remove.disabled=busy||notesEditing;
 const commit=async change=>{const base=structuredClone(detail.minutes);change();try{await saveMinutes(base);}catch(e){detail.minutes=base;renderDetail();throw e;}};
 // A person wrote the new wording, so it counts as checked.
 edit.onclick=()=>inlineEdit(textNode,item.text,value=>commit(()=>{item.text=value;item.review='verified';}),'Edit '+title);
 remove.onclick=()=>perform(async()=>{if(!(await ask('Delete this statement from '+title+'?\n\n'+item.text,{ok:'Delete',danger:true})))return;await commit(()=>items.splice(index,1));toast('Deleted');});
 return [edit,rowMenu('More actions for this statement',remove)];
}
// A decision keeps why it was taken, an open question what is known about it (2026-11-13). Null means that the
// meeting gave none; notes from before these fields have no key and show nothing.
const EXPLANATIONS={decisions:'rationale',open_questions:'context'};
function noteExplanation(field,item){
 const name=EXPLANATIONS[field];if(!name||!(name in item))return null;
 const text=String(item[name]||'').trim();
 if(!text)return name==='rationale'?el('p','note-explanation empty','No reason was given in the meeting.'):null;
 return linkedText(el('p','note-explanation'),text);
}
function noteSection(minutes,field,title,busy,hint) {
 const section=el('section','note-section'+(field==='observations'?' private-notes':''));
 section.append(el('h3','',title)); if(hint) section.append(el('p','hint',hint));
 const items=minutes[field]=minutes[field]||[];
 if(!notesEditing) {
  if(!items.length) section.append(el('p','empty-note','Nothing recorded.'));
  else { const list=el('ul','note-list');const entries=field==='decisions'?AtlantaTasks.meetingGroups(items).map(({task,index,mentions})=>({item:task,index,mentions})):items.map((item,index)=>({item,index,mentions:[item]})); entries.forEach(({item,index,mentions})=>{ const li=el('li','note-item'+(item.review==='verified'?' verified':'')), meta=el('div','note-meta'), decision=field==='decisions'&&state.settings?.meeting_task_ai&&detail.items?.[item.item_id];
   if(decision) meta.append(decisionBadge(decision));
   const noteText=linkedText(el('p','note-text'),decision?.text||item.text),actions=decision?editDeleteButtons(decision,noteText):noteButtons(items,index,noteText,busy,title);for(const action of actions){action.disabled=busy;for(const inner of action.querySelectorAll?.('button')||[])inner.disabled=busy||inner.disabled;}meta.append(decision?'':reviewBadge(item,busy),mentions.length===1?sourceBlock(item.evidence_timestamp):'',...actions);
   if(decision&&decisionState(decision).action){const accept=btn('primary small-action',decisionState(decision).action);accept.disabled=busy;accept.onclick=()=>perform(()=>changeItem(decision,{status:'accepted'}));meta.append(accept);} li.append(noteText);const why=noteExplanation(field,item);if(why)li.append(why);li.append(meta);if(mentions.length>1){const evidence=el('details','item-history meeting-task-evidence');evidence.append(el('summary','',mentions.length+' mentions in this meeting'));for(const mention of mentions)evidence.append(el('p','',mention.text),sourceBlock(mention.evidence_timestamp));li.append(evidence);}
   if(decision&&decision.links.length>1){const also=meetingChips(decision,detail.item_meetings,detail.id);also.prepend(el('span','hint','Also in'));li.append(also);}
   if(field==='decisions'&&state.settings?.meeting_task_ai&&item.link&&!item.item_id) li.append(linkCard({meeting_id:detail.id,kind:'decision',field,index,mention:item,text:item.text,candidates:item.link.candidates},detail.item_meetings,detail.items||{}));
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
  bottom.append(el('label','','Source'),select,remove); row.append(area);
  const name=EXPLANATIONS[field];if(name){const label=el('label','note-explanation-editor'),why=el('textarea');why.value=item[name]||'';why.rows=2;why.disabled=busy;why.placeholder=name==='rationale'?'Why it was decided, and how people reacted':'Who asked, what is known, what is unclear';why.oninput=()=>{if(why.value.trim())item[name]=why.value;else delete item[name];markNotes();};label.append(el('span','',name==='rationale'?'Reason':'Context'),why);row.append(label);}
  row.append(bottom); list.append(row); }); }
 draw();
 // A statement that you write yourself needs no AI check.
 const add=el('button','secondary','＋ Add'); add.type='button'; add.disabled=busy; add.onclick=()=>{items.push({text:'',evidence_timestamp:null,review:'verified'});markNotes();draw();list.lastElementChild?.querySelector('textarea').focus();};
 section.append(list,add); return section;
}
// Old one-line tasks: the AI writes a title, the text becomes the description, and only the titles a person keeps are saved.
// The same rule as the server: accepted, visible tasks without a description. Proposals and hidden tasks are never sent.
function untitledTask(item){return item.kind==='task'&&item.acceptance_state!=='proposed'&&!item.dismissed&&!String(item.details||'').trim()&&!!String(item.text||'').trim();}
let taskTitleRun=null,taskTitlePreview=null;
async function openTaskTitles(){
 const preview=await api('/api/task-titles/preview',{});taskTitlePreview=preview;taskTitleRun=null;
 $('task-titles-list').replaceChildren();$('task-titles-status').hidden=true;$('task-titles-apply').hidden=$('task-titles-stop').hidden=true;
 $('task-titles-target').textContent=!preview.count?'Every task already has a description.':preview.ai_available?'Atlanta sends the text of '+AtlantaUX.count(preview.count,'task')+' ('+preview.characters+' characters) to '+preview.target.model+(preview.target.base_url?' at '+preview.target.base_url:'')+'. Proposals and hidden tasks are not sent.':preview.ai_unavailable_reason;
 $('task-titles-generate').hidden=false;$('task-titles-generate').disabled=!preview.ai_available||!preview.count;
 editorDirty.clear('dialog:task-titles-dialog');$('task-titles-dialog').showModal();
}
async function pollTaskTitles(id){
 while(taskTitleRun===id&&$('task-titles-dialog').open){
  const job=await api('/api/task-titles/status?id='+encodeURIComponent(id));if(taskTitleRun!==id)return;
  $('task-titles-status').hidden=false;$('task-titles-status').textContent=job.error?job.status+' · '+job.error:job.status;
  if(!job.running){taskTitleRun=null;$('task-titles-stop').hidden=true;if(job.proposals?.length)renderTaskTitles(job.proposals);else{$('task-titles-generate').hidden=false;if(!job.error&&job.status!=='Cancelled')$('task-titles-status').textContent='The AI returned no new titles.';}return;}
  await new Promise(resolve=>setTimeout(resolve,1500));
 }
}
function renderTaskTitles(rows){
 const list=$('task-titles-list');list.replaceChildren(el('p','hint',AtlantaUX.count(rows.length,'title')+' to review. Edit a title, or clear its check box to keep the task as it is.'));
 for(const row of rows){
  const line=el('label','task-title-row'),check=el('input'),title=el('input'),fields=el('div','task-title-fields');
  check.type='checkbox';check.checked=true;check.setAttribute('aria-label','Apply the title for: '+row.text);
  title.value=row.title;title.maxLength=200;title.setAttribute('aria-label','Title for: '+row.text);title.oninput=()=>{check.checked=!!title.value.trim();};
  fields.append(title,el('p','task-description',row.text));line.append(check,fields);line.taskTitle={row,check,title};list.append(line);
 }
 $('task-titles-apply').hidden=false;
}
$('task-titles-open').onclick=()=>perform(openTaskTitles);
$('task-titles-generate').onclick=()=>perform(async()=>{const job=await api('/api/task-titles/start',{approved:true,preview_token:taskTitlePreview.preview_token});taskTitleRun=job.id;$('task-titles-generate').hidden=true;$('task-titles-stop').hidden=false;pollTaskTitles(job.id);});
$('task-titles-stop').onclick=()=>perform(async()=>{if(taskTitleRun)await api('/api/task-titles/cancel',{id:taskTitleRun});});
$('task-titles-close').onclick=()=>$('task-titles-dialog').close();
$('task-titles-dialog').addEventListener('close',()=>{if(taskTitleRun)api('/api/task-titles/cancel',{id:taskTitleRun}).catch(()=>{});taskTitleRun=null;});
$('task-titles-apply').onclick=()=>perform(async()=>{
 const changes=[...$('task-titles-list').querySelectorAll('.task-title-row')].map(line=>line.taskTitle).filter(t=>t.check.checked&&t.title.value.trim()).map(t=>({id:t.row.id,revision:t.row.revision,text:t.row.text,title:t.title.value.trim()}));
 if(!changes.length){toast('Choose at least one title');return;}
 const result=await api('/api/task-titles/apply',{changes});
 editorDirty.clear('dialog:task-titles-dialog');$('task-titles-dialog').close();await refreshAfterItemChange();
 toast(AtlantaUX.count(result.applied,'task')+' updated'+(result.skipped?' · '+result.skipped+' changed meanwhile and stayed as they were':''));
});
function changeText(field,item) { return field==='tasks'?[item.task,item.details,item.owner,item.deadline&&'said: '+item.deadline,item.due_date&&date(item.due_date)].filter(Boolean).join(' · '):field==='discussion'?item.topic+': '+item.points.map(point=>point.text).join(' · '):[item.text,item.rationale&&'Reason: '+item.rationale,item.context&&'Context: '+item.context].filter(Boolean).join(' · '); }
async function reviewNotes(action,accept) {
 detail=await api('/api/meetings/'+selected+'/notes-review',{action,accept,revision:detail.minutes_proposal.revision});
 lastFingerprint=JSON.stringify(detail); if($('review-dialog').open) $('review-dialog').close(); renderDetail();
}
function consolidationProof(audit){
 if(audit.status==='failed'){const note=el('p','notice warning consolidation-failed','Some statements may appear twice. The AI could not merge the repeated statements of '+AtlantaUX.count(audit.parts||0,'part')+' of this long meeting. Choose Generate new AI notes to try again; finished parts are reused.');
  // The technical reason helps support, not the reader of the notes.
  if(audit.error)note.title='Technical reason: '+audit.error;return note;}
 const box=el('details','consolidation-proof'),groups=Object.values(audit.groups||{}).filter(group=>(group.members||[]).length>1);
 box.append(el('summary','','Consolidation evidence · '+(audit.merged||0)+((audit.merged||0)===1?' repeated statement grouped':' repeated statements grouped')));
 box.append(el('p','hint','AI grouped extracted statements. Review the original wording and moments below; grouping does not confirm a task or decision.'));
 const candidates=new Map((audit.candidates||[]).map(fact=>[fact.id,fact]));
 for(const group of groups){const row=el('section','consolidation-group');row.append(el('strong','',FIELD_TITLES[group.field]||group.field));
  for(const id of group.members||[]){const fact=candidates.get(id);if(!fact)continue;const item=el('div','consolidation-source'),value=fact.value||{};item.append(el('span','',value.task||value.text||''));
   if(value.owner)item.append(el('span','hint',' · '+value.owner));if(value.evidence_timestamp)item.append(stampButton(value.evidence_timestamp));
   const quotes=el('details');quotes.append(el('summary','','Original transcript'));for(const evidence of fact.evidence||[])quotes.append(el('blockquote','',evidence.text));item.append(quotes);row.append(item);
  }box.append(row);
 }
 if(audit.rejected?.length)box.append(el('p','notice',audit.rejected.length+' proposed merges were kept separate because their details differ. Review tasks, owners, dates and environments.'));
 return box;
}
function openReview() {
 const proposal=detail.minutes_proposal, body=$('review-body'), choices=new Map(); body.replaceChildren(); clearError();
 if(proposal.consolidation)body.append(consolidationProof(proposal.consolidation));
 for(const field of Object.keys(FIELD_TITLES)) {
  const list=proposal.changes.filter(change=>change.field===field); if(!list.length) continue;
  const section=el('section','review-section'); section.append(el('h3','',meetingType(detail).sections.find(s=>s.key===field)?.title||FIELD_TITLES[field]));
  for(const change of list) {
   const row=el('label','review-change '+change.kind), box=el('input'), main=el('div'), checked=change.current?.review==='verified';
   // Additions and AI-only edits are preselected; edits of checked statements are not. A removal is preselected only
   // for an unchecked AI statement that is no task or decision: otherwise a reworded statement stayed next to the new one.
   // Removing a task or decision can delete its item, so a person chooses it.
   box.type='checkbox'; box.checked=change.kind==='added'||['changed','source'].includes(change.kind)&&!checked||change.kind==='removed'&&!checked&&!['tasks','decisions'].includes(field); choices.set(change.id,box);
   main.append(el('span','change-kind',{added:'New',changed:'Changed',source:'Source changed',removed:'Not in the new notes'}[change.kind]+(checked?' · you checked the saved version':'')));
   if(change.kind==='source'){
    // The same words with another moment or quote: show the old and the new proof.
    main.append(el('p','',changeText(field,change.current)));
    const proof=item=>[item.evidence_timestamp,item.quote&&'„'+item.quote+'“'].filter(Boolean).join(' · ')||'no source';
    main.append(el('del','',proof(change.current)),el('ins','',proof(change.proposed)));
   } else {
    if(change.current) main.append(el(change.kind==='removed'||change.kind==='changed'?'del':'p','',changeText(field,change.current)));
    if(change.proposed) main.append(el('ins','',changeText(field,change.proposed)));
   }
   const stamp=(change.proposed||change.current).evidence_timestamp; if(stamp) main.append(sourceBlock(stamp));
   row.append(box,main); section.append(row);
  }
  body.append(section);
 }
 $('review-apply').onclick=()=>perform(async()=>{await reviewNotes('apply',[...choices].filter(([,box])=>box.checked).map(([id])=>id));toast('Notes updated · the previous version is kept in versions/');});
 $('review-discard').onclick=()=>perform(async()=>{if(!(await ask('Discard the new AI notes? Your saved notes stay as they are.',{ok:'Discard',danger:true})))return;await reviewNotes('discard',[]);toast('New AI notes discarded');});
 for(const id of ['review-apply','review-discard'])protectDialogAction($('review-dialog'),$(id));
 $('review-dialog').showModal();
}
$('review-close').onclick=()=>$('review-dialog').close();
function transcriptRefreshBanner(busy) {
 const banner=el('div','notice proposal-banner'),button=btn('secondary','Update notes & tasks');button.disabled=busy||dirtyTranscript||dirtyNotes||itemEditing;
 banner.append(el('span','',detail.notes_refresh_error|| (busy?'Updating notes and tasks from the corrected transcript…':'The transcript changed. When you finish your corrections, update the notes and tasks.')));if(!busy)banner.append(button);
 button.onclick=()=>perform(async()=>{if(state.settings.summarizer==='none'){openSettings('notes');return;}await api('/api/meetings/'+detail.id+'/process',{action:'summarize'});await openMeeting(detail.id,true);});return banner;
}
function renderTranscriptRefresh(busy) {
 const target=$('transcript-refresh-status');target.replaceChildren();target.hidden=!(detail.minutes_proposal||detail.notes_need_refresh||detail.notes_refresh_error);
 if(!target.hidden)target.append(detail.minutes_proposal?proposalBanner(busy):transcriptRefreshBanner(busy));
}
function proposalBanner(busy) {
 const proposal=detail.minutes_proposal, count=proposal.changes.length, banner=el('div','notice proposal-banner');
 banner.append(el('span','',count?'New AI notes are ready · '+count+(count===1?' change':' changes')+' to review. Your saved notes have not changed.':'The new AI notes match your saved notes.'));
 const button=el('button','secondary',count?'Review changes':'Clear update'); button.type='button'; button.disabled=busy||notesEditing;
 button.onclick=count?openReview:()=>perform(()=>reviewNotes('discard',[]));
 banner.append(button); return banner;
}
function taskRow(task,index,busy,mentions=[task]) {
 // Since 2026-11-12 the AI stops at the notes unless Settings → AI turns meeting tasks on: a task line is text,
 // and the person makes the tasks they keep with Create task. Hidden AI proposals show as plain lines.
 const handMade=!state.settings?.meeting_task_ai;
 if(task.link&&!task.item_id&&!handMade){const box=el('div','link-card');box.append(el('p','link-text',task.task),el('p','hint','This may be an existing task. It waits in My Work → Inbox.'));const go=btn('secondary small-action','Open Inbox');go.onclick=()=>perform(openTaskInbox);box.append(go);return box;}
 // The persistent task holds the current state; the mention holds what this meeting said.
 const linked=detail.items?.[task.item_id], item=handMade&&linked?.acceptance_state==='proposed'?undefined:linked, current=item||{text:task.task,owner:task.owner,deadline:task.deadline,due_date:task.due_date,status:task.status};
 const today=state.task_summary?.today||new Date().toISOString().slice(0,10), [kind,label]=dueInfo(current,today);
 const row=el('div','tracked-task '+kind);
 const main=el('div','tracked-main'), meta=el('div','tracked-meta'), who=el('span','tracked-owner');
 who.append(avatar(current.owner||''),el('span','',current.owner||'No owner'));
 meta.append(item?workReviewBadge(item.review_state,item):handMade?'':reviewBadge(task,busy),who,el('span','due-label '+kind,current.due_date&&current.status!=='done'?label+' · '+date(current.due_date):label));
 if(current.deadline) meta.append(el('span','hint','Said: '+current.deadline));
 if(item&&!current.due_date&&current.deadline){const suggested=AtlantaTasks.suggestDueDate(current.deadline,(detail.created||'').slice(0,10));if(suggested){const applyDue=btn('secondary small-action','Set due '+date(suggested));applyDue.title='Apply the date said in the meeting as the due date';applyDue.onclick=()=>perform(()=>changeItem(item,{due_date:suggested}));meta.append(applyDue);}}
 const evidenceStamp=task.evidence_timestamp||item?.links?.find(l=>l.meeting_id===detail.id&&!l.detached)?.evidence_timestamp;if(evidenceStamp&&mentions.length===1)meta.append(sourceBlock(evidenceStamp));
 main.append(el('p','tracked-text',current.text||'Untitled task'));
 const description=String((item?item.details:task.details)||'').trim();if(description)main.append(taskDescription(description));
 if(item&&item.text!==task.task&&String(item.details||'').trim()!==task.task.trim()) main.append(el('p','hint said-here','Said here: '+task.task));
 main.append(meta);
 if(mentions.length>1){const evidence=el('details','item-history meeting-task-evidence');evidence.append(el('summary','',mentions.length+' mentions in this meeting'));for(const mention of mentions){const citation=el('div','meeting-task-citation');citation.append(el('p','',mention.task),sourceBlock(mention.evidence_timestamp));evidence.append(citation);}main.append(evidence);}
 if(item&&item.links.length>1) { const also=meetingChips(item,detail.item_meetings,detail.id); also.prepend(el('span','hint','Also in')); main.append(also,historyBlock(item,detail.item_meetings)); }
 // A task, for example a corrective action, becomes a GitHub draft or links to an existing issue.
 if(item){const edit=el('button','secondary small-action','Edit task'),remove=el('button','quiet small-action danger-text','Delete');edit.type=remove.type='button';edit.disabled=remove.disabled=busy;edit.onclick=()=>perform(()=>openTaskPanel(item.id));remove.onclick=()=>perform(()=>deleteItem(item));if(item.acceptance_state!=='proposed'){const actions=el('div','action-group task-item-actions');actions.append(doneButton(item,busy),edit,rowMenu('More actions for this task',remove));main.append(actions);}else main.append(edit);}
 if(item?.acceptance_state==='proposed'){const accept=el('button','primary small-action','Accept task'),skip=el('button','secondary small-action','Skip proposal');accept.type=skip.type='button';accept.disabled=skip.disabled=busy;accept.onclick=()=>perform(()=>changeItem(item,{acceptance_state:'accepted'}));skip.onclick=()=>perform(()=>changeWithUndo(item,{dismissed:true},'Proposal skipped: '+item.text,{dismissed:false}));const link=btn('secondary small-action','Link to existing task');link.disabled=busy;link.onclick=()=>perform(async()=>{const at=stampSeconds(task.evidence_timestamp||'00:00:00'),first=detail.transcript.findIndex(s=>s.start<=at&&s.end>=at);if(first<0)throw new Error('Select the supporting transcript passage to link this action.');await suggestTask(link,{provider:'meeting',id:detail.id,revision:detail.transcript_revision,first,last:first,link_only:true,proposal_item_id:item.id,proposal_item_revision:item.revision});});const actions=el('div','action-group proposal-actions');actions.append(accept,link,skip);main.append(actions);}
 if(item&&item.acceptance_state!=='proposed') main.append(githubActions({kind:'item',id:item.id},(detail.github_links||[]).filter(l=>l.resource.id===item.id)));
 if(!item&&handMade){const create=btn('secondary small-action','Create task');create.disabled=busy;create.title='Make this line of the notes a task in My Work';create.onclick=()=>perform(()=>openManualTask(detail.id,{text:task.task||'',details:task.details||'',owner:task.owner||'',due:task.due_date||'',mention:index}));const actions=el('div','action-group task-item-actions');actions.append(create);main.append(actions);}
 row.append(el('span'),main); return row;
}
function renderNotes(busy=false) {
 $('notes').replaceChildren();$('outcomes').replaceChildren();
 if(!detail.minutes||busy) notesEditing=false;
 for(const name of ['notes','outcomes']) { $('edit-'+name).hidden=notesEditing||!detail.minutes; $('edit-'+name).disabled=busy; $('save-'+name).hidden=$('cancel-'+name).hidden=!notesEditing; $('save-'+name).disabled=!dirtyNotes; }
 if(!detail.minutes) {
  const manual=Object.values(detail.items||{}).filter(i=>i.kind==='task'&&i.links.some(l=>l.meeting_id===detail.id&&l.manual_task));
  for(const item of manual)$('outcomes').append(taskRow({item_id:item.id,task:item.text,review:'verified'},0,busy));
 }
 if(!detail.minutes) { for(const id of ['notes','outcomes']) $(id).append(emptyNote('Generate meeting notes to see the decisions, tasks, unresolved questions and next steps.')); return; }
 const minutes=detail.minutes;
 if(!notesEditing)$('notes').append(notesOverview(minutes));
 if(detail.notes_consolidation&&!notesEditing&&!busy)$('notes').append(consolidationProof(detail.notes_consolidation));
 if(detail.minutes_proposal||detail.notes_need_refresh||detail.notes_refresh_error)for(const id of ['notes','outcomes']) $(id).append(detail.minutes_proposal?proposalBanner(busy):transcriptRefreshBanner(busy));
 $('notes').append(noteSection(minutes,'summary','Summary',busy),...(minutes.discussion?.length||notesEditing?[discussionSection(minutes,busy)]:[]),...typeSections(meetingType(detail),minutes).map(s=>noteSection(minutes,s.key,s.title,busy)),noteSection(minutes,'needs_decision','Questions for your decision',busy));
 $('outcomes').append(noteSection(minutes,'decisions','Decisions',busy));
 // Updates on work that started before the meeting. Older notes have none, so the section shows only when it has content.
 if(minutes.updates?.length||notesEditing)$('outcomes').append(noteSection(minutes,'updates','Updates on work in progress',busy,state.settings?.meeting_task_ai?'Progress, blockers and clarifications about work that started before this meeting. A later step suggests the task each one belongs to.':'Progress, blockers and clarifications about work that started before this meeting. Use them to update your tasks.'));
 const section=el('section','note-section');section.append(el('h3','',meetingType(detail).task_title));
 const taskList=el('div');section.append(taskList);
 function drawTasks() { taskList.replaceChildren(); AtlantaTasks.meetingGroups(minutes.tasks).forEach(({task,index,mentions})=>{
  if(detail.items?.[task.item_id]){taskList.append(taskRow(task,index,true,mentions));return;}
  // A task line of the notes is text (2026-11-12). Owner, dates and state belong to the task, set in its card.
  const box=el('div','task-editor');const text=el('textarea');text.value=task.task;text.disabled=busy;text.setAttribute('aria-label','Task '+(index+1));text.oninput=()=>{task.task=text.value;markNotes();};
  const remove=el('button','quiet','Remove');remove.type='button';remove.disabled=busy;remove.onclick=()=>{minutes.tasks.splice(index,1);markNotes();drawTasks();};
  const bottom=el('div','task-bottom');bottom.append(remove);box.append(text,bottom);taskList.append(box);}); }
 if(!notesEditing) {
  if(!minutes.tasks.length) taskList.append(el('p','empty-note','No tasks.'));
  // Who does what: the tasks by owner, as written meeting notes list them (2026-11-13). One owner needs no headings.
  const shown=AtlantaTasks.meetingGroups(minutes.tasks).filter(({task})=>!detail.items?.[task.item_id]?.dismissed);
  const owners=AtlantaTasks.ownerGroups(shown,({task})=>detail.items?.[task.item_id]?.owner||task.owner);
  for(const {owner,groups} of owners){
   if(owners.length>1){const head=el('h4','owner-group');head.append(avatar(owner||''),el('span','',owner||'No owner'),el('span','hint',AtlantaUX.count(groups.length,'task')));taskList.append(head);}
   for(const {task,index,mentions} of groups)taskList.append(taskRow(task,index,busy,mentions));
  }
 } else {
  if(minutes.tasks.some(task=>detail.items?.[task.item_id]))section.append(el('p','hint','Linked tasks are edited in their task card. Save or cancel these note edits first.'));
  // New tasks come from Add task or Create task, not from the notes editor: one way to add a task.
  drawTasks();
 }
 $('outcomes').append(section,noteSection(minutes,'open_questions','Unresolved questions',busy),noteSection(minutes,'next_steps','Agreed next steps',busy));
 $('notes').append(
  noteSection(minutes,'observations','Private observations',busy,'Only for you. AI interpretation of risks, unrealistic promises and disagreement. Check it against the recording. Not included in the Markdown export.'));
 if(!notesEditing)$('notes').append(el('p','hint notes-footer','AI notes from the recording of '+date(detail.created)+'. Each point links to the moment it comes from. Check it there before you rely on it.'));
}
// The details of the meeting by topic (2026-11-13): what was said that is no decision, task or question.
// A point has its source moment like any statement; a topic is only a heading.
function discussionSection(minutes,busy){
 const section=el('section','note-section discussion-notes'),head=el('h3','','Discussion');section.append(head);
 if(!notesEditing){
  const topics=minutes.discussion||[];head.append(el('span','hint section-count',AtlantaUX.count(topics.length,'topic')));
  for(const topic of topics){
   const box=el('section','discussion-topic'),title=el('h4');title.append(el('span','',topic.topic),el('span','hint',AtlantaUX.count(topic.points.length,'point')));
   const list=el('ul','discussion-points');
   topic.points.forEach((point,index)=>{const li=el('li','discussion-point'),text=linkedText(el('span','note-text'),point.text),actions=noteButtons(topic.points,index,text,busy,'Discussion');li.append(text);if(point.evidence_timestamp)li.append(stampButton(point.evidence_timestamp));for(const action of actions)action.disabled=busy||action.disabled;li.append(...actions);list.append(li);});
   box.append(title,list);section.append(box);
  }
  return section;
 }
 const topics=minutes.discussion=minutes.discussion||[],list=el('div','item-editors');
 // A point that you write yourself needs no AI check.
 const point=()=>({text:'',evidence_timestamp:null,review:'verified'});
 function draw(){list.replaceChildren();topics.forEach((topic,t)=>{
  const box=el('div','discussion-editor'),name=el('input'),top=el('div','task-bottom'),removeTopic=btn('quiet','Remove topic');
  name.value=topic.topic;name.disabled=removeTopic.disabled=busy;name.setAttribute('aria-label','Topic '+(t+1));name.oninput=()=>{topic.topic=name.value;markNotes();};
  removeTopic.onclick=()=>{topics.splice(t,1);markNotes();draw();};top.append(name,removeTopic);box.append(top);
  topic.points.forEach((item,p)=>{const row=el('div','task-editor'),area=el('textarea'),bottom=el('div','task-bottom'),remove=btn('quiet','Remove');area.value=item.text;area.rows=Math.max(1,Math.ceil(item.text.length/90));area.disabled=remove.disabled=busy;area.setAttribute('aria-label','Topic '+(t+1)+', point '+(p+1));area.oninput=()=>{item.text=area.value;markNotes();};remove.onclick=()=>{topic.points.splice(p,1);markNotes();draw();};bottom.append(remove);row.append(area,bottom);box.append(row);});
  const add=btn('secondary small-action','＋ Add point');add.disabled=busy;add.onclick=()=>{topic.points.push(point());markNotes();draw();list.children[t]?.querySelectorAll('textarea').forEach((area,i,all)=>{if(i===all.length-1)area.focus();});};box.append(add);list.append(box);});}
 draw();
 const addTopic=btn('secondary','＋ Add topic');addTopic.disabled=busy;addTopic.onclick=()=>{topics.push({topic:'',points:[point()]});markNotes();draw();list.lastElementChild?.querySelector('input').focus();};
 section.append(list,addTopic);return section;
}
// Empty points go; a topic without points goes; a topic without a name keeps its points under "Other".
function cleanDiscussion(topics){return topics.map(topic=>({...topic,topic:topic.topic.trim()||'Other',points:topic.points.filter(point=>point.text.trim())})).filter(topic=>topic.points.length);}
// The notes open with who spoke and what they hold, as written meeting notes do (2026-11-13).
// Speaker labels that nobody named (SPEAKER_00) are not people, so they are not listed.
function notesOverview(minutes){
 const box=el('dl','notes-overview'),names=[...new Set(detail.transcript.map(s=>s.speaker).filter(name=>name&&!/^SPEAKER[ _-]?\d+$/i.test(name)))];
 if(names.length)box.append(el('dt','','Present'),el('dd','',names.join(', ')));
 const counts=[[AtlantaTasks.meetingGroups(minutes.tasks||[]).length,'task'],[AtlantaTasks.meetingGroups(minutes.decisions||[]).length,'decision'],[(minutes.open_questions||[]).length,'open question']].map(([n,word])=>AtlantaUX.count(n,word)).join(' · ');
 const holds=btn('quiet notes-holds',counts);holds.title='Show the tasks and decisions';holds.onclick=()=>switchTab('outcomes');
 const value=el('dd');value.append(holds);box.append(el('dt','','Holds'),value);return box;
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
 target.replaceChildren();if(!rows.length){target.append(emptyNote('No diarized speaker time is available. Imported transcripts only have topic and question analytics.'));return;}
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
// Team analysis (2026-11-13): the person who runs Atlanta asked for it about their own meetings. It is private:
// not in the notes, exports, search or emails. One request goes to the Notes & AI provider after the person confirms.
const TEAM_PERSON_FIELDS=[['ownership','Ownership'],['proactivity','Proactivity'],['reporting','Reporting']];
const TEAM_COACHING=[['keep','Keep'],['change','Change'],['develop','Develop']];
let teamAnalysisRunning=null;
function teamObservations(rows){
 if(!rows?.length)return el('p','empty-note','Nothing in this meeting.');
 const list=el('ul','team-observations');
 for(const row of rows){const li=el('li');if(row.speaker)li.append(el('strong','',row.speaker+': '));li.append(linkedText(el('span'),row.text));if(row.evidence_timestamp)li.append(stampButton(row.evidence_timestamp));list.append(li);}
 return list;
}
function teamSection(title,...content){const section=el('section','team-section');section.append(el('h3','',title),...content.filter(Boolean));return section;}
function renderTeamAnalysis(busy=false){
 const target=$('team-analysis-content'),saved=detail.team_analysis,names=[...new Set(detail.transcript.map(s=>s.speaker).filter(Boolean))],running=teamAnalysisRunning===detail.id;
 target.replaceChildren();
 $('team-analysis-run').textContent=running?'Analyzing…':saved?'Analyze again':'Analyze';$('team-analysis-run').disabled=busy||running||!detail.transcript.length;
 // The coaching is for the person who runs Atlanta: they choose their own name among the speakers once.
 const who=el('label','team-self'),select=el('select');select.append(option('Choose your name',''),...names.map(name=>option(name,name)));
 select.value=names.includes(state.settings.self_name)?state.settings.self_name:'';select.disabled=busy||running;
 select.onchange=()=>perform(async()=>{await api('/api/settings',{self_name:select.value});state.settings.self_name=select.value;toast(select.value?'Saved: you are '+select.value:'Your name is cleared');});
 who.append(el('span','','You in this meeting'),select);target.append(who);
 const generic=names.filter(name=>/^SPEAKER[ _-]?\d+$/i.test(name));
 if(generic.length)target.append(el('p','notice warning','Name the speakers first: '+generic.join(', ')+'. The analysis describes each person by what the transcript says they said.'));
 target.append(el('p','hint','Only for you. The transcript can confuse speakers and words, so check each observation at its moment before you act on it.'));
 if(running)target.append(el('p','notice','The AI analyzes the meeting. A long meeting can take a few minutes.'));
 if(!saved){if(!running)target.append(emptyNote(detail.transcript.length?'Choose Analyze for work behavior by person, team dynamics, discourse and coaching for you.':'Transcribe the meeting first.'));return;}
 target.append(el('p','hint team-meta','By '+saved.model+' · '+AtlantaUX.dateTime(saved.created_at)+(saved.manager?' · coaching for '+saved.manager:'')));
 if(saved.stale)target.append(el('p','notice warning','The transcript changed after this analysis. Choose Analyze again to include the changes.'));
 if(saved.talk?.length)target.append(el('p','hint team-talk','Talk: '+saved.talk.map(row=>row.speaker+' '+row.percent+'% · '+AtlantaUX.count(row.turns,'turn')).join(' · ')));
 const analysis=saved.analysis,people=analysis.people.map(person=>{
  const box=el('section','team-person'),head=el('h4');head.append(avatar(person.name),el('span','',person.name));box.append(head);
  if(person.summary)box.append(el('p','team-summary',person.summary));
  for(const [key,label] of TEAM_PERSON_FIELDS)box.append(el('h5','',label),teamObservations(person[key]));
  return box;});
 target.append(
  teamSection('Work behavior by person',...(people.length?people:[el('p','empty-note','No other participant spoke.')])),
  teamSection('Communication and team dynamics',analysis.dynamics.overview&&el('p','team-summary',analysis.dynamics.overview),teamObservations(analysis.dynamics.observations)),
  teamSection('Discourse: words, wording and implied meanings',analysis.discourse.overview&&el('p','team-summary',analysis.discourse.overview),teamObservations(analysis.discourse.observations)),
  teamSection('Coaching: your management practice',...TEAM_COACHING.flatMap(([key,label])=>[el('h4','',label),teamObservations(analysis.coaching[key])])));
}
async function runTeamAnalysis(){
 const meetingId=detail.id,preview=await api('/api/team-analysis/preview',{meeting_id:meetingId});
 const lines=['Atlanta sends the transcript ('+preview.characters+' characters) with the speaker names to '+preview.model+(preview.base_url?' at '+preview.base_url:'')+'.','The analysis stays on this Mac.'];
 if(preview.unnamed.length)lines.push('Not named yet: '+preview.unnamed.join(', ')+'.');
 if(!state.settings.self_name)lines.push('Choose your name first if you want coaching for you; otherwise the coaching is for the person who leads the meeting.');
 if(!(await ask('Analyze the team in this meeting?\n\n'+lines.join('\n'),{ok:'Analyze'})))return;
 teamAnalysisRunning=meetingId;if(detail?.id===meetingId)renderTeamAnalysis();
 try{const result=await api('/api/team-analysis/generate',{meeting_id:meetingId,self_name:state.settings.self_name||''});if(detail?.id===meetingId){detail.team_analysis=result;lastFingerprint=JSON.stringify(detail);}toast('Team analysis ready');}
 finally{teamAnalysisRunning=null;if(detail?.id===meetingId)renderTeamAnalysis();}
}
function renderMeetingAnalytics(busy=false) {
 const data=detail.analytics,target=$('meeting-analytics-content');target.replaceChildren();
 $('reanalyze').disabled=busy||!detail.transcript.length;
 $('diarization-status').hidden=!detail.diarization_error;$('diarization-status').textContent=detail.diarization_error?'Speaker diarization unavailable · '+detail.diarization_error:'';
 $('meeting-analytics-error').hidden=!detail.analytics_error;$('meeting-analytics-error').textContent=detail.analytics_error?'Some analytics need attention · '+detail.analytics_error:'';
 if(!data){target.append(emptyNote(detail.transcript.length?'Choose Reanalyze to build talk-time, topic and question analytics.':'Transcribe or import a meeting to build conversation analytics.'));return;}
 const speakers=el('section','analytics-section'),speakerRows=el('div');speakers.append(el('h3','','Talk time'));if(data.total_speech_seconds)speakers.append(el('p','hint',shortDuration(data.total_speech_seconds)+' of diarized speech. Silence is excluded.'));speakers.append(speakerRows);speakerStats(speakerRows,data.speakers||[]);target.append(speakers);
 const topics=el('section','analytics-section');topics.append(el('h3','','Topic trackers'));
 if(!(data.topics||[]).length){const configure=el('button','secondary','Configure topic trackers');configure.onclick=()=>openSettings('trackers');topics.append(el('p','hint','No topic trackers are configured.'),configure);}
 for(const topic of data.topics||[]) {
  const box=el('div','topic-result'),heading=el('div','speaker-stat-heading');heading.append(el('strong','',topic.name),el('span','',topic.match_count+(topic.match_count===1?' hit':' hits')));box.append(heading);
  for(const hit of topic.matches||[]) {const evidence=el('div','evidence-row'),seek=listenButton(detail.id,hit.timestamp||0,{className:'quiet evidence-time'});const text=el('p','',hit.text);const meta=el('small','',(hit.speaker||'Unknown speaker')+(hit.semantic?' · AI match':' · '+(hit.phrases||[]).join(', ')));const main=el('div');main.append(text,meta);evidence.append(seek,main);box.append(evidence);}
  topics.append(box);
 }
 target.append(topics);
 const all=data.questions||[],questions=el('section','analytics-section');
 questions.append(el('h3','','Questions'),el('p','hint',all.length+' detected from wording · '+all.filter(q=>!q.answered).length+' not marked as answered. The app does not detect answers. Tick a question when it was answered.'));
 if(!all.length)questions.append(emptyNote('No questions detected.'));
 else {
  const filters=el('div','segmented question-filters');filters.setAttribute('role','group');filters.setAttribute('aria-label','Filter questions');
  for(const [key,label] of [['open','Not answered'],['answered','Answered'],['all','All']]){const button=btn(key===questionFilter?'selected':'',label);button.onclick=()=>{questionFilter=key;questionLimit=10;renderMeetingAnalytics(busy);};filters.append(button);}
  questions.append(filters);
 }
 const shown=all.filter(q=>questionFilter==='all'||(questionFilter==='answered')===!!q.answered);
 if(all.length&&!shown.length)questions.append(emptyNote('No questions match this filter.'));
 for(const question of shown.slice(0,questionLimit)) {
  const row=el('div','question-row'+(question.answered?' answered':'')),toggle=el('input');toggle.type='checkbox';toggle.checked=question.answered;toggle.disabled=busy;toggle.setAttribute('aria-label','Mark question as answered');
  toggle.onchange=()=>perform(async()=>{
   const meetingId=detail.id,answered=toggle.checked;
   const set=async value=>{const updated=await api('/api/meetings/'+meetingId+'/question',{id:question.id,text:question.text,answered:value});if(detail?.id!==meetingId)return;detail.analytics=updated;lastFingerprint=JSON.stringify(detail);renderMeetingAnalytics(false);};
   try{await set(answered);}catch(e){toggle.checked=!answered;throw e;}
   undoToast(answered?'Question marked as answered':'Question marked as open',()=>perform(async()=>{await set(!answered);toast('Undone');}));});
  const main=el('div'),text=el('p','',question.text),meta=el('div','tracked-meta'),seek=listenButton(detail.id,question.timestamp||0,{className:'quiet tracked-source'});meta.append(el('span','',question.speaker||'Unknown speaker'),seek);main.append(text,meta);row.append(toggle,main);questions.append(row);
 }
 if(shown.length>questionLimit){const more=btn('secondary','Show all '+shown.length+' questions');more.onclick=()=>{questionLimit=Infinity;renderMeetingAnalytics(busy);};questions.append(more);}
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
 $('analytics-summary').textContent=data.meeting_count+(data.meeting_count===1?' meeting':' meetings')+(data.total_speech_seconds?' · '+speech+' diarized speech':'')+' · '+AtlantaUX.count(data.questions,'question')+' · '+data.unanswered_questions+' not marked as answered';
 $('analytics-overview').replaceChildren(metric('Meetings',data.meeting_count),metric('Diarized speech',speech),metric('Questions',data.questions),metric('Not marked as answered',data.unanswered_questions));
 speakerStats($('analytics-speakers'),data.speakers,true);
 $('analytics-topics').replaceChildren();if(!data.topics.length)$('analytics-topics').append(emptyNote('No topic hits match these filters.'));
 for(const topic of data.topics){const box=el('div','metric');box.append(el('strong','',topic.matches),el('span','',topic.name+' · '+AtlantaUX.count(topic.meetings,'meeting')));$('analytics-topics').append(box);}
 $('analytics-meetings').replaceChildren();if(!data.meetings.length)$('analytics-meetings').append(emptyNote('No generated analytics match these filters.'));
 for(const meeting of data.meetings){const row=el('div','analytics-meeting'),button=el('button','quiet tracked-source',meeting.title);button.onclick=()=>perform(async()=>{await openMeeting(meeting.id);switchTab('analytics');});row.append(button,el('span','',date(meeting.date)),el('span','',meeting.talk_seconds?shortDuration(meeting.talk_seconds):'No talk time'),el('span','',AtlantaUX.count(meeting.questions,'question')+' · '+AtlantaUX.count(meeting.topic_matches,'topic hit')));$('analytics-meetings').append(row);}
}
function renderTrackers() {
 const target=$('tracker-list');target.replaceChildren();if(!trackersData.length)target.append(emptyNote('No topic trackers yet. Add topics such as Бюджет, Продажби or Риск.'));
 trackersData.forEach((tracker,index)=>{const box=el('fieldset','tracker-editor'),name=el('input');name.value=tracker.name;name.placeholder='Topic name, for example Бюджет';name.maxLength=100;name.setAttribute('aria-label','Topic name '+(index+1));name.oninput=()=>tracker.name=name.value;
  const phrases=el('textarea');phrases.value=(tracker.phrases||[]).join('\n');phrases.rows=3;phrases.placeholder='One phrase per line\nбюджет\nразходи';phrases.setAttribute('aria-label','Phrases for topic '+(index+1));phrases.oninput=()=>tracker.phrases=phrases.value.split('\n').map(value=>value.trim()).filter(Boolean);
  const label=el('label','checkbox'),semantic=el('input');semantic.type='checkbox';semantic.checked=!!tracker.semantic_matching;semantic.onchange=()=>tracker.semantic_matching=semantic.checked;label.append(semantic,document.createTextNode(' Also match by meaning with the Configured API'));
  const remove=btn('quiet danger-text','Remove topic');remove.onclick=()=>{trackersData.splice(index,1);renderTrackers();};box.append(name,phrases,label,remove);target.append(box);});
}
async function saveTrackers() {
 for(const tracker of trackersData)if(!tracker.name.trim()||!tracker.phrases.length)throw new Error('Every topic needs a name and at least one phrase.');
 const result=await api('/api/trackers',{trackers:trackersData});trackersData=result.trackers;state.trackers=result.trackers;renderTrackers();toast('Topic trackers saved · reanalyze meetings to refresh them');
}
function settingsFields() { const parakeet=$('provider').value.startsWith('parakeet');$('parakeet-runtime').hidden=!parakeet;$('parakeet-runtime').textContent=(state[$('provider').value]?.message)||'Parakeet v3 requires an Apple Silicon build with Parakeet support.'; $('local-model-field').hidden=false;$('cloud-model-field').hidden=$('provider').value!=='openai';$('notes-model-field').hidden=$('summarizer').value!=='openai'&&$('transcript-correction').value!=='openai';$('title-model-field').hidden=$('title-provider').value!=='openai';$('settings-privacy').textContent=privacy({transcription:$('provider').value,summarizer:$('summarizer').value,transcript_correction:$('transcript-correction').value,auto_title:$('auto-title').checked,title_provider:$('title-provider').value,local_ai_base_url:$('local-ai-base-url').value,calendar_enabled:$('calendar-enabled').checked});$('title-privacy').textContent=$('title-provider').value==='openai'?'Transcript excerpts are sent to OpenAI for title generation.':'Uses the configured API and its model above.'; }
function fileSize(bytes) { return bytes>=1e9?(bytes/1e9).toFixed(1)+' GB':bytes>=1e6?Math.round(bytes/1e6)+' MB':Math.max(1,Math.round(bytes/1e3))+' KB'; }
function renderBackups(data) {
 $('backup-folder').textContent=data.folder; const list=$('backup-list'); list.replaceChildren();
 if(!data.archives.length) list.append(emptyNote('No archives yet.'));
 for(const archive of data.archives) {
  const row=el('div','backup-row'), main=el('div'), actions=el('div','backup-actions');
  main.append(el('strong','',archive.created?dateTime(archive.created):archive.name),
   el('span','backup-meta '+(archive.verified?'ok':'bad'),fileSize(archive.bytes)+' · '+(archive.verified?'✓ Restore test passed · '+archive.meetings+(archive.meetings===1?' meeting':' meetings'):'✗ '+(archive.error||'Restore test failed'))));
  const reveal=el('button','quiet','Show in Finder'); reveal.type='button'; reveal.onclick=()=>perform(()=>api('/api/backups/reveal',{name:archive.name}));
  const restore=el('button','secondary','Restore'); restore.type='button'; restore.disabled=!archive.verified;
  restore.onclick=()=>perform(async()=>{const damaged=Object.keys(state.storage_errors||{});const recovery=damaged.length?'\n\nRecover these metadata files: '+damaged.join(', ')+'. The original bytes are preserved in separate .corrupt-*.json files.':'';if(!(await ask('Restore this archive?\n\nMissing meetings are added. Existing meetings and settings stay as they are.'+recovery,{ok:'Restore'})))return;
   restore.disabled=true;$('backup-status').textContent='Restoring and checking…';
   try{const result=await api('/api/backups/restore',{name:archive.name});renderBackups(result);$('backup-status').textContent=AtlantaUX.count(result.restored.length,'meeting')+' restored · '+result.skipped.length+' already in the library'+(result.recovered_metadata?.length?' · Metadata recovered: '+result.recovered_metadata.join(', '):'');state=await api('/api/state');renderState();}
   finally{restore.disabled=false;}});
  actions.append(reveal,restore); row.append(main,actions); list.append(row);
 }
}
async function loadBackups() { renderBackups(await api('/api/backups')); }
$('backup-now').onclick=()=>perform(async()=>{const button=$('backup-now');button.disabled=true;$('backup-status').textContent='Archiving and running the restore test… Large libraries take a few minutes.';
 try{const result=await api('/api/backups/create',{});renderBackups(result);$('backup-status').textContent='Archive created and verified · '+AtlantaUX.count(result.created.meetings,'meeting')+(result.created.skipped_meetings?.length?' · '+result.created.skipped_meetings.length+' active or processing meetings left out':'');}
 catch(e){$('backup-status').textContent='';throw e;}finally{button.disabled=false;}});
const SETTINGS_GROUPS={recording:['recording','vocabulary'],ai:['notes','prompts','trackers'],people:['speakers','calendar'],workspace:['projects','types'],advanced:['backup','help']};
function showSettingsTab(name) {
 const group=Object.keys(SETTINGS_GROUPS).find(key=>SETTINGS_GROUPS[key].includes(name))||'recording';
 for(const button of document.querySelectorAll('[data-settings-group]')){button.setAttribute('aria-selected',String(button.dataset.settingsGroup===group));button.classList.toggle('selected',button.dataset.settingsGroup===group);}
 document.querySelector('.settings-tabs').hidden=SETTINGS_GROUPS[group].length===1;
 for(const button of document.querySelectorAll('.settings-tabs button'))button.hidden=!SETTINGS_GROUPS[group].includes(button.dataset.tab);
 settingsTab=name; $('settings-save').hidden=!['recording','vocabulary','notes','calendar'].includes(name); document.querySelector('.advanced-toggle').hidden=!['recording','notes'].includes(name);document.querySelector('.settings-footer').hidden=!['recording','vocabulary','notes','calendar'].includes(name); if(name==='prompts')perform(loadPromptEditor); if(name==='backup') perform(loadBackups); if(name==='projects') renderProjectSettings(); if(name==='types') renderTypeSettings();
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
// Rendered markdown for texts authored in markdown (GitHub, drafts, AI output). renderMarkdown escapes all HTML first.
function markdownBlock(source){const box=el('div','markdown compact');box.innerHTML=renderMarkdown(source||'');return box;}
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
$('viewer-dialog').onclick=event=>{const dialog=$('viewer-dialog'),rect=dialog.getBoundingClientRect();if(event.target===dialog&&(event.clientX<rect.left||event.clientX>rect.right||event.clientY<rect.top||event.clientY>rect.bottom))dialog.close();};
// The fields that Save settings sends. Speakers, topics and projects save with their own buttons.
function settingsValues(){
 const fields=$('settings-form').querySelectorAll('.settings-panel:is([data-tab=recording],[data-tab=vocabulary],[data-tab=notes],[data-tab=calendar]) :is(input:not([type=file]):not([type=button]),select,textarea)');
 return JSON.stringify([...fields].map(f=>f.type==='checkbox'?f.checked:f.value));
}
let settingsOpened='';
// One question names everything that closing loses; the editors then discard without asking again.
async function closeSettings(){
 const lost=[settingsValues()!==settingsOpened&&'settings',typePromptDirty()&&'meeting-type instructions',promptDirty()&&'AI instructions'].filter(Boolean);
 const running=promptJob||promptPending;
 if(lost.length||running){
  const message=(lost.length?'Close Settings without saving the '+lost.join(', ')+'?':'Close Settings?')+(running?'\n\nThe running prompt test stops.':'');
  if(!(await ask(message,{ok:lost.length?'Discard and close':'Stop test and close',cancel:'Keep editing',danger:!!lost.length})))return;
 }
 await leaveTypePrompt(true);await leavePromptEditor(true);
 editorDirty.clear('ai-prompts');$('settings-dialog').close();
}
function openSettings(tab) { if(!state)return; clearError(); const s=state.settings;$('local-ai-base-url').value=s.local_ai_base_url;$('local-ai-model').value=s.local_ai_model;$('local-ai-format').value=s.local_ai_format;$('local-ai-reasoning').value=s.local_ai_reasoning;$('local-ai-max-tokens').value=s.local_ai_max_tokens;$('local-ai-status').textContent='';localModels=[];renderLocalModels();$('provider').value=s.transcription;$('local-model').value=s.local_model;$('audio-preparation').value=s.audio_preparation||'off';$('whisper-vad').checked=s.whisper_vad!==false;$('whisper-vocabulary').value=s.whisper_vocabulary||'';$('cloud-model').value=s.cloud_model;$('summarizer').value=s.summarizer;$('transcript-correction').value=s.transcript_correction||'none';$('llm-model').value=s.llm_model;$('auto-process').checked=s.auto_process;$('live-enabled').checked=s.live_transcription!==false;$('diarization-enabled').checked=s.diarization_enabled!==false;$('diarization-runtime').textContent=state.diarization?.message||'Speaker separation is checked after recording.';$('auto-title').checked=s.auto_title!==false;$('title-provider').value=s.title_provider||'local';$('title-model').value=s.title_model||'gpt-4.1-mini';$('calendar-enabled').checked=!!s.calendar_enabled;$('calendar-id').replaceChildren();const initialCalendar=el('option','',s.calendar_name||'Choose a calendar…');initialCalendar.value=s.calendar_id||'';$('calendar-id').append(initialCalendar);$('elevenlabs-api-key').value='';$('forget-elevenlabs-key').disabled=!state.elevenlabs_api_key_configured;$('local-ai-api-key').value='';$('forget-local-ai-key').disabled=!state.local_ai_api_key_configured;$('local-ai-key-state').textContent=state.local_ai_key_error?'· '+state.local_ai_key_error:state.local_ai_api_key_configured?'· configured':'';$('local-ai-context').value=s.local_ai_context||16384;$('local-ai-temperature').value=s.local_ai_temperature||'zero';$('task-matching-allow').checked=!!s.task_matching_target&&s.task_matching_target===s.local_ai_base_url;$('meeting-task-ai').checked=!!s.meeting_task_ai;renderCloudNote();renderTaskMatching();$('elevenlabs-key-state').textContent=state.elevenlabs_key_error?'· '+state.elevenlabs_key_error:state.elevenlabs_api_key_configured?'· configured':'';$('api-key').value='';$('forget-key').disabled=!state.api_key_configured;$('key-state').textContent=state.api_key_configured?'· configured':'';settingsFields();renderGoogleStatus();renderSpeakerSettings();trackersData=JSON.parse(JSON.stringify(state.trackers||[]));renderTrackers();showSettingsTab(typeof tab==='string'?tab:settingsTab);$('settings-dialog').showModal();markProfile();renderPeople();settingsOpened=settingsValues();
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
let itemKind='task', sourceFilter=stored('tasks-source')||'', itemsData={items:[],pending:[],meetings:{}};
const STATUS_FILTERS={task:[['open','Open'],['overdue','Overdue'],['done','Done'],['all','All'],['snoozed','Snoozed'],['dismissed','Dismissed']],decision:[['current','In force'],['proposed','Proposed'],['accepted','Accepted'],['superseded','Replaced'],['all','All'],['snoozed','Snoozed'],['dismissed','Dismissed']]};
const statusFilter={task:stored('tasks-status')||'open',decision:'current'};
const DECISION_LABELS={proposed:'Proposed',accepted:'Accepted',superseded:'Replaced'};
// One state for a decision: what was decided, and whether a person must look at it again.
// The status and the review state stay separate in the data; one badge shows both.
function decisionState(item){
 // A person hid it in My Work; it asks for nothing until it is restored there.
 if(item.dismissed)return {cls:'dismissed',label:'Hidden in My Work',title:'Restore it in My Work to work with it again.',action:null};
 if(item.status==='accepted'&&['needs_review','edited'].includes(item.review_state))
  return {cls:'recheck',label:'Accepted · check again',title:'The notes or the transcript changed after this decision was accepted. Confirm that it still holds.',action:'Confirm decision'};
 if(item.status==='proposed')return {cls:'proposed',label:'Proposed',title:'The AI proposed this decision. Accept it if it was agreed.',action:'Accept decision'};
 return {cls:item.status,label:DECISION_LABELS[item.status]||item.status,title:'',action:null};
}
function decisionBadge(item){const s=decisionState(item),badge=el('span','decision-status '+s.cls,s.label);if(s.title)badge.title=s.title;return badge;}
const FIELD_LABELS={text:'text',owner:'owner',deadline:'deadline as said',due_date:'due date',status:'status'};
const EVENT_LABELS={source_linked:'Source linked',proposal_linked:'Linked to task',projects_changed:'Projects changed',confirmed:'Owner confirmed',edited_on_accept:'Text edited on accept',created:'Created in',discussed:'Discussed in',duplicate:'Mentioned again in',changed:'Changed',removed:'Removed from',merged:'Merged with another item',superseded:'Replaced in',detached:'Waits for the new notes of',meeting_review_confirm:'Confirmed for',progress_update:'Update',owner_linked:'Owner linked to People',speaker_named:'Speaker named in',meeting_update_removed:'Update from the meeting removed',email_draft:'Email draft saved in Gmail'};
// An event without a label reads as words, never as its code name.
const eventLabel=name=>EVENT_LABELS[name]||String(name||'Event').replace(/_/g,' ').replace(/^./,c=>c.toUpperCase());
function meetingLabel(id,meetings) { const meeting=meetings?.[id]; return meeting?withDate(meeting.title,meeting.date):'a deleted meeting'; }
// The task card lists its meetings as rows: the meeting, its date, and the moment the task was said.
function taskMeetingList(item,meetings){
 const links=[...item.links].sort((a,b)=>(meetings[a.meeting_id]?.date||'').localeCompare(meetings[b.meeting_id]?.date||''));if(!links.length)return null;
 const box=el('div','task-meetings');box.append(el('p','task-meetings-title','Linked meetings · '+links.length));
 for(const link of links){const meeting=meetings[link.meeting_id],row=el('div','task-meeting');
  row.append(icon('calendar'),meeting?actionBtn('quiet task-meeting-title',meeting.title,async()=>{await openMeeting(link.meeting_id);switchTab('outcomes');}):el('span','task-meeting-title hint','A deleted meeting'),el('span','task-meeting-date',meeting?date(meeting.date):''));
  row.append(link.evidence_timestamp?listenButton(link.meeting_id,stampSeconds(link.evidence_timestamp),{label:link.evidence_timestamp.replace(/^00:(?=\d\d:)/,''),className:'task-meeting-listen'}):el('span'));box.append(row);}
 return box;
}
function meetingChips(item,meetings,except) {
 const box=el('div','item-meetings');
 for(const link of item.links.filter(link=>link.meeting_id!==except).sort((a,b)=>(meetings[a.meeting_id]?.date||'').localeCompare(meetings[b.meeting_id]?.date||''))) {
  box.append(originChip('meeting',meetingLabel(link.meeting_id,meetings)+(link.evidence_timestamp?' · at '+link.evidence_timestamp:''),async()=>{await openMeeting(link.meeting_id);switchTab('outcomes');}));
  if(link.evidence_timestamp)box.append(listenButton(link.meeting_id,stampSeconds(link.evidence_timestamp),{label:'',className:'chip-listen'}));
 }
 return box;
}
// The external sources (Gmail, Chat, GitHub) behind an item, from its saved source quotes.
function itemSources(item){const graph=itemsData.graph||{},ids=new Set(item.source_evidence||[]),evidence=(graph.source_evidence||[]).filter(e=>ids.has(e.id));return [...new Map(evidence.map(e=>[e.source_id,(graph.sources||[]).find(s=>s.id===e.source_id)])).values()].filter(Boolean);}
function sourceLabel(source){return source.remote?.authority==='github_code'?source.remote.repository+' · code':source.remote?.authority==='github'?source.remote.repository+' #'+source.remote.number:'';}
function itemProviders(item){return new Set([...(item.created_by==='user'?['manual']:[]),...(item.links.length?['meeting']:[]),...itemSources(item).map(s=>s.provider)]);}
function sourceChips(item,meetings,{withMeetings=true}={}){const box=withMeetings?meetingChips(item,meetings):el('div','item-meetings');for(const source of itemSources(item))box.append(originChip(source.provider,sourceLabel(source),()=>openSource(source)));return box;}
function historyBlock(item,meetings) {
 const box=el('details','item-history'), list=el('ol'); box.append(el('summary','','History · '+item.history.length));
 // The same event right after itself (for example a confirmation that was repeated) shows once, with how many times.
 const events=[];for(const event of [...item.history].reverse()){const last=events.at(-1);
  if(last&&last.event===event.event&&last.meeting_id===event.meeting_id&&last.by===event.by&&!Object.keys(event.changes||{}).length&&!Object.keys(last.changes||{}).length&&!event.text&&!last.text){last.times=(last.times||1)+1;continue;}
  events.push({...event});}
 for(const event of events) {
  const changes=Object.entries(event.changes||{}).map(([name,[from,to]])=>{if(name==='project_ids'){const label=ids=>ids===null?'Meeting projects':ids.map(id=>projectList().find(p=>p.id===id)?.name||'Removed project').join(', ')||'Unassigned';return 'Projects: '+label(from)+' → '+label(to);}const labelValue=value=>name==='assignee_person_ids'?(value||[]).map(id=>(state.people||[]).find(p=>p.id===id)?.name||'Removed person').join(', ')||'—':name.endsWith('_person_id')?(state.people||[]).find(p=>p.id===value)?.name||(value?'Removed person':'—'):name==='status'?({...DECISION_LABELS,open:'Open',done:'Done'})[value]||value:name==='workflow_state'?AtlantaTasks.STATES[value]||value:['due_date','follow_up_date'].includes(name)&&value?date(value):value??'—';return ({workflow_state:'State',status:'Status',text:'Text',requester_person_id:'Received from',assigned_by_person_id:'Assigned by',follower_person_id:'Followed by',owner_person_id:'Owner',follow_up_date:'Follow-up',acceptance_state:'Acceptance',details:'Details',completion_criteria:'Expected result'}[name]||FIELD_LABELS[name]||name)+': '+labelValue(from)+' → '+labelValue(to);}).join(' · ');
  // Date the action itself; the meeting remains its evidence reference.
  const when=event.at;
  const entry=el('li'); entry.append(el('span','history-date',dateTime(when)),
   el('span','',(event.event==='created'&&!event.meeting_id?'Created locally':eventLabel(event.event))+(event.meeting_id?' '+meetingLabel(event.meeting_id,meetings):'')+(changes?' · '+changes:'')+(event.text?' · '+event.text:'')+(event.by==='user'?' · by you':' · AI')+(event.times?' · '+event.times+' times':'')));
  list.append(entry);
 }
 box.append(list); return box;
}
async function refreshAfterItemChange() { lastTasks=''; if(view==='projects'){ itemsData=await api('/api/items'); await loadWorkspace(); } else if(view==='tasks') await loadTasks(); else if(view==='prepare') await loadPrepare(); else if(view==='detail'&&selected) await openMeeting(selected,true); state=await api('/api/state'); renderState(); }
async function changeWithUndo(item,changes,message,undo){
 if(!validDates($('tasks')))return;
 const saved=await api('/api/items/'+item.id,{text:item.text,revision:item.revision,changes});await refreshAfterItemChange();
 undoToast(message,()=>perform(async()=>{await api('/api/items/'+saved.id,{text:saved.text,revision:saved.revision,changes:undo});await refreshAfterItemChange();toast('Undone');}));
}
// Done is a labelled action with Undo, never an unlabelled checkbox.
function doneButton(item,busy=false){
 const finished=item.status==='done',previous=AtlantaTasks.workflow(item),button=el('button','secondary small-action task-done',finished?'Reopen':'Mark done');
 button.type='button';button.disabled=busy;
 button.onclick=()=>perform(()=>finished?changeItem(item,{workflow_state:'todo'}):changeWithUndo(item,{workflow_state:'done'},'Marked done: '+item.text,{workflow_state:previous==='done'?'todo':previous}));
 return button;
}
async function changeItem(item,changes,finishEdit=false) {if(!validDates($('tasks')))return; await api('/api/items/'+item.id,{text:item.text,revision:item.revision,changes});if(finishEdit)setItemEditing(false);await refreshAfterItemChange(); }
// A new mention that looks like an existing item: the person decides, nothing is linked before that.
function linkCard(entry,meetings,itemsById) {
 const kind=entry.kind, mention=entry.mention, card=el('div','link-card'), head=el('div','link-head');
 head.append(el('span','change-kind','Is this an existing '+kind+'?'),el('span','hint','From '+meetingLabel(entry.meeting_id,meetings)));
 const details=kind==='task'?[mention.owner,mention.deadline&&'said: '+mention.deadline,mention.due_date&&date(mention.due_date)].filter(Boolean):[];
 card.append(head,el('p','link-text',entry.text+(details.length?' · '+details.join(' · '):'')));
 const resolve=(action,itemId,extra={})=>perform(async()=>{await api('/api/meetings/'+entry.meeting_id+'/link',{field:entry.field,index:entry.index,text:entry.text,action,item_id:itemId,...extra});await refreshAfterItemChange();toast(action==='new'?'Added as a new '+kind:extra.fields?.length?'Linked · '+AtlantaUX.count(extra.fields.length,'field')+' changed':'Linked · the history shows this meeting');});
 for(const candidate of entry.candidates) {
  const item=itemsById[candidate.item_id]; if(!item) continue;
  const row=el('div','link-candidate'), main=el('div'), actions=el('div','link-actions');
  const facts=kind==='task'?[item.status==='done'?'Done':'Open',item.owner,item.due_date&&'due '+date(item.due_date)]:[DECISION_LABELS[item.status]];
  main.append(el('p','',item.text),el('span','hint',facts.filter(Boolean).join(' · ')+' · '+Math.round(candidate.score*100)+'% similar'),meetingChips(item,meetings));
  // A task: what the meeting said differently. Nothing changes unless you check it; a field that you edited stays.
  const changes=el('div','link-changes'),checks=[];
  if(kind==='task')for(const [name,label] of [['owner','Owner'],['deadline','Deadline as said'],['due_date','Due date']]){
   const said=mention[name],now=item[name];if(said==null||said===now)continue;
   const show=value=>value==null||value===''?'none':name==='due_date'?date(value):value;
   if((item.manual||[]).includes(name)){changes.append(el('p','hint',label+' stays '+show(now)+' · you edited it'));continue;}
   const line=el('label','checkbox link-change'),box=el('input');box.type='checkbox';box.value=name;
   line.append(box,document.createTextNode(label+': '+show(now)+' → '+show(said)));changes.append(line);checks.push(box);
  }
  if(checks.length)changes.prepend(el('p','hint','The meeting said something different. Check only what should change:'));
  const choices=kind==='task'?[['same','Same task','primary','Links this meeting as evidence. Only the checked fields change. The status stays.'],['duplicate','Duplicate','secondary','Links this meeting and changes nothing.']]
   :[['same','Same decision','primary','Links this meeting to the decision.'],['replaces','Replaces it','secondary','Saves this as a new decision; the older one becomes replaced.']];
  for(const [action,label,style,title] of choices){const button=btn(style,label);button.title=title;
   button.onclick=()=>resolve(action,item.id,{revision:item.revision,...(action==='same'&&kind==='task'?{fields:checks.filter(c=>c.checked).map(c=>c.value)}:{})});actions.append(button);}
  if(changes.childNodes.length)main.append(changes);
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
  const source=btn('quiet');source.append(icon('jump'),document.createTextNode(meetingLabel(evidence.source_id,meetings)+(evidence.timestamp?' · '+evidence.timestamp:'')));source.disabled=!meetings[evidence.source_id];
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
// A person can change or remove anything that the AI suggested, with or without saved sources.
const deleteWarning=item=>'Delete this '+item.kind+' everywhere?\n\n'+item.text+(item.links?.length?'\n\nIt is removed from the notes of '+item.links.length+(item.links.length===1?' meeting.':' meetings.'):'')+(item.source_evidence?.length?'\n\nSaved source quotes stay; links to other items are removed.':'');
async function deleteItem(item){if(!(await ask(deleteWarning(item),{ok:'Delete',danger:true})))return;await api('/api/items/'+item.id+'/delete',{text:item.text,revision:item.revision});await refreshAfterItemChange();toast('Deleted');}
// Replace a text node with an editor in place. save(value) returns a promise; Escape or Cancel keeps the text.
function inlineEdit(node,text,save,label='Text'){
 if(!node.isConnected||editorDirty.keys().includes('inline-edit'))return;
 const form=el('div','inline-editor'),area=el('textarea','tracked-edit'),bar=el('div','tracked-edit-bar'),ok=el('button','primary small-action','Save'),cancel=el('button','secondary small-action','Cancel');
 area.value=text;area.rows=Math.max(2,Math.ceil(text.length/90));area.setAttribute('aria-label',label);ok.type=cancel.type='button';bar.append(cancel,ok);form.append(area,bar);
 const close=()=>{editorDirty.clear('inline-edit');form.replaceWith(node);};
 cancel.onclick=()=>perform(async()=>{if(area.value!==text&&!(await ask('Discard these unsaved edits?',{ok:'Discard',cancel:'Keep editing',danger:true})))return;close();});area.onkeydown=event=>{if(event.key==='Escape'){event.preventDefault();event.stopPropagation();cancel.click();}if(event.key==='Enter'&&(event.metaKey||event.ctrlKey))ok.click();};
 ok.onclick=()=>perform(async()=>{const value=area.value.trim();if(!value){area.focus();return;}if(value===text){close();return;}ok.disabled=cancel.disabled=true;try{await save(value);editorDirty.clear('inline-edit');}finally{ok.disabled=cancel.disabled=false;}});
 editorDirty.set('inline-edit',true);node.replaceWith(form);
 // The field shows the whole text at once: it grows to its content, up to the CSS limit.
 area.style.height=area.scrollHeight+2+'px';area.focus();
}
// Rare and destructive actions wait in a small menu; the row keeps its main action in view.
function rowMenu(label,...buttons){
 const menu=el('details','menu row-menu'),summary=el('summary','overflow-trigger','...'),items=el('div','menu-items');
 summary.setAttribute('aria-label',label);summary.title=label;
 for(const button of buttons){button.classList.remove('quiet','small-action','secondary');items.append(button);}
 items.addEventListener('click',()=>{menu.open=false;});menu.append(summary,items);
 // A click elsewhere closes an open row menu. One listener serves every menu.
 if(!rowMenu.watching){rowMenu.watching=true;document.addEventListener('click',event=>{for(const open of document.querySelectorAll('details.row-menu[open]'))if(!open.contains(event.target))open.open=false;});}
 return menu;
}
function editDeleteButtons(item,textNode){
 const edit=el('button','quiet','Edit'),remove=el('button','quiet danger-text','Delete');edit.type=remove.type='button';
 edit.onclick=()=>inlineEdit(textNode,item.text,async value=>{await api('/api/items/'+item.id,{text:item.text,revision:item.revision,changes:{text:value}});await refreshAfterItemChange();toast('Saved');},'Edit '+item.kind);
 remove.onclick=()=>perform(()=>deleteItem(item));return [edit,rowMenu('More actions for this '+item.kind,remove)];
}
function itemActions(item,row) {
 const actions=el('div','tracked-actions'); actions.append(projectAssignment(item)); const edit=el('button','quiet','Edit'), merge=el('button','quiet','Merge…'), remove=el('button','quiet danger-text','Delete');
 const main=row.querySelector('.tracked-main'), text=main.querySelector('.tracked-text');
 edit.onclick=()=>item.kind==='task'?perform(()=>openTaskPanel(item.id)):inlineEdit(text,item.text,async value=>{await changeItem(item,{text:value});},'Edit '+item.kind);
 merge.onclick=()=>{const others=itemsData.items.filter(other=>other.kind===item.kind&&other.id!==item.id);if(!others.length){toast('There is no other '+item.kind+' to merge with');return;}
  if(itemEditing)return;setItemEditing(true,row);
  const bar=el('div','tracked-edit-bar'),select=el('select'),go=el('button','primary','Merge'),cancel=el('button','secondary','Cancel');
  select.setAttribute('aria-label','Merge into');select.append(option('Same as…',''),...others.map(other=>option(other.text.slice(0,100),other.id)));
  go.onclick=()=>{if(!select.value)return;perform(async()=>{await api('/api/items/'+item.id+'/merge',{into:select.value,revision:item.revision,into_revision:itemsData.items.find(other=>other.id===select.value)?.revision});setItemEditing(false);await refreshAfterItemChange();toast('Merged · both histories are kept');});};
  cancel.onclick=()=>{setItemEditing(false);bar.remove();actions.hidden=false;lastTasks='';perform(loadTasks);};bar.append(select,cancel,go);main.append(bar);actions.hidden=true;};
 remove.onclick=()=>perform(()=>deleteItem(item));
 const snooze=el('button','quiet',item.snoozed_until?'Unsnooze':'Snooze'),dismiss=el('button','quiet',item.dismissed?'Restore to My Work':'Hide item');
 snooze.onclick=()=>perform(async()=>{if(item.snoozed_until){await changeItem(item,{snoozed_until:null});return;}const day=new Date();day.setDate(day.getDate()+1);const value=await askDate('Snooze in My Work until dd.mm.yyyy. The item status and sources stay unchanged.',AtlantaUX.iso(day));if(value!==null)await changeItem(item,{snoozed_until:value});});
 dismiss.title='Hides this item in My Work and every linked meeting. Undo is available.';dismiss.onclick=()=>perform(()=>item.dismissed?changeItem(item,{dismissed:false}):changeWithUndo(item,{dismissed:true},'Dismissed: '+item.text,{dismissed:false}));
 if(item.kind==='task'&&item.acceptance_state!=='proposed'){const mail=el('button','quiet','Send by email…');mail.onclick=()=>perform(()=>openTaskEmail(item.id));actions.append(mail);}
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
  const check=btn('quiet','Check in GitHub');check.onclick=()=>perform(async()=>{check.disabled=true;try{await api('/api/github/link',{resource,reference:link.url,verify_live:true});await afterGitHubLink(resource);}finally{check.disabled=false;}});chip.append(check);
  const remove=btn('quiet');remove.append(icon('close'));remove.title='Remove this link from Atlanta (GitHub is not changed)';remove.setAttribute('aria-label','Remove link');
  remove.onclick=()=>perform(async()=>{await api('/api/github/unlink',{id:link.id,revision:link.revision});await afterGitHubLink(resource);});chip.append(remove);box.append(chip);
 }
 const menu=el('details','menu github-menu'),items=el('div','menu-items');menu.append(el('summary','','GitHub ▾'),items);
 for(const [label,run] of [['Create GitHub issue…',()=>openDraft(resource,'issue')],['Draft GitHub comment…',()=>openDraft(resource,'comment')],['Link existing issue or PR…',()=>openLink(resource)]]){
  const b=btn('',label);b.onclick=()=>{menu.open=false;perform(run);};items.append(b);
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
async function openDraft(resource,format){captureDraft();draftResource=resource;draftFormat=format;draftActiveKey='';$('github-draft-repo').replaceChildren();$('github-draft-assignee').replaceChildren();$('github-draft-assignee').dataset.chosen='';$('github-draft-preview').hidden=true;$('github-draft-body').hidden=false;$('github-draft-preview-toggle').textContent='Preview rendered text';await renderDraft();if(!$('github-draft-dialog').open)$('github-draft-dialog').showModal();}
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
 renderDraftRouting(draft);renderDraftAssignee(draft,format);
 $('github-draft-notes').textContent=[...draft.notes,draft.assignee?'Assignee suggestion: '+draft.assignee+' (a confirmed owner).':''].filter(Boolean).join(' ');draftEditNotice();updateDraftLink();
 }finally{if(sequence===draftSequence)$('github-draft-copy').disabled=$('github-draft-copy-title').disabled=$('github-draft-review').disabled=false;}
}
// No repository to choose: show why, and fix it here. A task gets a project; a project gets a repository.
function renderDraftRouting(draft){
 const box=$('github-draft-routing'),resource=draftResource,key=JSON.stringify([resource,draft.projects,draft.repositories]);
 // Option changes refresh the draft; staged repository links stay while the routing is the same.
 if(box.dataset.key===key)return;box.dataset.key=key;box.replaceChildren();box.hidden=!!draft.repositories.length;
 if(box.hidden)return;
 if(!draft.projects.length){
  if(resource.kind!=='item'||!projectList().length){box.append(el('p','notice warning',projectList().length?'This conversation has no project. Assign it to a project to choose a repository.':'Create a project in Projects, then link a repository to it.'));return;}
  const choose=el('select'),apply=el('button','primary small-action','Use this project'),row=el('div','work-actions');
  choose.setAttribute('aria-label','Project for this item');choose.append(option('Choose a project…',''),...projectList().map(p=>option(p.name,p.id)));apply.type='button';apply.disabled=true;
  choose.onchange=()=>{apply.disabled=!choose.value;};
  apply.onclick=()=>perform(async()=>{apply.disabled=true;try{await api('/api/work/project',{id:resource.id,revision:draft.revision,project_ids:[choose.value]});await renderDraft();perform(refreshAfterItemChange);}finally{apply.disabled=!choose.value;}});
  row.append(choose,apply);box.append(el('p','notice warning','This item has no project, so there is no repository to choose. Choose its project.'),row);return;
 }
 for(const project of draft.projects){
  box.append(el('p','notice warning','No repository is linked to '+project.name+'. Link one here.'));
  box.append(repositoryEditor(project,{open:true,onSaved:async()=>{await renderDraft();perform(refreshAfterItemChange);}}));
 }
}
// Who the issue goes to: a person in Atlanta with a GitHub username. A confirmed owner is the default.
function renderDraftAssignee(draft,format){
 const select=$('github-draft-assignee'),people=draft.people||[],suggested=(draft.assignee||'').replace(/^@/,'');
 const chosen=select.dataset.chosen,keep=chosen!==undefined&&chosen!==''?chosen:null;
 select.replaceChildren(option(people.length?'No assignee':'No person with a GitHub username',''),...people.map(p=>option(p.name+' · @'+p.login+(p.checked?'':' · not checked'),p.login)));
 const value=keep!==null?keep:suggested;select.value=people.some(p=>p.login===value)?value:'';
 select.hidden=format!=='issue';select.disabled=!people.length;
}
function updateDraftLink(){
 const repo=$('github-draft-repo').value,open=$('github-draft-open'),assignee=$('github-draft-assignee').value;open.hidden=draftFormat!=='issue'||!repo;
 if(!open.hidden)open.href='https://github.com/'+repo+'/issues/new?'+new URLSearchParams({title:$('github-draft-issue-title').value,body:$('github-draft-body').value,...(assignee?{assignees:assignee}:{}),...(draftLatest?.labels?.length?{labels:draftLatest.labels.join(',')}:{})});
}
$('github-draft-assignee').onchange=()=>{const select=$('github-draft-assignee');select.dataset.chosen=select.value||'-';updateDraftLink();};
async function copyText(text){
 try{await navigator.clipboard.writeText(text);}catch{const area=el('textarea');area.value=text;document.body.append(area);area.select();document.execCommand('copy');area.remove();}
 toast('Copied · paste it in GitHub');
}
$('github-draft-close').onclick=()=>{captureDraft();$('github-draft-dialog').close();};
$('github-draft-dialog').addEventListener('close',captureDraft);
for(const id of ['github-draft-meeting','github-draft-speaker','github-draft-repo'])$(id).onchange=()=>{updateDraftLink();perform(renderDraft);};
$('github-draft-body').oninput=$('github-draft-issue-title').oninput=()=>{captureDraft();draftEditNotice();updateDraftLink();};
$('github-draft-preview-toggle').onclick=()=>{const area=$('github-draft-body'),view=$('github-draft-preview'),show=view.hidden;if(show)view.innerHTML=renderMarkdown(area.value);view.hidden=!show;area.hidden=show;$('github-draft-preview-toggle').textContent=show?'Back to editing':'Preview rendered text';};
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
 list.replaceChildren(...rows.map(r=>sourceRow(false,[el('span','row-tag '+(r.kind==='issue'?'issue':'pr'),r.kind==='issue'?'Issue':'PR'),el('span','row-who',r.repository.split('/')[1]),el('span','row-number','#'+r.number),el('strong','row-title',r.title),el('span','row-when',r.state)],async()=>{$('github-link-ref').value=r.repository+'#'+r.number;renderLinkResults();})));
 list.hidden=!rows.length;
}
$('github-link-ref').oninput=$('github-link-repo').onchange=renderLinkResults;
$('github-link-close').onclick=()=>$('github-link-dialog').close();
$('github-link-form').onsubmit=event=>{event.preventDefault();return perform(async()=>{
 try{await api('/api/github/link',{resource:linkResource,reference:$('github-link-ref').value,repository:$('github-link-repo').value});$('github-link-dialog').close();toast('Linked in Atlanta · GitHub is not changed');await afterGitHubLink(linkResource);}
 catch(e){showError($('github-link-error'),e.message);}});};
// Statuses come from one vocabulary (status.js).
function statusBadge(status,detail){return el('span','status-badge status-'+status.tone,status.label+(detail?' · '+detail:''));}
function workReviewBadge(state,item){return ['needs_review','edited'].includes(state)&&!(item&&item.kind==='task'&&(item.status==='done'||['done','cancelled'].includes(item.workflow_state)))?statusBadge(AtlantaStatus.status('review',state)):'';}
// The people who work on a shared task: the owner first (accountable), then the others.
function taskCoAssignees(item){return (item.assignee_person_ids||[]).slice(1).map(id=>(state.people||[]).find(p=>p.id===id)).filter(Boolean);}
function taskPeopleNames(item){return [item.owner,...taskCoAssignees(item).map(p=>p.name)].filter(Boolean);}
const openTaskFields=new Set();
function globalTaskRow(item,today,{select=true,compact=false,showProject=true}={}) {
 let compactMenu=null;
 const [kind,label]=dueInfo(item,today), row=el('div','tracked-task entity-card task-card '+kind);row.dataset.itemId=item.id;const main=el('div','tracked-main'), meta=el('div','tracked-meta'), who=el('span','tracked-owner');
 // The shared card: title with its project, one metadata row, a one-line last update, the source and the actions.
 const projects=(item.effective_project_ids||[]).map(id=>projectList().find(p=>p.id===id)).filter(Boolean);
 if(projects.length===1&&projects[0].color){row.classList.add('has-project-line');row.style.setProperty('--project-color',projects[0].color);}
 const co=taskCoAssignees(item);
 who.append(avatar(item.owner||''),...co.slice(0,3).map(p=>avatar(p.name)),el('span','',(item.owner||'No owner')+(co.length?' +'+co.length:'')));
 // A shared task names its owner as accountable and the others apart.
 if(co.length){who.classList.add('shared');who.title='Owner (accountable): '+(item.owner||'none')+' · Also working on it: '+co.map(p=>p.name).join(', ');who.append(el('span','badge shared-badge','Shared'));}
 if(item.owner&&!item.manual?.includes('owner')){
  if(/^SPEAKER[ _-]?\d+$/i.test(item.owner))who.append(el('span','hint','Unidentified speaker · choose an owner'));
  else if(item.acceptance_state==='proposed')who.append(el('span','hint','Suggested owner · confirmed when accepted'));
  else{const confirm=btn('quiet small-action owner-confirm','Confirm owner');confirm.title='Confirm this person as the task owner.';confirm.onclick=()=>perform(()=>changeItem(item,{owner:item.owner}));who.append(confirm);}
 }
 const title=actionBtn('quiet tracked-text task-title',item.text,()=>openTaskPanel(item.id));
 const stateName=AtlantaTasks.STATES[AtlantaTasks.workflow(item)]||'';
 meta.append(who,el('span','task-state',stateName),el('span','due-label '+kind,label),workReviewBadge(item.review_state,item));
 const update=AtlantaTasks.lastUpdate(item),mailed=emailMark(item);if(mailed&&!update)meta.append(mailed);
 if(item.legacy_unreviewed&&item.review_state!=='confirmed')meta.append(el('span','badge','Existing task · review gradually'));
 const people=state.people||[],whoName=id=>people.find(p=>p.id===id)?.name||'Not specified';

 const head=el('div','entity-top'),chips=el('div','entity-chips');for(const project of projects)chips.append(projectChip(project));head.append(title,chips);
 // A task is a title and a description; the card shows up to three lines of it, the panel shows all.
 const description=String(item.details||'').trim();
 main.append(head,...(description?[taskDescription(description)]:[]),meta);
 // The last update is a short box; Timeline holds the full text.
 if(update){const box=el('div','task-update'),last=el('p','task-last-line');last.title=update.text;last.textContent=String(update.text||'').replace(/[*_`#>\[\]]/g,'').replace(/\s+/g,' ').trim();
  box.append(el('span','task-update-label','Last update'),el('span','task-last-when',dateTime(update.at)),last);if(mailed)box.append(mailed);main.append(box);}
 const linked=taskMeetingList(item,itemsData.meetings),others=sourceChips(item,itemsData.meetings,{withMeetings:false});
 if(linked)main.append(linked);if(others.childNodes.length)main.append(others);
 if(item.acceptance_state!=='proposed'){
  const quick=el('div','task-quick-fields'),label=(text,input)=>{const l=el('label','hint',text);l.append(input);return l;};
  const stateSelect=el('select');stateSelect.setAttribute('aria-label','State for '+item.text);stateSelect.append(...Object.entries(AtlantaTasks.STATES).map(([key,name])=>option(name,key)));stateSelect.value=AtlantaTasks.workflow(item);
  const owner=el('select');owner.setAttribute('aria-label','Owner for '+item.text);owner.append(option('No owner',''),...personOptions(people));let oldOwner=item.owner_person_id||'';
  // An owner name that matches one person shows as that person, not as a second entry with the same name.
  const ownerPerson=!oldOwner&&item.owner?personFor(item.owner):null;
  if(!oldOwner&&item.owner&&!ownerPerson){owner.append(option(item.owner+' · not in People','__current__'));oldOwner='__current__';}owner.value=oldOwner||ownerPerson?.id||'';const shownOwner=owner.value;
  const due=el('input');due.type='date';due.value=item.due_date||'';due.setAttribute('aria-label','Due date for '+item.text);
  const follow=el('input');follow.type='date';follow.value=item.follow_up_date||'';follow.setAttribute('aria-label','Next follow-up for '+item.text);
  const commit=(input,previous,changes,message,undo)=>perform(async()=>{if(!validDates(row)){input.value=previous;return;}try{await withEditorSave(row,()=>changeWithUndo(item,changes,message,undo));}catch(e){input.value=previous;throw e;}});
  const ownerUndo=item.owner_person_id?{owner_person_id:item.owner_person_id}:item.owner?{owner_person_id:null,owner:item.owner}:{owner_person_id:null,owner:null};
  const dayText=(name,value)=>value?name+': '+date(value):name+' removed';
  stateSelect.onchange=()=>commit(stateSelect,AtlantaTasks.workflow(item),{workflow_state:stateSelect.value},'State: '+AtlantaTasks.STATES[stateSelect.value],{workflow_state:AtlantaTasks.workflow(item)});
  owner.onchange=()=>{if(owner.value==='__current__')return;return commit(owner,shownOwner,owner.value?{owner_person_id:owner.value}:{owner_person_id:null,owner:null},owner.value?'Owner: '+owner.selectedOptions[0].textContent:'Owner removed',ownerUndo);};
  due.onchange=()=>commit(due,item.due_date||'',{due_date:due.value||null},dayText('Due date',due.value),{due_date:item.due_date||null});
  follow.onchange=()=>commit(follow,item.follow_up_date||'',{follow_up_date:follow.value||null},dayText('Next follow-up',follow.value),{follow_up_date:item.follow_up_date||null});
  const addUpdate=actionBtn('secondary small-action','Add update',()=>openTaskPanel(item.id,{focusUpdate:true}));
  const timeline=actionBtn('quiet small-action task-timeline','Timeline',()=>openTaskPanel(item.id,{focusTimeline:true}));quick.append(label('Owner',owner),label('State',stateSelect),label('Due date',due),label('Next check',follow));
  // The card shows the task; the fields open on request and stay open across a refresh after a save.
  quick.id='task-fields-'+item.id;quick.hidden=!openTaskFields.has(item.id);
  const toggle=btn('quiet small-action task-fields-toggle','');toggle.type='button';toggle.setAttribute('aria-controls',quick.id);
  const showFields=open=>{quick.hidden=!open;toggle.textContent=open?'Hide fields':'Edit';toggle.setAttribute('aria-expanded',String(open));if(open)openTaskFields.add(item.id);else openTaskFields.delete(item.id);};
  toggle.onclick=()=>showFields(quick.hidden);showFields(!quick.hidden);
  // Add update and Timeline stay on the card: a progress note and the history are not fields to change.
  const done=doneButton(item);if(item.status!=='done'){done.classList.replace('secondary','primary');done.prepend(icon('check'));}
  const rowActions=el('div','task-row-actions');rowActions.append(done,addUpdate,timeline,toggle);main.append(rowActions,quick);
  if(compact){
   // The compact row: the title, then owner, state and due date that change in place.
   // Add update, Timeline, the next check and the rare actions are in "…".
   row.classList.add('compact-task');quick.hidden=false;quick.removeAttribute('id');
   const nextCheck=quick.lastElementChild;nextCheck.classList.add('compact-next-check');
   if(!showProject)chips.replaceChildren();
   const flags=el('div','compact-flags');
   if(['overdue','today'].includes(kind))flags.append(el('span','due-label '+kind,dueInfo(item,today)[1]));
   const review=workReviewBadge(item.review_state,item);if(review)flags.append(review);
   if(co.length)flags.append(el('span','badge shared-badge','Shared · +'+co.length));
   const mailedFlag=emailMark(item);if(mailedFlag)flags.append(mailedFlag);
   // The card in the compact view: the title, then Owner, State and Due date with their labels, then the flags.
   const ownerField=quick.firstElementChild;ownerField.classList.add('compact-owner');owner.before(avatar(item.owner||''));
   main.replaceChildren(head,quick,...(flags.childNodes.length?[flags]:[]));
   for(const b of [addUpdate,timeline]){b.classList.remove('secondary','small-action');b.classList.add('quiet');}
   compactMenu=[addUpdate,timeline,nextCheck];
  }
 }
 if(item.acceptance_state==='proposed'){const actions=el('div','action-group proposal-actions');if(item.dismissed){const restore=el('button','secondary small-action','Restore proposal');restore.onclick=()=>perform(()=>changeItem(item,{dismissed:false}));actions.append(restore);}else{const accept=el('button','primary small-action','Accept task'),edit=el('button','secondary small-action','Edit'),skip=el('button','secondary small-action','Skip proposal');accept.onclick=()=>perform(()=>changeItem(item,{acceptance_state:'accepted'}));edit.type='button';edit.onclick=()=>perform(()=>openTaskPanel(item.id));skip.onclick=()=>perform(()=>changeWithUndo(item,{dismissed:true},'Proposal skipped: '+item.text,{dismissed:false}));actions.append(accept,edit,skip);}main.append(actions);}
 const marks=el('div','task-row-marks');if(select&&item.acceptance_state!=='proposed'&&!item.dismissed){const pick=el('label','task-pick'),select=el('input');select.type='checkbox';pick.title='Select for a bulk change';select.checked=taskSelection.has(item.id);select.setAttribute('aria-label','Select task: '+item.text);select.onchange=()=>{if(select.checked){if(taskSelection.size>=100){select.checked=false;toast('Select up to 100 tasks');return;}taskSelection.set(item.id,{id:item.id,revision:item.revision});}else taskSelection.delete(item.id);renderBulkTasks();};pick.append(select,el('span','','Select'));marks.append(pick);}
 // A card without bulk selection (Projects, Prepare me) has no empty selection column.
 row.append(...(select?[marks]:[]),main);if(item.acceptance_state!=='proposed'){const more=el('details','task-more');const trigger=el('summary','overflow-trigger','...');trigger.setAttribute('aria-label','More task actions');trigger.title='More task actions';const actions=itemActions(item,row);if(compactMenu)actions.prepend(...compactMenu);more.append(trigger,actions);row.append(more);}return row;
}
function taskDescription(text){const node=el('p','task-description',text);node.title=text;return node;}
function decisionRow(item,byId) {
 const row=el('div','tracked-task decision entity-card task-card '+item.status), main=el('div','tracked-main'), meta=el('div','tracked-meta');
 // The shared card: wording with its project, the state, only the action that waits for a person, the source.
 const projects=(item.effective_project_ids||[]).map(id=>projectList().find(p=>p.id===id)).filter(Boolean);
 if(projects.length===1&&projects[0].color){row.classList.add('has-project-line');row.style.setProperty('--project-color',projects[0].color);}
 meta.append(decisionBadge(item));
 // A decision that waits for a person has one clear button; the status change stays next to it.
 if(item.status==='accepted'&&decisionState(item).action)meta.append(actionBtn('primary small-action',decisionState(item).action,()=>changeItem(item,{status:'accepted'})));
 if(item.superseded_by&&byId[item.superseded_by]) meta.append(el('span','hint','Replaced by: '+byId[item.superseded_by].text));
 for(const id of item.supersedes||[]) if(byId[id]) meta.append(el('span','hint','Replaces: '+byId[id].text));
 const next={proposed:['accepted','Accept'],accepted:['proposed','Mark as proposed'],superseded:[item.superseded_previous_status==='accepted'?'accepted':'proposed',item.superseded_previous_status==='accepted'?'Restore as accepted':'Restore as proposed']}[item.status];
 // Accept is the action that waits; Mark as proposed and Restore are rare and live in the … menu.
 const change=actionBtn(item.status==='proposed'?'primary small-action':'quiet',next[1],()=>changeItem(item,{status:next[0]}));if(item.status==='proposed')meta.append(change);
 const head=el('div','entity-top'),chips=el('div','entity-chips'),text=el('p','tracked-text',item.text);for(const project of projects)chips.append(projectChip(project));head.append(text,chips);
 main.append(head,meta,sourceChips(item,itemsData.meetings),githubActions({kind:'item',id:item.id}),historyBlock(item,itemsData.meetings),evidenceBlock(item,itemsData.meetings));
 row.append(el('span'),main);
 const more=el('details','task-more'),trigger=el('summary','overflow-trigger','...');trigger.setAttribute('aria-label','More decision actions');trigger.title='More decision actions';const menuActions=itemActions(item,row);if(item.status!=='proposed')menuActions.prepend(change);more.append(trigger,menuActions);row.append(more); return row;
}
async function loadTasks() { const busy=()=>itemEditing||editorDirty.keys().includes('inline-edit');if(busy())return;const fresh=await api('/api/items'); if(busy())return;const signature=JSON.stringify(fresh); if(signature===lastTasks) return; lastTasks=signature; itemsData=fresh; renderTasks(); }
// Source identity: every item, proposal and inbox row names where it came from.
const SOURCES={manual:['Manual',''],meeting:['Meeting','src-meeting'],gmail:['Gmail','src-gmail'],google_chat:['Chat','src-chat'],github:['GitHub','src-github'],excerpt:['Excerpt','src-meeting']};
function originChip(provider,label,open){
 const chip=el(open?'button':'span','source-chip '+(SOURCES[provider]?.[1]||''));chip.append(el('i'),el('b','',SOURCES[provider]?.[0]||provider));
 if(label)chip.append(el('span','',label));
 if(open){chip.type='button';chip.title='Open the source';chip.onclick=()=>perform(open);}
 return chip;
}
function relTime(ms){
 if(!ms)return '';const minutes=Math.round((Date.now()-ms)/60000);
 if(minutes<1)return 'now';if(minutes<60)return minutes+' min';if(minutes<24*60)return Math.round(minutes/60)+' h';
 const day=new Date(ms);return date(ms);
}
function dayLabel(ms){return date(ms);}
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
 const row=btn('source-row'+(selected?' selected':''));row.setAttribute('role','option');row.setAttribute('aria-selected',String(selected));
 row.append(...cells);row.onclick=()=>perform(onopen);return row;
}
// Arrow keys move through a source list like in a mail client.
function listKeys(list){list.onkeydown=event=>{if(event.key!=='ArrowDown'&&event.key!=='ArrowUp')return;const rows=[...list.querySelectorAll('.source-row')],at=rows.indexOf(document.activeElement),next=rows[Math.max(0,Math.min(rows.length-1,at+(event.key==='ArrowDown'?1:-1)))];if(next){event.preventDefault();next.focus();next.click();}};}
function emptyState(box,text){box.replaceChildren(el('p','source-empty',text));}
function segmentedChoice(box,choices,current,choose){
 box.replaceChildren(...choices.map(([value,label])=>{const b=btn(value===current?'selected':'',label);b.onclick=()=>choose(value);return b;}));
}
function cacheAccounts(select,button,accounts,running){
 const old=select.value;select.replaceChildren(...accounts.map(([label,value])=>option(label,value)));
 if(accounts.some(a=>a[1]===old))select.value=old;button.disabled=running||!accounts.length;
}
async function openSource(source){
 if(source.provider==='meeting')return openMeeting(source.external_id);
 if(source.provider==='manual'){toast('Your original text is saved under Sources in the task card.');return;}if($('task-panel').open){if(!(await leaveEdits()))return;$('task-panel').close();}
 if(source.remote?.authority==='conversation'){const link=(itemsData.graph?.conversation_links||[]).find(a=>a.source_id===source.id);if(link)return openAttachment(link.id);}
 if(view==='projects'){show('tasks');lastTasks='';await loadTasks();}
 if(source.provider==='gmail'){showWorkTab('gmail');await openMail(source.external_id);}
 else if(source.provider==='google_chat'){chatSpace=source.external_id.split('/messages/')[0];chatMessage=source.external_id;showWorkTab('chat');}
 else if(source.provider==='github'&&source.remote?.authority==='github_code'){
  showWorkTab('github');showGitHubSection('reports');
  try{await openRepoReport(source.remote.report_id);}catch(exc){const box=$('repo-report-detail'),snapshot=(itemsData.graph?.source_revisions||[]).find(r=>r.id===source.current_revision);box.replaceChildren(el('h3','','Saved code evidence'),el('p','hint','The local report is unavailable. Saved source evidence is kept.'),el('pre','report-source',snapshot?.text||''));const link=reportLink(source.remote.url,'Open code on GitHub');if(link)box.append(link);}
 }
 else if(source.provider==='github'){showWorkTab('github');showGitHubSection('items');await openGitHubItem(Number(source.external_id.split(':')[1]));}
}

let mailView='needs_reply',mailTimer=null,mailAIWasRunning=false,mailThread='',mailThreads=[],mailAutoSyncedAt=0,mailAIStatus={},mailAISeenJob='';
async function loadMail(){
 const status=await api('/api/gmail'),ai=await api('/api/gmail/ai');
 mailAIStatus=ai;
 const aiText=ai.running?'Email AI is reading the approved message'+(ai.model?' with '+ai.model:'')+'…':ai.error?'Email AI: '+ai.error:['complete','reused'].includes(ai.status)?mailAIResultText(ai):'';
 sourceState('gmail',status.connected,[status.account,AtlantaUX.count(status.count,'thread'),jobText(status.job),status.sync.last_sync&&'updated '+relTime(status.sync.last_sync*1000),status.sync.limited&&'first 200 threads'],status.job.error||aiText);
 $('gmail-ai-cancel').hidden=!ai.running;
 if(ai.running||ai.error)refreshJobs();
 if(!ai.running&&(mailAIWasRunning||(['complete','reused'].includes(ai.status)&&ai.job_id!==mailAISeenJob))){lastTasks='';await loadTasks();if(['complete','reused'].includes(ai.status)){mailAISeenJob=ai.job_id;toast(mailAIResultText(ai));}}
 mailAIWasRunning=ai.running;
 $('gmail-sync').disabled=!status.connected||status.job.running;$('gmail-sync').textContent=status.job.running?'Syncing…':status.job.status==='continue'?'Continue sync':'Sync';
 $('gmail-cancel').disabled=!status.job.running;
 cacheAccounts($('gmail-cache-account'),$('gmail-clear'),status.cached_accounts.map(a=>[a,a]),status.job.running);
 // The open Gmail tab keeps the cache current: a sync starts when the last one is old or did not finish.
 if(mailSyncDue(status,Date.now())){mailAutoSyncedAt=Date.now();try{await api('/api/gmail/sync',{});return loadMail();}catch(e){/* A recording or processing has priority; the next check tries again. */}}
 segmentedChoice($('gmail-filters'),[['needs_reply','Needs reply'],['waiting','Waiting for'],['all','All']],mailView,value=>{mailView=value;perform(loadMail);});
 mailThreads=status.connected?await api('/api/gmail/threads?view='+mailView):[];
 renderMailList();renderMailAI();
 if(!mailThread)emptyState($('gmail-detail'),mailThreads.length?'Choose a thread above to read it here.':'');
 if(mailTimer)clearTimeout(mailTimer);mailTimer=null;
 // While a job runs, the list updates every 2 s. Otherwise a quiet check each minute; a failed check shows no error.
 if(view==='tasks'&&workTab==='gmail')mailTimer=status.job.running||ai.running?setTimeout(()=>perform(loadMail),2000):setTimeout(()=>loadMail().catch(()=>{}),MAIL_CHECK_MS);
}
const MAIL_CHECK_MS=60000,MAIL_STALE_MS=5*60000;
function mailSyncDue(status,now){
 if(!status.connected||status.job.running||now-mailAutoSyncedAt<MAIL_STALE_MS)return false;
 const last=(status.sync?.last_sync||0)*1000;
 return !status.count||status.job.status==='continue'||!last||now-last>=MAIL_STALE_MS;
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
 const request=readers.start('mail'),thread=await api('/api/gmail/thread?id='+encodeURIComponent(key));if(!readers.current(request)||view!=='tasks'||workTab!=='gmail')return;const box=$('gmail-detail');mailThread=key;syncRoute(true);renderMailList();
 const head=el('div','reader-head'),attach=actionBtn('secondary small-action','Attach to project',()=>attachExternal('gmail',thread.id));showReaderProjects('gmail',thread.id,attach,request);
 head.append(attach,el('h3','',thread.subject),el('p','hint',AtlantaUX.count(thread.messages.length,'message')+' · cached '+relTime(thread.fetched_at*1000)+(thread.omitted?' · '+AtlantaUX.count(thread.omitted,'message')+' too large to load':thread.partial?' · only the latest 100 messages':'')));
 const body=el('div','reader-body');
 for(const message of thread.messages){
  const card=el('article','mail-message'+(message.sent?' sent':'')),top=el('div','message-top');card.dataset.threadId=thread.id;card.dataset.messageId=message.id;
  top.append(avatar(personName(message.sender)),el('strong','',personName(message.sender)),el('span','hint',dateTime(message.date)));
  if(message.identity)top.append(senderIdentityButton(message.identity,message.sender));
  card.append(top,el('p','message-text',message.body||(message.omitted?'This message is too large to load here. Open it in Gmail.':'No inline text body. Attachments are not fetched.')));
  if(message.body){
   const actions=el('div','message-actions'),suggest=el('button','secondary small-action','Suggest a task'),analyze=el('button','quiet small-action','Analyze with AI');
   suggest.onclick=()=>perform(()=>suggestTask(suggest,{provider:'gmail',id:thread.id,revision:thread.revision,message_id:message.id}));
   const status=el('p','hint gmail-message-ai-status');status.hidden=true;status.setAttribute('role','status');
   suggest.type=analyze.type='button';analyze.dataset.messageAi='';
   analyze.onclick=()=>perform(()=>analyzeMail(thread,message,analyze,status));actions.append(suggest,analyze);card.append(actions,status);
  }
  body.append(card);
 }
 box.replaceChildren(head,body);renderMailAI();body.scrollTop=body.scrollHeight;
}
function mailAIResultText(ai){const count=ai.proposal_ids?.length||0;return count?AtlantaUX.count(count,'AI suggestion')+(count===1?' is':' are')+' waiting in Suggestions.':'Analysis complete. No supported task commitments were found; no suggestions were created.';}
function renderMailAI(){
 for(const card of $('gmail-detail').querySelectorAll('.mail-message')){
  const button=card.querySelector('[data-message-ai]'),note=card.querySelector('.gmail-message-ai-status');if(!button||!note)continue;
  const selected=card.dataset.threadId===mailAIStatus.thread_id&&card.dataset.messageId===mailAIStatus.message_id;
  button.disabled=!!mailAIStatus.running;button.textContent=selected&&mailAIStatus.running?'Analyzing…':'Analyze with AI';button.setAttribute('aria-busy',String(selected&&!!mailAIStatus.running));
  note.hidden=!selected;if(!selected)continue;
  const complete=['complete','reused'].includes(mailAIStatus.status);
  note.replaceChildren(document.createTextNode(mailAIStatus.running?'Analyzing the approved message…':mailAIStatus.error|| (complete?mailAIResultText(mailAIStatus):mailAIStatus.status||'')));
  if(complete&&mailAIStatus.proposal_ids?.length){const open=btn('quiet small-action','Open Inbox');open.onclick=()=>perform(openTaskInbox);note.append(' ',open);}
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
$('gmail-clear').onclick=()=>perform(async()=>{const account=$('gmail-cache-account').value;if(await ask('Clear the local email cache for '+account+'? It can be synced again. Saved work item source quotes and archives remain.',{ok:'Clear cache',danger:true})){await api('/api/gmail/clear',{account});mailThread='';$('gmail-detail').replaceChildren();await loadMail();}});
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
 list.replaceChildren(...rows.map(s=>{const label=chatLabel(s);return sourceRow(s.name===chatSpace,[avatar(label),el('strong','row-who',label),el('span','row-tag',CHAT_TYPES[s.type]||'Chat'),el('span','row-title',s.count?AtlantaUX.count(s.count,'message'):'Not synced yet'),el('span','row-when',relTime(s.last*1000))],async()=>{chatSpace=s.name;chatMessage='';await loadChat();});}));
 if(focused)list.querySelector('.selected')?.focus();
 if(!rows.length)emptyState(list,chatSpaces.length?'No conversation matches this filter.':'No conversations yet. Open the ... menu and choose Refresh conversation list.');
}
$('chat-search').oninput=renderChatList;listKeys($('chat-spaces'));
async function renderConversation(sync){
 const key=chatSpace,request=readers.start('chat-conversation'),space=chatSpaces.find(s=>s.name===key),messages=await api('/api/chat/conversation?space='+encodeURIComponent(key));if(!readers.current(request)||chatSpace!==key||view!=='tasks'||workTab!=='chat'||!space)return;const box=$('chat-detail');syncRoute(true);
 const head=el('div','reader-head'),attach=btn('secondary small-action','Attach to project');attach.disabled=!messages.some(m=>m.available&&m.body);attach.onclick=()=>perform(()=>attachExternal('google_chat',key));showReaderProjects('google_chat',key,attach,null);head.append(attach,el('h3','',chatLabel(space)),el('p','hint',[space.participants.join(', '),(sync.last_sync?'synced '+relTime(sync.last_sync*1000):'not synced yet'),sync.limited&&'200-message limit'].filter(Boolean).join(' · ')));
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
 suggest.onclick=()=>perform(()=>suggestTask(suggest,{provider:'chat',name:m.name,revision:m.revision}));
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
$('chat-clear').onclick=()=>perform(async()=>{const account=$('chat-cache-account').value;if(await ask('Clear this local Chat account cache? Saved work item source quotes and archives remain.',{ok:'Clear cache',danger:true})){await api('/api/chat/clear',{account});chatMessage='';chatSpace='';await loadChat();}});

let ghAccount='',ghItem=0,ghTimer=null,ghWasRunning=false,ghFilter='all',ghKind='all',ghItems=[],ghState={};const ghAutoSynced=new Set();
async function loadGitHub(){
 const status=await api('/api/github'),connection=status.connection;
 if(ghAccount!==connection.account_id){ghAccount=connection.account_id;ghItem=0;ghAutoSynced.clear();$('github-detail').replaceChildren();}
 const overview=connection.connected?await api('/api/github/overview?filter='+ghFilter):{items:[],state:{}};ghItems=overview.items;ghState=overview.state;
 sourceState('github',connection.connected,['@'+connection.login,ghItems.length+' open',jobText(status.job),ghState.last_sync&&'updated '+relTime(ghState.last_sync*1000),ghState.limited&&'first 300 items'],connection.error||status.job.error);
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
 list.replaceChildren(...rows.map(r=>sourceRow(r.issue_id===ghItem,[el('span','row-tag '+(r.kind==='issue'?'issue':'pr'),r.kind==='issue'?'Issue':'PR'),el('span','row-who',r.repository.split('/')[1]),el('span','row-number','#'+r.number),el('strong','row-title',r.title),el('span','row-when',relTime(Date.parse(r.updated)))],()=>openGitHubItem(r.issue_id))));
 if(focused)list.querySelector('.selected')?.focus();
 if(!rows.length)emptyState(list,ghItems.length?'No item matches this filter.':ghState.last_sync?'Nothing open here. Good news.':ghWasRunning?'Syncing the open items…':'No cached items. Choose Sync to try again.');
}
$('github-search').oninput=$('github-repo-filter').onchange=renderGitHubList;listKeys($('github-items'));
async function openGitHubItem(key){
 const request=readers.start('github-item'),r=await api('/api/github/item?id='+key);if(!readers.current(request)||view!=='tasks'||workTab!=='github')return;ghItem=key;syncRoute(true);renderGitHubList();
 const head=el('div','reader-head'),title=el('h3','',r.title),meta=el('div','entity-meta');
 // The GitHub state and the age of the local copy are two facts: a badge and a separate note.
 meta.append(el('span','',r.repository+' #'+r.number+' · '+(r.kind==='issue'?'Issue':'Pull request')),statusBadge({tone:r.state==='open'?'muted':'ok',label:r.state?r.state[0].toUpperCase()+r.state.slice(1):'State unknown'}),r.available?el('span','','Local copy from '+dateTime(r.fetched_at*1000)):statusBadge({tone:'warn',label:'Source unavailable'}));head.append(title,meta);
 const body=el('div','reader-body');body.append(r.available&&r.body?markdownBlock(r.body):el('p','message-text',r.available?'No description.':'Access or source unavailable. Saved work item source quotes remain.'));
 const actions=el('div','reader-actions'),suggest=el('button','primary small-action','Suggest a task'),refresh=el('button','secondary small-action','Refresh'),link=el('a','secondary small-action button-link','Open on GitHub ');link.append(icon('external'));
 link.href=r.url;link.target='_blank';link.rel='noopener noreferrer';suggest.disabled=!r.available;
 suggest.onclick=()=>perform(()=>suggestTask(suggest,{provider:'github',id:key,revision:r.revision}));
 refresh.onclick=()=>perform(async()=>{await api('/api/github/refresh',{id:key});ghWasRunning=true;await loadGitHub();});
 actions.append(el('span','reader-quote','Local task status stays independent of GitHub.'),suggest,refresh,link);
 const linked=await api('/api/github/links?'+new URLSearchParams({repository:r.repository,number:String(r.number)}));
 if(linked.length){const box=el('div','linked-in-atlanta');box.append(el('h4','','Linked in Atlanta · on this Mac'));for(const l of linked)box.append(el('p','profile-row',(l.resource_kind==='deleted'?'':l.resource_kind+' · ')+l.resource_text));body.prepend(box);}
 if(readers.current(request)&&view==='tasks'&&workTab==='github')$('github-detail').replaceChildren(head,body,actions);
}
$('github-connect').onclick=()=>perform(async()=>{const token=$('github-token').value.trim();try{await api('/api/github/connect',{token});await loadGitHub();await loadRepoReports();}finally{$('github-token').value='';}});
$('github-disconnect').onclick=()=>perform(async()=>{if(!(await ask('Remove the GitHub token from this Mac? The token stays valid on GitHub until you revoke it there.',{ok:'Disconnect',danger:true})))return;await api('/api/github/disconnect',{});await loadGitHub();repoReport=null;repoReportId='';$('repo-report-detail').replaceChildren();});
$('github-connection').onclick=()=>perform(loadGitHub);
$('github-sync').onclick=()=>perform(async()=>{await api('/api/github/overview/sync',{filter:ghFilter});ghWasRunning=true;await loadGitHub();});
$('github-cancel').onclick=()=>perform(async()=>{await api('/api/github/cancel',{});await loadGitHub();});
$('github-clear').onclick=()=>perform(async()=>{if(await ask('Clear the local GitHub cache for the selected account? Saved source quotes and archives remain.',{ok:'Clear cache',danger:true})){await api('/api/github/clear',{account:$('github-cache-account').value});ghItem=0;$('github-detail').replaceChildren();await loadGitHub();}});

let ghSection='items',repoTimer=null,repoAccount='',repoReportId='',repoReport=null,repoJob={},repoLoadSequence=0;
function showGitHubSection(section){
 ghSection=section;$('github-open-items').hidden=section!=='items';$('repo-reports').hidden=section!=='reports';
 $('github-show-items').classList.toggle('selected',section==='items');$('github-show-reports').classList.toggle('selected',section==='reports');
 syncRoute(true);if(section==='reports')perform(loadRepoReports);
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
 const maximum=AtlantaUX.iso(new Date());$('report-start').max=maximum;$('report-end').max=maximum;
 if(!$('report-start').value){$('report-start').value=data.defaults.start;$('report-end').value=data.defaults.end;}
 const repos=[...new Set(ghItems.map(i=>i.repository))];$('report-repositories').replaceChildren(...repos.map(name=>option(name,name)));
 if(!data.reports.some(r=>r.id===repoReportId))repoReportId=data.reports[0]?.id||'';
 $('report-list').replaceChildren(option('Choose a saved report',''),...data.reports.map(r=>option(r.repository+' · '+r.branch+' · '+date(r.period.start)+' → '+date(r.period.end)+' · '+r.status,r.id)));$('report-list').value=repoReportId;
 $('report-collect').disabled=!!data.job.running;$('report-cancel').hidden=!data.job.running;
 if(data.job.running||data.job.error)refreshJobs();
 $('report-job-status').textContent=data.error||data.job.error||data.job.status||'';
 if(repoReportId){const selectedId=repoReportId,meta=data.reports.find(r=>r.id===selectedId);if(repoReport?.id===selectedId&&repoReport.revision===meta?.revision){if(data.job.running&&view==='tasks'&&workTab==='github'&&ghSection==='reports')repoTimer=setTimeout(()=>perform(loadRepoReports),1500);return;}const detail=await api('/api/github/reports/detail?id='+encodeURIComponent(selectedId));if(sequence!==repoLoadSequence||selectedId!==repoReportId)return;repoReport=detail;renderRepoReport();syncRoute(true);}
 else $('repo-report-detail').replaceChildren(emptyNote('Choose a repository and period to collect its changes. Collection does not send code to AI.'));
 if(data.job.running&&view==='tasks'&&workTab==='github'&&ghSection==='reports')repoTimer=setTimeout(()=>perform(loadRepoReports),1500);
}
async function openRepoReport(id){const sequence=++repoLoadSequence;repoReportId=id;$('report-list').value=id;if(!id){repoReport=null;$('repo-report-detail').replaceChildren();return;}const detail=await api('/api/github/reports/detail?id='+encodeURIComponent(id));if(sequence!==repoLoadSequence||id!==repoReportId)return;repoReport=detail;renderRepoReport();syncRoute(true);}
$('report-list').onchange=()=>perform(()=>openRepoReport($('report-list').value));
$('report-clear-all').onclick=()=>perform(async()=>{if(await ask('Delete all local repository reports, cached diffs and AI results for every cached account? Saved work item source quotes and existing archives remain.',{ok:'Clear reports',danger:true})){await api('/api/github/reports/clear',{confirmed:true});repoReportId='';repoReport=null;$('repo-report-detail').replaceChildren();toast('Local repository reports cleared');}});
$('report-cancel').onclick=()=>perform(async()=>{await api('/api/github/reports/cancel',{});await loadRepoReports();});
$('repo-report-form').onsubmit=event=>{event.preventDefault();perform(async()=>{const result=await api('/api/github/reports/collect',{repository:$('report-repository').value.trim(),branch:$('report-branch').value.trim(),start:$('report-start').value,end:$('report-end').value});repoReportId=result.report_id;await loadRepoReports();});};
async function analyzeRepoReport(){
 const id=repoReport.id,preview=await api('/api/github/reports/preview',{id}),t=preview.target;
 const approved=await ask('Send this repository snapshot to AI?\n'+repoReport.repository+' · '+repoReport.branch+'\n'+date(repoReport.period.start)+' → '+date(repoReport.period.end)+'\nEndpoint: '+t.local_ai_base_url+'\nModel: '+t.local_ai_model+' · reasoning: '+t.local_ai_reasoning+' · output: '+t.local_ai_max_tokens+'\n'+preview.parts+' parts · '+preview.characters+' characters'+(preview.omitted_parts?' · '+preview.omitted_parts+' parts excluded by the AI limit':'')+(preview.partial?'\nCollection is partial; check the coverage below.':'')+'\nCode, PR descriptions and diff context will be sent. Suggestions require review. No GitHub writes.',{ok:'Approve & analyze',cancel:'Cancel'});
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
// A finding on the shared card: the short conclusion, whether it is an observation or an AI inference, the code evidence on request, and Suggest a task.
function findingCard(f,r,busy){
 const card=el('article','entity-card finding-card'),main=el('div','entity-main'),meta=el('div','entity-meta'),text=markdownBlock(f.text);text.classList.add('finding-text');
 meta.append(statusBadge(f.certainty==='inference'?{tone:'warn',label:'AI inference'}:{tone:'muted',label:'Observation from the source'}));
 main.append(text,meta);
 if(f.evidence.length){
  const box=el('details','finding-evidence');box.append(el('summary','','Code evidence · '+f.evidence.length));
  for(const ref of f.evidence){const ev=r.evidence.find(e=>e.id===ref.id);box.append(el('blockquote','',ref.quote));const link=ev&&reportLink(ev.url,ev.filename||ev.kind);if(link)box.append(link);}
  main.append(box);
 }
 // Suggest a task opens an editable draft; nothing is saved before you accept it.
 const suggest=btn('secondary small-action','Suggest a task');suggest.disabled=busy;suggest.onclick=()=>perform(()=>suggestTask(suggest,{provider:'report',id:r.id,finding_id:f.id}));
 const actions=el('div','action-group');actions.append(suggest);main.append(actions);card.append(main);return card;
}
function renderRepoReport(){
 const r=repoReport,box=$('repo-report-detail'),expanded=new Set([...box.querySelectorAll('details[open]')].map(node=>node.querySelector('summary')?.textContent));const activeId=document.activeElement?.id;box.replaceChildren();if(!r)return;
 const busy=!!repoJob.running,head=el('div','card-heading');head.append(el('h3','',r.repository+' · '+r.branch));
 const remove=btn('quiet danger-text','Delete report');remove.disabled=busy;remove.onclick=()=>perform(async()=>{if(await ask('Delete this local report and its cached code? Saved work item source quotes and existing archives remain.',{ok:'Delete report',danger:true})){await api('/api/github/reports/delete',{id:r.id});repoReportId='';await loadRepoReports();}});head.append(remove);box.append(head);
 box.append(el('p','hint',date(r.period.start)+' → '+date(r.period.end)+' · Europe/Sofia · '+r.status));
 if(r.head){const link=reportLink('https://github.com/'+r.repository+'/commit/'+r.head,'Pinned branch head '+r.head.slice(0,8));if(link)box.append(link);}
 if(r.error)box.append(el('p','notice',r.error));
 const actions=el('div','work-actions');
 if(!r.collection_complete){const resume=btn('secondary','Continue collection');resume.disabled=busy;resume.onclick=()=>perform(async()=>{await api('/api/github/reports/collect',{id:r.id});await loadRepoReports();});actions.append(resume);}
 else {const ai=btn('primary',r.analysis?.complete?'Analyze / use cached result':'Analyze with AI');ai.disabled=busy||!r.evidence.length;ai.onclick=()=>perform(analyzeRepoReport);actions.append(ai);}
 const inbox=btn('quiet','Open Inbox');inbox.onclick=()=>perform(openTaskInbox);actions.append(inbox);box.append(actions);
 const coverage=el('details','report-coverage'),omitted=r.coverage?.omitted||[],warnings=r.coverage?.warnings||[];
 const count=Object.values(r.changes||{}).filter(c=>!c.skipped).length,partial=omitted.length||warnings.length||r.evidence.length>80;
 coverage.append(el('summary','',(partial?'Partial coverage':'Collected coverage')+' · '+count+' logical changes · '+(r.coverage?.files||0)+' files · '+r.evidence.length+' evidence parts'));
 coverage.append(el('p','hint','PRs use merge time; other commits use committer time. Historic push times and complete branch history are not reconstructed. File context is bounded. CI and deployment status are not collected; AI findings are not proof of completed work.'));
 if(r.evidence.length>80)coverage.append(el('p','notice','AI reads the first 80 parts. '+(r.evidence.length-80)+' collected parts are excluded from analysis.'));
 for(const text of warnings)coverage.append(el('p','notice',text));
 for(const entry of omitted)coverage.append(el('p','hint',entry.change+' · '+entry.file+' · '+entry.reason));box.append(coverage);
 const association=el('div','work-actions'),meeting=el('select');meeting.setAttribute('aria-label','Link report to a meeting');meeting.append(option('No linked meeting',''),...(state.meetings||[]).map(m=>option(m.title,m.id)));meeting.value=r.meeting_id||'';
 const linkMeeting=btn('secondary','Link meeting');linkMeeting.disabled=busy;linkMeeting.onclick=()=>perform(async()=>{repoReport=await api('/api/github/reports/associate',{id:r.id,meeting_id:meeting.value||null});renderRepoReport();});association.append(meeting,linkMeeting);
 if(r.meeting_id){association.append(openMeetingBtn('Open linked meeting',r.meeting_id));}box.append(association);
 if(r.related_items?.length){const related=el('section','report-findings');related.append(el('h4','','Related work (same repository or linked meeting)'));for(const item of r.related_items)related.append(el('p','hint',item.kind+' · '+item.status+' · '+item.text));const open=btn('quiet','Open My Work');open.onclick=()=>{sourceFilter='';showWorkTab('task');};related.append(open);box.append(related);}
 if(r.analysis){box.append(el('p','hint','AI interpretation · '+r.analysis.target.local_ai_model+' · '+r.analysis.target.local_ai_base_url+' · '+Object.keys(r.analysis.parts).length+' parts completed. Check conclusions against their source.'));
  const findings=r.analysis.summary||reportFindings(r.analysis.parts);
  if(r.analysis.metrics)box.append(el('p','hint',r.analysis.metrics.worker_steps+' AI worker steps · '+Math.round(r.analysis.metrics.elapsed_seconds||0)+' s measured processing time'));
  if(r.analysis.summary_omitted_sources)box.append(el('p','notice','Overall summary has bounded coverage; '+r.analysis.summary_omitted_sources+' source passages are omitted. Review all group findings below.'));
  if(r.analysis.summary){const groups=el('details','report-groups');groups.append(el('summary','','Per-change findings'));groups.ontoggle=()=>{if(groups.open&&groups.children.length===1)for(const f of reportFindings(r.analysis.parts))groups.append(findingCard(f,r,busy));};box.append(groups);}
  const groups={change:'What changed',impact:'Practical effect',risk:'Risks and uncertainties',verification:'Checks to make',follow_up:'Suggested follow-ups'};
  if(!findings.length)box.append(el('p','empty-note',r.analysis.complete?'Analysis complete. No supported findings were returned.':'No completed analysis parts yet.'));
  for(const [kind,title] of Object.entries(groups)){
   const rows=findings.filter(f=>f.kind===kind);if(!rows.length)continue;const section=el('section','report-findings');section.append(el('h4','',title));
   for(const f of rows)section.append(findingCard(f,r,busy));box.append(section);
  }
 }
 const sources=el('details','report-sources');sources.append(el('summary','','Collected evidence · '+r.evidence.length));
 for(const ev of r.evidence){const entry=el('details');entry.append(el('summary','',ev.filename||ev.kind),el('pre','report-source',ev.text));const link=reportLink(ev.url,'Open on GitHub');if(link)entry.append(link);sources.append(entry);}box.append(sources);for(const node of box.querySelectorAll('details'))if(expanded.has(node.querySelector('summary')?.textContent))node.open=true;if(activeId)document.getElementById(activeId)?.focus({preventScroll:true});
}

// A long saved quote shows a few lines first; the full text is one click away.
function evidenceQuote(quote){const block=el('blockquote','',quote);if(quote.length<=320)return[block];
 const clamp=()=>{block.textContent=quote.slice(0,320).replace(/\s+\S*$/,'')+'…';};clamp();
 const more=btn('quiet small-action','Show more');more.setAttribute('aria-expanded','false');
 more.onclick=()=>{if(block.textContent===quote){clamp();more.textContent='Show more';more.setAttribute('aria-expanded','false');}else{block.textContent=quote;more.textContent='Show less';more.setAttribute('aria-expanded','true');}};
 return[block,more];}
let proposalFilter='pending';
// The proposal lists render inside the Inbox view; the nodes are captured once because renderTasks re-parents them on every render.
const proposalFiltersEl=$('proposal-filters'),proposalListEl=$('proposal-list'),meetingProposalListEl=$('meeting-proposal-list');
// A meeting mention that may be an existing task: what was said, the suggested task, why, and the result of each choice.
const MATCH_PRIMARY={existing_mention:['link','Link to this task'],existing_update:['update','Add the update'],proposed_change:['change','Apply the checked changes'],uncertain:['link','Link to the chosen task']};
function meetingMatchCard(p,ev){
 const m=p.match,card=el('div','work-proposal meeting-match'),byId=Object.fromEntries(itemsData.items.map(i=>[i.id,i]));
 const top=el('div','proposal-top');top.append(originChip('meeting',meetingLabel(m.meeting_id,itemsData.meetings),()=>openMeeting(m.meeting_id)),el('span','hint',(m.basis==='ai'?'AI suggestion':'Close wording')+' · '+(m.field==='updates'?'update':'task')));
 card.append(top,el('p','hint','Said in the meeting'),el('strong','proposal-text',p.text));
 if(ev)card.append(...evidenceQuote(ev.quote));
 const review=(action,extra={})=>graphAction('meeting-review',{id:p.id,revision:p.revision,action,...extra});
 const facts=t=>[t.owner||'No owner',AtlantaTasks.STATES[AtlantaTasks.workflow(t)],t.due_date&&'due '+date(t.due_date)].filter(Boolean).join(' · ');
 // The suggested task, or for an uncertain match a choice between the candidates.
 const ids=m.type==='uncertain'?[...new Set([m.task_id,...(m.candidates||[])].filter(id=>byId[id]))]:[m.task_id].filter(id=>byId[id]);
 let chosen=ids[0];const targets=el('div','match-targets');
 for(const id of ids){const t=byId[id],row=el('label',ids.length>1?'checkbox match-target':'match-target');
  if(ids.length>1){const radio=el('input');radio.type='radio';radio.name='match-'+p.id;radio.value=id;radio.checked=id===chosen;radio.onchange=()=>{chosen=id;};row.append(radio);}
  const open=btn('quiet small-action','Open task');open.onclick=event=>{event.preventDefault();perform(()=>openTaskPanel(id));};
  row.append(el('span','',(ids.length>1?'':'Suggested task: ')+t.text),el('span','hint',facts(t)),open);targets.append(row);}
 if(!ids.length)targets.append(el('p','hint','The suggested task is no longer available. Choose another task or make a new one.'));
 card.append(targets);if(m.reason)card.append(el('p','hint','Why: '+m.reason));
 let update=null;const checks=[];
 if(m.type==='existing_update'){update=el('textarea');update.rows=2;update.value=m.update_text||'';update.setAttribute('aria-label','Update to add');const l=el('label','','Update to add to the task history');l.append(update);card.append(l);}
 if(m.type==='proposed_change'&&byId[m.task_id]){const t=byId[m.task_id],box=el('div','link-changes');box.append(el('p','hint','The meeting proposed a change. Check only what should change:'));
  const show=(field,value)=>value==null||value===''?'none':field==='due_date'?date(value):field==='workflow_state'?AtlantaTasks.STATES[value]||value:value;
  for(const c of m.changes||[]){const now=c.field==='workflow_state'?AtlantaTasks.workflow(t):t[c.field];const line=el('label','checkbox link-change'),check=el('input');check.type='checkbox';check.value=c.field;
   line.append(check,document.createTextNode(({owner:'Owner',due_date:'Due date',workflow_state:'State'})[c.field]+': '+show(c.field,now)+' → '+show(c.field,c.value)));box.append(line);checks.push(check);}card.append(box);}
 const actions=el('div','work-actions');
 if(p.state==='pending'){
  const [action,label]=MATCH_PRIMARY[m.type]||MATCH_PRIMARY.uncertain;
  if(ids.length){const primary=btn('primary small-action',label);primary.onclick=()=>perform(async()=>{const t=byId[chosen];
   await review(action,{task_id:t.id,task_revision:t.revision,...(action==='update'?{update_text:update.value}:{}),...(action==='change'?{fields:checks.filter(c=>c.checked).map(c=>c.value)}:{})});});actions.append(primary);
   if(action!=='link'){const plain=btn('secondary small-action','Link only');plain.title='Link the meeting as evidence. Nothing else changes.';plain.onclick=()=>perform(()=>review('link',{task_id:byId[chosen].id,task_revision:byId[chosen].revision}));actions.append(plain);}}
  const other=el('select');other.setAttribute('aria-label','Other task');other.append(option('Other task…',''),...itemsData.items.filter(i=>i.kind==='task'&&i.acceptance_state!=='proposed'&&!i.dismissed&&!ids.includes(i.id)).map(i=>option(i.text.slice(0,90),i.id)));
  other.onchange=()=>{const t=byId[other.value];if(t)perform(()=>review('other',{task_id:t.id,task_revision:t.revision}));};actions.append(other);
  if(m.field==='tasks')actions.append(actionBtn('secondary small-action','New task',()=>review('new')));
  actions.append(actionBtn('quiet small-action','Reject',()=>review('reject')));
 }else if(p.state==='stale'){const open=btn('secondary small-action','Open meeting');open.onclick=()=>perform(()=>openMeeting(m.meeting_id));const dismiss=btn('secondary small-action','Dismiss');dismiss.onclick=()=>perform(()=>review('reject'));actions.append(el('span','hint','The notes changed after this proposal'),open,dismiss);}
 else actions.append(el('span','hint',p.state==='linked'?'Linked':p.state==='accepted'?'New task':p.state));
 card.append(actions);return card;
}
async function graphAction(action,body){await api('/api/work/'+action,body);await refreshAfterItemChange();}
function renderWorkGraph(){
 proposalCursor=-1;
 const graph=itemsData.graph||{},today=state.task_summary?.today||new Date().toLocaleDateString('en-CA');
 const sources=Object.fromEntries((graph.sources||[]).map(s=>[s.id,s])),evidence=Object.fromEntries((graph.source_evidence||[]).map(e=>[e.id,e]));
 proposalFiltersEl.replaceChildren();
 for(const value of ['pending','stale','snoozed','dismissed','all']){const b=el('button',proposalFilter===value?'selected':'',value[0].toUpperCase()+value.slice(1));b.onclick=()=>{proposalFilter=value;renderTasks();};proposalFiltersEl.append(b);}
 meetingProposalListEl.replaceChildren();proposalListEl.replaceChildren();
 const proposals=(graph.proposals||[]).filter(p=>proposalFilter==='all'||(proposalFilter==='dismissed'?p.state==='dismissed':proposalFilter==='stale'?p.state==='stale':p.state==='pending'&&(proposalFilter==='snoozed'?p.snoozed_until>today:!p.snoozed_until||p.snoozed_until<=today)));
 for(const p of proposals){
  if(itemKind==='task'&&managerView==='inbox'&&stored('task-search')&&!p.text.toLowerCase().includes(stored('task-search').toLowerCase()))continue;
  if(p.origin==='meeting_match'&&p.match){meetingProposalListEl.append(meetingMatchCard(p,evidence[p.evidence_id]));continue;}
  const card=el('div','work-proposal'),ev=evidence[p.evidence_id],source=sources[ev?.source_id];
  const top=el('div','proposal-top');top.append(source?originChip(source.provider,sourceLabel(source),()=>openSource(source)):originChip('','Unavailable source'),el('span','hint',(['gmail_ai','repo_ai'].includes(p.origin)?'AI suggestion · ':'')+p.kind+' · '+(p.state==='stale'?'stale · the source changed':p.state)+(p.snoozed_until?' · snoozed until '+p.snoozed_until:'')));
  card.append(top,el('strong','proposal-text',p.text));
  if(p.fields&&Object.keys(p.fields).length)card.append(el('p','hint',Object.entries(p.fields).map(([name,value])=>(name==='due_date'?'Due date':name==='owner'?'Owner':'Deadline')+': '+(name==='due_date'?date(value):value)).join(' · ')));
  if(source?.remote?.authority==='github')card.append(el('p','hint','GitHub '+(source.remote.kind==='pull_request'?'PR':'issue')+' state: '+source.remote.state+' · local task status is independent'+(!source.available?' · Source unavailable':'')));
  if(ev){card.append(...evidenceQuote(ev.quote),el('p','hint',(source?source.account:'Unavailable source')+' · saved revision '+ev.source_revision.slice(0,12)));}
  const actions=el('div','work-actions'),review=(action,extra={})=>graphAction('review',{id:p.id,revision:p.revision,action,...extra}).then(()=>toast(action==='accept'?'Accepted: '+p.text.slice(0,120):action==='link'?'Linked: '+p.text.slice(0,120):action==='dismiss'?'Proposal dismissed':action==='restore'?'Proposal restored':extra.snoozed_until?'Snoozed until '+date(extra.snoozed_until):'Snooze cleared'));
  const button=(label,run,kb)=>{const b=el('button','secondary small-action',label);if(kb)b.dataset.kb=kb;b.onclick=()=>perform(run);actions.append(b);return b;};
  if(p.state==='pending'){
   button('Edit & accept',()=>{const title=card.querySelector('.proposal-text');inlineEdit(title,p.text,async value=>{await review('accept',{text:value});},p.kind+' text');});
   button('Accept',()=>review('accept'),'accept');actions.lastChild.className='primary small-action';
   const select=el('select');select.setAttribute('aria-label','Link proposal to existing item');select.append(option('Link to existing…',''),...itemsData.items.filter(i=>i.kind===p.kind).map(i=>option(i.text,i.id)));actions.append(select);
   button('Link',async()=>{const target=itemsData.items.find(i=>i.id===select.value);if(!target){toast('Choose an existing item');return;}await review('link',{target_id:target.id,target_revision:target.revision});});
   button(p.snoozed_until?'Unsnooze':'Snooze',async()=>{if(p.snoozed_until)return review('snooze',{snoozed_until:null});const day=new Date();day.setDate(day.getDate()+1);const value=await askDate('Snooze proposal until dd.mm.yyyy',AtlantaUX.iso(day));if(value!==null)await review('snooze',{snoozed_until:value});},'snooze');
   button('Skip proposal',()=>review('dismiss'),'dismiss');
  }else if(p.state==='stale'){if(source)button('Open source',()=>openSource(source));button('Dismiss',()=>review('dismiss'),'dismiss');}
  else if(p.state==='dismissed')button('Restore',()=>review('restore'),'restore');
  if(p.result_id)actions.append(el('span','hint','Item '+p.result_id));
  card.append(actions);proposalListEl.append(card);
 }
 const questions=$('work-questions');questions.replaceChildren();
 renderMeetingQuestions(questions);
 const tracked=itemsData.items.filter(i=>i.kind==='question');
 if(tracked.length)questions.append(el('h3','','Tracked questions'));
 for(const q of tracked)questions.append(trackedQuestionCard(q));
 if(!questions.children.length)questions.append(el('p','hint','No questions yet. Questions from meeting notes appear here. You can also add one.'));
}
// Single keys review the Inbox once a card is chosen: j/k move, a accept, s snooze, d dismiss, r restore.
let proposalCursor=-1;
function proposalKeys(event){
 if(event.ctrlKey||event.metaKey||event.altKey||event.target?.closest?.('input,textarea,select,[contenteditable]')||document.querySelector('dialog[open]'))return;
 if(view!=='tasks'||workTab!=='task'||managerView!=='inbox')return;
 const cards=[...meetingProposalListEl.querySelectorAll('.work-proposal'),...proposalListEl.querySelectorAll('.work-proposal')];
 if(!cards.length)return;
 if(event.key==='j'||event.key==='k'){const delta=event.key==='j'?1:-1;proposalCursor=Math.min(cards.length-1,Math.max(0,(proposalCursor<0?delta>0?-1:0:proposalCursor)+delta));cards.forEach((card,index)=>card.classList.toggle('kb-focus',index===proposalCursor));cards[proposalCursor].scrollIntoView({block:'nearest'});event.preventDefault();return;}
 const action=proposalCursor>=0&&proposalCursor<cards.length?{a:'accept',s:'snooze',d:'dismiss',r:'restore'}[event.key]:null;
 if(action){const button=cards[proposalCursor].querySelector('[data-kb="'+action+'"]');if(button&&!button.disabled){button.click();event.preventDefault();}}
}
document.addEventListener('keydown',proposalKeys);
// A tracked question: the shared card in My Work and in a project.
function trackedQuestionCard(q){
  const row=el('div','entity-card question-card'),main=el('div','entity-main'),top=el('div','entity-top'),meta=el('div','entity-meta'),chips=el('div','entity-chips'),qText=el('p','question-text',q.text);
  const projects=(q.effective_project_ids||[]).map(id=>projectList().find(p=>p.id===id)).filter(Boolean);for(const project of projects)chips.append(projectChip(project));
  if(projects.length===1&&projects[0].color){row.classList.add('has-project-line');row.style.setProperty('--project-color',projects[0].color);}
  // Edit and Delete are rare; they share the … menu.
  const [edit,menu]=editDeleteButtons(q,qText);edit.classList.remove('quiet');menu.querySelector('.menu-items')?.prepend(edit);
  top.append(qText,chips,menu);
  meta.append(statusBadge(q.status==='answered'?{tone:'ok',label:'Answered'}:{tone:'muted',label:'Open'}));const origin=questionOrigin(q.origin);if(origin)meta.append(el('span','',origin.replace(/^ · /,'')));
  main.append(top,meta);if(q.answer)main.append(el('p','question-answer',q.answer));
  const b=el('button','secondary small-action',q.status==='answered'?'Reopen':'Mark answered…');b.onclick=()=>perform(async()=>{const answer=q.status==='answered'?null:await ask('Answer: '+q.text,{ok:'Save answer',value:''});if(q.status!=='answered'&&answer===null)return;await graphAction('question',{id:q.id,revision:q.revision,answer});});
  const actions=el('div','action-group');actions.append(b);main.append(actions,projectAssignment(q),githubActions({kind:'item',id:q.id}),historyBlock(q,itemsData.meetings),evidenceBlock(q,itemsData.meetings));row.append(main);return row;
}
// The questions in meeting notes: the same list as Prepare me, from every meeting. Track or answer one to keep it here.
function questionOrigin(origin){const meeting=origin&&itemsData.meetings?.[origin.meeting_id];return meeting?' · '+withDate(meeting.title,meeting.date):'';}
function renderMeetingQuestions(target){
 const list=itemsData.meeting_questions||[];if(!list.length)return;
 target.append(el('h3','','From meeting notes'),el('p','hint','Questions that the notes of your meetings left open. Answer one, or track it to answer later.'));
 for(const q of list){
  const meeting=itemsData.meetings?.[q.meeting_id],row=el('div','entity-card question-card meeting-question'),main=el('div','entity-main'),top=el('div','entity-top'),meta=el('div','entity-meta'),actions=el('div','action-group');
  const source={meeting_id:q.meeting_id,evidence_timestamp:q.evidence_timestamp||null};
  top.append(el('p','question-text',q.text),rowMenu('More actions for this question',btn('quiet','Open meeting',()=>perform(()=>openMeeting(q.meeting_id)))));
  meta.append(statusBadge(q.kind==='decide'?{tone:'warn',label:'Needs your decision'}:{tone:'muted',label:'Open question'}),el('span','',meeting?withDate(meeting.title,meeting.date):'Meeting'));
  if(q.evidence_timestamp&&meeting?.has_audio)meta.append(listenButton(q.meeting_id,stampSeconds(q.evidence_timestamp),{label:q.evidence_timestamp,className:'quiet'}));
  actions.append(btn('secondary small-action','Mark answered…',()=>perform(async()=>{const answer=await ask('Answer: '+q.text,{ok:'Save answer',value:''});if(answer===null)return;await graphAction('question',{text:q.text,source,answer});toast('Answer saved');})),
   btn('secondary small-action','Track',()=>perform(async()=>{await graphAction('question',{text:q.text,source});toast('Question tracked in My Work');})));
  main.append(top,meta,actions);row.append(main);target.append(row);
 }
}
$('new-work-question').onclick=()=>perform(async()=>{const value=await ask('New question',{ok:'Add question',value:''});if(value!==null)await graphAction('question',{text:value});});

let bulkSaving=false,taskSelection=new Map(),taskVisibleRows=[],bulkPending=null,taskWorkflow=stored('tasks-workflow')||'',taskSearchTimer=null;
// Assigned by me is gone (2026-11-12): nobody sets Assigned by now. A saved choice of it shows All tasks.
let managerView=['inbox','mine','followup','all'].includes(stored('manager-view'))?stored('manager-view'):'all',managerSelf=stored('manager-self')||'';
function renderManagerControls(){
 if(managerSelf&&!(state.people||[]).some(p=>p.id===managerSelf)){managerSelf='';store('manager-self','');}
 const controls=$('manager-controls');controls.replaceChildren();const person=el('select');person.setAttribute('aria-label','This is me');person.append(option('Choose who you are',''),...(state.people||[]).map(p=>option(p.name,p.id)));person.value=managerSelf;
 person.onchange=()=>{managerSelf=person.value;store('manager-self',managerSelf);renderTasks();};const label=el('label','hint manager-identity','This is me');label.append(person);label.hidden=managerView==='inbox';controls.append(label);
 const views=el('div','manager-views');views.setAttribute('role','group');views.setAttribute('aria-label','Task views');
 for(const [key,title] of [['inbox','Inbox'],['mine','My tasks'],['followup','Follow-up'],['all','All tasks']]){const button=btn('manager-view-button'+(managerView===key?' selected':''),title);button.setAttribute('aria-pressed',String(managerView===key));button.onclick=()=>{managerView=key;store('manager-view',key);renderTasks();};views.append(button);}controls.append(views);
 const search=el('input');search.type='search';search.placeholder='Search tasks';search.setAttribute('aria-label','Search tasks');search.value=stored('task-search')||'';search.oninput=()=>{clearTimeout(taskSearchTimer);taskSearchTimer=setTimeout(()=>{store('task-search',search.value);renderTasks();const fresh=$('manager-controls')?.querySelector('input[type=search]');if(fresh){fresh.focus();fresh.setSelectionRange(fresh.value.length,fresh.value.length);}},200);};controls.append(search);
 const filters=$('manager-person-filters');filters.replaceChildren();filters.hidden=itemKind!=='task';
 if(managerView!=='inbox'){
  const field=el('select');field.setAttribute('aria-label','Task state filter');field.append(option('Any state',''),...Object.entries(AtlantaTasks.STATES).map(([key,label])=>option(label,key)));field.value=taskWorkflow;field.onchange=()=>{taskWorkflow=field.value;store('tasks-workflow',taskWorkflow);if(taskWorkflow){statusFilter.task=taskWorkflow==='done'?'done':taskWorkflow==='cancelled'?'all':'open';store('tasks-status',statusFilter.task);}renderTasks();};filters.append(field);
 }
}

async function sendBulkTasks(body){
 if(bulkSaving)return;bulkSaving=true;
 try{
  await withEditorSave($('task-bulk-bar'),async()=>{try{await api('/api/items/bulk',body);}catch(e){if(e.status>=400&&e.status<500){bulkPending=null;taskSelection.clear();}throw e;}});
  taskSelection.clear();bulkPending=null;toast(AtlantaUX.count(body.items.length,'task')+' updated on this Mac');
 }finally{bulkSaving=false;renderBulkTasks();}
 await refreshAfterItemChange();
}
// The task list is compact by default; the detailed cards are the other view. A compact list selects tasks on request.
let taskDensity=(()=>{try{return localStorage.getItem('task-density')==='cards'?'cards':'compact';}catch{return 'compact';}})(),taskSelecting=false;
function renderBulkTasks(){
 const box=$('task-bulk-bar');box.replaceChildren();box.hidden=itemKind!=='task'||managerView==='inbox'||(!taskVisibleRows.length&&!taskSelection.size&&!bulkPending);if(box.hidden)return;
 const views=el('div','segmented task-density');views.setAttribute('role','group');views.setAttribute('aria-label','Task view');
 for(const [key,name] of [['compact','Compact'],['cards','Cards']]){const b=btn(taskDensity===key?'selected':'',name);b.setAttribute('aria-pressed',String(taskDensity===key));b.onclick=()=>{taskDensity=key;try{localStorage.setItem('task-density',key);}catch{}renderTasks();};views.append(b);}
 box.append(views);
 if(taskDensity==='compact'&&!taskSelection.size&&!bulkPending){
  const start=btn('secondary small-action',taskSelecting?'Done selecting':'Select tasks');start.setAttribute('aria-pressed',String(taskSelecting));start.onclick=()=>{taskSelecting=!taskSelecting;renderTasks();};box.append(start);
  if(!taskSelecting)return;
 }
 const count=bulkPending?.items.length||taskSelection.size,choose=el('button','secondary small-action','Select shown tasks'),clear=el('button','secondary small-action','Clear selection');choose.type=clear.type='button';
 choose.onclick=()=>{for(const item of taskVisibleRows.filter(i=>i.acceptance_state!=='proposed'&&!i.dismissed).slice(0,100))taskSelection.set(item.id,{id:item.id,revision:item.revision});renderTasks();};clear.onclick=()=>{taskSelection.clear();bulkPending=null;renderTasks();};
 box.append(choose,el('strong','',count+' selected'));if(!count)return;box.append(clear);
 if(bulkPending){choose.disabled=true;const retry=actionBtn('secondary','Retry the same update',()=>sendBulkTasks(bulkPending));box.append(el('p','notice','The previous result is uncertain. Retry the exact approved update, or clear the selection and inspect the list.'),retry);return;}
 const action=el('select');action.setAttribute('aria-label','Bulk field');action.append(option('Change state','workflow_state'),option('Change owner','owner_person_id'),option('Set due date','due_date'),option('Set next follow-up','follow_up_date'));
 const input=el('span'),apply=el('button','secondary','Apply to '+AtlantaUX.count(count,'selected task')),note=el('span','hint','Only the selected tasks on this list. Saved locally; nothing is sent.');apply.type='button';let value;
 function editor(){input.replaceChildren();if(action.value==='workflow_state'){value=el('select');value.append(...Object.entries(AtlantaTasks.STATES).map(([key,label])=>option(label,key)));}
 else if(action.value==='owner_person_id'){value=el('select');value.append(option('No owner',''),...personOptions());}
 else{value=el('input');value.type='date';}value.setAttribute('aria-label','Bulk value');input.append(value);}
 action.onchange=editor;editor();
 apply.onclick=()=>perform(async()=>{
  if(bulkSaving||!validDates(box))return;
  bulkSaving=true;apply.disabled=true;try{
  const changes={[action.value]:value.value||null};if(action.value==='owner_person_id'&&!value.value)changes.owner=null;
  const body={items:[...taskSelection.values()],changes,request_id:bulkPending?.request_id||crypto.randomUUID().replaceAll('-','')};
  if(bulkPending&&JSON.stringify({...body,request_id:''})!==JSON.stringify({...bulkPending,request_id:''}))throw new Error('Previous result uncertain. Retry the same action, or clear the selection and check the list.');
  const summary=action.selectedOptions[0].textContent+': '+(value.tagName==='SELECT'?value.selectedOptions[0]?.textContent:value.value?date(value.value):'Clear date');
  if(!(await ask(summary+' for '+body.items.length+' selected tasks?\n'+taskVisibleRows.filter(t=>taskSelection.has(t.id)).slice(0,6).map(t=>'• '+t.text).join('\n')+(body.items.length>6?'\n…':''),{ok:'Apply to '+body.items.length,cancel:'Cancel'})))return;
  bulkPending=body;bulkSaving=false;await sendBulkTasks(body);
  }finally{bulkSaving=false;apply.disabled=false;}
 });
 const mail=btn('secondary','Send by email…');mail.type='button';mail.title='One Gmail draft with all selected tasks. Each task gets the envelope mark.';
 mail.onclick=()=>perform(()=>openTaskEmail([...taskSelection.keys()]));
 box.append(action,input,apply,mail,note);
}
// Only the Tasks and Decisions tabs show task counts; the other tabs keep their own subtitle.
function taskSummary(text){if(['task','decision'].includes(workTab))$('tasks-summary').textContent=text;}
function renderTasks() {
 if(itemEditing||bulkSaving)return;
 const untitled=(itemsData.items||[]).filter(untitledTask).length;$('task-titles-open').hidden=!untitled;$('task-titles-open').textContent='Add titles · '+untitled;
 renderWorkGraph();renderManagerControls();$('manager-controls').hidden=itemKind!=='task';
 const today=state.task_summary?.today||new Date().toISOString().slice(0,10), meetings=itemsData.meetings, byId=Object.fromEntries(itemsData.items.map(item=>[item.id,item]));
 const project=$('work-project'), oldProject=project.value||stored('tasks-project')||'';
 project.replaceChildren(option('All projects',''),option('Unassigned','__none__'),...(state.projects?.projects||[]).map(p=>option(p.name,p.id)));
 if([...project.options].some(o=>o.value===oldProject))project.value=oldProject;
 const inbox=itemKind==='task'&&managerView==='inbox';
 const inProject=item=>inbox||!project.value||(project.value==='__none__'?!item.effective_project_ids?.length:item.effective_project_ids?.includes(project.value));
 const context={self:managerSelf,people:state.people||[],today,search:stored('task-search')||''};
 const tasks=itemsData.items.filter(item=>item.kind==='task'&&inProject(item)&&AtlantaTasks.inView(item,managerView,{...context,proposalFilter})), decisions=itemsData.items.filter(item=>item.kind==='decision'&&inProject(item));
 const open=tasks.filter(t=>t.acceptance_state!=='proposed'&&t.workflow_state!=='cancelled'&&t.status==='open'&&!t.dismissed&&(!t.snoozed_until||t.snoozed_until<=today)), late=open.filter(t=>t.due_date&&t.due_date<today), pending=itemsData.pending.filter(entry=>!project.value||meetings[entry.meeting_id]?.project_id===project.value);
 const accepted=decisions.filter(d=>d.status==='accepted'&&!d.dismissed&&(!d.snoozed_until||d.snoozed_until<=today)).length;
 const noWork=!itemsData.items.length&&!itemsData.pending.length;
 taskSummary(noWork?'Your tasks and decisions from every meeting and source.':open.length+' open task'+(open.length===1?'':'s')+' · '+late.length+' overdue · '+accepted+' accepted decision'+(accepted===1?'':'s')+(pending.length?' · '+pending.length+' to review':''));
 if(itemKind==='task'&&managerView==='inbox'&&!noWork)taskSummary(state.settings?.meeting_task_ai?(meetingProposalListEl.children.length+tasks.length)+' from meetings · '+proposalListEl.children.length+' from sources':AtlantaUX.count(proposalListEl.children.length,'suggestion')+' from sources');
 for(const button of document.querySelectorAll('[data-kind]')) { const count=pending.filter(p=>p.kind===button.dataset.kind).length; button.textContent=(button.dataset.kind==='task'?'Tasks':'Decisions')+(count?' · '+count+' to review':''); }
 const review=pending.filter(entry=>entry.kind===itemKind); $('link-review').hidden=!review.length; $('link-review').replaceChildren();
 if(review.length) { $('link-review').append(el('h2','',review.length+' to review'),el('p','hint','These mentions have wording close to existing items (text similarity). Nothing is linked until you choose.')); for(const entry of review) $('link-review').append(linkCard(entry,meetings,byId)); }
 const noKindItems=!itemsData.items.some(item=>item.kind===itemKind);
 $('manager-all-filters').hidden=noKindItems||inbox;$('source-filter').hidden=noKindItems||inbox;$('status-filter').closest('.task-filters').hidden=noKindItems||inbox;document.querySelector('#items-panel .work-messages').hidden=noKindItems;
 const filter=itemKind==='task'&&managerView==='inbox'?'all':statusFilter[itemKind];
 $('status-filter').replaceChildren(...STATUS_FILTERS[itemKind].map(([key,label])=>{const button=btn(key===filter?'selected':'',label);button.onclick=()=>{statusFilter[itemKind]=key;if(itemKind==='task'){store('tasks-status',key);taskWorkflow='';store('tasks-workflow','');}renderTasks();};return button;}));
 segmentedChoice($('source-filter'),[['','All sources'],['manual','Manual'],['meeting','Meetings'],['gmail','Gmail'],['google_chat','Chat'],['github','GitHub']],sourceFilter,value=>{sourceFilter=value;store('tasks-source',value);renderTasks();});
 $('task-owner').hidden=itemKind!=='task';
 const owner=$('task-owner').value||stored('tasks-owner')||'', owners=[...new Set(tasks.flatMap(taskPeopleNames))].sort((a,b)=>a.localeCompare(b));
 $('task-owner').replaceChildren(option('All owners',''),...owners.map(name=>option(name,name)),option('No owner','__none__'));
 $('task-owner').value=[...$('task-owner').options].some(o=>o.value===owner)?owner:'';
 // The newest meeting of a task, or its creation time: a manual task sorts with recent work, not last.
 const latest=item=>[...item.links.map(link=>meetings[link.meeting_id]?.date||''),(item.created||'').slice(0,10)].sort().at(-1)||'';
 let rows;
 const personal=item=>filter==='snoozed'?!!item.snoozed_until&&item.snoozed_until>today&&!item.dismissed:filter==='dismissed'?!!item.dismissed:filter==='all'||!item.dismissed&&(!item.snoozed_until||item.snoozed_until<=today);
 if(itemKind==='task') rows=tasks.filter(personal).filter(t=>['all','snoozed','dismissed'].includes(filter)||(filter==='done'?t.status==='done':t.status==='open'&&(filter==='open'&&t.workflow_state!=='cancelled'||t.workflow_state!=='cancelled'&&t.due_date&&t.due_date<today)))
  .filter(t=>inbox||!$('task-owner').value||($('task-owner').value==='__none__'?!t.owner:taskPeopleNames(t).includes($('task-owner').value)))
  .sort((a,b)=>(a.status===b.status?0:a.status==='open'?-1:1)||(a.due_date||'9999').localeCompare(b.due_date||'9999')||latest(b).localeCompare(latest(a)));
 else rows=decisions.filter(personal).filter(d=>['all','snoozed','dismissed'].includes(filter)||(filter==='current'?d.status==='accepted':d.status===filter)).sort((a,b)=>latest(b).localeCompare(latest(a)));
 if(itemKind==='task'&&managerView==='mine'&&!managerSelf)taskSummary('Choose “This is me” to show your responsibilities.');
 if(sourceFilter&&!inbox)rows=rows.filter(item=>itemProviders(item).has(sourceFilter));
 if(itemKind==='task'&&!inbox)rows=rows.filter(item=>!taskWorkflow||AtlantaTasks.workflow(item)===taskWorkflow);
 const activeFilters=[sourceFilter&&SOURCES[sourceFilter]?.[0],project.value&&project.selectedOptions[0]?.textContent,$('task-owner').value&&'Owner: '+$('task-owner').selectedOptions[0]?.textContent,itemKind==='task'&&taskWorkflow&&AtlantaTasks.STATES[taskWorkflow],filter!==(itemKind==='task'?'open':'current')&&filter].filter(Boolean);$('manager-filter-summary').textContent='Filters'+(activeFilters.length?' · '+activeFilters.join(' · '):'');
 taskVisibleRows=itemKind==='task'&&!inbox?rows:[];taskSelection=AtlantaTasks.visibleSelection(taskSelection,taskVisibleRows);renderBulkTasks();
 if(itemKind==='task'&&!inbox&&!noWork){const active=rows.filter(t=>!t.dismissed&&t.acceptance_state!=='proposed'&&!['done','cancelled'].includes(AtlantaTasks.workflow(t))&&(!t.snoozed_until||t.snoozed_until<=today));taskSummary(rows.length+' shown · '+active.length+' open · '+active.filter(t=>t.due_date&&t.due_date<today).length+' overdue');}
 $('task-list').replaceChildren();
 // The Inbox groups what waits for a decision in two queues: actions and matches from meetings first, then suggestions from connected sources.
 let rowTarget=$('task-list');
 if(inbox){
  const meetingCount=meetingProposalListEl.children.length+rows.length,sourceCount=proposalListEl.children.length,list=$('task-list');
  list.append(el('h2','','Inbox'),el('p','hint',state.settings?.meeting_task_ai?'Everything the AI proposed and waits for your decision. Accept, link or skip each one — nothing changes until you decide.':'Suggestions from Gmail, Google Chat and GitHub wait here for your decision. Accept, link or skip each one — nothing changes until you decide.'),proposalFiltersEl);
  if(meetingCount)list.append(el('h3','work-section','From meetings · '+meetingCount),meetingProposalListEl);
  if(sourceCount)list.append(el('h3','work-section','From connected sources · '+sourceCount),proposalListEl);
  if(!meetingCount&&!sourceCount){const box=el('div','empty-content no-match');box.append(el('p','','Nothing to review for this filter.'),el('p','hint',state.settings?.meeting_task_ai?'New proposals arrive after each meeting and each source sync.':'New suggestions arrive after each source sync.'));if(proposalFilter!=='pending')box.append(actionBtn('secondary small-action','Show pending',()=>{proposalFilter='pending';renderTasks();}));list.append(box);}
  rowTarget=el('div','task-rows');list.append(rowTarget);
 }

 if(!rows.length&&!inbox){if(noKindItems){const box=el('div','empty-work');box.append(el('h2','',itemKind==='task'?'No tasks yet':'No decisions yet'),el('p','',itemKind==='task'?'Add a task from your day, or collect actions from a meeting.':'Open a meeting and generate notes to review its decisions.'));if(itemKind!=='task'){const next=el('button','secondary','Open library');next.onclick=()=>perform(openConversations);box.append(next);}$('task-list').append(box);}else{
  // 0 results: the conditions that are active, and an action for each scope.
  const search=itemKind==='task'?stored('task-search')||'':'',view=itemKind==='task'&&managerView!=='all'?{inbox:'Inbox',mine:'My tasks',followup:'Follow-up'}[managerView]:'';
  const conditions=[view&&'View: '+view,...activeFilters,search&&'Search: “'+search+'”'].filter(Boolean),box=el('div','empty-content no-match');
  box.append(el('p','',itemKind==='task'?'No tasks match.':'No decisions match.'));
  if(conditions.length)box.append(el('p','hint','Active: '+conditions.join(' · ')));
  const actions=el('div','action-group'),filtered=!!view||activeFilters.length>0;
  if(filtered)actions.append(actionBtn('secondary small-action','Reset filters',()=>resetTaskFilters()));
  if(search)actions.append(actionBtn('secondary small-action','Clear search',()=>{store('task-search','');renderTasks();}));
  if(filtered&&search)actions.append(actionBtn('secondary small-action','Reset filters and search',()=>resetTaskFilters({all:true})));
  if(actions.childNodes.length)box.append(actions);$('task-list').append(box);
 }}
 const compact=taskDensity==='compact';if(itemKind==='task')rowTarget.classList.toggle('compact-list',compact);else rowTarget.classList.remove('compact-list');
 // The compact list has one header row with the column names; it lines up with the rows.
 // Each compact card labels its own fields, so the list has no column header row.
 for(const item of rows) rowTarget.append(itemKind==='task'?globalTaskRow(item,today,{compact,select:!compact||taskSelecting||taskSelection.size>0,showProject:!project.value}):decisionRow(item,byId));
}
// My Work shows one section at a time. Tasks and Decisions share one panel; each source loads when its tab opens.
const WORK_PANELS={task:'items-panel',decision:'items-panel',questions:'questions-panel',review:'review-queue-panel',gmail:'gmail-panel',chat:'chat-panel',github:'github-panel'};
let workTab='task';try{workTab=WORK_PANELS[localStorage.getItem('work-tab')]?localStorage.getItem('work-tab'):'task';}catch{}
// The Inbox is the Inbox view of the Tasks tab: everything that waits for a decision in one place.
let inboxOnPurpose=false;
function openTaskInbox(){managerView='inbox';store('manager-view','inbox');workTab='task';inboxOnPurpose=true;return $('open-tasks').onclick();}
function showWorkTab(tab){
 // Decisions are text in the meeting notes unless AI meeting items are on (2026-11-12); My Work then has no Decisions tab.
 const decisionsTab=$('work-tabs').querySelector('[data-work-tab=decision]');decisionsTab.hidden=!state?.settings?.meeting_task_ai;if(tab==='decision'&&decisionsTab.hidden)tab='task';
 if(tab==='sources')tab=stored('last-source-tab')||'gmail';if(['gmail','chat','github'].includes(tab))store('last-source-tab',tab);
 if(tab!==workTab)readers.invalidate();workTab=tab;syncRoute(true);try{localStorage.setItem('work-tab',tab);}catch{}
 for(const button of $('work-tabs').querySelectorAll('button')){const current=button.dataset.workTab===tab||button.dataset.workTab==='sources'&&['gmail','chat','github'].includes(tab);button.classList.toggle('selected',current);button.setAttribute('aria-selected',String(current));}
 $('source-tabs').hidden=!['gmail','chat','github'].includes(tab);for(const button of $('source-tabs').querySelectorAll('button')){const current=button.dataset.workTab===tab;button.classList.toggle('selected',current);button.setAttribute('aria-selected',String(current));}
 for(const id of new Set(Object.values(WORK_PANELS)))$(id).hidden=id!==WORK_PANELS[tab];
 for(const timer of [mailTimer,chatTimer,ghTimer,repoTimer])if(timer)clearTimeout(timer);mailTimer=chatTimer=ghTimer=repoTimer=null;
 if(tab==='task'||tab==='decision'){itemKind=tab;renderTasks();}
 else if(tab==='review')perform(loadReviewQueue);
 else if(tab==='gmail')perform(loadMail);else if(tab==='chat')perform(loadChat);else if(tab==='github')perform(async()=>{await loadGitHub();showGitHubSection(ghSection);});
 // The subtitle describes the tab that is shown; Tasks and Decisions set their own counts.
 const summaries={questions:()=>AtlantaUX.count((itemsData?.meeting_questions||[]).length,'question')+' from meeting notes · '+(itemsData?.items||[]).filter(i=>i.kind==='question').length+' tracked',
  review:()=>'Meetings that still wait for your review',gmail:()=>'Read-only sources on this Mac: Gmail, Chat and GitHub',chat:()=>'Read-only sources on this Mac: Gmail, Chat and GitHub',github:()=>'Read-only sources on this Mac: Gmail, Chat and GitHub'};
 if(summaries[tab])$('tasks-summary').textContent=summaries[tab]();
}
for(const button of document.querySelectorAll('#work-tabs button,#source-tabs button')) button.onclick=()=>showWorkTab(button.dataset.workTab);
// One queue for the whole library: each row opens the meeting at the step that resolves it.
async function loadReviewQueue(){
 const request=readers.start('review-queue'),data=await api('/api/review-queue');if(!readers.current(request))return;
 const count=$('review-queue-count');count.textContent=data.totals.meetings;count.hidden=!data.totals.meetings;
 if(view!=='tasks'||workTab!=='review')return;
 const box=$('review-queue');box.replaceChildren();
 if(!data.meetings.length){box.append(emptyNote('Nothing waits for review. A processed meeting appears here while it has open steps.'));return;}
 for(const row of data.meetings){
  const card=el('div','attention review-queue-row'),head=el('div','attention-head'),title=el('button','quiet review-queue-title',withDate(row.title,row.created));
  title.type='button';title.onclick=()=>row.repair?.length?openSettings('backup'):perform(()=>openMeeting(row.id));head.append(title);card.append(head);
  const add=(tone,text,label,run)=>{const line=el('div','attention-item '+tone),go=btn('secondary small-action',label);
   go.onclick=()=>perform(async()=>{await openMeeting(row.id);if(view==='detail'&&detail?.id===row.id)await run();});line.append(el('i'),el('span','',text),go);card.append(line);};
  if(row.repair?.length){const line=el('div','attention-item warn'),go=btn('secondary small-action','Open Backup settings');go.onclick=()=>openSettings('backup');line.append(el('i'),el('span','','Needs repair · '+row.repair.join(', ')+'. Original files are preserved.'),go);card.append(line);box.append(card);continue;}
  // Names change the transcript and new notes change the items, so a confirm comes last.
  if(row.speakers)add('warn','Name '+AtlantaUX.count(row.speakers,'speaker'),'Name speakers',async()=>{switchTab('transcript');$('speaker-review-container').open=true;$('speaker-review').scrollIntoView({block:'center'});});
  if(row.notes==='proposal')add('info','New AI notes are ready','Review changes',async()=>openReview());
  else if(row.notes)add('info','The transcript changed after the notes were made','Review update',async()=>{switchTab('transcript');$('primary-action').scrollIntoView({block:'center'});});
  if(row.items&&!row.review_blocked)add('warn',AtlantaUX.count(row.items,'item')+' to confirm or dismiss','Review items',async()=>switchTab('review'));
  else if(row.items){const line=el('div','attention-item info');line.append(el('i'),el('span','',AtlantaUX.count(row.items,'item')+' wait for review after the notes update'));card.append(line);}
  box.append(card);
 }
}
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
const PROJECT_PALETTE=['#5b8def','#4cb782','#e2b33c','#c9699e','#8d6fd1','#d97b54','#3fa9ad','#b15b5b'];
function projectDot(project){const dot=el('span','project-dot');if(project?.color)dot.style.background=project.color;dot.title=project?.color?'Project color':'No project color';return dot;}
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
 const edit=el('button','quiet scope-chip'); if(project?.color)edit.append(projectDot(project)); if(project)edit.append(document.createTextNode('Project: '+project.name+(series?' · '+series.name:'')+' '),icon('edit'));else edit.append(document.createTextNode('＋ Add to a project')); edit.type='button'; edit.title='Project and series of this meeting'; edit.onclick=()=>openScopeDialog(d); box.append(edit);
 const type=el('select','scope-chip scope-type'); type.setAttribute('aria-label','Meeting type'); type.title='Meeting type · changes the notes sections and Prepare me'; fillTypes(type,d.meeting_type||'general',d.meeting_template&&!typeList().some(t=>t.id===d.meeting_type)?[option(d.meeting_template.label+' · deleted template',d.meeting_type)]:[]);
 type.onchange=()=>perform(async()=>{
  const value=type.value,previous=d.meeting_type||'general',label=typeOf(value).label;
  const setType=async kind=>{const saved=await api('/api/meetings/'+d.id+'/type',{meeting_type:kind});if(detail?.id!==d.id)return;detail=saved;lastFingerprint=JSON.stringify(detail);renderDetail();};
  // Saved notes stay; new notes for the type become a proposal that the person reviews. The question comes before the change.
  let notes=false;
  if(d.minutes&&!['starting','recording','paused','stopping','processing'].includes(d.status)){
   const answer=await ask('Change the meeting type to "'+label+'"?\n\nYour saved notes stay as they are. New notes for this type are a proposal: you review each change before it is applied.',{ok:'Change and make new notes',extra:'Change type only'});
   if(!answer){type.value=previous;return;}
   notes=answer===true;
  }
  try{await setType(value);}catch(e){type.value=previous;throw e;}
  if(notes){
   if(state.settings.summarizer==='none'){toast('Meeting type saved. Choose a notes provider to make new notes.');openSettings('notes');return;}
   await api('/api/meetings/'+d.id+'/process',{action:'summarize'});await openMeeting(d.id,true);toast('Meeting type saved · new notes are being made');
  } else undoToast('Meeting type: '+label,()=>perform(async()=>{await setType(previous);toast('Undone');}));});
 const typeLabel=el('label','scope-type-label','Type');typeLabel.append(type);box.append(typeLabel);
 const instructions=btn('quiet scope-chip','AI instructions');instructions.onclick=()=>{promptRequestedScope='meeting:'+d.id;openSettings('prompts');};$('detail-secondary-actions').replaceChildren(instructions);
 if(project){const prepare=actionBtn('quiet','Prepare the next meeting',()=>openPrepare(d.project_id,d.series_id||''));$('detail-secondary-actions').append(prepare);}
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
$('scope-form').onsubmit=event=>{event.preventDefault();return perform(async()=>{
 const projectValue=$('scope-project').value, seriesValue=$('scope-series').value;
 const project=!projectValue?null:projectValue==='__new__'?{name:$('scope-project-name').value}:{id:projectValue};
 const series=!projectValue||!seriesValue?null:seriesValue==='__new__'?{name:$('scope-series-name').value}:{id:seriesValue};
 detail=await api('/api/meetings/'+selected+'/scope',{project,series}); lastFingerprint=JSON.stringify(detail);
 state=await api('/api/state'); $('scope-dialog').close(); renderState(); renderDetail(); lastLibrary=''; renderLibrary(); toast('Saved');});};
// Settings → Meeting types: the built-in types, read-only, and your own templates.
function renderTypeSettings(){
 const select=$('type-prompt-select'),wanted=select.value||'general';
 select.replaceChildren(...typeList().map(type=>option(type.label+(type.custom?' · custom':''),type.id)));select.value=typeList().some(t=>t.id===wanted)?wanted:'general';
 if(!typePromptDirty())perform(loadTypePrompt);
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
$('template-form').onsubmit=event=>{event.preventDefault();return perform(async()=>{
 const sections=[...$('template-sections').querySelectorAll('.template-section')].map(box=>({title:box.querySelector('.template-section-title').value.trim(),instruction:box.querySelector('.template-section-instruction').value.trim(),review:box.querySelector('.template-section-review').checked})).filter(s=>s.title||s.instruction);
 try{const result=await api('/api/templates/save',{id:templateEditing?.id,revision:templateEditing?.revision,label:$('template-label').value,description:$('template-description').value,prepare:$('template-prepare').value,sections});
  state.meeting_types=result.meeting_types;registerTypes();renderTypeSettings();$('template-dialog').close();toast('Saved '+result.template.label);}
 catch(e){showError($('template-error'),e.message);}});};
$('template-delete').onclick=()=>perform(async()=>{if(!templateEditing||!(await ask('Delete the template "'+templateEditing.label+'"?\n\nSaved meetings keep their notes and their copy of the template. Series that use it become General.',{ok:'Delete',danger:true})))return;
 const result=await api('/api/templates/delete',{id:templateEditing.id,revision:templateEditing.revision});state.meeting_types=result.meeting_types;state.projects=result.projects;lastProjects='';registerTypes();syncProjects();renderTypeSettings();$('template-dialog').close();toast('Template deleted');});
function renderProjectSettings() {
 const list=$('project-list'); list.replaceChildren();
 if(!projectList().length) list.append(emptyNote('No projects yet. Choose ＋ New project.'));
 const row=(kind,entry)=>{const line=el('div','scope-entry '+kind),rename=el('button','quiet','Rename'),remove=el('button','quiet danger-text','Delete');rename.type=remove.type='button';
  line.append(el(kind==='projects'?'strong':'span','',entry.name),rename,remove);
  const change=async body=>{state.projects=(await api('/api/projects/change',Object.assign({kind,id:entry.id},body))).projects;lastProjects='';syncProjects();renderProjectSettings();};
  if(kind==='series'){const type=el('select');type.setAttribute('aria-label','Default meeting type of '+entry.name);type.title='New meetings of this series start with this type';fillTypes(type,entry.type||'general');
   type.onchange=()=>perform(async()=>{const previous=entry.type||'general';await change({action:'type',name:type.value});undoToast('New meetings of "'+entry.name+'" start as '+typeOf(type.value).label,()=>perform(async()=>{await change({action:'type',name:previous});toast('Undone');}));});line.insertBefore(type,rename);}
  if(kind==='projects'){const color=el('input');color.type='color';color.className='project-color';color.value=entry.color||PROJECT_PALETTE[0];color.setAttribute('aria-label','Color of '+entry.name);color.title='Project color, shown on cards and headings';color.onchange=()=>perform(async()=>{const previous=entry.color||PROJECT_PALETTE[0];await change({action:'color',value:color.value});undoToast('Color of "'+entry.name+'" saved',()=>perform(async()=>{await change({action:'color',value:previous});toast('Undone');}));});line.insertBefore(color,rename);}
  rename.onclick=()=>perform(async()=>{const name=await ask('New name',{value:entry.name,ok:'Rename'});if(name?.trim()&&name.trim()!==entry.name)await change({action:'rename',name});});
  remove.onclick=()=>perform(async()=>{if(await ask('Delete "'+entry.name+'"'+(kind==='projects'?' and its series':'')+'?\n\nMeetings stay; they only leave this group.',{ok:'Delete',danger:true}))await change({action:'delete'});});
  return line;};
 for(const project of projectList()) { const box=el('div','project-entry'); box.append(row('projects',project),...seriesOf(project.id).map(series=>row('series',series))); list.append(box); }
}
function sourceListen(source){return source?.meeting_id&&source.timestamp?listenButton(source.meeting_id,source.start??stampSeconds(source.timestamp),{label:'',until:source.end,className:'chip-listen'}):'';}
function sourceChip(source) {
 const chip=btn('meeting-chip');chip.append(icon('jump'),document.createTextNode(withDate(source.meeting_title,source.meeting_date)+(source.timestamp?' · '+source.timestamp:''))); chip.title='Open the meeting at this moment';
 chip.onclick=()=>perform(async()=>{await openMeeting(source.meeting_id);if(source.timestamp&&detail.transcript.length)showMoment(source.timestamp);else switchTab('outcomes');});
 return chip;
}
// The project of the newest meeting that has one. Without such a meeting, the person chooses.
function latestMeetingProject(){
 const known=new Set(projectList().map(p=>p.id));
 return [...(state?.meetings||[])].filter(m=>known.has(m.project_id)).sort((a,b)=>String(b.started_at||b.created).localeCompare(String(a.started_at||a.created)))[0]?.project_id||'';
}
async function openPrepare(projectId,seriesId,kind) {
 if(!(await leaveEdits())) return; dirtyTranscript=dirtyNotes=false; selected=null; show('prepare');
 prepareScope={project:projectId||prepareScope.project||latestMeetingProject(),series:projectId?seriesId||'':prepareScope.series,type:kind||''};
 renderLibrary(); await loadPrepare();
}
async function loadPrepare() {
 const request=readers.start('prepare');syncRoute(true);
 fillProjects($('prepare-project'),prepareScope.project,'Choose a project'); fillSeries($('prepare-series'),prepareScope.project,prepareScope.series,'All meetings of the project');
 $('prepare-empty').hidden=!!projectList().length; $('prepare-content').hidden=true;
 if(!prepareScope.project){$('prepare-summary').textContent='Choose a project or a series.';return;}
 const query=prepareScope.series?{series:prepareScope.series}:{project:prepareScope.project};if(prepareScope.type)query.type=prepareScope.type;
 // The tasks of Prepare me use the My Work card, so they need the full work items.
 const [fresh,items]=await Promise.all([api('/api/prepare?'+new URLSearchParams(query)),api('/api/items')]);if(!readers.current(request)||view!=='prepare')return;prepareData=fresh;itemsData=items;
 const picker=$('prepare-type');picker.replaceChildren(option('Choose the upcoming meeting type…',''),...(state.meeting_types||[]).map(t=>option(t.label,t.id)));picker.value=prepareData.requires_type?'':prepareScope.type||prepareData.meeting_type;
 if(prepareData.requires_type){$('prepare-summary').textContent='This project contains different meeting types. Choose the upcoming meeting before preparing its agenda.';return;}
 renderPrepare(prepareData);
}
$('prepare-project').onchange=()=>{prepareScope={project:$('prepare-project').value,series:'',type:''};perform(loadPrepare);};
$('prepare-series').onchange=()=>{prepareScope.series=$('prepare-series').value;prepareScope.type='';perform(loadPrepare);};
$('open-prepare').onclick=()=>perform(()=>openPrepare());
$('prepare-next-meeting').onclick=()=>{prepareScope.type=$('prepare-type').value||prepareData?.meeting_type||'';$('new-meeting').click();};
$('copy-agenda').onclick=()=>perform(async()=>{await navigator.clipboard.writeText(prepareData.markdown);toast('Agenda copied · paste it into the invitation or a chat');});
function renderPrepare(data) {
 renderFollowup(data);
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
  // A known task gets the shared task card. The hints of Prepare me join its metadata row.
  const full=itemsData?.items?.find(i=>i.id===task.item_id);
  if(full){const card=globalTaskRow(full,today,{select:false}),facts=card.querySelector('.tracked-meta');if(task.deadline)facts.append(el('span','hint','Said: '+task.deadline));if(task.stalled)facts.append(statusBadge({tone:'warn',label:'No change for '+task.idle_days+' days'}));return card;}
  const [kind,label]=dueInfo(Object.assign({status:'open'},task),today), row=el('div','tracked-task '+kind), main=el('div','tracked-main'), meta=el('div','tracked-meta'), who=el('span','tracked-owner');
  who.append(avatar(task.owner||''),el('span','',task.owner||'No owner')); meta.append(who,el('span','due-label '+kind,task.due_date?label+' · '+date(task.due_date):label));
  if(task.deadline) meta.append(el('span','hint','Said: '+task.deadline));
  if(task.stalled) meta.append(el('span','hint','No change for '+task.idle_days+' days'));
  main.append(el('p','tracked-text',task.text),meta,sources([task.source])); if(!task.source){const open=actionBtn('quiet','Open source-backed task',()=>openTaskPanel(task.item_id));main.append(open);}main.append(doneButton({id:task.item_id,text:task.text,revision:task.revision,status:'open',workflow_state:task.workflow_state}));row.append(el('span'),main); return row;}):[emptyNote('No open tasks.')]));
 // A daily goes person by person, so its tasks are grouped by owner.
 if(type.id==='daily'&&data.tasks.length){const rows=[...$('prepare-tasks').children],groups=new Map();data.tasks.forEach((task,i)=>{const owner=task.owner||'No owner';if(!groups.has(owner))groups.set(owner,[]);groups.get(owner).push(rows[i]);});
  $('prepare-tasks').replaceChildren(...[...groups].sort(([a],[b])=>(a==='No owner')-(b==='No owner')||a.localeCompare(b)).flatMap(([owner,list])=>[el('h3','prepare-owner',owner+' · '+list.length),...list]));}
 $('prepare-questions').replaceChildren(...(data.questions.length?data.questions.map(question=>{
  const row=el('div','prepare-question'); row.append(el('span','change-kind',question.kind==='decide'?'Needs a decision':'Open question'),el('p','',question.text),sources([question.source]));
  if(question.maybe_answered_by){row.classList.add('maybe-answered');row.append(el('p','hint','A later decision may answer it: '+question.maybe_answered_by.text),sources([question.maybe_answered_by.source]));}
  return row;}):[emptyNote('No open questions in the last meetings.')]));
 $('prepare-decisions').replaceChildren(...(data.decisions.length?data.decisions.map(decision=>{const row=el('div','prepare-question');row.append(el('p','',decision.text),sources([decision.source]));return row;}):[emptyNote('No accepted decisions yet. Accept decisions in Tasks & decisions.')]));
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
// A search result on the shared card: its meeting, its project, what kind of passage it is, and the passage with the match marked.
function resultRow(result) {
 const project=result.project_id&&projectList().find(p=>p.id===result.project_id),row=el('article','entity-card result-card '+result.kind),main=el('div','entity-main'),top=el('div','entity-top'),meta=el('div','entity-meta'),chips=el('div','entity-chips');
 if(project?.color){row.classList.add('has-project-line');row.style.setProperty('--project-color',project.color);}
 const title=btn('entity-title',withDate(result.meeting_title,result.meeting_date),()=>perform(async()=>{await openMeeting(result.meeting_id);if(result.timestamp&&detail.transcript.length)showMoment(result.timestamp);else switchTab('outcomes');}));title.title='Open the meeting at this moment';
 if(project)chips.append(projectChip(project));top.append(title,chips);
 meta.append(el('span','change-kind',RESULT_LABELS[result.kind]||result.kind));
 if(result.status)meta.append(el('span','decision-status '+result.status,STATUS_LABELS[result.status]||result.status));
 const facts=[result.speaker,result.timestamp].filter(Boolean);if(facts.length)meta.append(el('span','',facts.join(' · ')));
 meta.append(sourceListen(result));
 main.append(top,meta,highlighted(result.snippet));row.append(main);return row;
}
async function openFind(query) {
 if(!(await leaveEdits())) return; dirtyTranscript=dirtyNotes=false; selected=null; show('find'); renderLibrary();
 fillProjects($('find-project'),$('find-project').value,'All projects');
 $('find-kinds').replaceChildren(...FIND_KINDS.map(([key,label])=>{const button=btn(key===findKind?'selected':'',label);button.onclick=()=>{findKind=key;openFind($('find-query').value);};return button;}));
 if(query!==undefined) $('find-query').value=query;
 $('find-query').focus(); if($('find-query').value.trim()) perform(runFind);
}
let findSequence=0;
async function runFind() {
 const query=$('find-query').value.trim(),sequence=++findSequence; $('find-results').replaceChildren(); if(!query) return;
 const results=await api('/api/find?'+new URLSearchParams({q:query,kind:findKind,project:$('find-project').value}));
 // A slower answer to an earlier search must not replace the newer results.
 if(sequence!==findSequence)return;
 if(!results.length){$('find-results').append(el('p','empty-content card find-empty','Nothing matches. Try fewer or other words.'));return;}
 for(const [title,kinds] of RESULT_GROUPS) { const rows=results.filter(r=>kinds.includes(r.kind)); if(!rows.length) continue;
  const group=el('section','result-group'),list=el('div','entity-list'); list.append(...rows.map(resultRow)); group.append(el('h2','',title+' · '+rows.length),list); $('find-results').append(group); }
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
  if(full.ai?.found){written.append(markdownBlock(full.ai.answer));const cites=el('div','item-meetings');cites.append(el('span','hint','Sources'));
   for(const number of full.ai.cited){const chip=sourceChip(full.sources[number-1]);chip.textContent='['+number+'] '+chip.textContent;cites.append(chip,sourceListen(full.sources[number-1]));}written.append(cites);}
  else if(full.ai) written.append(el('p','hint','The found passages do not answer this question.'));
  else if(full.ai_error) written.append(el('p','notice warning','No written answer: '+full.ai_error));
 } catch(e) {
  if(e.name!=='AbortError') throw e;
  written.replaceChildren(el('p','hint','You stopped waiting. The model server may still finish this request before it starts the next one.'));
 } finally { clearInterval(timer); }
}

function renderProcessingTime(){
 if(!detail)return;
 const d=detail, active=d.status==='processing', now=Date.now()/1000;
 const elapsed=active&&d.processing_started_at?Math.max(0,now-d.processing_started_at):d.processing_elapsed||0;
 const timings=Object.entries(d.processing_timings||{}).map(([name,seconds])=>name+': '+time(seconds));
 $('processing-details').hidden=!d.processing_stage;$('processing-time').hidden=false;
 $('processing-time').textContent=d.processing_stage+' · '+time(elapsed)+(active&&d.processing_stage_started_at?' · this stage '+time(Math.max(0,now-d.processing_stage_started_at)):'')+(timings.length?'\n'+timings.join('\n'):'');
}
setInterval(()=>{if(!document.hidden&&view==='detail')renderProcessingTime();},1000);
// A calendar link reaches the desktop window through atlanta://; open the meeting in place.
window.addEventListener('desktop-open',event=>{const id=String(event.detail?.meeting||'');if(/^[a-f0-9]{32}$/.test(id))perform(()=>openMeeting(id));});
window.addEventListener('desktop-status',event=>{desktopStatus=String(event.detail||'');setConnection(desktopStatus);error(desktopStatus);});
$('cancel-processing').onclick=()=>perform(async()=>{await api('/api/meetings/'+selected+'/cancel',{});toast('Cancellation requested');await openMeeting(selected,true);});
// Profiles fill the form; nothing changes until Save settings.
const PROFILES={
 fast:{provider:'local','local-model':'large-v3-turbo','live-enabled':false,'transcript-correction':'none','diarization-enabled':false,'whisper-vad':true},
 balanced:{provider:'local','local-model':'large-v3-turbo','live-enabled':true,'transcript-correction':'none','diarization-enabled':true,'whisper-vad':true},
 best:{provider:'local','local-model':'large-v3','live-enabled':true,'transcript-correction':'local','diarization-enabled':true,'whisper-vad':true},
};
const CLOUD_FIELDS=['provider','summarizer','transcript-correction','title-provider'];
function applyProfile(name){
 if(name==='private'){for(const id of CLOUD_FIELDS)if(['openai','elevenlabs'].includes($(id).value))$(id).value='local';}
 else for(const [id,value] of Object.entries(PROFILES[name]))$(id)[typeof value==='boolean'?'checked':'value']=value;
 if(name==='fast'&&/qwen3\.5/i.test($('local-ai-model').value))$('local-ai-reasoning').value='none';
 settingsFields();markProfile();toast('Profile filled in. Save settings to apply.');
}
// Fast, Balanced and Best quality are one choice: the first that fits the fields is selected, or none (custom settings).
// Maximum privacy is a property of the settings, not a choice among them: it shows "In effect" when no step uses a cloud provider.
function markProfile(){
 const fits=name=>name==='private'?CLOUD_FIELDS.every(id=>!['openai','elevenlabs'].includes($(id).value)):Object.entries(PROFILES[name]).every(([id,value])=>(typeof value==='boolean'?$(id).checked:$(id).value)===value);
 const chosen=['fast','balanced','best'].find(fits);
 for(const b of document.querySelectorAll('.profile')){
  const privacy=b.dataset.profile==='private',on=privacy?fits('private'):b.dataset.profile===chosen;
  b.classList.toggle('selected',!privacy&&on);b.classList.toggle('in-effect',privacy&&on);b.setAttribute('aria-pressed',String(!privacy&&on));
 }
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
// The server says when something changed; the tab loads data only then, and not at all while it is hidden.
let events=null, refreshing=false, refreshPending=false, pendingChanged=[];
// changed is the list of meetings that changed, or null for "anything may have changed".
async function refresh(changed) {
 if(refreshing){refreshPending=true;pendingChanged=pendingChanged===null||changed===null?null:[...pendingChanged,...changed];return;}
 refreshing=true;
 try {
  state=await api('/api/state'); renderState();
  if(!initialRouteHandled){initialRouteHandled=true;await perform(applyRoute);}
  if(view==='calendar')renderCalendar();
  if(view==='tasks') await loadTasks();
  if(view==='detail'&&selected&&!hasEdits()&&(!changed||changed.includes(selected))) {
   const key=selected,request=readers.start('meeting-refresh'),generation=meetingLoadSequence;
   const fresh=await api('/api/meetings/'+key);const fingerprint=JSON.stringify(fresh);
   if(view!=='detail'||selected!==key||generation!==meetingLoadSequence||!readers.current(request))return;
   if(hasEdits()){if(fingerprint!==lastFingerprint){detailChangedWhileEditing=true;$('detail-refresh-notice').hidden=false;}return;}
   if(fingerprint!==lastFingerprint){const firstNotes=!detail.minutes&&!!fresh.minutes&&fresh.status==='ready'&&meetingTab==='transcript';detail=fresh;lastFingerprint=fingerprint;if(notesEditing)notesBase=structuredClone(fresh.minutes);renderDetail();if(firstNotes)switchTab('outcomes');}
  }
 } catch(e) { setConnection(disconnectedMessage()); }
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
 events.onerror=()=>{ setConnection(disconnectedMessage()); };
}
document.addEventListener('visibilitychange',()=>{ if(document.hidden){events?.close();events=null;} else listen(); });
// The microphone list is scanned only while the new-meeting form is visible.
setInterval(()=>{ if(view!=='setup'||document.hidden||!state) return;
 api('/api/devices').then(result=>{if(JSON.stringify(result.devices)!==JSON.stringify(state.devices)||result.device_error!==state.device_error){state.devices=result.devices;state.device_error=result.device_error;renderState();}}).catch(()=>{}); },3000);
$('open-tasks').onclick=()=>perform(async()=>{if(!(await leaveEdits()))return;dirtyTranscript=dirtyNotes=false;selected=null;show('tasks');lastTasks='';await loadTasks();
 // My Work opens on All tasks when the saved view is an empty Inbox (2026-11-12); a link to the Inbox still opens it.
 const waiting=(itemsData?.graph?.proposals||[]).some(p=>p.state==='pending')||(itemsData?.items||[]).some(i=>i.acceptance_state==='proposed'&&!i.dismissed);
 if(managerView==='inbox'&&!inboxOnPurpose&&!waiting){managerView='all';store('manager-view','all');}inboxOnPurpose=false;showWorkTab(workTab);renderLibrary();if(workTab!=='review')perform(loadReviewQueue);});
$('open-analytics').onclick=()=>perform(async()=>{if(!(await leaveEdits()))return;dirtyTranscript=dirtyNotes=false;selected=null;show('analytics');await loadAnalytics();renderLibrary();});
$('analytics-apply').onclick=()=>perform(loadAnalytics);
$('analytics-reset').onclick=()=>perform(async()=>{for(const id of ['analytics-from','analytics-to','analytics-speaker','analytics-topic'])$(id).value='';await loadAnalytics();});
// Reset filters: every filter and the task view (they change the results); the search stays.
// Clear all: also the search, back to the first state. "This is me" is who you are, not a filter: neither clears it.
function resetTaskFilters({all=false}={}){
 taskWorkflow=sourceFilter='';$('work-project').value=$('task-owner').value='';statusFilter.task='open';statusFilter.decision='current';
 for(const key of ['tasks-workflow','tasks-source','tasks-project','tasks-owner'])store(key,'');store('tasks-status','open');
 managerView='all';store('manager-view','all');
 if(all){store('task-search','');taskSelecting=false;taskSelection.clear();}
 renderTasks();
}
$('task-reset-filters').onclick=()=>resetTaskFilters();$('task-clear-all').onclick=()=>resetTaskFilters({all:true});
$('work-project').onchange=()=>{store('tasks-project',$('work-project').value);renderTasks();};
$('task-owner').onchange=()=>{store('tasks-owner',$('task-owner').value);renderTasks();};
// Transcript rows grow with their text instead of showing an inner scroll bar.
document.addEventListener('input',event=>{const area=event.target;if(area.matches?.('.segment textarea')){area.style.height='auto';area.style.height=area.scrollHeight+2+'px';}});
$('new-meeting').onclick=async()=>{const context=view==='prepare'?{project_id:prepareScope.project||null,series_id:prepareScope.series||null,meeting_type:prepareScope.type||'general'}:view==='projects'?{project_id:$('workspace-project').value==='__none__'?null:$('workspace-project').value||null}:view==='detail'?{project_id:detail.project_id||null,series_id:detail.series_id||null,meeting_type:detail.meeting_type||'general'}:{};const project=contextProject();if(!(await leaveEdits()))return;dirtyTranscript=dirtyNotes=false;selected=null;show(state?.active?'recording':'setup');window.scrollTo(0,0);if(state?.active)selected=state.active.id;else{if(project){fillProjects($('record-project'),project,'No project');fillSeries($('record-series'),project,'','No series');renderRecordMore();}renderTranscriptionTiming(true);captureContext=context;if(Object.keys(context).length)applyCaptureSetup(recordingSetupDraft(context),false);renderCaptureSetup();}renderLibrary();};
$('record-form').addEventListener('change',()=>{renderReadiness();renderRecordMore();});
{const mode=document.querySelector(`input[name=mode][value="${stored('record-mode')}"]`);if(mode)mode.checked=true;}
for(const radio of document.querySelectorAll('input[name=mode]'))radio.onchange=()=>{$('mode-help').textContent=radio.value==='online'?'Captures audio from all Mac apps plus your microphone. Use headphones to avoid echo. macOS requires Screen & System Audio Recording permission.':'Place your iPhone near the centre of the table, or use your Mac microphone.';};
// A remembered meeting type shows its own help text.
document.querySelector('input[name=mode]:checked')?.onchange?.();
$('check-mic').onclick=()=>perform(async()=>{await api('/api/check-mic',{device:Number($('microphone').value),device_name:$('microphone').selectedOptions[0]?.textContent});toast('Microphone test started · 10 seconds');});
$('microphone').onchange=()=>{captureWantedMic=null;renderState();};
$('record-form').onsubmit=event=>{event.preventDefault();perform(async()=>{pending=true;$('start').disabled=true;store('record-mode',document.querySelector('input[name=mode]:checked').value);store('record-mic',$('microphone').selectedOptions[0]?.textContent||'');try{const m=await api('/api/start',{title:$('meeting-title').value,mode:document.querySelector('input[name=mode]:checked').value,device:Number($('microphone').value),device_name:$('microphone').selectedOptions[0]?.textContent,fallback_device_name:$('fallback-microphone').value,transcription_timing:$('transcription-timing').value,project_id:$('record-project').value||null,series_id:$('record-series').value||null,meeting_type:$('record-type').value||null});selected=m.id;state.active=m;renderState();show('recording');}finally{pending=false;}});};
async function importTranscript(text,filename,modified=null) {
 if(!(await approveImport(filename||'pasted transcript')))return;
 activityStep('Importing the transcript and building analytics');
 const d=await api('/api/import',{text,filename,modified});activityStep('Opening the meeting');
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
  validateImportFile(file);if(AUDIO_FILE.test(file.name)){if(!(await approveImport(file.name)))return;const d=await uploadAudio(file);$('import-file').value='';toast('Audio imported · '+shortDuration(d.duration));state=await api('/api/state');renderState();await openMeeting(d.id,true);return;}
  if(file.size>5_000_000)throw new Error('Choose a transcript file of at most 5 MB');
  await importTranscript(await file.text(),file.name,file.lastModified||null);
 }finally{$('import-button').textContent='Import file';$('import-button').disabled=!$('import-file').files.length;}});
$('import-text').oninput=()=>{$('import-paste-button').disabled=!$('import-text').value.trim();};
$('import-paste-button').onclick=()=>perform(async()=>{$('import-paste-button').disabled=true;try{await importTranscript($('import-text').value,'');}finally{$('import-paste-button').disabled=!$('import-text').value.trim();}});
$('pause').onclick=$('bar-pause').onclick=()=>perform(()=>api('/api/pause',{paused:state.active.status!=='paused'}));$('stop').onclick=()=>perform(()=>api('/api/stop',{}));
// The bar is always on screen, so its Stop asks first; the recording view's Stop is the deliberate one.
$('bar-stop').onclick=()=>perform(async()=>{if(await ask('Stop and save “'+(state.active?.title||'this recording')+'”?',{ok:'Stop & save',cancel:'Keep recording'}))await api('/api/stop',{});});
$('bar-open').onclick=()=>perform(async()=>{if(!state.active||!(await leaveEdits()))return;dirtyTranscript=dirtyNotes=false;selected=state.active.id;show('recording');renderState();});
for(const [id,action] of [['process','transcribe'],['summarize','summarize'],['recover','recover'],['correct','correct']])$(id).onclick=()=>perform(async()=>{if(!(await leaveEdits()))return;if(action==='summarize'&&state.settings.summarizer==='none'){openSettings('notes');toast('Choose a meeting-notes provider first');return;}await api('/api/meetings/'+selected+'/process',{action});dirtyNotes=dirtyTranscript=false;toast('Processing queued');await openMeeting(selected,true);});
$('edit-title').onclick=()=>perform(async()=>{const title=await ask('Meeting name',{value:detail.title,ok:'Rename'});if(title?.trim()){await api('/api/meetings/'+selected+'/edit',{title});await openMeeting(selected,true);}});
$('save-transcript').onclick=()=>perform(async()=>{await withEditorSave($('detail'),async()=>{if(!detail||detail.id!==selected)throw new Error('Reopen the meeting before saving.');if(dirtyNotes||itemEditing||speakerNaming)throw new Error('Save other edits before updating the transcript.');detail=await api('/api/meetings/'+selected+'/edit',{transcript:detail.transcript,transcript_revision:detail.transcript_revision,refresh_notes:false,defer_analysis:true});dirtyTranscript=false;detailChangedWhileEditing=false;transcriptEditing=false;lastFingerprint=JSON.stringify(detail);renderDetail();toast('Transcript corrections saved');});});
$('save-notes').onclick=$('save-outcomes').onclick=()=>perform(()=>withEditorSave($('detail'),async()=>{if(!validDates($('detail')))return;for(const field of ITEM_FIELDS)detail.minutes[field]=(detail.minutes[field]||[]).filter(item=>item.text.trim());if(detail.minutes.discussion)detail.minutes.discussion=cleanDiscussion(detail.minutes.discussion);notesEditing=false;try{await saveMinutes(notesBase);}catch(e){notesEditing=true;throw e;}toast('Meeting notes saved');}));
for(const name of ['notes','outcomes']) {
 $('edit-'+name).onclick=()=>{notesBase=structuredClone(detail.minutes);notesEditing=true;renderNotes(false);};
 $('cancel-'+name).onclick=()=>perform(async()=>{if(dirtyNotes&&!(await ask('Discard your changes to the notes?',{ok:'Discard',cancel:'Keep editing',danger:true})))return;notesEditing=false;await openMeeting(selected,true);});
}
$('reanalyze').onclick=()=>perform(async()=>{if(!(await leaveEdits()))return;await api('/api/meetings/'+selected+'/reanalyze',{});dirtyTranscript=dirtyNotes=false;toast('Analytics queued');await openMeeting(selected,true);});
for(const tab of ['review','transcript','outcomes','notes','team','analytics']) $('tab-'+tab).onclick=()=>switchTab(tab);
$('team-analysis-run').onclick=()=>perform(runTeamAnalysis);
$('settings-open').onclick=()=>openSettings();$('settings-inline').onclick=()=>openSettings('recording');
for(const tab of document.querySelectorAll('.settings-tabs button')) tab.onclick=()=>showSettingsTab(tab.dataset.tab);
// A required field on a hidden tab would block saving without a visible message.
$('settings-save').onclick=event=>{const invalid=$('settings-form').querySelector('input:invalid,select:invalid,textarea:invalid');if(invalid){event.preventDefault();if(invalid.closest('.advanced-setting'))showAdvanced(true);showSettingsTab(invalid.closest('.settings-panel').dataset.tab);invalid.reportValidity();}};$('settings-close').onclick=()=>perform(closeSettings);
$('provider').onchange=settingsFields;$('summarizer').onchange=()=>{$('llm-model').value=$('summarizer').value==='openai'?'gpt-4.1-mini':'gpt-4.1-mini';settingsFields();};$('transcript-correction').onchange=settingsFields;
$('settings-form').onsubmit=event=>{event.preventDefault();if(settingsTab==='prompts')return;return perform(async()=>{if(!(await leaveTypePrompt()))return;if(!(await leavePromptEditor()))return;const vocabularyChanged=$('whisper-vocabulary').value.trim()!==state.settings.whisper_vocabulary;const body={local_ai_base_url:$('local-ai-base-url').value.trim(),local_ai_model:$('local-ai-model').value.trim(),local_ai_format:$('local-ai-format').value,local_ai_reasoning:$('local-ai-reasoning').value,local_ai_max_tokens:Number($('local-ai-max-tokens').value),local_ai_context:Number($('local-ai-context').value),local_ai_temperature:$('local-ai-temperature').value,meeting_task_ai:$('meeting-task-ai').checked,task_matching_target:$('task-matching-allow').checked&&remoteAPI($('local-ai-base-url').value)?$('local-ai-base-url').value.trim():'',transcription:$('provider').value,local_model:$('local-model').value,audio_preparation:$('audio-preparation').value,whisper_vad:$('whisper-vad').checked,whisper_vocabulary:$('whisper-vocabulary').value.trim(),cloud_model:$('cloud-model').value,summarizer:$('summarizer').value,transcript_correction:$('transcript-correction').value,llm_model:$('llm-model').value,auto_process:$('auto-process').checked,live_transcription:$('live-enabled').checked,diarization_enabled:$('diarization-enabled').checked,auto_title:$('auto-title').checked,title_provider:$('title-provider').value,title_model:$('title-model').value,calendar_enabled:$('calendar-enabled').checked,calendar_id:$('calendar-id').value};if($('elevenlabs-api-key').value.trim())body.elevenlabs_api_key=$('elevenlabs-api-key').value.trim();if($('api-key').value.trim())body.api_key=$('api-key').value.trim();if($('local-ai-api-key').value.trim())body.local_ai_api_key=$('local-ai-api-key').value.trim();const saved=await api('/api/settings',body);$('api-key').value='';$('elevenlabs-api-key').value='';$('local-ai-api-key').value='';$('settings-dialog').close();toast(saved.elevenlabs_key_error||'Settings saved');state=await api('/api/state');renderState();if(vocabularyChanged)await offerReprocess({scope:'global',action:'correction_notes',reason:'Vocabulary saved. Choose whether to correct existing transcripts or explicitly recognize audio again.'});});};

function renderGoogleStatus() {
 const google=state.google||{};
 $('google-status').textContent=(google.connected?'Signed in as '+google.account:google.sign_in_available?'Not signed in. Sign in with your Google account to add meetings to your calendar.':'Google sign-in is not set up for this app yet. See docs/calendar-and-titles.md, or use Advanced below.')+(google.error?' · '+google.error:'');
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

$('add-tracker').onclick=()=>{trackersData.push({id:'',name:'',phrases:[],semantic_matching:false});renderTrackers();$('tracker-list').lastElementChild.querySelector('input').focus();};
$('save-trackers').onclick=()=>perform(saveTrackers);
$('delete-meeting').onclick=()=>perform(async()=>{
 const id=selected, title=detail.title;
 const hasEvent=!!detail.calendar_sync?.event_id;
 const answer=await ask('Delete "'+title+'"?\n\nThe recording, transcript, notes and all other files of this meeting are removed from this Mac. You cannot undo this.'+(hasEvent?'\n\nThe meeting also has a Google Calendar event.':''),
  hasEvent?{ok:'Delete meeting and event',extra:'Delete meeting, keep event',danger:true}:{ok:'Delete meeting',danger:true});
 if(!answer) return;
 const calendar_event=answer===true&&hasEvent;
 await api('/api/meetings/'+id+'/delete',{calendar_event});
 $('audio').pause();$('audio').removeAttribute('src');
 dirtyTranscript=dirtyNotes=false;detail=null;selected=null;
 if(window.searchResults) window.searchResults=window.searchResults.filter(m=>m.id!==id);
 state=await api('/api/state');lastLibrary='';
 // Back to the list the meeting came from, not to a new recording. An active recording stays in front.
 if(state.active){selected=state.active.id;show('recording');renderState();}else{renderState();await openConversations();}
 window.scrollTo(0,0);toast('Meeting deleted');
});
$('sync-all-meetings').onclick=()=>perform(async()=>{const result=await api('/api/calendar/sync-all',{});toast(result.queued+' saved meetings queued for calendar sync');});
$('auto-title').onchange=$('calendar-enabled').onchange=settingsFields;
$('title-provider').onchange=()=>{$('title-model').value=$('title-provider').value==='openai'?'gpt-4.1-mini':'gpt-4.1-mini';settingsFields();};
$('generate-title').onclick=()=>perform(async()=>{await api('/api/meetings/'+selected+'/title',{});toast('AI title queued');await openMeeting(selected,true);});
$('sync-calendar').onclick=()=>perform(async()=>{await api('/api/meetings/'+selected+'/calendar',{});toast('Calendar sync queued');await openMeeting(selected,true);});
$('forget-elevenlabs-key').onclick=()=>perform(async()=>{const saved=await api('/api/settings',{elevenlabs_api_key:''});state.elevenlabs_api_key_configured=false;state.elevenlabs_key_error=saved.elevenlabs_key_error;$('elevenlabs-api-key').value='';$('elevenlabs-key-state').textContent=saved.elevenlabs_key_error?'· '+saved.elevenlabs_key_error:'';$('forget-elevenlabs-key').disabled=true;toast(saved.elevenlabs_key_error||'ElevenLabs key removed from Keychain');});
$('forget-local-ai-key').onclick=()=>perform(async()=>{const saved=await api('/api/settings',{local_ai_api_key:''});state.local_ai_api_key_configured=false;state.local_ai_key_error=saved.local_ai_key_error;$('local-ai-api-key').value='';$('local-ai-key-state').textContent=saved.local_ai_key_error?'· '+saved.local_ai_key_error:'';$('forget-local-ai-key').disabled=true;toast(saved.local_ai_key_error||'API key removed from Keychain');});
// A cloud endpoint says so next to its address, and the key becomes required.
function renderCloudNote(){const url=$('local-ai-base-url').value,remote=remoteAPI(url),note=$('local-ai-cloud-note');note.hidden=!remote;$('settings-form').classList.toggle('cloud-api',remote);note.textContent=remote?'This API is outside this Mac. Meeting text for notes, correction and titles goes to '+apiHost(url)+'. '+(state?.local_ai_api_key_configured||$('local-ai-api-key').value.trim()?'':'Add its API key below.'):'';}
// Task matching sends the context of existing tasks. A remote API needs a permission for its own address;
// another address clears it. An API on this Mac or the local network needs none.
function renderTaskMatching(){
 const url=$('local-ai-base-url').value.trim(),remote=remoteAPI(url),host=apiHost(url),allow=$('task-matching-allow');
 // Task matching runs only with AI meeting tasks; without them no task context leaves this Mac.
 $('task-matching-field').hidden=!$('meeting-task-ai').checked;
 allow.closest('label').hidden=!remote;
 if(remote&&url!==state?.settings?.task_matching_target&&document.activeElement!==allow)allow.checked=false;
 $('task-matching-label').textContent='Send task context to '+host+' to match meeting tasks with existing tasks';
 $('task-matching-hint').textContent=remote?'Per meeting: titles, owners, states, due dates, expected results and up to 2 updates of at most 30 similar existing tasks. Proposed and hidden tasks, email and chat text are never sent. Turned off, task matching waits. The permission ends when the API address changes.'
  :'Task matching uses this API on this Mac or your network. No permission is needed.';
}
$('local-ai-base-url').addEventListener('input',()=>{renderCloudNote();settingsFields();renderTaskMatching();});$('meeting-task-ai').addEventListener('change',renderTaskMatching);$('local-ai-api-key').addEventListener('input',renderCloudNote);
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
$('load-local-models').onclick=()=>perform(async()=>{const button=$('load-local-models');button.disabled=true;$('local-ai-status').textContent='Connecting…';try{const result=await api('/api/local-ai/models',{base_url:$('local-ai-base-url').value.trim()});$('local-ai-models').replaceChildren(...result.models.map(id=>{const option=document.createElement('option');option.value=id;return option;}));localModels=result.models;$('local-ai-status').textContent=result.models.length+' models available. Click one to use it; embedding models cannot generate notes.';if(result.models.length===1)$('local-ai-model').value=result.models[0];renderLocalModels();}catch(error){$('local-ai-status').textContent='Could not load models: '+error.message;throw error;}finally{button.disabled=false;}});

$('audio-source').onchange=()=>{if(!detail)return;const audio=$('audio'),position=audio.currentTime,playing=!audio.paused;audio.src='/files/'+detail.id+'/'+$('audio-source').value;audio.currentTime=position;if(playing)audio.play().catch(e=>error(e.message));};


let workspaceData=null, workspaceSection='overview', workspaceSequence=0;
function projectAssignment(item){
 const box=el('details','project-assignment'), projects=(item.effective_project_ids||[]).map(id=>projectList().find(p=>p.id===id)).filter(Boolean);
 const summary=el('summary'); if(projects.length){summary.append(document.createTextNode('Project: '));projects.forEach((project,i)=>{if(i)summary.append(document.createTextNode(' · '));if(project.color)summary.append(projectDot(project));summary.append(document.createTextNode(project.name));});}else summary.textContent='Project: none · assign';
 box.append(summary);
 const hint=el('p','hint',Array.isArray(item.project_ids)?'Manual assignment · preserved during sync':projects.length?'Inherited from linked meetings':'No project inherited. Select projects below, or assign a project to a linked meeting.');box.append(hint);
 const choices=[];
 for(const project of projectList()){
  const label=el('label','project-choice'),check=el('input');check.type='checkbox';check.checked=(item.effective_project_ids||[]).includes(project.id);label.append(check);if(project.color)label.append(projectDot(project));label.append(document.createTextNode(project.name));box.append(label);choices.push([project.id,check]);
 }
 const save=el('button','primary small-action','Save projects'),inherit=el('button','secondary small-action','Use meeting projects');save.type=inherit.type='button';
 save.onclick=()=>perform(()=>graphAction('project',{id:item.id,revision:item.revision,project_ids:choices.filter(([,check])=>check.checked).map(([id])=>id)}));
 inherit.onclick=()=>perform(()=>graphAction('project',{id:item.id,revision:item.revision,project_ids:null}));const actions=el('div','action-group project-assignment-actions');actions.append(save,inherit);box.append(actions);return box;
}
// Saved links between work items build the project trace. A person makes each link; none is inferred.
const RELATION_LABELS={implements:['implements','is implemented by'],derives_from:['comes from','leads to'],supports:['supports','is supported by'],same_as:['is the same as','is the same as'],supersedes:['supersedes','is superseded by']};
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
 if(item.kind==='decision')kind.append(option('This decision supersedes…','supersedes'));
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
 button.append(el('i'),el('b','',kinds[node.kind]||node.kind),el('span','trace-label',node.label));button.title=node.label;
 const meta=[node.status&&(STATUS_LABELS[node.status]||node.status),node.ref.timestamp,node.ref.state,node.date&&date(node.date)].filter(Boolean);
 if(meta.length)button.append(el('small','',meta.join(' · ')));
 if(!url)button.onclick=()=>perform(async()=>{
  const ref=node.ref;
  if(ref.attachment_id)return openAttachment(ref.attachment_id);
  if(ref.meeting_id){await openMeeting(ref.meeting_id);if(ref.timestamp)showSeconds(ref.timestamp.split(':').reduce((n,v)=>n*60+Number(v),0));return;}
  if(ref.source_id){const source=(workspaceData.graph.sources||[]).find(s=>s.id===ref.source_id);if(source)return openSource(source);}
  if(ref.item_id){const item=workspaceData.items.find(i=>i.id===ref.item_id);if(item?.kind==='task'||node.kind==='task')return openTaskPanel(ref.item_id);show('tasks');lastTasks='';await loadTasks();showWorkTab(item?.kind==='question'?'questions':item?.kind||'task');}
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
 const card=el('article','trace-card'),grid=el('div','trace-grid'),missing=[];
 for(const [stage,title] of TRACE_STAGES){
  const nodes=chain.stages[stage]||[];
  if(!nodes.length){missing.push(title);continue;}
  const column=el('div','trace-stage'),content=el('div','trace-nodes');column.append(el('h4','',title),content);
  let expanded=false;
  const more=btn('quiet small-action trace-expand');more.setAttribute('aria-expanded','false');
  const draw=()=>{content.replaceChildren(...nodes.slice(0,expanded?nodes.length:6).map(traceStep));more.textContent=expanded?'Show fewer '+title.toLowerCase()+' links':'Show '+(nodes.length-6)+' more '+title.toLowerCase()+' links';more.setAttribute('aria-expanded',String(expanded));};
  if(nodes.length>6){more.onclick=()=>{expanded=!expanded;draw();};column.append(more);}
  draw();grid.append(column);
 }
 card.append(grid);
 if(missing.length)card.append(el('p','trace-missing','Not linked: '+missing.join(' · ')));
 return card;
}
let timelineView='chains';
function renderTimeline(box,data){
 const timeline=data.timeline||{events:[],chains:[]},switcher=el('div','segmented');
 segmentedChoice(switcher,[['chains','Linked work'],['events','Activity']],timelineView,value=>{timelineView=value;renderWorkspace();});
 box.append(el('h2','','Project timeline'),switcher);
 if(timelineView==='chains'){
  box.append(el('p','hint','Follow the saved links from a conversation to its work and GitHub changes. Open a title to inspect it; use the play button to hear the evidence.'));
  for(const chain of timeline.chains||[])box.append(traceCard(chain));
  if(!(timeline.chains||[]).length)box.append(emptyNote('No decisions or tasks in this project yet.'));
  return;
 }
 box.append(el('p','hint','Dates belong to the recorded events. Work item text and status describe their current state.'));
 let day='';
 for(const event of timeline.events||[]){
  const when=new Date(event.at),label=date(event.at);
  if(label!==day){day=label;box.append(el('h3','timeline-day',label));}
  const row=el('article','timeline-event'),kind=event.kind==='code'?'code':event.kind;
  row.append(el('span','timeline-time',when.toLocaleTimeString(undefined,{hour:'2-digit',minute:'2-digit'})),traceStep(eventNode(event,kind)));
  if(event.event)row.append(el('span','hint',TIMELINE_EVENTS[event.event]||event.event.replace(/_/g,' ')));
  box.append(row);
 }
 if(!(timeline.events||[]).length)box.append(emptyNote('No events yet.'));
}
const TIMELINE_EVENTS={confirmed:'Owner confirmed',created:'Created',discussed:'Discussed',duplicate:'Mentioned again',changed:'Changed',removed:'Removed from a meeting',merged:'Merged',superseded:'Replaced',detached:'Waits for new notes',projects_changed:'Projects changed',source_linked:'Source linked',answered:'Answered',reopened:'Reopened'};
function eventNode(event,kind){
 const ref=event.url?{url:event.url,report_id:event.report_id}:event.attachment_id?{attachment_id:event.attachment_id,...(event.meeting_id?{meeting_id:event.meeting_id,start:event.start,end:event.end}:{})}:event.source_id?{source_id:event.source_id}:event.item_id?{item_id:event.item_id}:{meeting_id:event.meeting_id};
 return {kind,label:event.text,status:event.status,ref};
}
// The GitHub repositories of a project: drafts and links offer them first. One repository can serve several projects.
function repositoryEditor(project,{open=false,onSaved=null}={}){
 const box=el('section','project-repos'),chips=el('div','item-meetings'),repos=[...(project.repositories||[])];
 let baseline=[...repos],saving=false,catalogSequence=0,catalogTimer=null,available=[];
 const heading=el('div','repository-heading'),linkButton=el('button','secondary small-action','Link repository');linkButton.type='button';heading.append(el('h3','','Repositories'),linkButton);box.append(heading,chips);
 const row=el('div','work-actions'),input=el('input'),add=el('button','secondary','Add repository'),save=el('button','primary','Save links');
 const search=el('input'),list=el('select'),choose=el('button','secondary','Link selected repository'),selection=el('div','repository-picker'),manual=el('details');
 search.placeholder='Search accessible repositories';search.setAttribute('aria-label','Search repositories');list.setAttribute('aria-label','Accessible repositories');list.size=6;choose.type='button';choose.disabled=true;
 manual.append(el('summary','','Enter owner/name manually'));manual.append(row);
 const refresh=el('button','secondary','Refresh repositories'),status=el('p','hint'),edits=el('p','hint'),validation=el('p','notice');validation.hidden=true;validation.setAttribute('role','alert');refresh.type='button';status.setAttribute('role','status');edits.setAttribute('role','status');
 input.placeholder='owner/name';input.setAttribute('aria-label','Repository');add.type=save.type='button';save.disabled=true;
 const changed=()=>{const dirty=JSON.stringify(repos)!==JSON.stringify(baseline)||!!input.value.trim();editorDirty.set('project-repositories',dirty);save.disabled=saving||!dirty;edits.textContent=dirty?'Unsaved project links — use Save links to apply.':'All project links saved.';};
 const fail=message=>{validation.textContent=message;validation.hidden=false;return false;};
 const valid=name=>/^[A-Za-z0-9][A-Za-z0-9-]{0,38}\/[A-Za-z0-9_.-]{1,100}$/.test(name)&&!['.','..'].includes(name.split('/')[1]);
 const draw=()=>{chips.replaceChildren(...repos.map(name=>{const chip=el('span','source-chip src-github'),remove=el('button','quiet','Unlink');remove.type='button';remove.setAttribute('aria-label','Unlink '+name);
  remove.onclick=()=>perform(async()=>{if(saving)return;const count=project.repository_usage?.[name]||0;if(!(await ask('Unlink '+name+' from '+project.name+'?'+(count?' '+AtlantaUX.count(count,'task')+(count===1?' uses':' use')+' this destination and may need a new repository.':'')+' Existing GitHub issues and links will be kept. Apply with Save links.',{ok:'Unlink'})))return;if(saving||!box.isConnected)return;linkButton.click();repos.splice(repos.indexOf(name),1);draw();changed();});
  const shared=project.repository_projects?.[name]||[];chip.append(el('b','',name),remove);if(shared.length>1)chip.append(el('small','hint','Also linked to '+shared.filter(n=>n!==project.name).join(', ')));return chip;}));if(!repos.length)chips.append(el('span','hint','No repository linked to this project.'));};
 const addName=name=>{if(!valid(name))return fail('Enter a repository as owner/name, without a URL.');if(repos.some(r=>r.toLowerCase()===name.toLowerCase()))return fail('This repository is already linked to the project.');if(repos.length>=30)return fail('A project can have at most 30 repositories.');repos.push(name);validation.hidden=true;draw();changed();return true;};
 const addPending=()=>{const name=input.value.trim();if(!name)return true;if(!addName(name))return false;input.value='';changed();return true;};
 add.onclick=()=>{if(!saving)addPending();};input.oninput=()=>{if(!saving){validation.hidden=true;changed();}};
 input.onkeydown=event=>{if(event.key==='Enter'){event.preventDefault();add.click();}};
 const drawChoices=()=>{const old=list.value,query=search.value.trim().toLowerCase();list.replaceChildren(...available.filter(r=>r.full_name.toLowerCase().includes(query)).map(repo=>option(repo.full_name+(repo.archived?' · archived':repo.disabled?' · disabled':''),repo.full_name)));if(available.some(r=>r.full_name===old))list.value=old;choose.disabled=saving||!list.value;};
 search.oninput=drawChoices;list.onchange=()=>{choose.disabled=saving||!list.value;};choose.onclick=()=>{if(!saving&&list.value)addName(list.value);};
 save.onclick=()=>perform(async()=>{
  if(saving||!addPending())return;saving=true;input.disabled=add.disabled=save.disabled=true;
  try{await withEditorSave(box,async()=>{
   const result=await api('/api/projects/repositories',{id:project.id,repositories:[...repos],expected_repositories:[...baseline]});
   baseline=[...result.repositories];repos.splice(0,repos.length,...baseline);editorDirty.clear('project-repositories');toast('Project repository links saved');if(onSaved)await onSaved(result);else await loadWorkspace();
  });}finally{saving=false;input.disabled=add.disabled=false;changed();}
 });
 const alive=sequence=>box.isConnected&&sequence===catalogSequence;
 async function catalog(mode='initial'){
  const sequence=++catalogSequence;clearTimeout(catalogTimer);refresh.disabled=true;
  try{
   let data=await api('/api/github/repos/status');if(!alive(sequence))return;
   available=data.repositories;drawChoices();
   const fresh=data.current&&data.checked_at&&Date.now()-Date.parse(data.checked_at)<300000;
   if(mode==='refresh'||mode==='initial'&&!fresh&&!data.job.running){
    status.textContent='Refreshing repository list from GitHub…';
    data=await api('/api/github/repos/sync',{});if(!alive(sequence))return;
    available=data.repositories;drawChoices();
   }
   const running=data.job.running&&data.job.kind==='repositories',count=AtlantaUX.count(data.repositories.length,'repository','repositories');
   status.textContent=running?data.job.status+' · cached choices remain available':
    data.job.kind==='repositories'&&data.job.error?'Refresh failed: '+data.job.error+' Cached choices kept.':
    data.checked_at?count+' · '+(data.current?'last checked ':'cached; last checked ')+dateTime(data.checked_at):count+' cached · full access list has not been loaded yet.';
   refresh.disabled=running;
   if(running)catalogTimer=setTimeout(()=>catalog('poll'),1000);
  }catch(error){if(alive(sequence)){status.textContent='Repository list unavailable: '+error.message+' Existing links are kept. You can enter owner/name manually; access will be checked before publication.';refresh.disabled=false;}}
 }
 refresh.onclick=()=>catalog('refresh');
 row.append(input,add);selection.append(search,list,choose);box.append(selection,manual,validation,save,edits,refresh,status,el('p','hint','These repositories belong to this project. One repository can be linked to several projects. Manual entries are local references; GitHub access and Issues: Read and write are checked before publishing.'));
 const controls=[selection,manual,validation,save,edits,refresh,status,box.children[9]];for(const node of controls)node.hidden=true;let opened=false;
 linkButton.onclick=()=>{selection.hidden=manual.hidden=save.hidden=edits.hidden=refresh.hidden=status.hidden=box.children[9].hidden=false;if(!opened){opened=true;catalog();}search.focus();};
 draw();changed();if(open)linkButton.click();return box;
}
async function loadWorkspace(){
 const sequence=++workspaceSequence,key=$('workspace-project').value;
 const fresh=await api('/api/projects/workspace?id='+encodeURIComponent(key));if(sequence!==workspaceSequence||view!=='projects'||editorDirty.keys().includes('project-repositories'))return;
 workspaceData=fresh;// Keep the project colour and the other saved fields: the cards in Projects show the colour too.
 const known=new Map((state.projects?.projects||[]).map(p=>[p.id,p]));state.projects={...state.projects,projects:fresh.projects.filter(p=>p.id!=='__none__').map(({id,name,color})=>({...known.get(id),id,name,...(color?{color}:{})}))};
 fillProjects($('workspace-project'),fresh.project_id,'All projects',[option('Unassigned','__none__')]);renderWorkspace();syncRoute(true);
}
function renderWorkspace(){
 const data=workspaceData;if(!data)return;
 const cards=$('workspace-cards');cards.replaceChildren();$('workspace-browser').hidden=!!data.project_id;
 for(const project of data.projects){const b=el('button','project-card'+(data.project_id===project.id?' selected':''));const head=el('div','project-card-head');head.append(projectDot(project),el('strong','',project.name));const counts=[[project.open_tasks,'open task'],[project.open_questions,'open question'],[project.meetings,'meeting'],[project.linked_conversations,'conversation']].filter(([n])=>n).map(([n,label])=>AtlantaUX.count(n,label));if(project.color){b.classList.add('has-project-line');b.style.setProperty('--project-color',project.color);}b.append(head,el('span','hint',counts.join(' · ')||'No meetings or work yet'));b.onclick=()=>perform(async()=>{if(!(await leaveEdits()))return;$('workspace-project').value=project.id;await loadWorkspace();});cards.append(b);}
 const activeSection=['task','decision','question'].includes(workspaceSection)?'work':workspaceSection;
 for(const b of $('workspace-tabs').querySelectorAll('button')){const on=b.dataset.section===activeSection;b.classList.toggle('selected',on);b.setAttribute('aria-selected',String(on));const count=b.dataset.section==='meetings'?data.meetings.length:b.dataset.section==='work'?data.items.length:b.dataset.section==='conversations'?(data.conversations||[]).length:0;const title={overview:'Overview',work:'Work',meetings:'Meetings',timeline:'Timeline',conversations:'Conversations'}[b.dataset.section];b.textContent=title+(count?' · '+count:'');}
 const extraSection={sources:'Sources'}[activeSection];$('workspace-more-label').textContent='...';$('workspace-more-label').setAttribute('aria-label','More project sections'+(extraSection?' · '+extraSection+' selected':''));$('workspace-more-label').title='More project sections'+(extraSection?' · '+extraSection+' selected':'');$('workspace-more-label').classList.toggle('selected',!!extraSection);
 const box=$('workspace-content');box.replaceChildren();
 const today=state.task_summary?.today||new Date().toLocaleDateString('en-CA');
 const visible=data.items.filter(i=>!i.dismissed&&(!i.snoozed_until||i.snoozed_until<=today));
 const kinds={task:'Tasks',decision:'Decisions',question:'Questions'};
 // A task or a decision looks and works the same as in My Work.
 const byId=Object.fromEntries((itemsData?.items||[]).map(i=>[i.id,i]));
 function workCard(item){const full=byId[item.id]||item;if(full.kind==='task')return globalTaskRow(full,today,{select:false});if(full.kind==='decision')return decisionRow(full,byId);if(full.kind==='question'&&byId[item.id])return trackedQuestionCard(full);return itemCard(item);}
 function itemCard(item){
  const card=el('article','workspace-item'),cardText=el('strong','',item.text);card.append(cardText,el('p','hint',item.kind+' · '+item.status+(item.owner?' · '+item.owner:'')),projectAssignment(item));
  if(item.answer)card.append(el('p','',item.answer));card.append(sourceChips(item,itemsData.meetings),githubActions({kind:'item',id:item.id}),relationLinks(item),evidenceBlock(item,itemsData.meetings));
  const actions=el('div','action-group workspace-actions');actions.append(...editDeleteButtons(item,cardText));const open=el('button','quiet',item.kind==='task'?'Open task':'Open in My Work');open.onclick=()=>item.kind==='task'?perform(()=>openTaskPanel(item.id)):perform(async()=>{show('tasks');lastTasks='';await loadTasks();$('work-project').value=data.project_id;renderTasks();showWorkTab(item.kind==='question'?'questions':item.kind);});actions.append(open);card.append(actions);return card;
 }
 if(workspaceSection==='overview'){
  const current=data.projects.find(p=>p.id===data.project_id),title=el('h2');if(current?.color)title.append(projectDot(current));title.append(document.createTextNode(current?.name||'All projects'));box.append(title);
  box.append(el('p','hint','One work item can belong to several projects. Manual assignments take priority over linked meeting projects. Source states and saved quotes remain unchanged.'));
  if(current&&current.id!=='__none__')box.append(repositoryEditor(current));else{const repositories=el('section','project-repos');repositories.append(el('h3','','Repositories'),el('p','hint','Choose a project above to view and link its repositories.'));box.append(repositories);}
  for(const [kind,title] of Object.entries(kinds)){
   const rows=visible.filter(i=>i.kind===kind&&(kind==='task'?i.status==='open':kind==='question'?i.status==='open':i.status==='accepted'));
   if(rows.length){box.append(el('h3','',title+' · '+rows.length));for(const item of rows.slice(0,5))box.append(workCard(item));
    // The heading counts the open items; Work lists every item of the kind, also closed ones.
    if(rows.length>5)box.append(actionBtn('secondary small-action workspace-show-all','All '+title.toLowerCase()+' in Work →',async()=>{workspaceSection='work';workspaceWorkKind=kind;renderWorkspace();syncRoute(true);}));}
  }
 }else if(workspaceSection==='meetings'){
  box.append(el('h2','',AtlantaUX.count(data.meetings.length,'meeting')));
  const meetingList=el('div','entity-list');for(const meeting of data.meetings)meetingList.append(meetingCard(meeting,{onChange:loadWorkspace}));box.append(meetingList);
  if(!data.meetings.length)box.append(emptyNote('No meetings in this project yet. Add one from Library with + Add project.'));
 }else if(workspaceSection==='conversations'){
  box.append(el('h2','','Project conversations'),el('p','hint','External conversations cached locally and attached to this project. The meetings themselves are in the Meetings tab. Source snapshots do not imply a task or commitment.'));
  if(!(data.conversations||[]).length)box.append(emptyNote('No external conversations attached yet. Attach one from Library.'));
  for(const conversation of data.conversations||[])box.append(attachmentCard(conversation));
 }else if(workspaceSection==='timeline'){
  renderTimeline(box,data);
 }else if(workspaceSection==='sources'){
  const evs=new Set(data.items.flatMap(i=>i.source_evidence||[])),ids=new Set((data.graph.source_evidence||[]).filter(e=>evs.has(e.id)).map(e=>e.source_id));
  box.append(el('h2','','Sources linked through project work'),el('p','hint','Accept or link a proposal in My Work, then assign its item to a project. This view keeps the original source and its evidence.'));
  const sourceList=el('div','entity-list');for(const source of data.graph.sources||[])if(ids.has(source.id))sourceList.append(sourceCard(source));box.append(sourceList);if(!sourceList.children.length)box.append(emptyNote('No sources are linked through project work yet.'));
 }else if(['work','task','decision','question'].includes(workspaceSection)){if(data.project_id&&data.project_id!=='__none__'){const add=actionBtn('primary','New task in this project',()=>openManualTask());box.append(add);}const filter=el('select');filter.setAttribute('aria-label','Work kind');filter.append(option('All work',''),...Object.entries(kinds).map(([key,title])=>option(title,key)));filter.value=workspaceSection==='work'?workspaceWorkKind:workspaceSection;filter.hidden=!visible.length;filter.onchange=()=>{workspaceSection='work';workspaceWorkKind=filter.value;renderWorkspace();syncRoute(true);};box.append(filter);const rows=visible.filter(i=>!filter.value||i.kind===filter.value);for(const item of rows)box.append(workCard(item));}
 if(!visible.length&&['overview','work','task','decision','question'].includes(workspaceSection)){const empty=el('div','empty-work');empty.append(el('h3','','A place for your next conversation'),el('p','','Record a meeting or attach a conversation to bring this project to life.'));const next=el('button','primary','New meeting');next.onclick=()=>$('new-meeting').click();empty.append(next);box.append(empty);}
 if(box.children.length<2)box.append(el('p','hint','Nothing assigned here yet.'));
}
// A source behind project work: what it is and whether it is still there. The title opens it.
function sourceCard(source){
 const card=el('article','entity-card source-card'),main=el('div','entity-main'),top=el('div','entity-top'),meta=el('div','entity-meta'),label=sourceLabel(source)||SOURCES[source.provider]?.[0]||source.provider;
 top.append(btn('entity-title',label,()=>perform(()=>openSource(source))));meta.append(originChip(source.provider));
 if(!source.available)meta.append(statusBadge({tone:'warn',label:'Source unavailable'}),el('span','','Saved evidence remains'));
 main.append(top,meta);card.append(main);return card;
}
let workspaceWorkKind='';
// Team: the people in my team and their 1:1 reviews. Membership records periods only; it starts no analysis.
let teamTab='members',teamStatus='active',teamData=null,teamSequence=0,teamDialogAction=null,teamReviewId='',teamReview=null,teamReviewRows=null,teamReviewPerson=null;
// The unsaved edits of the open 1:1 review. A save of one part re-renders the panel; the other parts keep their edits.
let teamDrafts={};
async function openTeam(tab){
 if(!(await leaveEdits()))return;dirtyTranscript=dirtyNotes=false;selected=null;if(tab)teamTab=tab;teamReviewId='';teamReview=null;show('team');renderLibrary();await loadTeam();
}
async function loadTeam(){const sequence=++teamSequence,[fresh,reviews]=await Promise.all([api('/api/team'),api('/api/team/reviews')]);if(sequence!==teamSequence||view!=='team')return;teamData=fresh;teamReviewRows=reviews.reviews;renderTeam();}
function teamPeriodText(periods){
 const last=periods.at(-1);if(!last)return '';
 return last.end===null?'In the team since '+date(last.start):'In the team '+date(last.start)+' · left '+date(last.end);
}
function teamCard(member,person){
 const card=el('article','entity-card team-card'),main=el('div','entity-main'),top=el('div','entity-top'),chips=el('div','entity-chips'),meta=el('div','entity-meta');
 const projects=member.project_ids.map(id=>projectList().find(p=>p.id===id)).filter(Boolean);
 if(projects.length===1&&projects[0].color){card.classList.add('has-project-line');card.style.setProperty('--project-color',projects[0].color);}
 top.append(btn('entity-title',person.name,()=>perform(()=>openPerson(person.id))));for(const project of projects)chips.append(projectChip(project));
 const change=member.active?btn('quiet','Leave the team…',()=>openTeamDialog('leave',person)):btn('quiet','Rejoin the team…',()=>openTeamDialog('join',person));
 top.append(chips,rowMenu('More actions for '+person.name,btn('quiet','Open profile',()=>perform(()=>openPerson(person.id))),change));
 const identity=personIdentity(person);if(identity)meta.append(el('span','',identity));
 meta.append(el('span','',teamPeriodText(member.periods)));
 // Earlier periods stay visible: leaving and rejoining keep the history.
 if(member.periods.length>1){const history=el('details','entity-people');history.append(el('summary','',AtlantaUX.count(member.periods.length,'team period')),el('p','hint',member.periods.map(p=>date(p.start)+' – '+(p.end?'left '+date(p.end):'now')).join(' · ')));meta.append(history);}
 if(member.draft)meta.append(statusBadge({tone:'warn',label:'Draft review'}));
 if(member.last_finalized)meta.append(el('span','','Last 1:1 review · '+date(member.last_finalized.end)));else if(!member.draft)meta.append(statusBadge({tone:'muted',label:'No 1:1 review yet'}));
 main.append(top,meta);
 // One visible action: continue the draft, or prepare the next 1:1. A former member keeps it in the … menu.
 const prepare=member.draft?actionBtn('secondary small-action','Open draft',()=>openTeamReview(member.draft.id)):actionBtn('secondary small-action','Prepare 1:1',()=>openPrepareReview(person));
 if(member.active){const actions=el('div','action-group');actions.append(prepare);main.append(actions);}else{prepare.classList.remove('secondary','small-action');top.querySelector('.menu-items')?.prepend(prepare);}
 card.append(avatar(person.name),main);return card;
}
function renderTeam(){
 if(!teamData)return;
 for(const b of $('team-tabs').querySelectorAll('button')){const on=b.dataset.teamTab===teamTab;b.classList.toggle('selected',on);b.setAttribute('aria-selected',String(on));}
 $('team-members-panel').hidden=teamTab!=='members';$('team-reviews-panel').hidden=teamTab!=='reviews';syncRoute(true);
 const people=new Map((state.people||[]).map(p=>[p.id,p])),members=teamData.members.filter(m=>people.has(m.id)),active=members.filter(m=>m.active).length;
 fillProjects($('team-project'),$('team-project').value,'All projects');
 segmentedChoice($('team-status'),[['active','Active · '+active],['former','Former · '+(members.length-active)]],teamStatus,value=>{teamStatus=value;renderTeam();});
 const project=$('team-project').value,list=$('team-list');list.replaceChildren();
 $('team-project').hidden=$('team-status').hidden=!members.length;
 if(!members.length){
  const empty=el('div','empty-work');empty.append(el('h3','','Your team is empty'),el('p','','Add the people who work with you. Their meetings, tasks and sources then stay in one place. Adding a person starts no analysis.'));
  empty.append(actionBtn('primary','＋ Add to my team',()=>openTeamDialog('join')));list.append(empty);
 }else{
  const rows=members.filter(m=>m.active===(teamStatus==='active')&&(!project||m.project_ids.includes(project))).sort((a,b)=>people.get(a.id).name.localeCompare(people.get(b.id).name));
  for(const member of rows)list.append(teamCard(member,people.get(member.id)));
  if(!rows.length)list.append(emptyNote(teamStatus==='active'?(project?'No active member works in this project.':'No active members. Rejoin a former member or add a person.'):(project?'No former member worked in this project.':'No former members. A person who leaves the team stays here with the history.')));
 }
 $('team-review-panel').hidden=true;renderTeamReviews();
}
// One dialog adds a person, ends a period or starts a new one. The date is the first day in the team, or the first day outside it.
function openTeamDialog(action,person=null){
 teamDialogAction={action,person};const today=new Date().toLocaleDateString('en-CA');
 const candidates=(state.people||[]).filter(p=>!(teamData?.members||[]).some(m=>m.id===p.id&&m.active)).sort((a,b)=>a.name.localeCompare(b.name));
 $('team-person-field').hidden=!!person;$('team-error').hidden=true;$('team-date').value=today;
 $('team-person').replaceChildren(...candidates.map(p=>option(p.name,p.id)));
 const leave=action==='leave';
 $('team-dialog-title').textContent=leave?'Leave the team · '+person.name:person?'Rejoin the team · '+person.name:'Add to my team';
 $('team-date-label').textContent=leave?'Left the team on':'In the team from';
 $('team-save').textContent=leave?'Leave the team':person?'Rejoin the team':'Add to my team';
 $('team-dialog-hint').textContent=leave?'The history and the 1:1 reviews stay. The person moves to Former.':'Adding a person starts no analysis. Atlanta prepares a 1:1 only when you ask.';
 if(!person&&!candidates.length){$('team-error').textContent='Everybody in People is already in your team. Add a new person in Settings → People first.';$('team-error').hidden=false;}
 $('team-save').disabled=!person&&!candidates.length;$('team-dialog').showModal();
}
// Reviews: every 1:1 review with its person, period, status and coverage. Search by person, filter by status.
const REVIEW_STATUS={draft:{tone:'warn',label:'Draft'},finalized:{tone:'ok',label:'Finalized'},superseded:{tone:'muted',label:'Superseded'}};
function reviewPeriod(period){const at=value=>dateTime(value);return at(period.start)+' – '+at(period.end)+' · '+period.timezone;}
function reviewCoverage(review){const sources=review.coverage?.sources||[];return sources.length?AtlantaUX.count(sources.length,'source'):'No facts collected yet';}
// A review keeps the name from its time; a later rename shows both. The person ID keeps the attribution.
function reviewPersonName(review){const now=(state.people||[]).find(p=>p.id===review.person_id)?.name||review.person_current_name;return now&&now!==review.person_name?now+' (then '+review.person_name+')':review.person_name;}
function teamReviewCard(review){
 const card=el('article','entity-card team-review-card'),main=el('div','entity-main'),top=el('div','entity-top'),meta=el('div','entity-meta');
 top.append(btn('entity-title',reviewPersonName(review)+' · 1:1 review',()=>perform(()=>openTeamReview(review.id))));
 meta.append(statusBadge(REVIEW_STATUS[review.status]||{tone:'muted',label:review.status}),el('span','',reviewPeriod(review.period)));
 if(review.version>1)meta.append(el('span','','Version '+review.version));
 meta.append(el('span','',reviewCoverage(review)),el('span','',(review.finalized_at?'Finalized ':'Created ')+date(review.finalized_at||review.created)));
 main.append(top,meta);card.append(main);return card;
}
function renderTeamReviews(){
 const box=$('team-reviews'),rows=teamReviewRows||[],query=$('team-review-search').value.trim().toLocaleLowerCase(),status=$('team-review-status').value;
 const shown=rows.filter(r=>(!status||r.status===status)&&(!query||reviewPersonName(r).toLocaleLowerCase().includes(query)));
 box.replaceChildren(...shown.map(teamReviewCard));
 $('team-review-search').hidden=$('team-review-status').hidden=!rows.length;
 if(!rows.length)box.append(emptyNote('No 1:1 reviews yet. Choose Prepare 1:1 on a member of your team.'));
 else if(!shown.length)box.append(emptyNote('No review matches this search or status.'));
}
$('team-review-search').oninput=$('team-review-status').onchange=renderTeamReviews;
// Prepare 1:1: the period comes from the last finalized review, or the last 7 days. Creating the draft collects nothing yet.
const localInput=value=>{const d=new Date(value),pad=n=>String(n).padStart(2,'0');return d.getFullYear()+'-'+pad(d.getMonth()+1)+'-'+pad(d.getDate())+'T'+pad(d.getHours())+':'+pad(d.getMinutes());};
async function openPrepareReview(person){
 const next=await api('/api/team/review/prepare?person='+encodeURIComponent(person.id));teamReviewPerson=person;
 $('team-review-dialog-title').textContent='Prepare 1:1 · '+person.name;$('team-review-error').hidden=true;
 $('team-review-period-hint').textContent=next.first?'First review: the last 7 days. Change the period if you need a different one.':'From the end of the last finalized review until now.';
 $('team-review-start').value=localInput(next.start);$('team-review-end').value=localInput(next.end);$('team-review-dialog').showModal();
}
$('team-review-form').onsubmit=event=>{event?.preventDefault();return perform(async()=>{
 try{const review=await api('/api/team/review/create',{person_id:teamReviewPerson.id,start:$('team-review-start').value,end:$('team-review-end').value});$('team-review-dialog').close();toast('Draft review created');await openTeamReview(review.id,{saved:true});}
 catch(exc){$('team-review-error').textContent=exc.message;$('team-review-error').hidden=false;}
});};
$('team-review-close').onclick=()=>$('team-review-dialog').close();
// One review: the period, status and coverage on top; the review text; then the conversation notes, which stay editable.
async function openTeamReview(id,{saved=false}={}){
 // After a save in a dialog nothing is unsaved; the dialog save is still settling.
 if(!saved&&!(await leaveEdits()))return;dirtyTranscript=dirtyNotes=false;selected=null;
 const review=await api('/api/team/review?id='+encodeURIComponent(id));teamReviewId=id;teamReview=review;show('team');renderLibrary();renderTeamReview();
}
function renderTeamReview(){
 const r=teamReview,box=$('team-review-panel');$('team-members-panel').hidden=$('team-reviews-panel').hidden=true;box.hidden=false;
 for(const b of $('team-tabs').querySelectorAll('button')){const on=b.dataset.teamTab==='reviews';b.classList.toggle('selected',on);b.setAttribute('aria-selected',String(on));}
 editorDirty.clear('team-review');editorDirty.clear('team-notes');editorDirty.clear('team-agreements');editorDirty.clear('team-previous');syncRoute(true);
 if(teamDrafts.id!==r.id)teamDrafts={id:r.id};
 const drafts=teamDrafts;
 const back=actionBtn('quiet team-back','← All reviews',()=>openTeam('reviews'));
 const head=el('div','card team-review-head'),title=el('h2','',reviewPersonName(r)+' · 1:1 review'),meta=el('div','entity-meta');
 meta.append(statusBadge(REVIEW_STATUS[r.status]||{tone:'muted',label:r.status}),el('span','',reviewPeriod(r.period)),el('span','','Version '+r.version),el('span','',reviewCoverage(r)));
 head.append(el('p','eyebrow','1:1 REVIEW'),title,meta);
 // The limitations are in the Coverage section of the review; the head names only what waits for a person.
 if(r.coverage?.excluded)head.append(el('p','hint',AtlantaUX.count(r.coverage.excluded,'item')+' excluded from the analysis · '+(r.coverage.excluded===1?'it needs':'they need')+' confirmation. See Coverage.'));
 if(r.status==='superseded'&&r.superseded_by)head.append(el('p','notice','A newer version replaces this review.'));
 // A source that changed after the review: a finalized review stays fixed and suggests a new version.
 const changes=r.source_changes||[];
 if(changes.length&&r.status!=='superseded'){const box=el('details','notice team-source-changes');box.append(el('summary','',AtlantaUX.count(changes.length,'source')+' changed after this review was collected.'+(r.status==='finalized'?' Make a new version to correct it.':' Collect the facts again to update it.')),...changes.map(c=>el('p','hint',(c.removed?'Removed · ':'Changed · ')+c.text)));head.append(box);}
 // The AI run of this review: what wrote it, or that it is incomplete and blocks Finalize.
 const gen=r.generator;if(gen)head.append(el('p',gen.complete?'hint':'notice',gen.complete?'AI preparation · '+gen.model+' · '+(gen.at?dateTime(gen.at):'')+(gen.rejected?' · '+AtlantaUX.count(gen.rejected,'statement')+' rejected by the check':''):'The AI preparation is incomplete. Run it again before you finalize; the finished parts are kept.'));
 const aiJob=teamAIJob&&teamAIJob.review_id===r.id?teamAIJob:null;
 if(aiJob?.running){const line=el('p','notice team-ai-progress',aiJob.status+(aiJob.total>1?' · '+aiJob.done+' of '+aiJob.total+' parts':''));line.append(' ',actionBtn('quiet small-action','Stop',async()=>{teamAIJob=await api('/api/team/review/ai/stop',{job:aiJob.id});refreshJobs();renderTeamReview();}));head.append(line);}
 else if(aiJob?.error)head.append(el('p','error',aiJob.error));
 const ghJob=teamGitHubJob&&teamGitHubJob.review_id===r.id?teamGitHubJob:null;
 if(ghJob?.running){const line=el('p','notice team-ai-progress','GitHub · '+ghJob.status);line.append(' ',actionBtn('quiet small-action','Stop',async()=>{teamGitHubJob=await api('/api/team/review/github/stop',{job:ghJob.id});refreshJobs();renderTeamReview();}));head.append(line);}
 else if(ghJob?.error)head.append(el('p','error',ghJob.error));
 for(const text of r.coverage?.github?.limitations||[])head.append(el('p','hint','GitHub · '+text));
 const actions=el('div','action-group team-review-actions'),draft=r.status==='draft';
 const text=el('textarea','team-review-text');text.rows=22;text.setAttribute('aria-label','Review text');
 text.oninput=()=>{const edited=text.value!==teamReview.review_md;if(edited)drafts.review_md=text.value;else delete drafts.review_md;editorDirty.set('team-review',edited);};
 if(drafts.review_md!==undefined&&draft&&drafts.review_md!==r.review_md){text.value=drafts.review_md;editorDirty.set('team-review',true);}else{delete drafts.review_md;text.value=r.review_md;}
 const saveText=async()=>{if(text.value!==teamReview.review_md){teamReview=await api('/api/team/review/save',{id:r.id,revision:teamReview.revision,review_md:text.value});}delete drafts.review_md;editorDirty.clear('team-review');};
 if(draft){
  actions.append(actionBtn('primary','Finalize',async()=>{if(!(await ask('Finalize this review? The review text is then fixed. A correction becomes a new version. The conversation notes stay editable.',{ok:'Finalize'})))return;await saveText();teamReview=await api('/api/team/review/finalize',{id:r.id,revision:teamReview.revision});toast('Review finalized');renderTeamReview();}),
   actionBtn('secondary','Save draft',async()=>{await saveText();toast('Draft saved');renderTeamReview();}),
   actionBtn('secondary','Collect GitHub contribution…',()=>openTeamGitHub(r)),
   actionBtn('secondary','Prepare with AI…',()=>openTeamAI(r)),
   ...([actionBtn('secondary','Collect facts again',async()=>{if(!(await ask('Collect the facts of this period again? The new facts replace the review text, also your edits, the GitHub part and the AI part. The conversation notes stay.',{ok:'Collect again'})))return;teamReview=await api('/api/team/review/collect',{id:r.id,revision:teamReview.revision});delete drafts.review_md;editorDirty.clear('team-review');toast('Facts collected again');renderTeamReview();})]),
   actionBtn('quiet danger-text','Discard draft',async()=>{if(!(await ask('Discard this draft? The next period does not change.',{ok:'Discard draft',danger:true})))return;await api('/api/team/review/discard',{id:r.id,revision:teamReview.revision});editorDirty.clear('team-review');editorDirty.clear('team-notes');editorDirty.clear('team-agreements');editorDirty.clear('team-previous');teamDrafts={};toast('Draft discarded');await openTeam('reviews');}));
 }else{
  if(r.status==='finalized')actions.append(actionBtn('secondary','New version…',async()=>{if(!(await ask('Make a new version to correct this review? This review stays as it is until you finalize the new version.',{ok:'Make new version'})))return;const fresh=await api('/api/team/review/version',{id:r.id});await openTeamReview(fresh.id);}));
 }
 actions.append(actionBtn('secondary','Export Markdown',()=>exportTeamReview(teamReview)));
 // Delete is explicit and removes the review, its notes, actions, goals and evidence from this Mac.
 if(r.status!=='draft')actions.append(actionBtn('quiet danger-text','Delete review…',async()=>{if(!(await ask('Delete this 1:1 review of '+reviewPersonName(r)+' with its notes, actions, goals and evidence from this Mac? This cannot be undone. Earlier backup archives keep their copies until you delete them.',{ok:'Delete review',danger:true})))return;await api('/api/team/review/delete',{id:r.id,revision:teamReview.revision});editorDirty.clear('team-notes');editorDirty.clear('team-agreements');editorDirty.clear('team-previous');teamDrafts={};toast('Review deleted');await openTeam('reviews');}));
 // The version links: to the newer review, and to the one that this version replaces.
 if(r.status==='superseded'&&r.superseded_by)actions.prepend(actionBtn('primary','Open the newer version',()=>openTeamReview(r.superseded_by)));
 if(r.supersedes)actions.append(actionBtn('quiet','Open the version it replaces',()=>openTeamReview(r.supersedes)));
 head.append(actions);
 const body=el('section','card team-review-body');body.append(el('h3','','Review'));
 // A draft reads like the final review; Edit text opens the Markdown.
 if(draft){const view=markdownBlock(r.review_md),edit=btn('secondary small-action team-edit-text','Edit text');text.hidden=true;
  // Unsaved edits of the text stay open in the editor, so they are in view.
  if(drafts.review_md!==undefined)queueMicrotask(()=>edit.click());edit.onclick=()=>{const open=text.hidden;text.hidden=!open;view.hidden=open;edit.textContent=open?'Show the review':'Edit text';if(open)text.focus();};body.querySelector('h3').after(edit);body.append(view,text);}
 else body.append(markdownBlock(r.review_md));
 body.append(evidenceList(r));
 const notesCard=el('section','card team-review-notes'),notes=el('textarea','team-notes-text');notes.rows=8;notes.placeholder='Notes, agreed actions and goals of the conversation';notes.setAttribute('aria-label','Conversation notes');
 if(drafts.notes_md!==undefined&&drafts.notes_md!==r.notes_md){notes.value=drafts.notes_md;editorDirty.set('team-notes',true);}else{delete drafts.notes_md;notes.value=r.notes_md;}
 notes.oninput=()=>{const edited=notes.value!==teamReview.notes_md;if(edited)drafts.notes_md=notes.value;else delete drafts.notes_md;editorDirty.set('team-notes',edited);};
 const saveNotes=actionBtn('secondary small-action','Save notes',async()=>{const value=notes.value;teamReview=await api('/api/team/review/notes',{id:r.id,revision:teamReview.revision,notes_md:value});if(notes.value===value){delete drafts.notes_md;editorDirty.clear('team-notes');}toast('Notes saved');});
 notesCard.append(el('h3','','Conversation notes'),el('p','hint','Separate from the review. Edit them before and after the conversation; they never change the review.'),notes,saveNotes);
 box.replaceChildren(back,head,...(r.previous_agreements?.agreements?.length?[previousAgreementsCard(r.previous_agreements,drafts)]:[]),body,notesCard,agreementsCard(r,drafts));
}
// The evidence records that the review cites: what, when, why it counts, and the quote. Each opens its source.
const EVIDENCE_LABELS={task_assigned:'Assigned',task_taken_on:'Taken on',task_completed:'Completed',result_confirmed:'Result confirmed',task_overdue:'Overdue',task_cancelled:'Cancelled',task_transferred:'Transferred',task_left:'Took part until',due_changed:'Due date changed',task_open:'Open',task_carried:'Carried over',decision:'Decision',waits_for:'Waits for',github_pr_opened:'PR opened',github_pr_merged:'PR merged',github_pr_closed_without_merge:'PR closed',github_pr_changed:'PR changed',github_review:'Review given',github_commit:'Commit'};
function evidenceList(r){
 const box=el('details','team-evidence'),rows=r.evidence||[];box.append(el('summary','','Evidence · '+rows.length));
 if(!rows.length){box.append(el('p','hint','No evidence records in this review.'));return box;}
 for(const e of rows){
  const row=el('div','team-evidence-row'),head=el('div','entity-meta');
  head.append(el('strong','',e.id),el('span','',EVIDENCE_LABELS[e.kind]||e.kind),el('span','',e.occurred_at?date(e.occurred_at):''),el('span','',e.confirmation_basis));
  row.append(head,el('p','',e.facts?.text||''));if(e.quote)row.append(el('blockquote','',e.quote));
  const ref=e.source_ref||{},links=el('div','action-group');row.append(links);
  if(ref.meeting_id&&ref.timestamp)links.append(listenButton(ref.meeting_id,stampSeconds(ref.timestamp),{label:'',className:'chip-listen',title:'Play from '+ref.timestamp}));
  if(ref.url&&/^https:\/\/github\.com\//.test(ref.url)){const open=el('a','quiet small-action button-link','Open on GitHub ');open.append(icon('external'));open.href=ref.url;open.target='_blank';open.rel='noopener noreferrer';links.append(open);}
  if(ref.item_id)links.append(actionBtn('quiet small-action','Open the work item',async()=>{const item=(await api('/api/items')).items.find(i=>i.id===ref.item_id);if(!item){toast('This work item no longer exists');return;}if(item.kind==='task')return openTaskPanel(item.id);show('tasks');lastTasks='';await loadTasks();showWorkTab(item.kind==='question'?'questions':item.kind);}));
  box.append(row);
 }
 return box;
}
// AI preparation: a preview of the destination and the exact records, an explicit approval, then one job.
let teamAIPreview=null,teamAIJob=null,teamAITimer=null;
async function openTeamAI(r){
 if(editorDirty.keys().includes('team-review')){toast('Save the draft first');return;}
 const p=await api('/api/team/review/ai/preview?id='+encodeURIComponent(r.id));teamAIPreview=p;
 const box=$('team-ai-summary');box.replaceChildren();$('team-ai-error').hidden=true;$('team-ai-approve').checked=false;$('team-ai-start').disabled=true;
 if(!p.ai_available){$('team-ai-error').textContent=p.ai_unavailable_reason;$('team-ai-error').hidden=false;}
 const t=p.target,facts=[['Destination',(t.provider==='openai'?'OpenAI':'Configured API')+' · '+t.local_ai_model],['Address',t.local_ai_base_url||'—'],['Records',p.records+' · '+AtlantaUX.count(p.batches,'part')+' · '+p.characters.toLocaleString('en-GB')+' characters']];
 for(const [name,value] of facts){const row=el('p','team-ai-fact');row.append(el('strong','',name+': '),document.createTextNode(value));box.append(row);}
 if(p.remote)box.append(el('p','notice','This destination is outside this Mac. The records, with their quotes and the name '+r.person_name+', leave the Mac.'));
 if(!p.records)box.append(el('p','hint','This review has no records. The AI can only say that there is not enough data.'));
 $('team-ai-input').textContent=JSON.stringify(p.input,null,2);$('team-ai-dialog').showModal();
}
$('team-ai-approve').onchange=()=>{$('team-ai-start').disabled=!$('team-ai-approve').checked||!teamAIPreview?.ai_available;};
$('team-ai-form').onsubmit=event=>{event?.preventDefault();return perform(async()=>{
 try{teamAIJob=await api('/api/team/review/ai/start',{id:teamReview.id,preview_token:teamAIPreview.preview_token,approved:$('team-ai-approve').checked});refreshJobs();$('team-ai-dialog').close();renderTeamReview();pollTeamAI();}
 catch(exc){$('team-ai-error').textContent=exc.message;$('team-ai-error').hidden=false;}
});};
$('team-ai-close').onclick=()=>$('team-ai-dialog').close();
// The job runs in the background; the page follows it and reloads the draft when it ends.
function pollTeamAI(){
 clearTimeout(teamAITimer);if(!teamAIJob)return;
 teamAITimer=setTimeout(()=>perform(async()=>{
  try{teamAIJob=await api('/api/team/review/ai/status?job='+teamAIJob.id);}catch(exc){refreshJobs();throw exc;}
  refreshJobs();
  const here=view==='team'&&teamReview?.id===teamAIJob.review_id;
  if(teamAIJob.running){if(here&&!editorDirty.has())renderTeamReview();pollTeamAI();return;}
  if(teamAIJob.status==='Ready to review')toast('AI preparation ready · check it against the evidence');
  else if(teamAIJob.error)toast('AI preparation stopped: '+teamAIJob.error);
  if(here){teamReview=await api('/api/team/review?id='+encodeURIComponent(teamReview.id));renderTeamReview();}
 }),1500);
}
// GitHub: find the repositories with activity, let the person exclude some, then collect in the background.
let teamGitHubFound=null,teamGitHubJob=null,teamGitHubTimer=null;
async function openTeamGitHub(r){
 if(editorDirty.keys().includes('team-review')){toast('Save the draft first');return;}
 if(r.generator&&!(await ask('Collecting GitHub removes the AI part, because it may cite old records. Run the AI again after it. Continue?',{ok:'Continue'})))return;
 const box=$('team-github-repos');box.replaceChildren();$('team-github-error').hidden=true;$('team-github-start').disabled=true;$('team-github-hint').textContent='Finding the repositories with activity in the period…';$('team-github-dialog').showModal();
 try{teamGitHubFound=await api('/api/team/review/github/discover?id='+encodeURIComponent(r.id));}
 catch(exc){$('team-github-error').textContent=exc.message;$('team-github-error').hidden=false;$('team-github-hint').textContent='';return;}
 const f=teamGitHubFound;$('team-github-hint').textContent=f.repositories.length?'@'+f.login+' · '+AtlantaUX.count(f.repositories.length,'repository','repositories')+' with pull requests or reviews in the period. Clear a repository to leave it out.':'@'+f.login+' has no pull requests or reviews in the period that this token can see.';
 for(const repo of f.repositories){const label=el('label','project-choice'),check=el('input');check.type='checkbox';check.value=repo.name;check.checked=true;check.onchange=syncGitHubStart;label.append(check,document.createTextNode(repo.name+' · '+[repo.authored&&AtlantaUX.count(repo.authored,'pull request'),repo.reviewed&&AtlantaUX.count(repo.reviewed,'review')].filter(Boolean).join(' · ')));box.append(label);}
 for(const text of f.limitations)box.append(el('p','notice',text));
 syncGitHubStart();
}
function syncGitHubStart(){const n=$('team-github-repos').querySelectorAll('input:checked').length;$('team-github-start').disabled=!n;$('team-github-start').textContent=n?'Collect from '+AtlantaUX.count(n,'repository','repositories'):'Collect';}
$('team-github-form').onsubmit=event=>{event?.preventDefault();return perform(async()=>{
 try{teamGitHubJob=await api('/api/team/review/github/start',{id:teamReview.id,revision:teamGitHubFound.revision,repositories:[...$('team-github-repos').querySelectorAll('input:checked')].map(c=>c.value)});refreshJobs();$('team-github-dialog').close();renderTeamReview();pollTeamGitHub();}
 catch(exc){$('team-github-error').textContent=exc.message;$('team-github-error').hidden=false;}
});};
$('team-github-close').onclick=()=>$('team-github-dialog').close();
function pollTeamGitHub(){
 clearTimeout(teamGitHubTimer);if(!teamGitHubJob)return;
 teamGitHubTimer=setTimeout(()=>perform(async()=>{
  try{teamGitHubJob=await api('/api/team/review/github/status?job='+teamGitHubJob.id);}catch(exc){refreshJobs();throw exc;}
  refreshJobs();
  const here=view==='team'&&teamReview?.id===teamGitHubJob.review_id;
  if(teamGitHubJob.running){if(here&&!editorDirty.has())renderTeamReview();pollTeamGitHub();return;}
  if(teamGitHubJob.status==='Ready to review')toast('GitHub contribution collected');else if(teamGitHubJob.error)toast(teamGitHubJob.error);
  if(here){teamReview=await api('/api/team/review?id='+encodeURIComponent(teamReview.id));renderTeamReview();}
 }),1200);
}
// Actions and goals after the conversation: only what the manager saves counts. They stay editable, also after Finalize.
const AGREEMENT_OWNERS=[['person','The person'],['manager','Me'],['both','Both']],AGREEMENT_STATES=[['open','Open'],['done','Done'],['dropped','Dropped']];
function agreementRow(row,onchange,{full=true,person=''}={}){
 const line=el('div','team-agreement'),kind=el('select'),text=el('input'),owner=el('select'),due=el('input'),status=el('select');
 kind.append(option('Action','action'),option('Goal','goal'));kind.value=row.kind;text.value=row.text;text.maxLength=1000;text.placeholder=row.kind==='goal'?'What should change?':'What will happen?';
 owner.append(...AGREEMENT_OWNERS.map(([v,l])=>option(l,v)));owner.value=row.owner;due.type='date';due.value=row.due_date||'';status.append(...AGREEMENT_STATES.map(([v,l])=>option(l,v)));status.value=row.status;
 for(const [c,n] of [[kind,'Kind'],[text,'Action or goal'],[owner,'Owner'],[due,'Due date'],[status,'State']])c.setAttribute('aria-label',n);
 const read=()=>Object.assign(row,{kind:kind.value,text:text.value,owner:owner.value,due_date:due.value||null,status:status.value});
 for(const c of [kind,text,owner,due,status])c.oninput=c.onchange=()=>{read();onchange();};
 if(!full){line.classList.add('compact');line.append(el('span','team-agreement-text',(row.kind==='goal'?'Goal · ':'Action · ')+row.text+(row.due_date?' · due '+date(row.due_date):'')),status);return line;}
 line.append(kind,text,owner,due,status);
 // A goal keeps the column of Make a task…, so the rows stay aligned.
 line.append(row.kind==='action'?actionBtn('quiet small-action','Make a task…',()=>openManualTask(null,{text:row.text,owner:row.owner==='person'?person:'',due:row.due_date||''})):el('span'));
 line.append(actionBtn('quiet small-action','Remove',()=>{line.dispatchEvent(new CustomEvent('remove-agreement',{bubbles:true}));}));
 return line;
}
function agreementsCard(r,drafts={}){
 const saved=JSON.stringify(r.agreements||[]);if(drafts.agreements&&JSON.stringify(drafts.agreements)===saved)delete drafts.agreements;
 const card=el('section','card team-agreements'),list=el('div','team-agreement-list'),rows=structuredClone(drafts.agreements||r.agreements||[]);
 const dirty=()=>{const edited=JSON.stringify(rows)!==saved;if(edited)drafts.agreements=structuredClone(rows);else delete drafts.agreements;editorDirty.set('team-agreements',edited);};
 if(drafts.agreements)editorDirty.set('team-agreements',true);
 const draw=()=>{list.replaceChildren(...rows.map(row=>agreementRow(row,dirty,{person:reviewPersonName(r).replace(/ \(then .*\)$/,'')})));if(!rows.length)list.append(emptyNote('No actions or goals yet. Add what you agreed in the conversation.'));};
 list.addEventListener('remove-agreement',event=>{const index=[...list.children].indexOf(event.target);if(index>=0){rows.splice(index,1);draw();dirty();}});
 const add=kind=>()=>{rows.push({kind,text:'',owner:'person',due_date:null,status:'open'});draw();dirty();list.lastElementChild?.querySelector('input')?.focus();};
 const save=actionBtn('secondary small-action','Save actions and goals',async()=>{teamReview=await api('/api/team/review/agreements',{id:r.id,revision:teamReview.revision,agreements:rows.filter(x=>x.text.trim())});delete drafts.agreements;editorDirty.clear('team-agreements');toast('Actions and goals saved');renderTeamReview();});
 const buttons=el('div','action-group');buttons.append(actionBtn('quiet small-action','＋ Action',add('action')),actionBtn('quiet small-action','＋ Goal',add('goal')),save);
 card.append(el('h3','','Agreed actions and goals'),el('p','hint','Only what you save here counts. The next review shows each one with its state. A task starts only when you create it.'),list,buttons);draw();return card;
}
// The actions and goals of the last 1:1, with their state. A change saves to that review; its text stays fixed.
function previousAgreementsCard(previous,drafts={}){
 const saved=JSON.stringify(previous.agreements),kept=drafts.previous?.revision===previous.revision&&JSON.stringify(drafts.previous.rows)!==saved;if(!kept)delete drafts.previous;
 const card=el('section','card team-agreements previous'),rows=structuredClone(kept?drafts.previous.rows:previous.agreements),list=el('div','team-agreement-list');
 if(kept)editorDirty.set('team-previous',true);
 const dirty=()=>{const edited=JSON.stringify(rows)!==saved;if(edited)drafts.previous={revision:previous.revision,rows:structuredClone(rows)};else delete drafts.previous;editorDirty.set('team-previous',edited);};
 list.append(...rows.map(row=>agreementRow(row,dirty,{full:false})));
 const save=actionBtn('secondary small-action','Save states',async()=>{await api('/api/team/review/agreements',{id:previous.review_id,revision:previous.revision,agreements:rows});delete drafts.previous;editorDirty.clear('team-previous');toast('States saved · collect the facts again to update this draft');teamReview=await api('/api/team/review?id='+encodeURIComponent(teamReview.id));renderTeamReview();});
 card.append(el('h3','','From the last 1:1 · '+date(previous.period.start)+' – '+date(previous.period.end)),el('p','hint','Mark each one done or dropped. Collect the facts again to show the new states in this draft.'),list,save);return card;
}
// Export: the review and the notes as one Markdown file. Nothing is sent anywhere.
function exportTeamReview(r){
 const agreements=(r.agreements||[]).map(a=>'- '+(a.kind==='goal'?'Goal':'Action')+' · '+a.text+' · '+a.status+(a.due_date?' · due '+date(a.due_date):'')).join('\n');
 const text=r.review_md.trimEnd()+'\n\n---\n\n## Conversation notes\n\n'+(r.notes_md.trim()||'_No notes._')+'\n\n## Agreed actions and goals\n\n'+(agreements||'_None._')+'\n',link=document.createElement('a');
 link.href=URL.createObjectURL(new Blob([text],{type:'text/markdown'}));link.download='1-1-review-'+r.person_name.replace(/[^\p{L}\p{N}]+/gu,'-').toLowerCase()+'-'+r.period.end.slice(0,10)+'-v'+r.version+'.md';
 document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(link.href),1000);
}
$('team-form').onsubmit=event=>{event?.preventDefault();return perform(async()=>{
 const {action,person}=teamDialogAction,chosen=person||(state.people||[]).find(p=>p.id===$('team-person').value);if(!chosen)return;
 if(!validDates($('team-form')))return;
 try{const result=await api('/api/team/membership',{id:chosen.id,revision:(state.people||[]).find(p=>p.id===chosen.id)?.revision,action,date:$('team-date').value});
  state.people=result.people;teamData=result.team;$('team-dialog').close();if(action==='join')teamStatus='active';renderTeam();toast(action==='leave'?chosen.name+' left the team':chosen.name+' is in your team');}
 catch(exc){$('team-error').textContent=exc.message;$('team-error').hidden=false;}
});};
$('team-close').onclick=()=>$('team-dialog').close();
$('team-add').onclick=()=>openTeamDialog('join');
$('team-project').onchange=renderTeam;
for(const b of $('team-tabs').querySelectorAll('button'))b.onclick=()=>perform(()=>openTeam(b.dataset.teamTab));
$('open-team').onclick=()=>perform(()=>openTeam());
$('open-projects').onclick=()=>perform(async()=>{if(!(await leaveEdits()))return;dirtyTranscript=dirtyNotes=false;selected=null;show('projects');itemsData=await api('/api/items');await loadWorkspace();});
$('workspace-project').onchange=()=>perform(async()=>{if(!(await leaveEdits())){$('workspace-project').value=workspaceData?.project_id||'';return;}await loadWorkspace();});
$('workspace-refresh').onclick=()=>perform(async()=>{if(!(await leaveEdits()))return;itemsData=await api('/api/items');await loadWorkspace();});
function askProject(){return new Promise(resolve=>{const dialog=$('project-dialog');$('project-name').value='';$('project-color').value=PROJECT_PALETTE[projectList().length%PROJECT_PALETTE.length];dialog.returnValue='';dialog.onclose=()=>{resolve(dialog.returnValue==='ok'&&$('project-name').value.trim()?{name:$('project-name').value.trim(),color:$('project-color').value}:null);};dialog.showModal();$('project-name').focus();});}
// One way to create a project, from Projects and from Settings → Projects.
async function createProject(){const spec=await askProject();if(!spec)return null;const created=await api('/api/projects/create',spec);state.projects=created.projects;lastProjects='';syncProjects();return created;}
$('workspace-new').onclick=()=>perform(async()=>{if(!(await leaveEdits()))return;const created=await createProject();if(!created)return;fillProjects($('workspace-project'),created.id,'All projects',[option('Unassigned','__none__')]);await loadWorkspace();});
$('settings-new-project').onclick=()=>perform(async()=>{if(await createProject())renderProjectSettings();});
for(const b of $('workspace-tabs').querySelectorAll('button'))b.onclick=()=>perform(async()=>{if(!(await leaveEdits()))return;workspaceSection=b.dataset.section;renderWorkspace();syncRoute(true);});

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
 if(!(await leaveEdits()))return;dirtyTranscript=dirtyNotes=false;selected=null;show('conversations');syncConversationFilters();if(!conversationPage){try{const saved=JSON.parse(sessionStorage.getItem('atlanta-library-filters')||'null');if(saved){for(const id of ['query','source','project','from','to'])$('conversation-'+id).value=saved[id]|| (id==='source'?'meeting':'');syncConversationFilters();$('conversation-participant').replaceChildren(option(saved.participant||'All participants',saved.participant||''));$('conversation-series').value=saved.series||'';conversationOffset=saved.offset||0;}}catch{}}await loadConversations();renderLibrary();
}
function rememberConversationFilters(){const values={offset:conversationOffset};for(const id of ['query','source','project','series','participant','from','to'])values[id]=$('conversation-'+id).value;try{sessionStorage.setItem('atlanta-library-filters',JSON.stringify(values));}catch{};renderConversationFilterChips();}
function renderConversationFilterChips(){const box=$('conversation-filter-chips');box.replaceChildren();let extra=0;for(const [id,label,empty] of [['query','Search',''],['project','Project',''],['from','From',''],['to','Through',''],['source','Source','meeting'],['series','Series',''],['participant','Participant','']]){const control=$('conversation-'+id);if(control.value===empty)continue;const value=id==='from'||id==='to'?date(control.value):control.selectedOptions?.[0]?.textContent||control.value;const remove=btn('quiet',label+': '+value+' ×');remove.onclick=()=>{control.value=empty;if(id==='project')fillSeries($('conversation-series'),'','','All series');conversationOffset=0;selectedConversations.clear();perform(loadConversations);};box.append(remove);if(id!=='query')extra++;}$('conversation-filter-count').textContent=extra?'('+extra+')':'';}
async function loadConversations(){
 rememberConversationFilters();
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
function attachmentCard(row){return conversationCard(row,{onChange:loadWorkspace});}
// A Gmail thread, a Chat conversation or a saved snapshot on the shared card: what it is, its projects, its last activity and a short preview.
// The title opens it. The project picker attaches a thread or changes the projects of a snapshot.
function conversationCard(row,{onChange=null}={}){
 const attached=!row.provider||row.provider==='attached',kind=attached?row.kind:row.provider,excerpt=kind==='excerpt',attachmentId=attached?(row.external_id||row.id):row.attachment_id;
 const ids=row.project_ids||[],projects=ids.map(id=>projectList().find(p=>p.id===id)).filter(Boolean),title=excerpt?row.title.replace(/ · excerpt$/,''):row.title;
 const card=el('article','entity-card conversation-card'+(excerpt?' excerpt-card':''));
 if(projects.length===1&&projects[0].color){card.classList.add('has-project-line');card.style.setProperty('--project-color',projects[0].color);}
 const main=el('div','entity-main'),top=el('div','entity-top'),chips=el('div','entity-chips'),meta=el('div','entity-meta');
 const open=async()=>{if(attached)return openAttachment(attachmentId);show('tasks');lastTasks='';await loadTasks();if(kind==='gmail'){showWorkTab('gmail');await openMail(row.external_id);}else{chatSpace=row.external_id;showWorkTab('chat');}};
 const heading=btn('entity-title',title);heading.onclick=()=>perform(open);top.append(heading);
 for(const project of projects)chips.append(projectChip(project));
 // The same project picker as a meeting card. A thread or a snapshot can belong to several projects.
 const picker=el('details','project-pick'),summary=el('summary','add-project','＋ Add project'),body=el('div','project-pick-body multi'),choices=conversationProjectChoices(ids),buttons=el('div','action-group'),save=btn('primary small-action','Save'),cancel=btn('secondary small-action','Cancel',()=>{picker.open=false;});
 summary.hidden=!!projects.length;buttons.append(save,cancel);body.append(choices.box,buttons);picker.append(summary,body);chips.append(picker);
 save.onclick=()=>perform(async()=>{
  const chosen=choices.value();if(!chosen.length){toast('Choose at least one project');return;}
  if(attached)await api('/api/conversations/projects',{id:attachmentId,revision:row.revision,project_ids:chosen});
  else await api('/api/conversations/attach',{provider:kind,external_id:row.external_id,account:row.account,revision:row.revision,attachment_revision:row.attachment_revision,project_ids:chosen});
  picker.open=false;toast((attached?'Projects saved · ':'Attached · ')+AtlantaUX.count(chosen.length,'project'));if(onChange)await onChange();
 });
 const actions=[btn('quiet',excerpt?'Open excerpt':attached?'Open snapshot':'Open conversation',()=>perform(open)),btn('quiet',projects.length?'Change projects…':'Add to a project…',()=>{picker.open=true;})];
 if(!attached&&row.attachment_id)actions.push(btn('quiet','Open saved snapshot',()=>perform(()=>openAttachment(row.attachment_id))));
 if(excerpt&&row.locator?.meeting_id)actions.push(btn('quiet','Open original meeting',()=>perform(async()=>{await openMeeting(row.locator.meeting_id);showSeconds(row.locator.start);})));
 top.append(chips,rowMenu('More actions for '+title,...actions));
 // One row of facts: the source, when, and who. A snapshot says that it does not update.
 meta.append(originChip(kind));
 const facts=[];
 if(excerpt&&row.locator)facts.push(time(row.locator.start)+'–'+time(row.locator.end));
 facts.push(excerpt?date(row.date):dateTime(row.date));
 if(attached&&!excerpt)facts.push('saved snapshot');
 meta.append(el('span','',facts.join(' · ')));
 const people=(row.participants||[]).filter(Boolean);
 if(people.length===1)meta.append(el('span','',people[0]));
 else if(people.length){const box=el('details','entity-people');box.append(el('summary','',AtlantaUX.count(people.length,excerpt?'speaker':'participant')),el('p','hint',people.join(', ')));meta.append(box);}
 if(excerpt&&row.locator?.meeting_id)meta.append(listenButton(row.locator.meeting_id,row.locator.start,{label:'',until:row.locator.end,className:'chip-listen',title:'Play the excerpt'}));
 main.append(top,meta);
 if(row.preview)main.append(el('p','entity-preview'+(excerpt?' quote':''),row.preview));
 card.append(main);return card;
}
function renderConversations(){
 if(!conversationPage)return;const result=conversationPage,list=$('conversation-list');list.replaceChildren();
 $('conversation-select-page').disabled=!result.rows.some(row=>row.provider==='meeting');
 const hasFilters=['query','project','series','participant','from','to'].some(id=>$('conversation-'+id).value)||$('conversation-source').value!=='meeting';
 const emptyLibrary=!result.total&&!state.meetings.length&&!hasFilters;
 $('conversation-empty').hidden=!emptyLibrary;$('conversation-filters').hidden=emptyLibrary;$('conversation-notices').hidden=emptyLibrary;
 $('conversation-count').textContent=AtlantaUX.count(result.total,'conversation')+(result.total>result.rows.length?' · '+(result.offset+1)+'–'+Math.min(result.offset+result.rows.length,result.total):'');
 $('conversation-count').parentElement.hidden=!result.total;document.querySelector('.conversation-pagination').hidden=result.total<=50;
 $('conversation-selection').textContent=AtlantaUX.count(selectedConversations.size,'meeting')+' selected';$('conversation-move').disabled=!selectedConversations.size;$('conversation-move').closest('.conversation-bulk').hidden=!selectedConversations.size;
 $('conversation-prev').disabled=!result.offset;$('conversation-next').disabled=result.offset+result.rows.length>=result.total;
 for(const row of result.rows){
  if(row.provider==='meeting'){list.append(meetingCard({...row,id:row.external_id},{participants:row.participants,onChange:loadConversations,select:{checked:selectedConversations.has(row.external_id),onchange:check=>{if(check.checked){if(selectedConversations.size>=200){check.checked=false;toast('Select up to 200 meetings');return;}selectedConversations.set(row.external_id,{id:row.external_id,revision:row.scope_revision});}else selectedConversations.delete(row.external_id);$('conversation-selection').textContent=AtlantaUX.count(selectedConversations.size,'meeting')+' selected';$('conversation-move').disabled=!selectedConversations.size;$('conversation-move').closest('.conversation-bulk').hidden=!selectedConversations.size;}}}));continue;}
  list.append(conversationCard(row,{onChange:loadConversations}));
 }
 if(!result.rows.length&&!emptyLibrary){
  // The chips above name the active conditions; here is an action for each scope.
  const query=$('conversation-query').value,filtered=['project','series','participant','from','to'].some(id=>$('conversation-'+id).value)||$('conversation-source').value!=='meeting';
  const box=el('div','empty-content no-match'),actions=el('div','action-group');box.append(el('p','','No conversations match.'),el('p','hint','The active conditions are above.'));
  if(filtered)actions.append(actionBtn('secondary small-action','Reset filters',()=>resetConversationFilters()));
  if(query)actions.append(actionBtn('secondary small-action','Clear search',()=>{$('conversation-query').value='';conversationOffset=0;perform(loadConversations);}));
  if(filtered&&query)actions.append(actionBtn('secondary small-action','Clear all',()=>resetConversationFilters({all:true})));
  if(actions.childNodes.length)box.append(actions);list.append(box);
 }
}
// One meeting card for Library, Projects and Calendar: what it is, its project, its state and what to do.
// A status shows only when a meeting needs something; a plain ready meeting has none.
function meetingStatus(m){
 if(m.error||m.status==='error')return {tone:'danger',label:'Processing stopped'};
 if(['starting','recording','paused','stopping','processing'].includes(m.status))return {tone:'warn',label:statusNames[m.status]||'Processing'};
 if(m.status==='interrupted')return {tone:'danger',label:'Interrupted'};
 if(m.notes_need_refresh)return {tone:'warn',label:'Notes need update'};
 return null;
}
function projectChip(project){const chip=el('span','project-chip');chip.append(projectDot(project),document.createTextNode(project.name));return chip;}
function clockTime(value){const d=new Date(value);return Number.isFinite(d.getTime())?d.toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit'}):'';}
function meetingCard(m,{variant='list',participants=null,select=null,onChange=null}={}){
 const ids=m.project_ids||(m.project_id?[m.project_id]:[]),projects=ids.map(id=>projectList().find(p=>p.id===id)).filter(Boolean),compact=variant==='calendar';
 const card=el('article','entity-card meeting-card'+(compact?' compact':''));card.dataset.meetingId=m.id;
 if(projects.length===1&&projects[0].color){card.classList.add('has-project-line');card.style.setProperty('--project-color',projects[0].color);}
 if(select){const check=el('input','entity-check');check.type='checkbox';check.checked=select.checked;check.setAttribute('aria-label','Select '+m.title+' for a bulk change');check.onchange=()=>select.onchange(check);card.append(check);}
 const main=el('div','entity-main'),top=el('div','entity-top'),chips=el('div','entity-chips');
 if(compact)top.append(el('span','entity-time',clockTime(m.started_at||m.created||m.date)));
 top.append(openMeetingBtn(m.title,m.id,'entity-title'));
 for(const project of projects)chips.append(projectChip(project));
 // The project picker: "+ Add project" for a meeting without one, "Change project…" in the menu otherwise.
 const picker=el('details','project-pick'),summary=el('summary','add-project','＋ Add project'),pick=el('select'),save=el('button','primary small-action','Save'),cancel=el('button','secondary small-action','Cancel');
 summary.hidden=!!projects.length;pick.setAttribute('aria-label','Project for '+m.title);fillProjects(pick,ids[0]||'','No project');save.type=cancel.type='button';
 cancel.onclick=()=>{picker.open=false;};
 save.onclick=()=>perform(async()=>{await api('/api/meetings/'+m.id+'/scope',{project:pick.value?{id:pick.value}:null,series:pick.value&&pick.value===m.project_id&&m.series_id?{id:m.series_id}:null});picker.open=false;state=await api('/api/state');renderState();lastTasks='';toast(pick.value?'Meeting moved to '+(projectList().find(p=>p.id===pick.value)?.name||'the project'):'Meeting removed from its project');if(onChange)await onChange();});
 const pickBody=el('div','project-pick-body');pickBody.append(pick,save,cancel);picker.append(summary,pickBody);chips.append(picker);
 const change=btn('quiet',projects.length?'Change project…':'Add to a project…',()=>{picker.open=true;pick.focus();});
 const menu=rowMenu('More actions for '+m.title,btn('quiet','Open meeting',()=>perform(()=>openMeeting(m.id))),change);
 const meta=el('div','entity-meta'),facts=[];
 if(!compact)facts.push('Meeting',dateTime(m.started_at||m.created||m.date));
 if(m.duration)facts.push(shortDuration(m.duration));
 meta.append(el('span','',facts.join(' · ')));
 // The participant count is the control that shows their names.
 if(participants?.length){const people=el('details','entity-people');people.append(el('summary','',AtlantaUX.count(participants.length,'participant')),el('p','hint',participants.join(', ')));meta.append(people);}
 const status=meetingStatus(m);if(status)meta.append(statusBadge(status));
 // A compact card (Calendar) gives the title the width; the project joins the metadata row.
 if(compact){top.append(menu);meta.append(chips);}else top.append(chips,menu);
 main.append(top,meta);
 card.append(main);return card;
}
// The open Gmail or Chat reader says which projects hold its thread, so a saved link is visible where it was made.
let readerProjects=null;
async function showReaderProjects(provider,id,button,request){
 readerProjects={provider,id,button,request};
 let row;try{row=await api('/api/conversations/external?provider='+provider+'&id='+encodeURIComponent(id));}catch{return;}
 if(readerProjects?.button!==button||(request&&!readers.current(request)))return;
 const projects=(row.project_ids||[]).map(key=>projectList().find(p=>p.id===key)).filter(Boolean);
 button.textContent=projects.length?'Projects: '+projects.map(p=>p.name).join(', ')+' · Change…':'Attach to project';
 button.nextElementSibling?.classList.contains('reader-projects')&&button.nextElementSibling.remove();
 if(projects.length){const chips=el('span','reader-projects');for(const project of projects){const chip=btn('quiet small-action','Open '+project.name,()=>perform(()=>openProjectConversations(project.id)));chip.prepend(projectDot(project));chips.append(chip);}button.after(chips);}
}
function refreshReaderProjects(){const r=readerProjects;if(r&&r.button.isConnected)showReaderProjects(r.provider,r.id,r.button,r.request);}
// A project's saved conversations, from anywhere.
async function openProjectConversations(projectId){
 if($('conversation-reader').open)$('conversation-reader').close();
 const select=$('workspace-project');if(![...select.options].some(o=>o.value===projectId))select.append(option(projectId,projectId));
 select.value=projectId;workspaceSection='conversations';await $('open-projects').onclick();
}
// A whole email thread or Chat conversation can join a project before any task exists.
async function attachExternal(provider,id){
 const row=await api('/api/conversations/external?provider='+provider+'&id='+encodeURIComponent(id)),box=$('conversation-reader-body');
 const choices=conversationProjectChoices(row.project_ids),save=el('button','primary','Save project links');
 box.replaceChildren(el('h2','',row.title),el('p','hint',(CONVERSATION_LABELS[provider]||provider)+' · '+row.participants.join(', ')),
  el('p','hint','Atlanta saves a snapshot of the cached '+(provider==='gmail'?'messages of this thread':'messages of this conversation')+' with the project. No task is created and no AI request is sent. A later sync does not change the snapshot; attach again to save the new version.'),choices.box,save);
 if(!projectList().length)box.append(el('p','notice','Create a project in Projects first.'));
 save.onclick=()=>perform(async()=>{const ids=choices.value();if(!ids.length){toast('Choose at least one project');return;}const saved=await api('/api/conversations/attach',{provider,external_id:row.external_id,account:row.account,revision:row.revision,attachment_revision:row.attachment_revision,project_ids:ids});toast('Attached to '+projectNames(ids));refreshReaderProjects();await openAttachment(saved.id);});
 if(!$('conversation-reader').open)$('conversation-reader').showModal();
}
function projectNames(ids){const names=ids.map(key=>projectList().find(p=>p.id===key)?.name).filter(Boolean);return names.length?names.join(', '):AtlantaUX.count(ids.length,'project');}
async function openAttachment(id){
 const request=readers.start('attachment');const row=await api('/api/conversations/attachment?id='+encodeURIComponent(id));if(!readers.current(request))return;const box=$('conversation-reader-body');box.replaceChildren(el('h2','',row.title),el('p','hint',(CONVERSATION_LABELS[row.kind]||row.kind)+' · saved '+dateTime(row.created)));
 if(row.kind!=='excerpt')box.append(el('p','hint','Saved local snapshot. It does not update automatically and current remote state is not checked.'));
 if(row.partial)box.append(el('p','notice','This is a snapshot of cached text, not the full remote conversation.'));
 if(row.stale)box.append(el('p','notice','The original transcript or source revision has changed or is unavailable. This saved quotation is preserved.'));
 box.append(el('pre','conversation-snapshot',row.text));const choices=conversationProjectChoices(row.project_ids),save=el('button','secondary','Save project links');box.append(choices.box,save);
 save.onclick=()=>perform(async()=>{const ids=choices.value();await api('/api/conversations/projects',{id:row.id,revision:row.revision,project_ids:ids});toast(ids.length?'Project links saved · '+projectNames(ids):'Project links removed');refreshReaderProjects();if(view==='conversations')await loadConversations();if(view==='projects')await loadWorkspace();await openAttachment(row.id);});
 // Where the snapshot is: each project opens on its Conversations section.
 const places=(row.project_ids||[]).map(key=>projectList().find(p=>p.id===key)).filter(Boolean);
 if(places.length){const go=el('div','action-group');for(const project of places)go.append(btn('quiet small-action','Open in '+project.name,()=>perform(()=>openProjectConversations(project.id))));box.append(go);}
 if(row.kind==='excerpt'){const jump=el('button','quiet','Open original meeting at '+time(row.locator.start));jump.onclick=()=>perform(async()=>{$('conversation-reader').close();await openMeeting(row.locator.meeting_id);showSeconds(row.locator.start);if(row.stale)toast('Saved excerpt differs from the current transcript');});box.append(jump,listenButton(row.locator.meeting_id,row.locator.start,{label:'Listen to the excerpt',until:row.locator.end,className:'secondary'}));
  box.append(githubActions({kind:'attachment',id:row.id},await api('/api/github/links?kind=attachment&id='+encodeURIComponent(row.id))));}
 if(!$('conversation-reader').open)$('conversation-reader').showModal();
}
$('conversation-reader-close').onclick=()=>$('conversation-reader').close();
// A moment that plays from the reader stops with it.
$('conversation-reader').addEventListener('close',()=>{if(moment.player===moment.audio)stopMoment();});
$('open-conversations').onclick=()=>{const last=stored('library-view');if(last==='calendar')perform(openCalendar);else if(last==='find')$('open-find').click();else if(last==='analytics')$('open-analytics').click();else perform(openConversations);};
for(const b of $('library-tabs').querySelectorAll('button'))b.onclick=()=>b.dataset.library==='calendar'?perform(openCalendar):b.dataset.library==='conversations'?perform(openConversations):$('open-'+b.dataset.library).click();
// Prepare me belongs to a project: it opens for the project on screen.
$('workspace-prepare').onclick=()=>perform(()=>openPrepare(['','__none__'].includes($('workspace-project').value)?'':$('workspace-project').value,''));
$('conversation-filters').onsubmit=event=>{event.preventDefault();conversationOffset=0;selectedConversations.clear();perform(async()=>{await loadConversations();$('conversation-advanced').open=false;});};
$('conversation-project').onchange=()=>fillSeries($('conversation-series'),$('conversation-project').value,'','All series');
$('conversation-bulk-project').onchange=()=>fillSeries($('conversation-bulk-series'),$('conversation-bulk-project').value,'','Keep series when project stays the same');
// Reset filters keeps the search; Clear all also clears it.
function resetConversationFilters({all=false}={}){
 for(const id of ['conversation-project','conversation-series','conversation-participant','conversation-from','conversation-to',...(all?['conversation-query']:[])])$(id).value='';
 $('conversation-source').value='meeting';syncConversationFilters();conversationOffset=0;selectedConversations.clear();perform(loadConversations);
}
$('conversation-reset').onclick=()=>resetConversationFilters();$('conversation-clear-all').onclick=()=>resetConversationFilters({all:true});
$('conversation-select-page').onclick=()=>{for(const row of conversationPage?.rows||[])if(row.provider==='meeting'&&selectedConversations.size<200)selectedConversations.set(row.external_id,{id:row.external_id,revision:row.scope_revision});renderConversations();};
$('conversation-clear').onclick=()=>{selectedConversations.clear();renderConversations();};
$('conversation-prev').onclick=()=>{conversationOffset=Math.max(0,conversationOffset-50);perform(loadConversations);};
$('conversation-next').onclick=()=>{conversationOffset+=50;perform(loadConversations);};
$('conversation-move').onclick=()=>perform(async()=>{if(!selectedConversations.size)return;const project=$('conversation-bulk-project').value;if(!(await ask('Move '+AtlantaUX.count(selectedConversations.size,'meeting')+' to '+(projectList().find(p=>p.id===project)?.name||'No project')+'? Manual work item assignments stay unchanged.',{ok:'Move meetings'})))return;await api('/api/conversations/bulk',{meetings:[...selectedConversations.values()],project_id:project||null,series_id:$('conversation-bulk-series').value||null});selectedConversations.clear();state=await api('/api/state');lastLibrary='';renderState();syncConversationFilters();await loadConversations();});
function openExcerpt(){
 if(hasEdits()){error('Save transcript corrections before selecting an excerpt.');return;}
 if(!detail?.transcript?.length){error('Finish transcription before selecting an excerpt.');return;}
 const turns=transcriptTurns(detail.transcript),first=$('excerpt-first'),last=$('excerpt-last');first.replaceChildren();last.replaceChildren();
 for(const turn of turns){const start=turn.segments[0],end=turn.segments.at(-1),label=time(start.segment.start)+' · '+(turn.speaker||'Speaker')+' · '+turn.segments.map(s=>s.segment.text).join(' ').slice(0,90);first.append(option(label,String(start.index)));last.append(option(label,String(end.index)));}
 last.value=String(turns[0].segments.at(-1).index);if(excerptSelection){for(const [control,index] of [[first,excerptSelection.first],[last,excerptSelection.last]]){if(![...control.options].some(o=>o.value===String(index)))control.append(option(time(detail.transcript[index].start)+' · Selected segment',String(index)));control.value=String(index);}}$('excerpt-from').value=time(detail.transcript[0].start);$('excerpt-to').value=time(Math.ceil(detail.transcript.at(-1).end));fillProjects($('excerpt-project'),detail.project_id||'','Choose a project');$('excerpt-error').hidden=true;$('excerpt-dialog').showModal();
}
$('save-excerpt').onclick=openExcerpt;
$('excerpt-first').onchange=()=>{if(Number($('excerpt-last').value)<Number($('excerpt-first').value)){const first=Number($('excerpt-first').value),turn=transcriptTurns(detail.transcript).find(t=>t.segments[0].index===first);$('excerpt-last').value=String(turn.segments.at(-1).index);}};
$('excerpt-mode').onchange=()=>{$('excerpt-times').hidden=$('excerpt-mode').value!=='range';$('excerpt-turns').hidden=$('excerpt-mode').value==='range';};
$('excerpt-cancel').onclick=()=>$('excerpt-dialog').close();
$('excerpt-form').onsubmit=async event=>{event.preventDefault();$('excerpt-error').hidden=true;const button=event.submitter||$('excerpt-form').querySelector('[type=submit]');button.disabled=true;try{const body={provider:'excerpt',meeting_id:detail.id,transcript_revision:detail.transcript_revision,first:Number($('excerpt-first').value),last:Number($('excerpt-last').value),project_ids:[$('excerpt-project').value]};if($('excerpt-mode').value==='range'){const seconds=value=>{if(!/^\d{2,}:\d{2}:\d{2}$/.test(value)||value.split(':').slice(1).some(n=>Number(n)>59))throw new Error('Use HH:MM:SS for the time range');return value.split(':').reduce((n,v)=>n*60+Number(v),0);};body.range=[seconds($('excerpt-from').value),seconds($('excerpt-to').value)];}const saved=await api('/api/conversations/attach',body);$('excerpt-dialog').close();await openAttachment(saved.id);}catch(exc){$('excerpt-error').textContent=exc.message;$('excerpt-error').hidden=false;}finally{button.disabled=false;}};

$('prepare-type').onchange=()=>{prepareScope.type=$('prepare-type').value;perform(loadPrepare);};
function githubVerificationLabel(link){
 const status=AtlantaStatus.verification(link),checked=link.checked_at?' · last live check '+dateTime(link.checked_at):'';
 const cached=status.state==='cached'&&link.cached_at?' · '+dateTime(typeof link.cached_at==='number'?link.cached_at*1000:link.cached_at):'';
 return status.label+(status.state==='verified'?' in GitHub':'')+cached+checked;
}
$('github-draft-review').onclick=()=>{
 captureDraft();const buffer=draftBuffers.get(draftActiveKey);if(!buffer)return;
 $('draft-review-current').innerHTML=renderMarkdown((buffer.values.title?'# '+buffer.values.title+'\n\n':'')+(buffer.values.body||''));
 $('draft-review-generated').innerHTML=renderMarkdown((buffer.generated.title?'# '+buffer.generated.title+'\n\n':'')+(buffer.generated.body||''));
 $('draft-review-dialog').showModal();
};
$('draft-review-cancel').onclick=()=>$('draft-review-dialog').close();
$('draft-review-apply').onclick=()=>{const buffer=draftBuffers.get(draftActiveKey);if(!buffer)return;const next=buffer.reset();$('github-draft-issue-title').value=next.title;$('github-draft-body').value=next.body;draftEditNotice();updateDraftLink();$('draft-review-dialog').close();};
let channelContext=null;
function senderIdentityButton(identity,label){
 const b=btn('quiet sender-person',identity.person_name?'✓ '+identity.person_name:'Link sender to person…');b.disabled=!identity.available;
 b.onclick=event=>{event.stopPropagation();perform(async()=>{if(identity.person_id)return openPerson(identity.person_id);channelContext=identity;$('channel-person-context').textContent=(identity.provider==='gmail'?'Gmail':'Google Chat')+' · '+label+' · '+identity.account;
 $('channel-person-select').replaceChildren(option('Choose a person',''),...(state.people||[]).map(p=>option(p.name,p.id)));$('channel-person-error').hidden=true;$('channel-person-dialog').showModal();});};return b;
}
$('channel-person-cancel').onclick=()=>$('channel-person-dialog').close();
$('channel-person-new').onclick=()=>perform(async()=>{$('channel-person-dialog').close();await openPerson(null);});
$('channel-person-confirm').onclick=async()=>{
 const person=(state.people||[]).find(p=>p.id===$('channel-person-select').value);if(!person){$('channel-person-error').textContent='Choose a person first.';$('channel-person-error').hidden=false;return;}
 const context=channelContext;$('channel-person-confirm').disabled=true;
 try{const result=await api('/api/people/channel',{...context,person_id:person.id,revision:person.revision});state.people=result.people;renderPeople();if(context!==channelContext)return;$('channel-person-dialog').close();if(context.provider==='gmail')await openMail(context.thread_id);else await loadChat();toast('Sender identity confirmed');}
 catch(e){showError($('channel-person-error'),e.message);}
 finally{$('channel-person-confirm').disabled=false;}
};
function renderPersonIdentities(person){
 const box=$('person-identities');box.replaceChildren();if(!person)return;
 for(const identity of person.identities||[]){const row=el('div','identity-row'),remove=btn('quiet','Remove identity');row.append(el('span','hint',(identity.provider==='gmail'?'Gmail':'Google Chat')+' · '+identity.external_id+' · '+identity.account));
  remove.onclick=()=>perform(async()=>{const text=identity.provider==='gmail'?'Remove this confirmed email and its channel links from '+person.name+'?':'Remove this confirmed Chat identity from '+person.name+'?';if(!(await ask(text,{ok:'Remove identity'})))return;const result=await api('/api/people/channel/remove',{person_id:person.id,revision:person.revision,identity});state.people=result.people;renderPeople();await openPerson(person.id);});row.append(remove);box.append(row);
 }
}
function renderChannelProfile(profile){
 const channels=profile.channels;if(!channels)return;const box=$('person-profile');box.append(el('p','hint',channels.coverage));
 for(const [key,label] of [['email','Email messages'],['chat','Chat messages']]){const section=el('section','profile-section');section.append(el('h4','',label+' · '+channels[key].length));for(const message of channels[key]){const row=el('div','profile-message'),open=el('button','quiet','Open cached source');row.append(el('p','',message.text),el('small','hint',message.title+' · '+message.account+' · '+dateTime(message.date*1000)));open.type='button';open.onclick=()=>perform(async()=>{const status=await api(message.provider==='gmail'?'/api/gmail':'/api/chat');if((message.provider==='gmail'?status.account:status.account_id)!==message.account)throw new Error('Connect '+message.account+' to open its source. The cached quotation is shown here.');$('person-dialog').close();show('tasks');lastTasks='';await loadTasks();if(message.provider==='gmail'){showWorkTab('gmail');await openMail(message.thread_id);}else{chatSpace=message.space;chatMessage=message.name;showWorkTab('chat');}});row.append(open);section.append(row);}box.append(section);}
}

async function openManualTask(meetingId=null,{text:startText='',details:startDetails='',owner:startOwner='',due:startDue='',mention=null}={}){
 if(taskEvidenceTarget){taskEvidenceTarget=null;renderTaskEvidenceContext();}
 if(!(await leaveEdits()))return;
  const dialog=$('manual-task-dialog'),box=$('manual-task-body');const manualTitle=el('h3','','New task');manualTitle.id='manual-task-title';box.replaceChildren(manualTitle);
 // The same fields, names and order as the task editor: Title, Description, then owner, due date and context.
 const text=el('textarea');text.maxLength=1000;text.rows=2;text.required=true;text.setAttribute('aria-label','Title');text.placeholder='What needs to be done?';
 const details=el('textarea');details.maxLength=5000;details.rows=4;details.setAttribute('aria-label','Description');details.placeholder='Context, scope and links (optional)';
 // The owner is chosen from People, as in the task editor. A name from the notes that is not in People stays as said.
 const named=String(startOwner||'').trim(),known=(state.people||[]).find(p=>p.name.toLocaleLowerCase()===named.toLocaleLowerCase());
 const owner=el('select');owner.setAttribute('aria-label','Owner');owner.append(option('No owner',''),...personOptions());
 if(named&&!known)owner.append(option(named+' · not in People','__named__'));owner.value=known?known.id:named?'__named__':'';
 const ownerName=()=>owner.value==='__named__'?named:(state.people||[]).find(p=>p.id===owner.value)?.name||'';
 const due=el('input');due.type='date';due.setAttribute('aria-label','Due date');
 const meeting=el('select');meeting.setAttribute('aria-label','Meeting');meeting.append(option('No meeting · standalone task',''),...(state.meetings||[]).map(m=>option(m.title,m.id)));meeting.value=meetingId||'';
 // A task from a line of the notes stays with that meeting: the line links to the new task.
 if(mention!==null)meeting.disabled=true;
 const project=el('select');project.setAttribute('aria-label','Project');const initial=(state.meetings||[]).find(m=>m.id===meetingId)?.project_id||(view==='projects'?contextProject():($('work-project').value!=='__none__'?$('work-project').value:''));fillProjects(project,initial||'','No project');
 let projectEdited=false;project.onchange=()=>{projectEdited=true;};meeting.onchange=()=>{if(!projectEdited)fillProjects(project,(state.meetings||[]).find(m=>m.id===meeting.value)?.project_id||'','No project');};
 const actions=el('div','action-group editor-actions'),save=el('button','primary','Create task'),cancel=el('button','secondary','Cancel');save.type=cancel.type='button';actions.append(cancel,save);
 // An action from a 1:1 starts the draft with its text, owner and due date; the person still edits and creates it.
 text.value=startText;details.value=startDetails||'';due.value=startDue||'';
 const label=(name,input)=>{const l=el('label','',name);l.append(input);return l;};const grid=el('div','task-card-grid');grid.append(label('Owner',owner),label('Due date',due),label('Project',project),label('Meeting',meeting));box.append(label('Title',text),label('Description',details),grid,actions);
 const refine=btn('secondary','Draft with AI…');refine.onclick=()=>perform(async()=>{if(!text.value.trim())throw new Error('Enter the source text first');if(!validDates(box))return;const source={provider:'manual',id:crypto.randomUUID().replaceAll('-',''),source_text:text.value,capture_owner:ownerName(),capture_due_date:due.value,capture_project_id:project.value,capture_meeting_id:meeting.value||null};dialog.close();const result=await suggestTask(refine,source);if(!result){dialog.showModal();text.focus();}});if(mention===null)actions.insertBefore(refine,save);
 const requestId=crypto.randomUUID().replaceAll('-','');let submitted=null;
 cancel.onclick=()=>perform(()=>requestDialogClose(dialog,()=>dialog.close()));
 save.onclick=()=>perform(()=>withDialogAction(dialog,async()=>{
  if(!text.value.trim()){text.focus();throw new Error('Enter a title');}if(!validDates(box))return;
  const body={text:text.value.trim(),details:details.value.trim()||null,owner:ownerName()||null,due_date:due.value||null,meeting_id:meeting.value||null,project_id:project.value||null,request_id:requestId};
  if(mention!==null)body.mention_index=mention;
  // A response lost after a successful save can be retried with the exact same request.
  if(submitted&&JSON.stringify(body)!==JSON.stringify(submitted))throw new Error('The previous result is uncertain. Retry with the same fields or check My Work before creating another task.');
  submitted=body;
  let item;await withEditorSave(box,async()=>{try{item=await api('/api/items/create',body);}catch(e){if(e.status>=400&&e.status<500&&e.status!==409)submitted=null;throw e;}});
  editorDirty.clear('dialog:manual-task-dialog');dialog.close();showCreatedTask(item.id);
  try{await refreshAfterItemChange();revealTask(item.id);}catch{error('Task saved. Refresh My Work to see it.');}
 }));
 dialog.showModal();text.focus();
}
$('new-task').onclick=()=>perform(()=>openManualTask());
$('meeting-add-task').onclick=()=>perform(()=>openManualTask(selected));

function progressChangeText(changes){return Object.entries(changes||{}).filter(([key])=>!['legacy_unreviewed'].includes(key)).map(([key,[before,after]])=>{const name={owner:'Owner',owner_person_id:'Owner',assignee_person_ids:'Assignees',requester_person_id:'Received from',assigned_by_person_id:'Assigned by',follower_person_id:'Followed by',workflow_state:'State',follow_up_date:'Next check',due_date:'Due',text:'Title',acceptance_state:'Acceptance'}[key]||key.replaceAll('_',' ');const format=value=>key==='assignee_person_ids'?(value||[]).map(id=>(state.people||[]).find(p=>p.id===id)?.name||'Removed person').join(', ')||'—':key.endsWith('_person_id')?(state.people||[]).find(p=>p.id===value)?.name||(value?'Removed person':'—'):['due_date','follow_up_date'].includes(key)&&value?date(value):key==='workflow_state'?AtlantaTasks.STATES[value]||value:typeof value==='string'?value.slice(0,300):value==null?'—':Array.isArray(value)?value.join(', '):String(value);return name+': '+format(before)+' → '+format(after);}).join(' · ');}
function renderTaskProgress(box,progress,item,{alive,dirty,editing,setWorkflow,onLinks=()=>{}}){
 box.replaceChildren(el('h3','','Task timeline'),el('span','badge','Local: '+(AtlantaTasks.STATES[progress.local_state]||progress.local_state)),el('p','hint','Your task state is kept separate from GitHub. Check GitHub activity to refresh its status.'));onLinks(progress.links||[]);
 const links=el('div','task-progress-links');
 for(const link of progress.links||[]){const status=el('div','task-progress-link'),remote=el('a','',link.repository+' #'+link.number);remote.href=link.url;remote.target='_blank';remote.rel='noopener noreferrer';status.append(remote,el('span','hint',githubVerificationLabel(link)+' · '+(link.state||'Unknown state')));
  const snapshot=link.progress||{};if(snapshot.checked_at)status.append(el('p','hint','Activity snapshot: '+dateTime(snapshot.checked_at)));if(snapshot.partial)status.append(el('p','notice','Partial activity · more events may be available; older cached excerpts may be omitted.'));if(snapshot.error)status.append(el('p','notice',snapshot.error));
  const check=btn('secondary small-action','Check GitHub activity');const load=async more=>{check.disabled=true;try{const current=await api('/api/items/'+item.id+'/github-progress',{link_id:link.id,more});if(alive())renderTaskProgress(box,current,item,{alive,dirty,editing,setWorkflow,onLinks});}finally{check.disabled=false;}};check.onclick=()=>perform(()=>load(false));status.append(check);
  if(snapshot.events?.length){const clear=btn('quiet small-action','Clear activity cache');clear.onclick=()=>perform(async()=>{if(!(await ask('Remove cached GitHub activity for this link? The local task, its updates, source evidence and GitHub itself stay unchanged.',{ok:'Clear cache'})))return;const current=await api('/api/items/'+item.id+'/github-progress',{link_id:link.id,clear:true});if(alive())renderTaskProgress(box,current,item,{alive,dirty,editing,setWorkflow,onLinks});});status.append(clear);}
  if(snapshot.next_page){const more=actionBtn('quiet small-action','Load next activity pages',()=>load(true));status.append(more);}
  const mismatch=AtlantaProgress.mismatch(progress.local_state,link.state);if(mismatch){status.append(el('p','notice',mismatch));if(link.verification==='github'&&!snapshot.error){const action=btn('secondary small-action',link.state==='open'?'Review reopening locally':'Review completion locally');action.onclick=()=>{setWorkflow(link.state==='open'?'todo':'done');dirty();};status.append(action);}}
  links.append(status);
 }box.append(links);
 for(const operation of progress.publications||[]){if(!['unknown','created','failed'].includes(operation.state))continue;
  const status=el('section','notice'),destination=operation.repository||'',repo=el('input');repo.value=destination;repo.placeholder='owner/repository used for this publication';repo.setAttribute('aria-label','Publication repository');status.append(el('strong','',operation.state==='unknown'?'Publication outcome unknown':operation.state==='created'?'Created · verification pending':'Publication refused'),el('p','hint',(operation.account_login?'Account: '+operation.account_login+' · ':'')+destination+(operation.error?' · '+operation.error:'')));
  if(!destination)status.append(repo);
  if(['unknown','created'].includes(operation.state)){const check=btn('secondary','Check GitHub outcome');check.disabled=String(operation.account_id)!==String(progress.account_id);if(check.disabled)status.append(el('p','hint','Connect the original GitHub account to verify this operation.'));check.onclick=()=>perform(async()=>{check.disabled=true;try{await api(operation.state==='unknown'?'/api/github/reconcile':'/api/github/verify',{id:operation.id,repository:repo.value});const current=await api('/api/items/'+item.id+'/progress');if(alive())renderTaskProgress(box,current,item,{alive,dirty,editing,setWorkflow,onLinks});}finally{check.disabled=false;}});status.append(check);}
  if(operation.state==='unknown'&&operation.last_check){status.append(el('p','hint','Last complete check: '+dateTime(operation.last_check.at)+' · '+operation.last_check.matches+' matches'));if(operation.last_check.matches===0){const release=btn('quiet','Allow a new preview');release.onclick=()=>perform(async()=>{if(!(await ask('The complete check found no result. A late GitHub result could still appear. Allow a new preview? This does not publish anything.',{ok:'Allow preview'})))return;await api('/api/github/abandon',{id:operation.id});const current=await api('/api/items/'+item.id+'/progress');if(alive())renderTaskProgress(box,current,item,{alive,dirty,editing,setWorkflow,onLinks});});status.append(release);}}
  box.append(status);
 }
 const list=el('ol','task-timeline'),events=progress.events||[];let limit=60;
 const draw=()=>{list.replaceChildren();for(const event of events.slice(0,limit)){const row=el('li','task-timeline-event');row.append(el('small','hint',event.at?dateTime(event.at):'Date not recorded'),el('strong','',AtlantaProgress.label(event)));if(event.text)row.append(markdownBlock(event.text));const changes=progressChangeText(event.changes);if(changes)row.append(el('p','hint',changes));if(event.actor)row.append(el('small','hint','@'+event.actor));if(event.quote)row.append(el('blockquote','',event.quote));
   // An update that a meeting added by itself can be removed; the history keeps a record of the removal.
   if(event.kind==='progress_update'&&event.by==='ai'){const remove=btn('quiet small-action','Remove this update');remove.type='button';remove.title='Atlanta added this from the meeting without review. Remove it if it is wrong.';
    remove.onclick=()=>perform(async()=>{if(editing())throw new Error('Save or cancel task edits first.');if(!(await ask('Remove this update from the task?',{ok:'Remove',cancel:'Keep',danger:true})))return;
     await api('/api/items/'+item.id+'/meeting-update/remove',{meeting_id:event.meeting_id,evidence_timestamp:event.timestamp||null,text:event.text});toast('Update removed');
     const fresh=await api('/api/items/'+item.id+'/progress');if(alive())renderTaskProgress(box,fresh,item,{alive,dirty,editing,setWorkflow,onLinks});await refreshAfterItemChange();});row.append(remove);}
   const mid=event.meeting_id||event.locator?.meeting_id;if(mid){const open=btn('quiet small-action','Open meeting evidence');open.onclick=()=>perform(async()=>{if(!(await leaveEdits()))return;$('task-panel').close();await openMeeting(mid);if(event.timestamp)showSeconds(stampSeconds(event.timestamp));else if(event.locator?.start!=null)showSeconds(event.locator.start);});row.append(open);if(event.timestamp||event.locator?.start!=null)row.append(listenButton(mid,event.locator?.start??stampSeconds(event.timestamp),{label:'Play evidence',until:event.locator?.end??null}));}
   if(event.source_id){const source=itemsData.graph?.sources?.find(s=>s.id===event.source_id);if(source){const open=actionBtn('quiet small-action','Open saved source',()=>openSource(source));row.append(open);}}
   if(event.url){const open=el('a','','Open in GitHub ');open.append(icon('external'));open.href=event.url;open.target='_blank';open.rel='noopener noreferrer';row.append(open);}list.append(row);}
  more.hidden=limit>=events.length;};
 const more=btn('quiet','Show more timeline events');more.onclick=()=>{limit+=60;draw();};draw();box.append(list,more);
 if(progress.revision!==item.revision)box.prepend(el('p','notice','The task changed since this editor opened. Reopen it before saving; your current text has been kept.'));
}
async function openTaskPanel(id,{focusUpdate=false,focusTimeline=false}={}){
 const sequence=++taskPanelSequence;const data=await api('/api/items');if(sequence!==taskPanelSequence)return;itemsData=data;const item=data.items.find(i=>i.id===id);if(!item)throw new Error('This task is no longer available.');
 const dialog=$('task-panel'),box=$('task-panel-body');
 // The Project field names the current projects, so the editor shows them in one place.
 const currentProjects=(item.effective_project_ids||[]).map(key=>projectList().find(p=>p.id===key)?.name||'Removed project');
 const panelHead=el('div','task-panel-head');// The title is in the Title field; the heading names the action, so the title does not show two times.
 const panelTitle=el('h2','task-card-title',item.acceptance_state==='proposed'?'Proposed task':'Edit task');panelTitle.id='task-panel-title';panelHead.append(panelTitle);
 box.replaceChildren(panelHead);
 const label=(name,input)=>{const l=el('label','',name);l.append(input);return l;};
 const area=el('textarea');area.value=item.text;area.maxLength=1000;area.rows=2;area.required=true;area.setAttribute('aria-label','Title');area.placeholder='What needs to be done?';
 const details=el('textarea');details.value=item.details||'';details.maxLength=5000;details.rows=4;details.setAttribute('aria-label','Description');details.placeholder='Context, scope and links (optional)';
 const criterion=el('textarea');criterion.value=item.completion_criteria||'';criterion.maxLength=5000;criterion.rows=2;criterion.setAttribute('aria-label','Expected result');criterion.placeholder='How do we know it is done? (optional)';
 const project=el('select');project.setAttribute('aria-label','Project');project.append(option(currentProjects.length?currentProjects.join(', '):'No project','keep'),...(currentProjects.length?[option('No project','none')]:[]),...(state.projects?.projects||[]).map(p=>option(p.name,p.id)));project.value='keep';
 const owner=el('select');owner.setAttribute('aria-label','Owner');owner.append(option('No owner',''),...personOptions());let ownerStart=item.owner_person_id||'';
 if(!ownerStart&&item.owner){owner.append(option(item.owner+' · current name','__current__'));ownerStart='__current__';}owner.value=ownerStart;
 // The others who work on the task. The owner stays accountable; adding people is a manual choice.
 const coStart=(item.assignee_person_ids||[]).slice(1),coBox=el('div','assignee-choices');coBox.setAttribute('role','group');coBox.setAttribute('aria-label','Also working on it');
 const coChecks=(({team,others})=>[...team,...others])(peopleByTeam()).map(p=>{const l=el('label','project-choice'),c=el('input');c.type='checkbox';c.value=p.id;c.checked=coStart.includes(p.id);l.append(c,document.createTextNode(p.name));coBox.append(l);return c;});
 const due=el('input');due.type='date';due.value=item.due_date||'';due.setAttribute('aria-label','Due date');
 const follow=el('input');follow.type='date';follow.value=item.follow_up_date||'';follow.setAttribute('aria-label','Next follow-up');
 const workflow=el('select');workflow.setAttribute('aria-label','State');workflow.append(...Object.entries(AtlantaTasks.STATES).map(([key,title])=>option(title,key)));workflow.value=AtlantaTasks.workflow(item);
 const update=el('textarea');update.maxLength=5000;update.rows=2;update.setAttribute('aria-label','Add an update');update.placeholder='What changed? Who or what are we waiting for?';
 // One order in the new task and the task editor: what the task is (title, description, expected result), then
 // who and when, then progress. Every field has one place that does not move; only rare fields are in sections.
 // Received from, Assigned by, Followed by and the evidence of an update are not in the editor (2026-11-12): the
 // person does not use them. Saving keeps their saved values, because the editor sends only the fields it shows.
 const core=el('div','task-card-grid task-core');
 core.append(label('Owner',owner),label('State',workflow),label('Project',project),label('Due date',due),label('Next follow-up',follow));
 const coField=el('div','assignee-field');coField.append(el('p','hint','The owner is accountable. The others share the task and its state.'),coBox);
 const section=(title,...nodes)=>{const box=el('details','task-section'),head=el('summary'),note=el('span','task-section-summary');head.append(el('span','task-section-title',title),note);box.append(head,...nodes);box.note=note;return box;};
 const peopleSection=section('Also working on it',coField),sourcesSection=section('Sources and GitHub'),historySection=section('History');
 const sectionNotes=()=>{
  const names=coChecks.filter(c=>c.checked).map(c=>(state.people||[]).find(p=>p.id===c.value)?.name).filter(Boolean);
  peopleSection.note.textContent=names.join(', ');
 };
 let editing=false;const dirty=()=>{editing=true;close.textContent='Cancel';github.inert=true;editorDirty.set('task-panel',true);};for(const control of [...coChecks,area,details,criterion,owner,due,follow,project,workflow,update]){control.oninput=control.onchange=()=>{dirty();sectionNotes();};}
 // The owner is not in the list of the others: choosing an owner takes them out of it.
 const syncCo=()=>{for(const c of coChecks){const own=c.value===owner.value;c.closest('label').hidden=own;if(own)c.checked=false;}};syncCo();owner.addEventListener('change',syncCo);
 const save=el('button',item.acceptance_state==='proposed'?'secondary':'primary',item.acceptance_state==='proposed'?'Save draft':item.review_state==='needs_review'||item.review_state==='edited'?'Save & confirm':'Save changes'),close=el('button','secondary','Close'),footer=el('div','task-card-footer');save.type=close.type='button';
 close.onclick=()=>perform(()=>requestDialogClose(dialog,async()=>{if(editing&&!(await ask('Discard task edits?',{ok:'Discard',cancel:'Keep editing'})))return;dialog.close();}));dialog.oncancel=event=>{event.preventDefault();close.click();};dialog.onclose=()=>{editorDirty.clear('task-panel');};
 const persist=accept=>perform(()=>withDialogAction(dialog,async()=>{
  // A field with an error opens its section, so the error is in view.
  for(const part of box.querySelectorAll('details.task-section'))if(part.querySelector(':invalid,[aria-invalid=true]'))part.open=true;
  if(!area.value.trim()){area.focus();throw new Error('Enter a title');}
  if(!validDates(box))return;
  const changes={text:area.value,details:details.value,completion_criteria:criterion.value};
  const co=coChecks.filter(c=>c.checked&&c.value!==owner.value).map(c=>c.value),coChanged=co.join()!==coStart.filter(id=>id!==owner.value).join();
  const ownerChanged=owner.value!==ownerStart&&owner.value!=='__current__';
  if(coChanged||ownerChanged&&coStart.length){
   // The whole list goes at once: the owner first, then the others.
   if(!owner.value||owner.value==='__current__'){if(co.length)throw new Error('Choose the owner from People before you add others to the task.');Object.assign(changes,{assignee_person_ids:[]},owner.value?{}:{owner:null});}
   else changes.assignee_person_ids=[owner.value,...co];
  }else if(ownerChanged)Object.assign(changes,owner.value?{owner_person_id:owner.value}:{owner_person_id:null,owner:null});
  for(const [key,value] of [['due_date',due.value||null],['follow_up_date',follow.value||null],['workflow_state',workflow.value]])if(value!==(item[key]??(key==='workflow_state'?AtlantaTasks.workflow(item):null)))changes[key]=value;
  if(project.value!=='keep')changes.project_ids=project.value==='none'?[]:[project.value];
  if(update.value.trim())changes.update_note=update.value.trim();const reviewed=area.value!==item.text||details.value!==(item.details||'')||criterion.value!==(item.completion_criteria||'')||'owner_person_id' in changes||'assignee_person_ids' in changes||'due_date' in changes;
  // Only a pending review or a changed commitment confirms; a progress note or a state change does not.
  if(accept||item.legacy_unreviewed||item.acceptance_state!=='proposed'&&(['needs_review','edited'].includes(item.review_state)||reviewed))changes.acceptance_state='accepted';
  await api('/api/items/'+item.id,{text:item.text,revision:item.revision,changes});editing=false;editorDirty.clear('task-panel');dialog.close();toast(accept?'Task accepted':'Task saved');await refreshAfterItemChange();
 }));save.onclick=()=>persist(false);footer.append(close,save);
 if(item.acceptance_state!=='proposed'&&!['done','cancelled'].includes(AtlantaTasks.workflow(item))){const cancelTask=btn('danger-action','Cancel task…');cancelTask.onclick=()=>{workflow.value='cancelled';dirty();workflow.focus();cancelTask.textContent='Cancellation selected · Save changes to apply';};footer.prepend(cancelTask);}
 if(item.acceptance_state!=='proposed'){const mail=btn('secondary','Send by email…');mail.type='button';mail.onclick=()=>perform(async()=>{if(editing)throw new Error('Save task edits before you send the task by email.');dialog.close();await openTaskEmail(item.id);});footer.prepend(mail);}
 if(item.acceptance_state==='proposed'){const accept=btn('primary','Accept task');accept.onclick=()=>persist(true);footer.append(accept);box.append(el('p','notice','Proposed action · accept it to add it to active work.'));}
 const progress=el('section','task-progress');progress.append(el('h3','','Progress'),label('Add an update',update));
 box.append(label('Title',area),label('Description',details),label('Expected result',criterion),core,el('p','hint','Assigning an owner is saved locally. Atlanta does not send a message or assume the person accepted.'),progress,peopleSection,sourcesSection,historySection,footer);
 sectionNotes();
 const sources=el('section','note-section');sources.append(el('h3','','Sources'),sourceChips(item,data.meetings),evidenceBlock(item,data.meetings));const from=el('select');from.setAttribute('aria-label','Evidence channel');from.append(option('Meeting / transcript','meeting'),option('Gmail','gmail'),option('Chat','chat'),option('GitHub','github'));const attach=btn('secondary','Link another source');attach.onclick=()=>perform(async()=>{if(editing)throw new Error('Save task edits before selecting another source.');taskEvidenceTarget={id:item.id,text:item.text};renderTaskEvidenceContext();dialog.close();if(from.value==='meeting')await openConversations();else{show('tasks');lastTasks='';await loadTasks();showWorkTab(from.value);}});sources.append(from,attach);sourcesSection.append(sources);
 const github=el('section','note-section'),createIssue=el('button','secondary','Create GitHub issue'),linkIssue=el('button','secondary','Link existing issue / PR');createIssue.type=linkIssue.type='button';createIssue.onclick=()=>perform(async()=>{if(editing)throw new Error('Save task edits before preparing an issue.');await openDraft({kind:'item',id:item.id},'issue');});linkIssue.onclick=()=>perform(async()=>{if(editing)throw new Error('Save task edits before linking an issue.');await openLink({kind:'item',id:item.id});});const linkedActions=githubActions({kind:'item',id:item.id});github.append(el('h3','','GitHub'));if(item.acceptance_state==='proposed')github.append(el('p','hint','Accept this task before creating or linking a GitHub issue.'));else github.append(createIssue,linkIssue,linkedActions);
 const destinations=[...new Set((item.effective_project_ids||[]).flatMap(key=>projectList().find(p=>p.id===key)?.repositories||[]))];if(destinations.length){const repository=el('select');repository.setAttribute('aria-label','Repository readiness');repository.append(...destinations.map(name=>option(name,name)));const readiness=btn('quiet','Check repository access'),result=el('p','hint','Read access and issue publication permissions are separate.');readiness.onclick=()=>perform(async()=>{if(editing)throw new Error('Save task edits first.');readiness.disabled=true;try{const value=await api('/api/items/'+item.id+'/readiness',{repository:repository.value});if(dialog.open&&sequence===taskPanelSequence)result.textContent=value.repository+' · '+value.account+' · '+(value.archived?'Archived or disabled':!value.issues_enabled?'Issues disabled':value.message);}finally{readiness.disabled=false;}});github.append(repository,readiness,result);}sourcesSection.append(github);
 const links=(itemsData.github_links||[]).filter(link=>link.resource.kind==='item'&&link.resource.id===item.id).length,records=(item.source_evidence||[]).length;
 sourcesSection.note.textContent=[records&&AtlantaUX.count(records,'evidence record'),links&&AtlantaUX.count(links,'GitHub link')].filter(Boolean).join(' · ');
 const timeline=el('section','task-progress');timeline.append(el('h3','','Task timeline'),el('p','hint','Loading saved history…'));historySection.append(timeline);box.append(footer);dialog.showModal();
 const options={alive:()=>dialog.open&&sequence===taskPanelSequence,dirty,editing:()=>editing,setWorkflow:value=>{workflow.value=value;workflow.focus();},onLinks:links=>{
  itemsData.github_links=[...(itemsData.github_links||[]).filter(link=>link.resource.kind!=='item'||link.resource.id!==id),...links];const fresh=githubActions({kind:'item',id},links);linkedActions.replaceChildren(...fresh.childNodes);
  [...linkedActions.querySelectorAll('button')].filter(button=>button.textContent==='Check in GitHub').forEach((button,index)=>{button.onclick=()=>perform(async()=>{button.disabled=true;try{const progress=await api('/api/items/'+id+'/github-progress',{link_id:links[index].id});if(options.alive())renderTaskProgress(timeline,progress,item,options);}finally{button.disabled=false;}});});
 }};
 api('/api/items/'+id+'/progress').then(progress=>{if(options.alive()){renderTaskProgress(timeline,progress,item,options);if(focusTimeline&&!editing){historySection.open=true;timeline.scrollIntoView({block:'start'});}}}).catch(error=>{if(options.alive()){timeline.replaceChildren(el('p','notice','Timeline unavailable. '+error.message),historyBlock(item,data.meetings));}});if(focusUpdate){update.focus();update.scrollIntoView({block:'center'});}
}

// Native close and recovery get only a dirty bit and heartbeat, never editor contents.
let editorStateSent=null,editorHeartbeatAt=0;
function editorHeartbeat(){if(!state?.desktop_mode)return;const dirty=hasEdits(),now=Date.now();if(dirty===editorStateSent&&now-editorHeartbeatAt<5000)return;editorStateSent=dirty;editorHeartbeatAt=now;api('/api/editor-state',{dirty}).catch(()=>{editorStateSent=null;});}
document.addEventListener('input',()=>queueMicrotask(editorHeartbeat));document.addEventListener('change',()=>queueMicrotask(editorHeartbeat));setInterval(editorHeartbeat,500);

$('review-primary').onclick=()=>perform(async()=>{if(detail.minutes_proposal)openReview();else{switchTab('review');$('review-panel').scrollIntoView({block:'start'});}});

// Dialog lifecycle: close buttons and Escape use the same policy. Saved requests
// own their dialog until they settle; failures keep the editor and its text open.
const dialogJobs=new WeakSet(),dialogClosings=new WeakMap();
// Follow-up email: reviewed notes become a draft that the person edits, then saves to Gmail and sends from there.
let followupEmailMeeting=null;
function followupEmailStatus(text,warning=false){const box=$('followup-status');box.textContent=text||'';box.hidden=!text;box.classList.toggle('warning',warning);}
function followupEmailRecipients(){const chosen=[...$('followup-people').querySelectorAll('input:checked')].map(input=>input.value);
 const extra=$('followup-extra').value.split(/[,;\s]+/).map(v=>v.trim()).filter(Boolean);return [...new Set([...chosen,...extra].map(v=>v.toLowerCase()))];}
function renderFollowupEmail(data){
 const people=$('followup-people');people.replaceChildren();
 if(!data.recipients.length)people.append(emptyNote('No people with an email address yet.'));
 for(const row of data.recipients){const label=el('label','checkbox followup-person'),check=el('input');check.type='checkbox';check.value=row.email;check.checked=row.involved;
  label.append(check,el('span','',row.name),el('span','hint',row.email+(row.involved?' · in this meeting':'')));people.append(label);}
 $('followup-subject').value=data.subject;$('followup-body').value=data.body;
 $('followup-ai').disabled=!data.ai.available;$('followup-ai').title=data.ai.available?'Rewrite the text with '+data.ai.model+' from the reviewed notes':data.ai.reason;
 const drafts=data.gmail.drafts;$('followup-connect').hidden=drafts;$('followup-save').hidden=!drafts;
 $('followup-save').textContent=data.draft?'Update Gmail draft':'Save Gmail draft';
 followupEmailStatus(drafts?(data.draft?'This meeting already has a Gmail draft. Saving updates it.':''):'Gmail drafts need one more Google permission: compose drafts. Atlanta never sends email.');
 $('followup-result').hidden=true;$('followup-auth-link').hidden=true;
}
$('followup-email').onclick=()=>perform(async()=>{
 if(!(await leaveEdits()))return;const data=await api('/api/followup-email/prepare',{meeting_id:selected});followupEmailMeeting=selected;
 renderFollowupEmail(data);editorDirty.clear('dialog:followup-dialog');$('followup-dialog').showModal();$('followup-subject').focus();
});
$('followup-close').onclick=()=>$('followup-dialog').close();
$('followup-ai').onclick=()=>perform(async()=>{
 if($('followup-body').value.trim()&&!(await ask('Replace the current text with a new AI draft?',{ok:'Write with AI',cancel:'Keep my text'})))return;
 const button=$('followup-ai');button.disabled=true;button.textContent='Writing…';
 try{const data=await api('/api/followup-email/generate',{meeting_id:followupEmailMeeting});$('followup-subject').value=data.subject;$('followup-body').value=data.body;followupEmailStatus(data.note,!data.ai);}
 finally{button.disabled=false;button.textContent='Write with AI';}
});
$('followup-copy').onclick=()=>perform(async()=>{await copyText($('followup-subject').value+'\n\n'+$('followup-body').value);toast('Copied the subject and text');});
$('followup-connect').onclick=()=>perform(async()=>{const result=await api('/api/calendar/connect',{capability:'gmail_compose'});$('followup-auth-link').href=result.authorization_url;$('followup-auth-link').hidden=false;
 followupEmailStatus('Approve Gmail drafts in your browser. Then close this window and open Follow-up email again; your text here is not kept.');});
$('followup-save').onclick=()=>perform(async()=>{
 const to=followupEmailRecipients();if(!to.length)throw new Error('Choose at least one recipient');
 const button=$('followup-save');button.disabled=true;
 try{const result=await api('/api/followup-email/draft',{meeting_id:followupEmailMeeting,to,subject:$('followup-subject').value,body:$('followup-body').value});
  editorDirty.clear('dialog:followup-dialog');button.textContent='Update Gmail draft';
  const box=$('followup-result'),link=el('a','','Open the draft in Gmail');link.href=result.url;link.target='_blank';link.rel='noopener noreferrer';
  box.replaceChildren(document.createTextNode('Draft saved in Gmail for '+AtlantaUX.count(to.length,'recipient')+'. Check it and send it from Gmail. '),link);box.hidden=false;box.scrollIntoView({block:'nearest'});}
 finally{button.disabled=false;}
});
// One task by email: Atlanta saves a Gmail draft and marks the task; the person sends it from Gmail.
function emailMark(item,{compact=false}={}){
 const draft=item.email_draft;if(!draft)return null;
 const mark=el('span','email-mark'),count=(draft.to||[]).length;
 mark.title='Email draft saved in Gmail · '+dateTime(draft.saved_at)+(count?' · to '+draft.to.join(', '):'');
 mark.setAttribute('aria-label',mark.title);mark.append(icon('mail'));if(!compact)mark.append(document.createTextNode('Emailed'));return mark;
}
let taskEmailItems=[];
function taskEmailStatus(text,warning=false){const box=$('task-email-status');box.textContent=text||'';box.hidden=!text;box.classList.toggle('warning',warning);}
function taskEmailRecipients(){const chosen=[...$('task-email-people').querySelectorAll('input:checked')].map(input=>input.value);
 const extra=$('task-email-extra').value.split(/[,;\s]+/).map(v=>v.trim()).filter(Boolean);return [...new Set([...chosen,...extra].map(v=>v.toLowerCase()))];}
function renderTaskEmail(data){
 const people=$('task-email-people');people.replaceChildren();
 if(!data.recipients.length)people.append(emptyNote('No people with an email address yet.'));
 const before=new Set(data.draft?.to||[]);
 for(const row of data.recipients){const label=el('label','checkbox followup-person'),check=el('input');check.type='checkbox';check.value=row.email;check.checked=before.size?before.has(row.email):row.involved;
  label.append(check,el('span','',row.name),el('span','hint',row.email+(row.involved?' · on this task':'')));people.append(label);}
 $('task-email-extra').value=[...before].filter(email=>!data.recipients.some(row=>row.email===email)).join(', ');
 $('task-email-subject').value=data.subject;$('task-email-body').value=data.body;
 $('task-email-title').textContent=data.tasks.length>1?'Send '+data.tasks.length+' tasks in one email':'Send the task by email';
 const drafts=data.gmail.drafts;$('task-email-connect').hidden=drafts;$('task-email-save').hidden=!drafts;
 $('task-email-save').textContent=data.draft?'Update Gmail draft':'Save Gmail draft';
 taskEmailStatus(drafts?(data.draft?(data.tasks.length>1?'These tasks already share':'This task already has')+' a Gmail draft from '+dateTime(data.draft.saved_at)+'. Saving updates it. If you sent it, saving makes a new draft.':''):'Gmail drafts need one more Google permission: compose drafts. Atlanta never sends email.');
 $('task-email-result').hidden=true;$('task-email-auth-link').hidden=true;
}
async function openTaskEmail(ids){
 ids=Array.isArray(ids)?ids:[ids];if(!(await leaveEdits()))return;const data=await api('/api/task-email/prepare',{item_ids:ids});taskEmailItems=ids;
 renderTaskEmail(data);editorDirty.clear('dialog:task-email-dialog');$('task-email-dialog').showModal();$('task-email-subject').focus();
}
$('task-email-close').onclick=()=>$('task-email-dialog').close();
$('task-email-copy').onclick=()=>perform(async()=>{await copyText($('task-email-subject').value+'\n\n'+$('task-email-body').value);toast('Copied the subject and text');});
$('task-email-connect').onclick=()=>perform(async()=>{const result=await api('/api/calendar/connect',{capability:'gmail_compose'});$('task-email-auth-link').href=result.authorization_url;$('task-email-auth-link').hidden=false;
 taskEmailStatus('Approve Gmail drafts in your browser. Then close this window and choose Send by email again; your text here is not kept.');});
$('task-email-save').onclick=()=>perform(async()=>{
 const to=taskEmailRecipients();if(!to.length)throw new Error('Choose at least one recipient');
 const button=$('task-email-save');button.disabled=true;
 try{const result=await api('/api/task-email/draft',{item_ids:taskEmailItems,to,subject:$('task-email-subject').value,body:$('task-email-body').value});
  editorDirty.clear('dialog:task-email-dialog');button.textContent='Update Gmail draft';
  const box=$('task-email-result'),link=el('a','','Open the draft in Gmail');link.href=result.url;link.target='_blank';link.rel='noopener noreferrer';
  box.replaceChildren(document.createTextNode('Draft '+(result.updated?'updated':'saved')+' in Gmail for '+AtlantaUX.count(to.length,'recipient')+'. '+(taskEmailItems.length>1?'Each of the '+taskEmailItems.length+' tasks shows':'The task shows')+' an envelope and has a new history entry. Check the draft and send it from Gmail. '),link);box.hidden=false;box.scrollIntoView({block:'nearest'});
  await refreshAfterItemChange();}
 finally{button.disabled=false;}
});
const dialogPolicies={
 'manual-task-dialog':{dismiss:()=>$('manual-task-dialog').close()},
 'excerpt-dialog':{close:'excerpt-cancel',form:'excerpt-form'},
 'person-dialog':{close:'person-close',cancel:'person-cancel',form:'person-form',actions:['person-delete']},
 'team-dialog':{close:'team-close',cancel:'team-cancel',form:'team-form'},
 'team-review-dialog':{close:'team-review-close',cancel:'team-review-cancel',form:'team-review-form'},
 // The approval box is not an edit: closing the AI preview never asks to discard it.
 'team-ai-dialog':{close:'team-ai-close',cancel:'team-ai-cancel',form:'team-ai-form',transient:true},
 'team-github-dialog':{close:'team-github-close',cancel:'team-github-cancel',form:'team-github-form',transient:true},
 'template-dialog':{close:'template-close',cancel:'template-cancel',form:'template-form',actions:['template-delete']},
 'github-link-dialog':{close:'github-link-close',cancel:'github-link-cancel',form:'github-link-form'},
 'scope-dialog':{close:'scope-close',cancel:'scope-cancel',form:'scope-form'},
 'channel-person-dialog':{close:'channel-person-cancel',actions:['channel-person-confirm'],otherClose:['channel-person-new']},
 'review-dialog':{close:'review-close',cancel:'review-cancel',actions:['review-apply','review-discard']},
 'settings-dialog':{close:'settings-close',cancel:'settings-cancel',form:'settings-form',actions:['type-prompt-save','type-prompt-reset'],custom:true},
 'github-draft-dialog':{close:'github-draft-close',cancel:'github-draft-cancel',actions:['github-publish-preview'],custom:true},
 'task-panel':{custom:true},'task-draft-dialog':{custom:true},
 'reprocess-dialog':{close:'reprocess-close',actions:['reprocess-run'],transient:true},
 'viewer-dialog':{close:'viewer-close',transient:true},
 'conversation-reader':{close:'conversation-reader-close',transient:true},
 'draft-review-dialog':{close:'draft-review-cancel',transient:true},
 'followup-dialog':{close:'followup-close',cancel:'followup-cancel'},
 'task-titles-dialog':{close:'task-titles-close',cancel:'task-titles-cancel'},
 'task-email-dialog':{close:'task-email-close',cancel:'task-email-cancel'},
 'ask-dialog':{transient:true},// A typed project name is an edit: Cancel and Escape ask before they discard it.
 'project-dialog':{cancel:'project-cancel',dismiss:()=>$('project-dialog').close()}
};
// The values before the first edit. pointerdown and keydown come before the change they cause.
const dialogBaselines=new WeakMap();
function dialogValues(dialog){return JSON.stringify([...dialog.querySelectorAll('input:not([type=file]):not([type=button]):not([type=submit]),select,textarea')].map(f=>f.type==='checkbox'||f.type==='radio'?f.checked:f.value));}
function rememberDialog(event){const dialog=event.target.closest?.('dialog');if(dialog?.open&&!dialogBaselines.has(dialog))dialogBaselines.set(dialog,dialogValues(dialog));}
for(const type of ['pointerdown','keydown','focusin'])document.addEventListener(type,rememberDialog,true);
// A change that is typed and then undone again is no change.
function dialogChanged(dialog){return editorDirty.keys().includes('dialog:'+dialog.id)&&(!dialogBaselines.has(dialog)||dialogValues(dialog)!==dialogBaselines.get(dialog));}
function markDialogDirty(event){
 const dialog=event.target.closest?.('dialog');if(!dialog)return;
 const policy=dialogPolicies[dialog.id];
 if(policy?.transient||dialog.id==='task-draft-dialog'||dialog.id==='task-panel')return;
 // Parent editors do not own changes made in a nested dialog.
 editorDirty.set('dialog:'+dialog.id,true);
}
async function requestDialogClose(dialog,close){
 if(!dialog.open)return true;
 if(dialogJobs.has(dialog)){toast('Wait for the current operation to finish');return false;}
 if(dialogClosings.has(dialog))return dialogClosings.get(dialog);
 const pending=(async()=>{
  const policy=dialogPolicies[dialog.id]||{};
  if(!policy.custom&&!policy.transient&&dialogChanged(dialog)&&
     !(await ask('Discard unsaved changes in this editor?',{ok:'Discard',cancel:'Keep editing'})))return false;
  await close();return !dialog.open;
 })();
 dialogClosings.set(dialog,pending);
 try{return await pending;}finally{dialogClosings.delete(dialog);}
}
function protectDialogAction(dialog,button){
 const action=button.onclick;if(!action||action.dialogGuard)return;
 const guarded=event=>perform(()=>withDialogAction(dialog,()=>action(event)));guarded.dialogGuard=true;button.onclick=guarded;
}
async function withDialogAction(dialog,action){
 if(dialogJobs.has(dialog))return;
 dialogJobs.add(dialog);editorDirty.set('dialog-save:'+dialog.id,true);
 const inert=dialog.inert,focus=document.activeElement;
 dialog.inert=true;dialog.setAttribute('aria-busy','true');
 // The activity status names the action above the dialog; a text here only pushed the dialog's buttons down.
 editorHeartbeat();
 try{return await action();}
 finally{dialog.inert=inert;dialog.removeAttribute('aria-busy');dialogJobs.delete(dialog);editorDirty.clear('dialog-save:'+dialog.id);editorHeartbeat();if(dialog.open&&focus?.isConnected)focus.focus();}
}
// Every dialog keeps its title and its button bar in view; only the content between them scrolls.
// Settings has its own fixed layout. A status or an error that changes out of view scrolls into view.
const DIALOG_HEAD='.card-heading,h2,h3,.dialog-dismiss-row,.task-panel-head',DIALOG_FOOT='.review-footer,.editor-actions,.task-card-footer';
function dialogParts(dialog){
 // The date calendar opens inside a dialog; it is neither its content nor its title or buttons.
 const visible=e=>e.getClientRects().length>0&&!e.classList.contains('date-popup');
 const top=[...dialog.children].filter(visible);
 const root=top.length===1&&top[0].children.length?top[0]:dialog;
 const kids=[...root.children].filter(visible);
 const head=kids[0]?.matches(DIALOG_HEAD)?kids[0]:null,last=kids[kids.length-1];
 return {head,foot:last&&last!==head&&last.matches(DIALOG_FOOT)?last:null};
}
function frameDialog(dialog){
 if(dialog.id==='settings-dialog'||!dialog.open)return;
 const {head,foot}=dialogParts(dialog);
 for(const node of dialog.querySelectorAll('.dialog-head,.dialog-foot'))if(node!==head&&node!==foot)node.classList.remove('dialog-head','dialog-foot');
 head?.classList.add('dialog-head');foot?.classList.add('dialog-foot');
 dialog.classList.toggle('dialog-scrolls',dialog.scrollHeight>dialog.clientHeight+1);
}
function revealInDialog(dialog,node){
 if(!node.isConnected||!node.getClientRects().length||!node.textContent.trim())return;
 if(dialog.id==='settings-dialog'&&node.getAttribute('role')!=='alert')return;
 const view=dialog.getBoundingClientRect(),head=dialog.querySelector('.dialog-head'),foot=dialog.querySelector('.dialog-foot'),box=node.getBoundingClientRect();
 const top=head?head.getBoundingClientRect().bottom:view.top,bottom=foot?foot.getBoundingClientRect().top:view.bottom;
 if(box.top<top)dialog.scrollTop-=top-box.top+8;else if(box.bottom>bottom)dialog.scrollTop+=Math.min(box.bottom-bottom,box.top-top)+8;
}
// Test contexts load this code without a DOM.
if(typeof MutationObserver==='function'&&typeof document.querySelectorAll==='function')for(const dialog of document.querySelectorAll('dialog')){
 let queued=false;const changed=new Set();
 new MutationObserver(records=>{
  if(dialog.open&&records.some(r=>r.target===dialog&&r.attributeName==='open'))raiseActivity();
  for(const record of records){const node=record.target.nodeType===1?record.target:record.target.parentElement;const message=node?.closest('[role=status],[role=alert]');if(message&&dialog.contains(message))changed.add(message);}
  if(queued)return;queued=true;
  requestAnimationFrame(()=>{queued=false;frameDialog(dialog);if(dialog.open)for(const message of changed)revealInDialog(dialog,message);changed.clear();});
 }).observe(dialog,{attributes:true,attributeFilter:['open','hidden'],childList:true,subtree:true,characterData:true});
}
if(typeof window!=='undefined'&&typeof document.querySelectorAll==='function')window.addEventListener('resize',()=>{for(const dialog of document.querySelectorAll('dialog[open]'))frameDialog(dialog);});
document.addEventListener('input',markDialogDirty);document.addEventListener('change',markDialogDirty);
document.addEventListener('close',event=>{if(event.target.tagName==='DIALOG'){editorDirty.clear('dialog:'+event.target.id);dialogBaselines.delete(event.target);}},true);
document.addEventListener('cancel',event=>{
 const dialog=event.target,policy=dialogPolicies[dialog.id];if(!policy)return;
 if(dialogJobs.has(dialog)){event.preventDefault();event.stopImmediatePropagation();toast('Wait for the current operation to finish');return;}
 if(['task-draft-dialog','task-panel','ask-dialog'].includes(dialog.id))return;
 event.preventDefault();event.stopImmediatePropagation();
 perform(()=>requestDialogClose(dialog,policy.dismiss));
},true);
// Expose only safe runtime metadata for support, never tokens or conversation text.
$('copy-diagnostics').onclick=()=>perform(async()=>{const info={desktop:!!state?.desktop_mode,view,active_recording:!!state?.active,connection:$('connection').textContent,transcription:state?.settings?.transcription,notes_provider:state?.settings?.summarizer,ui_version:'ux-flow-2'};await navigator.clipboard.writeText(JSON.stringify(info,null,2));toast('Safe diagnostics copied');});

$('metadata-recover').onclick=()=>openSettings(Object.keys(state.storage_errors||{}).length?'backup':undefined);


async function openImport(){
 if(!(await leaveEdits()))return;selected=null;show('importing');renderLibrary();
}
$('open-import').onclick=()=>perform(openImport);
$('library-new').onclick=()=>$('new-meeting').click();
$('library-import').onclick=()=>perform(openImport);
$('library-sources').onclick=()=>{$('conversation-source').value='all';perform(loadConversations);};
for(const button of document.querySelectorAll('[data-settings-group]'))button.onclick=()=>showSettingsTab(SETTINGS_GROUPS[button.dataset.settingsGroup][0]);
for(const button of document.querySelectorAll('[data-project-section]'))button.onclick=()=>perform(async()=>{if(!(await leaveEdits()))return;workspaceSection=button.dataset.projectSection;$('workspace-more').open=false;renderWorkspace();syncRoute(true);});
$('edit-transcript').onclick=()=>perform(async()=>{if(transcriptEditing&&dirtyTranscript){if(!(await ask('Discard the unsaved transcript corrections?',{ok:'Discard corrections',cancel:'Keep editing'})))return;detail.transcript=structuredClone(transcriptBaseline);dirtyTranscript=false;}transcriptEditing=!transcriptEditing;renderTranscript(detail,['starting','recording','paused','stopping','processing'].includes(detail.status));$('timestamp-note').hidden=!transcriptEditing;});
let excerptSelection=null,excerptSelectionTimer=null;
function selectedTranscriptRange(){
 const selection=window.getSelection();if(view!=='detail'||transcriptEditing||!selection?.rangeCount||selection.isCollapsed||!selection.toString().trim())return null;
 const range=selection.getRangeAt(0),root=$('transcript');if(!root.contains(range.commonAncestorContainer))return null;
 const indices=[...root.querySelectorAll('[data-segment-index]')].filter(node=>range.intersectsNode(node)).map(node=>Number(node.dataset.segmentIndex));
 return indices.length?{first:Math.min(...indices),last:Math.max(...indices)}:null;
}
document.addEventListener('selectionchange',()=>{clearTimeout(excerptSelectionTimer);excerptSelectionTimer=setTimeout(()=>{if($('excerpt-dialog').open)return;excerptSelection=selectedTranscriptRange();$('save-excerpt').hidden=!excerptSelection;$('task-from-selection').hidden=!excerptSelection;$('save-excerpt').textContent='Attach selection to project';},100);});
$('task-from-selection').onclick=()=>perform(async()=>{const range=excerptSelection;if(!range)return;await suggestTask($('task-from-selection'),{provider:'meeting',id:detail.id,revision:detail.transcript_revision,...range});});
for(const button of document.querySelectorAll('.sidebar>button,.primary-navigation a,.sidebar footer button')){
 button.setAttribute('aria-label',button.id==='open-tasks'?'My Work':button.textContent.replace(/↗/g,'').trim());button.title=button.getAttribute('aria-label');
 for(const node of [...button.childNodes])if(node.nodeType===3&&node.textContent.trim()){const label=el('span','nav-label',node.textContent);node.replaceWith(label);}
}
for(const link of document.querySelectorAll('.primary-navigation a')){const navigate=link.onclick;link.onclick=event=>{if(event&&(event.button>0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey))return;event?.preventDefault();return navigate();};}
$('header-import').onclick=()=>perform(openImport);
const settingsGlyph=icon('gear');settingsGlyph.classList.add('settings-glyph');$('settings-open').prepend(settingsGlyph);


let captureInitialized=false,captureContext={},captureWantedMic=null,captureWantedFallback=null,captureMissing={},captureEdited=new Set();
function recordingSetupDraft(context={}){
 const saved=state?.capture_setup?.data||{},draft={mode:'in_person',meeting_type:'general',project_id:null,series_id:null,microphone_name:$('microphone').selectedOptions[0]?.textContent||'',fallback_microphone:'',transcription_timing:'after',...saved};
 if(Object.hasOwn(context,'project_id')&&context.project_id!==draft.project_id){draft.series_id=null;draft.meeting_type='general';}
 return {...draft,...context};
}
function applyCaptureSetup(draft,automatic){
 const assign=(id,value)=>{if(automatic&&captureEdited.has(id))return;const control=$(id);if(value&&![...control.options].some(o=>o.value===value))control.append(option('Unavailable · choose another',value));control.value=value||'';};
 captureMissing={};assign('record-project',draft.project_id);fillSeries($('record-series'),$('record-project').value,'','No series');assign('record-series',draft.series_id);assign('record-type',draft.meeting_type);
 for(const [id,value] of [['record-project',draft.project_id],['record-series',draft.series_id],['record-type',draft.meeting_type]])if(value)captureMissing[id]=value;
 if(!automatic||!captureEdited.has('microphone'))captureWantedMic=draft.microphone_name;
 if(!automatic||!captureEdited.has('mode')){const mode=document.querySelector('input[name=mode][value="'+(draft.mode==='online'?'online':'in_person')+'"]');mode.checked=true;}
 assign('transcription-timing',draft.transcription_timing);captureWantedFallback=draft.fallback_microphone;assign('fallback-microphone',draft.fallback_microphone);$('record-prepare').disabled=!$('record-project').value;
 renderRecordMore();renderReadiness();renderCaptureSetup();
}
function renderCaptureSetup(){
 if(!state)return;const saved=state.capture_setup;$('repeat-capture').disabled=!saved?.data||!!saved.error;
 if(!captureInitialized){captureInitialized=true;if(saved?.data){applyCaptureSetup(recordingSetupDraft(),true);return;}}
 const errors=[];
 for(const [id,value] of Object.entries(captureMissing)){
  const available=id==='record-project'?projectList().some(p=>p.id===value):id==='record-series'?seriesOf($('record-project').value).some(p=>p.id===value):typeList().some(p=>p.id===value);
  if(!available){if(![...$(id).options].some(o=>o.value===value))$(id).append(option('Unavailable · choose another',value));$(id).value=value;errors.push(id==='record-project'?'Choose a project; the previous one is unavailable.':id==='record-series'?'Choose a series; the previous one is unavailable in this project.':'Choose a meeting type; the previous one is unavailable.');}
 }
 if(captureWantedMic){const matches=state.devices.filter(d=>d.name===captureWantedMic);if(matches.length===1)$('microphone').value=String(matches[0].id);else{if(![...$('microphone').options].some(o=>o.value==='__missing__'))$('microphone').append(option('Choose microphone · '+captureWantedMic,'__missing__'));$('microphone').value='__missing__';errors.push('Choose the microphone; the previous device is unavailable or ambiguous.');}}
 if(captureWantedFallback!==null){if(captureWantedFallback&&![...$('fallback-microphone').options].some(o=>o.value===captureWantedFallback))$('fallback-microphone').append(option('Unavailable backup · choose another',captureWantedFallback));$('fallback-microphone').value=captureWantedFallback;}
 if($('fallback-microphone').value&&!state.devices.some(d=>d.name===$('fallback-microphone').value))errors.push('Choose a valid backup microphone, or remove the backup.');
 renderReadiness();renderRecordMore();renderTranscriptionTiming();
 const note=$('capture-setup-status');note.textContent=errors.join(' ')||(saved?.error||'');note.hidden=!note.textContent;
 $('start').disabled=!!state.active||!state.devices.length||pending||!!errors.length||$('microphone').value==='__missing__';
}
$('repeat-capture').onclick=()=>{captureEdited.clear();applyCaptureSetup(recordingSetupDraft(captureContext),false);toast('Previous setup restored · review it, then Start recording');};
$('record-form').addEventListener('change',event=>{const id=event.target.id||event.target.name;captureEdited.add(id);if(id==='fallback-microphone')captureWantedFallback=null;delete captureMissing[id];if(id==='record-project'){delete captureMissing['record-series'];delete captureMissing['record-type'];}renderCaptureSetup();});
function validateImportFile(file){if(!file||(!AUDIO_FILE.test(file.name)&&!/\.(md|markdown|txt|srt)$/i.test(file.name)))throw new Error('Choose an audio file or a .md, .txt or .srt transcript');if(!file.size||file.size>(AUDIO_FILE.test(file.name)?4_000_000_000:5_000_000))throw new Error('Choose a non-empty audio file up to 4 GB or transcript up to 5 MB');}
async function approveImport(name){const settings=state.settings,cloud=settings.auto_process&&(settings.summarizer==='openai'||['openai','elevenlabs'].includes(settings.transcription)||settings.transcript_correction==='openai'&&settings.transcription!=='elevenlabs');return !cloud||await ask('Import '+name+' and use the configured cloud processing? '+privacy(settings)+' The file is saved locally first. Use Recording settings to disable automatic cloud processing.',{ok:'Import & process',cancel:'Cancel'});}
const dropZone=$('import-drop-zone');
for(const event of ['dragenter','dragover'])dropZone.addEventListener(event,e=>{e.preventDefault();dropZone.classList.add('drop-active');});
dropZone.addEventListener('dragleave',()=>dropZone.classList.remove('drop-active'));
dropZone.addEventListener('drop',event=>{event.preventDefault();dropZone.classList.remove('drop-active');perform(async()=>{if(event.dataTransfer.files.length!==1)throw new Error('Drop one file at a time');const file=event.dataTransfer.files[0];validateImportFile(file);const files=new DataTransfer();files.items.add(file);$('import-file').files=files.files;$('import-button').disabled=false;$('import-drop-status').textContent='Checked '+file.name+' · saving locally…';await $('import-button').onclick();});});

// Review lives in the meeting as a tab: the transcript, notes and player stay one click away.
let reviewShownFor=null;
function syncReviewPanel(){
 if(reviewShownFor===detail.id)return;
 // Another meeting: an unsaved inline edit belonged to the previous one, which openMeeting already left.
 editorDirty.clear('meeting-review');reviewShownFor=null;$('meeting-review-body').replaceChildren();
 if(meetingTab==='review')perform(openMeetingReview);
}
// Where an item belongs and goes. Each item has its own project; nothing joins a guessed common one.
function reviewRouting(item){
 const box=el('div','review-routing'),names=ids=>ids.map(id=>projectList().find(p=>p.id===id)?.name).filter(Boolean).join(' · ');
 const project=el('select');project.setAttribute('aria-label','Project');
 project.append(option(item.project_ids===null?'Meeting project'+(item.effective_project_ids.length?' · '+names(item.effective_project_ids):' · none'):'Use the meeting project','inherit'),...projectList().map(p=>option(p.name,p.id)));
 if(item.project_ids&&item.project_ids.length>1){const several=option('Several · '+names(item.project_ids),'several');several.disabled=true;project.append(several);}
 project.value=item.project_ids===null?'inherit':item.project_ids.length===1?item.project_ids[0]:'several';
 project.onchange=()=>perform(async()=>{
  const previous=item.project_ids,label=project.selectedOptions[0].textContent;let saved;project.disabled=true;
  try{saved=await api('/api/work/project',{id:item.id,revision:item.revision,project_ids:project.value==='inherit'?null:[project.value]});}finally{await openMeetingReview();}
  undoToast('Project: '+label,()=>perform(async()=>{try{await api('/api/work/project',{id:saved.id,revision:saved.revision,project_ids:previous});toast('Undone');}finally{await openMeetingReview();}}));});
 const projectLabel=el('label','review-route','Project');projectLabel.append(project);box.append(projectLabel);
 if(item.kind!=='task')return box;
 const destination=el('select');destination.setAttribute('aria-label','Destination');
 destination.append(option('This Mac only',''),...item.repositories.map(r=>option('GitHub · '+r,r)));
 const current=item.destination_repository;
 if(current&&!item.repositories.includes(current))destination.append(option(current+' · not in the project',current));
 destination.value=current||'';
 destination.onchange=()=>perform(async()=>{
  const label=destination.selectedOptions[0].textContent;let saved;destination.disabled=true;
  try{saved=await api('/api/items/'+item.id,{text:item.text,revision:item.revision,changes:{destination_repository:destination.value||null}});}finally{await openMeetingReview();}
  undoToast('Destination: '+label,()=>perform(async()=>{try{await api('/api/items/'+saved.id,{text:saved.text,revision:saved.revision,changes:{destination_repository:current||null}});toast('Undone');}finally{await openMeetingReview();}}));});
 const destinationLabel=el('label','review-route','Destination');destinationLabel.append(destination);box.append(destinationLabel);
 if(!item.repositories.length)box.append(el('span','hint','No repository in the project. Draft in GitHub lets you link one.'));
 {const draft=actionBtn('secondary small-action','Draft in GitHub…',()=>openDraft({kind:'item',id:item.id},'issue'));box.append(draft);}
 return box;
}
async function openMeetingReview(){
 const meetingId=detail.id,box=$('meeting-review-body');
 // An open inline edit stays; the panel refreshes after it is saved or cancelled.
 if(editorDirty.keys().includes('meeting-review'))return;
 const data=await api('/api/meeting-review',{meeting_id:meetingId});
 if(detail.id!==meetingId)return;
 reviewShownFor=meetingId;box.replaceChildren();
 if(detail.notes_consolidation)box.append(consolidationProof(detail.notes_consolidation));
 // What Atlanta understood: the saved summary statements, each with its moment.
 const summary=typeof data.summary==='string'?[{text:data.summary}]:(data.summary||[]).filter(entry=>entry?.text);
 if(summary.length){const list=el('ul','review-summary');for(const entry of summary){const line=el('li','',entry.text);if(entry.evidence_timestamp)line.append(' ',stampButton(entry.evidence_timestamp));list.append(line);}box.append(el('h3','','What Atlanta understood'),list);}
 // A closed task is not asked again: it shows its state, but does not count as waiting for a review.
 const waiting=item=>['needs_review','edited'].includes(item.state)&&!item.closed,open=data.items.filter(waiting).length;
 if(data.items.length)box.append(el('h3','',open?open+' of '+data.items.length+' need your review':'All '+data.items.length+' reviewed'));
 if(data.source_changed){const notice=el('div','notice warning'),update=btn('secondary small-action','Update notes');notice.append(el('span','',AtlantaStatus.label('verification','changed')+' · update the notes before confirming.'),update);update.onclick=()=>perform(async()=>{switchTab('transcript');$('primary-action').scrollIntoView({block:'center'});});box.append(notice);}
 for(const item of data.items){
  const row=el('section','entity-card review-card'+(waiting(item)?' review-pending':'')),state=statusBadge(AtlantaStatus.status('review',item.state));
  const head=el('div','entity-top');head.append(el('p','review-text',item.text),state);row.append(head);if(item.details)row.append(taskDescription(item.details));
  row.append(el('p','entity-meta',(item.kind==='decision'?'Decision':'Task')+(item.owner?' · Owner: '+item.owner:'')));
  row.append(reviewRouting(item));
  // A short quote with its moment; the full quote shows on request and plays in place.
  for(const evidence of item.evidence||[]){const proof=el('div','review-evidence'),quote=el('blockquote','',evidence.quote);quote.title='Show the whole quote';quote.onclick=()=>quote.classList?.toggle('expanded');proof.append(listenButton(meetingId,evidence.start,{label:evidence.timestamp,until:evidence.end,className:'quiet'}),quote);row.append(proof);}
  const actions=el('div','action-group review-item-actions');
  const edit=btn('secondary','Edit');
  edit.onclick=()=>{
   if(item.kind==='task')return perform(()=>openTaskPanel(item.id));
   edit.disabled=true;const form=el('div','review-inline-editor'),text=el('textarea'),owner=el('input'),save=el('button','primary','Save edit'),cancel=el('button','secondary','Cancel');
   text.value=item.text;text.setAttribute('aria-label','Task or decision text');owner.value=item.owner||'';owner.setAttribute('aria-label','Owner');
   const dirty=()=>editorDirty.set('meeting-review',true);text.oninput=owner.oninput=dirty;
   save.type=cancel.type='button';form.append(text);if(item.kind==='task')form.append(owner);const editActions=el('div','action-group editor-actions');editActions.append(cancel,save);form.append(editActions);row.append(form);
   cancel.onclick=()=>perform(async()=>{if((text.value!==item.text||owner.value!==(item.owner||''))&&!(await ask('Discard these unsaved edits?',{ok:'Discard',cancel:'Keep editing',danger:true})))return;editorDirty.clear('meeting-review');form.remove();edit.disabled=false;});form.onkeydown=event=>{if(event.key==='Escape'){event.preventDefault();event.stopPropagation();cancel.click();}};
   save.onclick=()=>perform(async()=>{save.disabled=cancel.disabled=true;try{const changes={text:text.value};if(item.kind==='task')changes.owner=owner.value;await api('/api/meeting-review',{meeting_id:meetingId,item_id:item.id,source:data.source,content:item.content,action:'edit',changes});editorDirty.clear('meeting-review');await openMeetingReview();}finally{save.disabled=cancel.disabled=false;}});
  };const showEdit=!(item.kind==='task'&&item.dismiss_blocked_reason&&item.state!=='dismissed');

  if(item.dismiss_blocked_reason&&item.state!=='dismissed'){
   const notice=el('div','notice review-confirmation-context');
   notice.append(el('p','',item.dismiss_blocked_reason==='confirmed_elsewhere'?(item.kind==='task'?'Already confirmed in another meeting. Open the task to review it. If it no longer applies, choose Cancel task.':'Already confirmed in another meeting. Review the existing item instead of dismissing it as a new proposal.'):item.kind==='task'?'This task is already accepted. If it no longer applies, open the task and choose Cancel task.':'This item is already confirmed.'));
   for(const confirmation of item.confirmed_in||[])notice.append(openMeetingBtn(confirmation.title,confirmation.meeting_id));
   const open=btn('secondary',item.kind==='task'?'Open task':'Open in My Work');open.onclick=()=>perform(async()=>{if(item.kind==='task')return openTaskPanel(item.id);if(!(await leaveEdits()))return;show('tasks');lastTasks='';await loadTasks();showWorkTab(item.kind);});notice.append(open);row.append(notice);
  }
  // One group in the same order on every card: Confirm, Edit, Skip (or Restore).
  const ordered={};
  for(const [action,label] of item.state==='dismissed'?[['restore','Restore to My Work']]:[['confirm','Confirm'],['dismiss','Skip proposal']]){
   if(item.state==='confirmed'||action==='dismiss'&&item.can_dismiss===false)continue;
   const button=btn(action==='confirm'?'primary':'secondary',label);button.disabled=data.source_changed;
   if(action==='dismiss')button.title='Hides this '+item.kind+' in My Work and in every meeting. You can undo it.';if(action==='confirm')button.title='Saves your review on this Mac. Nothing is sent.';
   button.onclick=()=>perform(async()=>{button.disabled=true;try{const result=await api('/api/meeting-review',{meeting_id:meetingId,item_id:item.id,source:data.source,content:item.content,action});await openMeetingReview();
    if(action==='dismiss'){const row=result.items.find(r=>r.id===item.id);if(row)undoToast('Dismissed: '+item.text,()=>perform(async()=>{await api('/api/meeting-review',{meeting_id:meetingId,item_id:item.id,source:result.source,content:row.content,action:'restore'});await openMeetingReview();toast('Undone');}));}}finally{button.disabled=false;}});ordered[action]=button;
  }
  for(const button of [ordered.confirm,showEdit?edit:null,ordered.dismiss,ordered.restore])if(button)actions.append(button);
  row.append(actions);box.append(row);
 }
 if(!data.items.length)box.append(el('p','hint','No linked tasks or decisions. Review the saved notes and unresolved mentions in Tasks & decisions.'));
 box.querySelector('.review-pending')?.scrollIntoView({block:'nearest'});
}

// The publication state and the next safe step. Atlanta never sends again by itself.
function renderPublication(op,repository){
 const status=$('github-publish-status'),result=op.result||{},check=result.last_check;
 const shown=AtlantaStatus.publication(op);
 const detail={verified:'in GitHub'+(result.checked_at?' · '+dateTime(result.checked_at):''),created:'GitHub check pending.',
  failed:(result.error||'GitHub refused the request.')+' Nothing was created. Your text is kept: preview again to retry.',offline:'Your text is kept: copy it, or preview again later.',
  unknown:check&&!check.matches?'A complete check at '+dateTime(check.at)+' found nothing in GitHub.':check?'GitHub has '+check.matches+' results with this operation. Open GitHub and resolve them there.':'Atlanta will not retry. Check GitHub before you try again.',
  abandoned:'You can preview again for a new attempt.',cancelled:'A newer preview replaced it.',approved:'Approve the preview to send it.'}[shown.state]||'';
 status.replaceChildren(statusBadge(shown),document.createTextNode(' '+detail+' '));
 if(result.url){const link=el('a','','Open in GitHub ');link.append(icon('external'));link.href=result.url;link.target='_blank';link.rel='noopener noreferrer';status.append(link);}
 if(['unknown','created'].includes(op.state)){const button=btn('secondary','Check GitHub outcome');button.onclick=()=>perform(async()=>{button.disabled=true;try{renderPublication(await api('/api/github/reconcile',{id:op.id,repository}),repository);}finally{button.disabled=false;}});status.append(button);}
 if(op.state==='unknown'&&check&&!check.matches){const button=btn('secondary','Not in GitHub — allow a new attempt');button.onclick=()=>perform(async()=>{
  if(!(await ask('GitHub has no result for this publication. Allow a new attempt? A late result can still appear in GitHub; check it before you send again.',{ok:'Allow a new attempt'})))return;
  renderPublication(await api('/api/github/abandon',{id:op.id}),repository);});status.append(button);}
}
$('github-publish-preview').onclick=()=>perform(async()=>{
 const button=$('github-publish-preview');button.disabled=true;
 try{
  const repository=$('github-draft-repo').value;
  const preview=await api('/api/github/preview',{resource:draftResource,format:draftFormat,repository,title:$('github-draft-issue-title').value,body:$('github-draft-body').value,target:Number($('github-publish-target').value)||null,assignee:draftFormat==='issue'?$('github-draft-assignee').value||null:null});
  const op=preview.operation,payload=op.payload;
  if(op.state!=='approved'){renderPublication(op,repository);return;}
  const description=(payload.action==='issue'?'Create issue':'Add comment to #'+payload.target)+' in '+preview.repository+' as '+preview.account+'?'+(payload.assignees?.length?'\nAssignee: @'+payload.assignees.join(', @'):'')+(payload.labels?.length?'\nLabels: '+payload.labels.join(', '):'')+'\n\n'+payload.title+'\n\n'+payload.body;
  if(!(await ask(description,{ok:payload.action==='issue'?'Create in GitHub':'Add comment'})))return;
  renderPublication(await api('/api/github/publish',{id:op.id,repository}),repository);
 }finally{button.disabled=false;}
});

// Who took on a commitment. Only a person's choice links it; a name match or a shared name asks for one.
function followupOwner(row){
 const box=el('div','followup-owner'),link=person=>perform(async()=>{await api('/api/items/'+row.item_id,{text:row.text,revision:row.revision,changes:{owner_person_id:person}});await loadPrepare();});
 const name=row.person_name||row.owner;
 if(row.person_link==='linked'){const open=btn('quiet','✓ '+name);open.title='Open this person';open.onclick=()=>perform(()=>openPerson(row.person_id));box.append(el('span','hint','Owner:'),open);return box;}
 box.append(el('span','hint',row.owner?'Owner: '+row.owner+({name:' · matched by name, not confirmed',ambiguous:' · several people have this name'}[row.person_link]||' · not linked to a person'):'No owner'));
 if(row.person_link==='name'){const confirm=btn('quiet small-action','Confirm '+row.person_name);confirm.onclick=()=>link(row.person_id);box.append(confirm);}
 const choose=el('select');choose.setAttribute('aria-label','Link a person');choose.append(option(row.person_link==='name'?'Someone else…':'Link a person…',''),...(state.people||[]).filter(p=>p.id!==row.person_id).map(p=>option(p.name,p.id)));
 choose.onchange=()=>{if(choose.value)link(choose.value);};box.append(choose);
 return box;
}
let followupOwnerFilter='';
function renderFollowup(data){
 const follow=data.followup||{},box=$('followup-content');box.replaceChildren();
 const owners=[...new Set((follow.commitments||[]).map(row=>row.person_name||row.owner).filter(Boolean))].sort((a,b)=>a.localeCompare(b));if(followupOwnerFilter&&!owners.includes(followupOwnerFilter))followupOwnerFilter='';
 if(owners.length){const filter=el('select');filter.setAttribute('aria-label','Follow-up owner');filter.append(option('All owners',''),...owners.map(name=>option(name,name)));filter.value=followupOwnerFilter;filter.onchange=()=>{followupOwnerFilter=filter.value;renderFollowup(data);};box.append(filter);}

 $('followup-boundary').textContent=follow.anchor?'Since '+withDate(follow.anchor.title,follow.anchor.started_at||follow.anchor.created):'No previous meeting of this type — no comparison period yet.';
 for(const [key,label] of [['externally_updated','GitHub changes since last meeting'],['updated','Updated since last meeting'],['waiting','Waiting on someone or something'],['follow_up_due','Follow-up due'],['completed','Completed since last meeting'],['completed_unknown','Completed, date unknown'],['unchanged','No local edits since last meeting'],['blocked','Confirmed blockers'],['blockers_to_review','Blockers to review'],['commitments','Open commitments'],['questions','Open questions'],['decisions','Current and proposed decisions']]){
  const rows=(follow[key]||[]).filter(row=>!followupOwnerFilter||row.kind!=='task'||(row.person_name||row.owner)===followupOwnerFilter);if(!rows.length)continue;
  const section=el('section','note-section');section.append(el('h3','',label+' · '+rows.length));
  for(const row of rows){
   // The shared card: the commitment and its state, the owner and next check, what changed, the evidence, then the actions.
   const card=el('article','entity-card followup-card'),main=el('div','entity-main'),top=el('div','entity-top'),meta=el('div','entity-meta');
   top.append(el('p','entity-text',row.text));if(row.status)top.append(statusBadge({tone:row.workflow_state==='blocked'?'danger':['done','completed'].includes(row.status)?'ok':'muted',label:AtlantaTasks.STATES[row.workflow_state]||STATUS_LABELS[row.status]||row.status}));
   if(row.kind==='task')meta.append(followupOwner(row));else if(row.owner)meta.append(el('span','','Owner: '+row.owner));
   meta.append(workReviewBadge(row.review));if(row.follow_up_date)meta.append(el('span','','Next check: '+date(row.follow_up_date)));
   main.append(top,meta);
   if(row.last_update){const last=el('p','task-last-line');last.title=row.last_update.text;last.append(el('span','task-last-when','Last update · '+dateTime(row.last_update.at)+' · '),document.createTextNode(String(row.last_update.text||'').replace(/[*_`#>\[\]]/g,'').replace(/\s+/g,' ').trim()));main.append(last);}
   for(const event of row.updates_since||[])if(!(event.event==='progress_update'&&event.at===row.last_update?.at&&event.text===row.last_update?.text))main.append(el('p','hint',dateTime(event.at)+' · '+(event.text||progressChangeText(event.changes)||EVENT_LABELS[event.event]||event.event)));
   for(const event of row.github_updates||[]){const excerpt=el('p','hint',dateTime(event.at)+' · '+AtlantaProgress.label({kind:'github_'+event.kind})+(event.text?' · '+event.text:''));if(event.url){const open=el('a','',' Open in GitHub ');open.append(icon('external'));open.href=event.url;open.target='_blank';open.rel='noopener noreferrer';excerpt.append(open);}main.append(excerpt);}if(row.github_updates_omitted)main.append(el('p','hint',row.github_updates_omitted+' more cached changes · open the task timeline'));
   if(row.quote)main.append(el('blockquote','',row.quote));
   if(row.source){const source=el('div','item-meetings');source.append(sourceChip(row.source),sourceListen(row.source));main.append(source);}
   // The GitHub state and the time of the last check are two facts, not one.
   for(const link of row.external||[]){const remote=el('div','entity-meta followup-github'),open=el('a','',link.repository+' #'+link.number+' ');open.append(icon('external'));open.href=link.url;open.target='_blank';open.rel='noopener noreferrer';remote.append(originChip('github'),open,statusBadge({tone:link.state==='closed'?'ok':'muted',label:link.state?link.state[0].toUpperCase()+link.state.slice(1):'State unknown'}),el('span','',githubVerificationLabel(link)));main.append(remote);if(link.completion_suggested)main.append(el('p','notice','The last known external state is closed. Check GitHub and review whether the local commitment is fulfilled; it remains open.'));}
   if(row.item_id){const actions=el('div','action-group');if(row.kind==='task')actions.append(actionBtn('secondary small-action','Add update',()=>openTaskPanel(row.item_id,{focusUpdate:true})));actions.append(actionBtn(row.kind==='task'?'quiet small-action':'secondary small-action',row.kind==='task'?'Open task':'Open in My Work',async()=>{if(row.kind==='task')await openTaskPanel(row.item_id);else{show('tasks');lastTasks='';await loadTasks();showWorkTab(row.kind==='question'?'questions':'decision');}}));main.append(actions);}
   card.append(main);
   section.append(card);
  }box.append(section);
 }
 if(!box.children.length)box.append(emptyNote('No commitments or confirmed blockers yet. Review a meeting or link work to this project.'));
 for(const error of follow.check_errors||[])box.append(el('p','notice warning',error));
}
$('followup-check').onclick=()=>perform(async()=>{const button=$('followup-check');button.disabled=true;try{const data=await api('/api/followup/check',{project_id:prepareScope.project,series_id:prepareScope.series||null,meeting_type:prepareData.meeting_type});if(view==='prepare'&&prepareScope.project===data.project_id){prepareData=data;renderPrepare(data);}}finally{button.disabled=false;}});

let typePromptCatalog=null,typePromptSelected=null,typePromptOriginal='',typePromptSequence=0;
function typePromptDirty(){return typePromptSelected!==null&&$('type-prompt-text').value!==typePromptOriginal;}
async function leaveTypePrompt(confirmed=false){
 if(!confirmed&&typePromptDirty()&&!(await ask('Discard unsaved meeting-type instructions?',{ok:'Discard changes',cancel:'Keep editing'})))return false;
 $('type-prompt-text').value=typePromptOriginal;editorDirty.clear('type-prompt');return true;
}
async function loadTypePrompt(){
 const seq=++typePromptSequence,id=$('type-prompt-select').value;
 $('type-prompt-save').disabled=$('type-prompt-reset').disabled=true;
 $('type-prompt-text').disabled=true;
 const catalog=await api('/api/prompts');if(seq!==typePromptSequence)return;
 typePromptCatalog=catalog;typePromptSelected=id;const type=typeOf(id),entry=catalog.entries['meeting_minutes|type:'+id];
 const standard=catalog.meeting_type_prompts[id];$('type-prompt-text').value=entry?.text?(entry.mode==='replace'?entry.text:standard+'\n\n'+entry.text):standard;typePromptOriginal=$('type-prompt-text').value;editorDirty.clear('type-prompt');
 $('type-prompt-description').textContent=type.description;$('type-prompt-sections').textContent=type.sections.map(s=>s.title).join(' · ')||'Summary, decisions, tasks and questions';
 $('type-prompt-structure').textContent=type.custom?'Edit template structure':'Customize a copy';
 $('type-prompt-status').textContent=catalog.error||'Changes affect future AI notes for '+type.label+'.';
 $('type-prompt-text').disabled=!!catalog.error;$('type-prompt-save').disabled=$('type-prompt-reset').disabled=!!catalog.error;
}
$('type-prompt-select').onchange=()=>perform(async()=>{const wanted=$('type-prompt-select').value;if(!(await leaveTypePrompt())){$('type-prompt-select').value=typePromptSelected;return;}$('type-prompt-select').value=wanted;await loadTypePrompt();});
$('type-prompt-text').oninput=()=>{editorDirty.set('type-prompt',typePromptDirty());editorHeartbeat();$('type-prompt-status').textContent=typePromptDirty()?'Unsaved changes':'Saved instructions';};
async function saveTypePrompt(reset=false){
 const selected=typePromptSelected,body={stage:'meeting_minutes',scope:'type:'+selected,text:reset?null:$('type-prompt-text').value.trim(),revision:typePromptCatalog.revision,mode:'replace'};
 $('type-prompt-save').disabled=$('type-prompt-reset').disabled=true;$('type-prompt-select').disabled=$('type-prompt-text').disabled=true;
 try{await api('/api/prompts/save',body);typePromptOriginal=reset?'':$('type-prompt-text').value;editorDirty.clear('type-prompt');await loadTypePrompt();$('type-prompt-status').textContent='Saved · applies to future notes.';await offerReprocess({scope:'type:'+selected,action:'notes',reason:'Meeting-type prompt saved. Select existing meetings to update.'});}
 catch(error){$('type-prompt-status').textContent=error.message+' Your text is kept. Copy it before reloading settings.';throw error;}
 finally{$('type-prompt-save').disabled=$('type-prompt-reset').disabled=!!typePromptCatalog.error;$('type-prompt-select').disabled=false;$('type-prompt-text').disabled=!!typePromptCatalog.error;}
}
$('type-prompt-save').onclick=()=>perform(()=>saveTypePrompt());
$('type-prompt-reset').onclick=()=>perform(async()=>{if(await ask('Restore the default prompt for this meeting type? Your previous version stays in history.',{ok:'Reset to default'}))await saveTypePrompt(true);});
$('type-prompt-structure').onclick=()=>perform(async()=>{const type=typeOf($('type-prompt-select').value);if(type.custom)openTemplate(type.template);else{const catalog=await api('/api/prompts');openTemplate(catalog.builtin_templates[type.id]);templateEditing=null;$('template-delete').hidden=true;}});
$('type-prompt-advanced').onclick=()=>perform(async()=>{if(!(await leaveTypePrompt()))return;promptRequestedScope='type:'+$('type-prompt-select').value;showSettingsTab('prompts');});

function openTurnSpeakerEditor(d,turn,row,button,busy){
 if(hasEdits()){toast('Save or cancel other edits before changing this speaker');return;}
 button.disabled=true;editorDirty.set('turn-speaker',true);editorHeartbeat();
 const box=el('div','turn-speaker-editor'),label=el('label','','Speaker for this turn only'),choice=el('select'),name=el('input'),save=el('button','primary','Save speaker'),cancel=el('button','secondary','Cancel'),status=el('p','hint');
 choice.setAttribute('aria-label','Speaker for this turn');choice.append(option('Unidentified speaker',''),...[...new Set([...(state.speakers||[]),...d.transcript.map(s=>s.speaker).filter(Boolean)])].map(value=>option(participantLabel(value),value)),option('New person…','__new__'));choice.value=turn.speaker||'';
 name.placeholder='Participant name';name.maxLength=120;name.setAttribute('aria-label','New participant name');name.hidden=true;
 choice.onchange=()=>{name.hidden=choice.value!=='__new__';if(!name.hidden)name.focus();};
 save.type=cancel.type='button';label.append(choice);const actions=el('div','editor-actions');actions.append(cancel,save);box.append(label,name,el('p','hint','Only this turn changes. Other turns keep their current speaker.'),status,actions);row.append(box);
 const close=()=>{editorDirty.clear('turn-speaker');editorHeartbeat();box.remove();button.disabled=busy;};cancel.onclick=()=>perform(async()=>{if((choice.value!==(turn.speaker||'')||name.value.trim())&&!(await ask('Discard the unsaved speaker change?',{ok:'Discard',cancel:'Keep editing',danger:true})))return;close();});box.onkeydown=event=>{if(event.key==='Escape'){event.preventDefault();event.stopPropagation();cancel.click();}};
 save.onclick=async()=>{const speaker=choice.value==='__new__'?name.value.trim():choice.value;if(choice.value==='__new__'&&!speaker){status.textContent='Enter a participant name';name.focus();return;}save.disabled=cancel.disabled=choice.disabled=name.disabled=true;
  try{const updated=await api('/api/meetings/'+d.id+'/edit',{speaker_assignment:{revision:d.transcript_revision,indices:turn.segments.map(s=>s.index),name:speaker||null,defer_analysis:false}});close();if(detail?.id===d.id){detail=updated;lastFingerprint=JSON.stringify(updated);renderDetail();}toast('Speaker saved for this turn. Talk time is updated.');}
  catch(error){status.textContent=error.message;save.disabled=cancel.disabled=choice.disabled=name.disabled=false;}
 };
}



let reprocessToken=null,reprocessSequence=0;
function invalidateReprocess(){++reprocessSequence;reprocessToken=null;$('reprocess-run').disabled=true;$('reprocess-status').hidden=true;}
async function offerReprocess({scope='global',action='notes',reason='Saved changes. Choose whether to update existing meetings.'}={}){
 invalidateReprocess();const seq=++reprocessSequence;$('reprocess-preview').disabled=true;$('reprocess-reason').textContent=reason;
 try{const data=await api('/api/reprocess/candidates',{scope});if(seq!==reprocessSequence)return;
  const list=$('reprocess-meetings');list.replaceChildren(...data.meetings.map(meeting=>{const node=option(withDate(meeting.title,meeting.created)+(meeting.eligible?'':' · unavailable while busy or without transcript'),meeting.id);node.disabled=!meeting.eligible;node.selected=meeting.eligible&&scope.startsWith('meeting:');return node;}));
  $('reprocess-action').value=action;$('reprocess-preview').disabled=!data.meetings.some(m=>m.eligible);if(!$('reprocess-dialog').open)$('reprocess-dialog').showModal();
 }catch(e){toast('Changes saved. Reprocessing choices could not load: '+e.message);}
}
$('reprocess-meetings').onchange=$('reprocess-action').onchange=invalidateReprocess;
$('reprocess-close').onclick=()=>{++reprocessSequence;invalidateReprocess();$('reprocess-dialog').close();};

$('reprocess-preview').onclick=()=>perform(async()=>{const status=$('reprocess-status');invalidateReprocess();const seq=++reprocessSequence;
 try{const result=await api('/api/reprocess/preview',{meetings:[...$('reprocess-meetings').selectedOptions].map(o=>o.value),action:$('reprocess-action').value});if(seq!==reprocessSequence||!$('reprocess-dialog').open)return;reprocessToken=result.token;status.textContent=result.count+' meeting(s). '+(result.uses_audio?'Audio will be recognized again. ':'Uses saved text; no speech recognition. ')+result.providers.map(p=>p.operation+': '+p.provider+' · '+p.destination).join('; ');status.hidden=false;$('reprocess-run').disabled=false;}
 catch(e){if(seq===reprocessSequence){status.textContent=e.message;status.hidden=false;}}
});
$('reprocess-run').onclick=()=>perform(async()=>{if(!reprocessToken)return;const token=reprocessToken;reprocessToken=null;for(const id of ['reprocess-run','reprocess-preview','reprocess-meetings','reprocess-action','reprocess-close'])$(id).disabled=true;
 try{const result=await api('/api/reprocess/start',{token,approved:true});$('reprocess-status').textContent=result.queued.length+' meeting(s) queued. '+result.failed.map(f=>f.error).join('; ');$('reprocess-status').hidden=false;state=await api('/api/state');renderState();toast('Processing queued · review updated notes in each meeting');}
 catch(e){$('reprocess-status').textContent=e.message+' No automatic retry.';$('reprocess-status').hidden=false;}
 finally{for(const id of ['reprocess-preview','reprocess-meetings','reprocess-action','reprocess-close'])$(id).disabled=false;}
});

// Read-only calendar over the state metadata: no transcript reads, model calls or connector writes.
let calendarDay=AtlantaUX.meetingDay({created:new Date().toISOString()});
async function openCalendar(day,project){
 if(!(await leaveEdits()))return;dirtyTranscript=dirtyNotes=false;selected=null;
 if(AtlantaUX.parseISO(day))calendarDay=day;
 syncConversationFilters();fillProjects($('calendar-project'),project===undefined?$('conversation-project').value:project,'All projects',[option('Unassigned','__none__')]);
 $('conversation-project').value=$('calendar-project').value;syncConversationFilters();rememberConversationFilters();
 show('calendar');renderCalendar();renderLibrary();
}
function renderCalendar(){
 const project=$('calendar-project').value;fillProjects($('calendar-project'),project,'All projects',[option('Unassigned','__none__')]);
 const rows=AtlantaUX.calendarMeetings(state.meetings||[],$('calendar-project').value),today=AtlantaUX.meetingDay({created:new Date().toISOString()}),month=calendarDay.slice(0,7),counts=new Map();
 for(const row of rows)counts.set(row.day,(counts.get(row.day)||0)+1);
 $('calendar-month').textContent=new Intl.DateTimeFormat('en-GB',{month:'long',year:'numeric'}).format(AtlantaUX.parseISO(calendarDay));
 const grid=$('calendar-days');grid.replaceChildren();
 for(const day of AtlantaUX.calendarDays(calendarDay)){
  if(!AtlantaUX.parseISO(day)){grid.append(el('span'));continue;}
  const n=counts.get(day)||0,b=btn('calendar-day'+(day.slice(0,7)!==month?' outside':'')+(day===today?' today':''));b.dataset.day=day;
  b.tabIndex=day===calendarDay?0:-1;b.setAttribute('aria-label',date(day)+' · '+AtlantaUX.count(n,'meeting'));b.setAttribute('aria-pressed',String(day===calendarDay));if(day===today)b.setAttribute('aria-current','date');
  b.append(el('span','',String(Number(day.slice(-2)))));if(n)b.append(el('small','calendar-density',String(n)));
  b.onclick=()=>chooseCalendarDay(day,true);b.onkeydown=event=>{let next=null;const steps={ArrowLeft:-1,ArrowRight:1,ArrowUp:-7,ArrowDown:7};
   if(event.key in steps)next=AtlantaUX.shiftDay(day,steps[event.key]);else if(event.key==='PageUp'||event.key==='PageDown')next=AtlantaUX.shiftMonth(day,event.key==='PageUp'?-1:1);
   if(next){event.preventDefault();chooseCalendarDay(next,true);}};grid.append(b);
 }
 $('calendar-day-title').textContent=date(calendarDay);const daily=rows.filter(row=>row.day===calendarDay),box=$('calendar-meetings');box.replaceChildren();
 $('calendar-day-count').textContent=AtlantaUX.count(daily.length,'meeting');
 for(const row of daily)box.append(meetingCard(row,{variant:'calendar',onChange:async()=>renderCalendar()}));
 if(!daily.length){box.append(emptyNote('No saved meetings on this day.' ));const actions=el('div','work-actions');for(const [label,id] of [['New meeting','new-meeting'],['Import audio or transcript','open-import']]){if(!$(id))continue;const b=btn('secondary',label);b.onclick=()=>$(id).click();actions.append(b);}box.append(actions);}
 const missing=(state.meetings||[]).filter(m=>!AtlantaUX.meetingDay(m)).length;
 $('calendar-notice').textContent='Saved locally · Europe/Sofia'+(missing?' · '+AtlantaUX.count(missing,'meeting')+' without a valid date; available in Conversations.':'');
}
function chooseCalendarDay(day,focus=false){calendarDay=day;renderCalendar();syncRoute(true);if(focus)$('calendar-days').querySelector('[data-day="'+day+'"]')?.focus();}
$('calendar-project').onchange=()=>{ $('conversation-project').value=$('calendar-project').value;syncConversationFilters();conversationOffset=0;rememberConversationFilters();renderCalendar();syncRoute(true);};
for(const [id,amount] of [['calendar-prev',-1],['calendar-next',1]])$(id).onclick=()=>{calendarDay=AtlantaUX.shiftMonth(calendarDay,amount);renderCalendar();syncRoute(true);};
for(const [id,amount] of [['calendar-day-prev',-1],['calendar-day-next',1]])$(id).onclick=()=>{calendarDay=AtlantaUX.shiftDay(calendarDay,amount);renderCalendar();syncRoute(true);};
$('calendar-today').onclick=()=>{calendarDay=AtlantaUX.meetingDay({created:new Date().toISOString()});renderCalendar();syncRoute(true);};

// All static modal controls are registered once; dynamic task editors use the same helpers.
for(const [id,policy] of Object.entries(dialogPolicies)){
 const dialog=$(id);
 if(policy.close){
  const button=$(policy.close),close=button.onclick;
  policy.dismiss=close;
  button.onclick=()=>perform(()=>requestDialogClose(dialog,close));
 }
 if(policy.cancel)$(policy.cancel).onclick=()=>perform(()=>requestDialogClose(dialog,policy.dismiss));
 for(const name of policy.otherClose||[]){const button=$(name),close=button.onclick;button.onclick=()=>perform(()=>requestDialogClose(dialog,close));}
 if(policy.form){const form=$(policy.form),submit=form.onsubmit;form.onsubmit=event=>{event.preventDefault();return perform(()=>withDialogAction(dialog,()=>submit(event)));};}
 for(const name of policy.actions||[])protectDialogAction(dialog,$(name));
}
