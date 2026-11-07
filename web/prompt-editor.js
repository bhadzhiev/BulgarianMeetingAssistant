/* Versioned AI task layers. Test results never write meeting data. */
let promptCatalog=null,promptRequestedScope=null,promptSelection=null,promptOriginal='',promptPreview=null,promptJob=null,promptTimer=null,promptSequence=0,promptDraftMode='append',promptPending=false,promptLaunch=0;
function promptBody(){return {stage:$('prompt-stage').value,scope:$('prompt-scope').value,text:$('prompt-text').value.trim()||null,revision:promptCatalog.revision,mode:promptDraftMode};}
function promptError(error){$('prompt-error').textContent=error?.message||'';$('prompt-error').hidden=!error;}
function promptDirty(){return $('prompt-text').value!==promptOriginal;}
async function leavePromptEditor(){
 if((promptJob||promptPending)&&!(await ask('Cancel the running prompt test and close settings?',{ok:'Cancel test'})))return false;
 if(promptDirty()&&!(await ask('Discard the unsaved AI instructions?',{ok:'Discard changes',cancel:'Keep editing'})))return false;
 if(promptJob)await api('/api/prompts/test/cancel',{id:promptJob});
 ++promptLaunch;promptPending=false;promptJob=null;promptBusy(false);invalidatePromptTest();clearTimeout(promptTimer);$('prompt-text').value=promptOriginal;editorDirty.clear('ai-prompts');return true;
}
function invalidatePromptTest(){promptSequence++;promptPreview=null;$('prompt-test').disabled=true;$('prompt-request').hidden=true;$('prompt-target').textContent='';}
function fillPromptScopes(wanted){
 const stage=$('prompt-stage').value,scopes=[option('All operations of this kind · global','global')];
 if(promptCatalog.meeting_stages.includes(stage)){
  for(const type of promptCatalog.types)scopes.push(option('Meeting type · '+type.label,'type:'+type.id));
  for(const meeting of promptCatalog.meetings)scopes.push(option('Meeting · '+meeting.title,'meeting:'+meeting.id));
 }
 $('prompt-scope').replaceChildren(...scopes);$('prompt-scope').value=scopes.some(o=>o.value===wanted)?wanted:'global';
}
async function renderPromptEffective(){
 const seq=++promptSequence,body=promptBody();
 if(!promptCatalog)return;
 try{const result=await api('/api/prompts/resolve',body);if(seq!==promptSequence)return;
  $('prompt-effective').textContent=result.stages[body.stage].effective;
  $('prompt-context').textContent='Library revision '+result.revision+' · '+(result.stages[body.stage].layers.map(v=>v.scope+' (v'+v.revision+')').join(' → ')||'Built-in defaults')+(promptDirty()?' · unsaved preview':'');
 }catch(error){if(seq===promptSequence)promptError(error);}
}
function renderPromptSelection(){
 const body=promptBody(),row=promptCatalog.entries[body.stage+'|'+body.scope];promptSelection={stage:body.stage,scope:body.scope};promptDraftMode=row?.mode||'append';
 $('prompt-text').value=row?.text||'';promptOriginal=$('prompt-text').value;editorDirty.clear('ai-prompts');invalidatePromptTest();promptError(null);
 $('prompt-history').replaceChildren(option('Choose a saved version…',''),...(row?.history||[]).slice().reverse().map(v=>option('v'+v.revision+' · '+date(v.at)+(v.text===null?' · inherited':''),String(v.revision))));
 $('prompt-reprocess').hidden=!(['meeting_minutes','meeting_consolidation'].includes(body.stage)&&body.scope.startsWith('meeting:'));
 $('prompt-policy').textContent=promptCatalog.policy;$('prompt-save').disabled=!!promptCatalog.error;$('prompt-reset').disabled=!!promptCatalog.error;
 if(promptCatalog.error)promptError(new Error(promptCatalog.error));
 renderPromptEffective();
}
async function loadPromptEditor(){
 if(promptDirty()&&promptSelection)return;
 promptCatalog=await api('/api/prompts');const stage=$('prompt-stage').value||'meeting_minutes';
 $('prompt-stage').replaceChildren(...promptCatalog.stages.map(s=>option(s.label,s.id)));$('prompt-stage').value=stage;
 fillPromptScopes(promptRequestedScope||promptSelection?.scope||'global');promptRequestedScope=null;renderPromptSelection();
}
async function changePromptSelection(isStage){
 const requested={stage:$('prompt-stage').value,scope:$('prompt-scope').value};
 if(promptDirty()&&!(await ask('Discard these unsaved instructions before switching?',{ok:'Discard changes',cancel:'Keep editing'}))){$('prompt-stage').value=promptSelection.stage;$('prompt-scope').value=promptSelection.scope;return;}
 if(isStage)fillPromptScopes(requested.scope);renderPromptSelection();
}
$('prompt-stage').onchange=()=>perform(()=>changePromptSelection(true));$('prompt-scope').onchange=()=>perform(()=>changePromptSelection(false));
$('prompt-text').oninput=()=>{editorDirty.set('ai-prompts',promptDirty());editorHeartbeat();invalidatePromptTest();clearTimeout(promptTimer);promptTimer=setTimeout(renderPromptEffective,350);};
$('prompt-snippet').oninput=invalidatePromptTest;
async function savePrompt(reset=false){
 promptError(null);const body=promptBody();if(reset)body.text=null;
 try{const result=await api('/api/prompts/save',body);promptCatalog={...promptCatalog,...result};renderPromptSelection();toast('AI instructions saved');if(['meeting_minutes','meeting_consolidation','transcript_correction','topic_matches'].includes(body.stage))await offerReprocess({scope:body.scope,action:({meeting_minutes:'notes',meeting_consolidation:'notes',transcript_correction:'correction_notes',topic_matches:'analytics'})[body.stage],reason:'AI instructions saved. Select existing meetings to update.'});}
 catch(error){promptError(error);if(error.message.includes('changed')){$('prompt-context').textContent='Another editor saved changes. Copy your unsaved instructions, then close and reopen Settings to reload.';}}
}
$('prompt-save').onclick=()=>perform(()=>savePrompt());$('prompt-reset').onclick=()=>perform(async()=>{if(await ask('Reset this layer to inherited instructions? The previous text stays in version history.',{ok:'Reset layer'}))await savePrompt(true);});
$('prompt-restore').onclick=()=>{const body=promptBody(),row=promptCatalog.entries[body.stage+'|'+body.scope],version=row?.history.find(v=>String(v.revision)===$('prompt-history').value);if(!version)return;
 promptDraftMode=version.mode||'append';$('prompt-text').value=version.text||'';$('prompt-text').dispatchEvent(new Event('input',{bubbles:true}));toast('Version loaded · choose Save instructions to restore it');};
