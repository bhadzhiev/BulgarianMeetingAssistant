const fs=require('node:fs'),assert=require('node:assert/strict'),vm=require('node:vm');
const app=fs.readFileSync('web/app.js','utf8');
const at=app.indexOf('async function suggestTask(');assert.notEqual(at,-1);
const code=app.slice(at,app.indexOf('\n// Improve with AI',at));
// Suggest a task ends its action when the dialog opens: the page shows no "in progress" while the person edits.
// The source button and a second draft stay locked until the dialog closes.
(async()=>{
 let close;const calls=[],toasts=[],errors=[];
 const c=vm.createContext({taskDraftPending:false,taskEvidenceTarget:null,itemsData:null,toast:m=>toasts.push(m),error:m=>errors.push(m),
  ensureTaskModel:async()=>{},
  api:async(path)=>{calls.push(path);return path==='/api/items'?{items:[]}:{ai_available:true};},
  openManualTask:()=>new Promise(resolve=>close=resolve)});
 vm.runInContext(code+';this.suggestTask=suggestTask;',c);
 const button={disabled:false};
 await c.suggestTask(button,{provider:'github',id:1,revision:'r'});
 assert.deepEqual(Array.from(calls),['/api/items','/api/task-draft/preview']);
 assert.equal(c.taskDraftPending,true);assert.equal(button.disabled,true);
 await c.suggestTask({disabled:false},{provider:'github',id:2,revision:'r'});
 assert.deepEqual(Array.from(toasts),['Finish the current task draft first']);
 close(null);await new Promise(r=>setTimeout(r,0));
 assert.equal(c.taskDraftPending,false);assert.equal(button.disabled,false);
 // A failed preview releases the lock at once and reports through the calling action.
 c.api=async()=>{throw new Error('offline');};
 await assert.rejects(c.suggestTask(button,{provider:'github',id:3,revision:'r'}),/offline/);
 assert.equal(c.taskDraftPending,false);assert.equal(button.disabled,false);assert.equal(errors.length,0);
 console.log('Suggest a task PASS: the action ends when the dialog opens; the lock holds until it closes.');
})().catch(e=>{console.error(e);process.exit(1);});
