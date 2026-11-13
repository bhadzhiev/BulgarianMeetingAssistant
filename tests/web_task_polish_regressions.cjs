const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const src=fs.readFileSync('web/app.js','utf8'),py=fs.readFileSync('app/task_draft.py','utf8');
// Improve with AI suggests sharper fields in the new-task dialog and in the task editor; the person reviews before saving (2026-11-14).
assert.ok(src.includes("provider:'task_edit'"),'the suggestion goes through the task_edit provider');
assert.ok(src.includes('Send the current card to '),'sending the card asks for consent first');
assert.ok(src.includes('The result is a suggestion you review before saving.'),'the consent names the review boundary');
assert.ok(src.includes('toast(\'Suggestion applied · review it before saving\')'),'applying the suggestion asks for review, not trust');
// The suggestion never writes: create() rejects task_edit, and the panel only fills the editor fields.
assert.ok(py.includes("if body.get('provider')=='task_edit':raise ValueError"),'task_edit can never create or change a task');
assert.ok(py.includes('POLISH_SYSTEM'),'the polish prompt is separate from the draft prompt');
const panel=src.slice(src.indexOf('async function openTaskPanel('),src.indexOf('// Native close and recovery'));
assert.ok(panel.includes("btn('quiet small-action','Improve with AI')"),'the task editor offers Improve with AI');
assert.ok(panel.includes('criterion.value=result.completion_criteria||criterion.value'),'an empty suggestion never wipes a filled field');
const manual=src.slice(src.indexOf('async function openManualTask('),src.indexOf("$('new-task').onclick"));
assert.ok(manual.includes("btn('secondary','Improve with AI')"),'the new-task dialog offers Improve with AI');
assert.ok(manual.includes("goal?'Project goal: '+goal:''"),'a chosen project goal travels as context');
// The new-task dialog has the Expected result field, so the suggested criteria are not lost; it is sent only when filled.
assert.ok(manual.includes('criterion.value=result.completion_criteria||criterion.value'),'the dialog keeps the suggested expected result');
assert.ok(manual.includes('if(criterion.value.trim())body.completion_criteria=criterion.value.trim();'),'Create task sends a filled expected result');

// Behavior of improveWithAI in a vm: a changed card asks first, a failed or abandoned job is cancelled.
const fn=src.slice(src.indexOf('async function improveWithAI('),src.indexOf('// A new task is never hidden'));
async function run({statuses,answers=[true],change=false,alive=()=>true}){
 const calls=[],applied=[],asked=[];let card={text:'Fix sync',details:'',completion_criteria:''};
 const c=vm.createContext({crypto:{randomUUID:()=>'0'.repeat(8)+'-'+'0'.repeat(4)+'-'+'0'.repeat(4)+'-'+'0'.repeat(4)+'-'+'0'.repeat(12)},setTimeout:f=>f(),toast:()=>{},JSON,encodeURIComponent,
  ask:async m=>{asked.push(m);return answers.shift();},
  api:async(path,body)=>{calls.push(path);if(path==='/api/task-draft/preview')return {ai_available:true,target:{local_ai_model:'m',local_ai_base_url:'u'},characters:9,preview_token:'t'};
   if(path==='/api/task-draft/start')return {id:'job'};if(path==='/api/task-draft/cancel')return {};
   const next=statuses.shift();if(next instanceof Error)throw next;if(change)card={...card,details:'typed meanwhile'};return next;}});
 vm.runInContext(fn,c);
 const button={textContent:'Improve with AI',disabled:false};let error=null;
 try{await c.improveWithAI(()=>card,'',r=>applied.push(r),button,alive);}catch(e){error=e;}
 return {calls,applied,asked,error,button,card};
}
(async()=>{
 let r=await run({statuses:[{running:true,status:'Working'},{text:'Провери sync',details:'d'}]});
 assert.equal(r.applied.length,1);assert.equal(r.asked.length,1,'only the consent');assert.ok(!r.calls.includes('/api/task-draft/cancel'));
 assert.deepEqual([r.button.disabled,r.button.textContent],[false,'Improve with AI']);
 r=await run({statuses:[{text:'Провери sync'}],change:true,answers:[true,false]});
 assert.equal(r.applied.length,0,'a card changed meanwhile is not replaced without a yes');assert.match(r.asked[1],/You changed the card/);
 r=await run({statuses:[{text:'Провери sync'}],change:true,answers:[true,true]});
 assert.equal(r.applied.length,1,'the person can still take the suggestion');
 r=await run({statuses:[new Error('offline')]});
 assert.equal(r.error.message,'offline');assert.ok(r.calls.includes('/api/task-draft/cancel'),'a failed status request cancels the job');
 r=await run({statuses:[{running:true,status:'Working'}],alive:()=>false});
 assert.equal(r.calls.filter(p=>p==='/api/task-draft/cancel').length,1,'a closed dialog cancels the job once');
 r=await run({statuses:[{error:'Model failed'}]});
 assert.equal(r.error.message,'Model failed');assert.ok(!r.calls.includes('/api/task-draft/cancel'),'a finished job is not cancelled');
 console.log('Task polish PASS: consent before sending, suggestion never writes, empty fields are kept, a changed card asks, failed jobs are cancelled.');
})().catch(e=>{console.error(e);process.exit(1);});