$('prompt-preview').onclick=()=>perform(async()=>{
 promptError(null);try{const body={...promptBody(),snippet:$('prompt-snippet').value},seq=++promptSequence,result=await api('/api/prompts/test/preview',body);if(seq!==promptSequence||JSON.stringify(body)!==JSON.stringify({...promptBody(),snippet:$('prompt-snippet').value}))return;
  promptPreview={...body,preview_token:result.preview_token};$('prompt-messages').textContent=JSON.stringify({messages:result.messages,schema:result.schema},null,2);$('prompt-request').hidden=false;$('prompt-request').open=true;
  $('prompt-target').textContent='Send the displayed excerpt to '+result.target.local_ai_base_url+' · '+result.target.local_ai_model+' · '+result.target.local_ai_max_tokens+' output tokens. Tests use the saved Notes & AI settings.';$('prompt-test').disabled=false;
 }catch(error){promptError(error);}
});
function promptBusy(busy){for(const id of ['prompt-stage','prompt-scope','prompt-text','prompt-save','prompt-reset','prompt-restore','prompt-reprocess','prompt-snippet','prompt-preview'])$(id).disabled=busy;$('prompt-test').disabled=true;$('prompt-cancel').hidden=!busy;}
async function pollPromptTest(id){
 if(promptJob!==id)return;
 try{const result=await api('/api/prompts/test/status?id='+encodeURIComponent(id));if(promptJob!==id)return;
  $('prompt-result').textContent=result.error||result.status+(result.result?'\n\n'+JSON.stringify(result.result,null,2):'');
  if(result.running)promptTimer=setTimeout(()=>pollPromptTest(id),800);else{promptJob=null;promptBusy(false);invalidatePromptTest();}
 }catch(error){promptError(error);promptJob=null;promptBusy(false);}
}
$('prompt-test').onclick=()=>perform(async()=>{
 if(!promptPreview||promptPending||promptJob)return;const preview=promptPreview,launch=++promptLaunch;
 promptPending=true;promptError(null);promptBusy(true);$('prompt-result').textContent='Starting isolated test…';
 try{const job=await api('/api/prompts/test/start',{...preview,approved:true});
  if(launch!==promptLaunch||!$('settings-dialog').open){await api('/api/prompts/test/cancel',{id:job.id});return;}
  promptJob=job.id;pollPromptTest(job.id);
 }catch(error){if(launch===promptLaunch){promptError(error);promptBusy(false);invalidatePromptTest();}}
 finally{if(launch===promptLaunch)promptPending=false;}
});
$('prompt-cancel').onclick=()=>perform(async()=>{
 if(promptPending){++promptLaunch;promptPending=false;promptBusy(false);invalidatePromptTest();$('prompt-result').textContent='Cancelling test…';}
 if(promptJob){await api('/api/prompts/test/cancel',{id:promptJob});$('prompt-result').textContent='Cancelling test…';}
});

$('prompt-reprocess').onclick=()=>perform(async()=>{
 if(promptDirty()){promptError(new Error('Save your instructions before generating new notes.'));return;}
 const body=promptBody();if(body.stage!=='meeting_minutes'||!body.scope.startsWith('meeting:'))return;
 await offerReprocess({scope:body.scope,action:'notes'});
});

for(const id of ['prompt-save','prompt-reset'])protectDialogAction($('settings-dialog'),$(id));
