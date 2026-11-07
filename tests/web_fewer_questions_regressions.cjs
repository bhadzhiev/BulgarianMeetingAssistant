const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const UX=require('../web/ux.js'),app=fs.readFileSync('web/app.js','utf8');
const slice=(a,b)=>{const at=app.indexOf(a);assert.notEqual(at,-1,a);return app.slice(at,app.indexOf(b,at));};

(async()=>{
 // Leaving names what is lost instead of "your corrections".
 {
  const c=vm.createContext({editorDirty:UX.dirtyRegistry()});
  vm.runInContext('let dirtyTranscript=false,dirtyNotes=true,itemEditing=false,speakerNaming=false;'+slice('function hasEdits()','// The desktop window'),c);
  vm.runInContext("editorDirty.set('task-panel',true);editorDirty.set('dialog:person-dialog',true)",c);
  assert.deepEqual([...vm.runInContext('unsavedNames()',c)],['notes changes','task changes','changes in the open window']);
 }
 // A dialog value typed and erased again asks nothing; a real change still asks.
 {
  const field={type:'text',value:'Maria'},dialog={id:'person-dialog',open:true,querySelectorAll:()=>[field]};
  const listeners={},c=vm.createContext({editorDirty:UX.dirtyRegistry(),dialogPolicies:{},
   document:{addEventListener:(type,fn)=>{(listeners[type]||=[]).push(fn);}}});
  vm.runInContext(slice('// The values before the first edit.','async function requestDialogClose('),c);
  const target={closest:()=>dialog};
  listeners.keydown[0]({target});field.value='Mariaa';vm.runInContext('markDialogDirty',c)({target});
  assert.equal(vm.runInContext('dialogChanged',c)(dialog),true);
  field.value='Maria';assert.equal(vm.runInContext('dialogChanged',c)(dialog),false);
  // Without a remembered baseline the old rule stays: an edit event means a change.
  const other={id:'scope-dialog',open:true,querySelectorAll:()=>[]};vm.runInContext("editorDirty.set('dialog:scope-dialog',true)",c);
  assert.equal(vm.runInContext('dialogChanged',c)(other),true);
 }
 // Closing Settings asks one question for everything, then discards without asking again.
 {
  const asked=[];let closed=false;
  const c=vm.createContext({ask:async message=>{asked.push(message);return true;},editorDirty:UX.dirtyRegistry(),
   settingsValues:()=>'changed',typePromptDirty:()=>true,promptDirty:()=>true,
   leaveTypePrompt:async confirmed=>{assert.equal(confirmed,true);return true;},leavePromptEditor:async confirmed=>{assert.equal(confirmed,true);return true;},
   $:()=>({close(){closed=true;}})});
  vm.runInContext("let settingsOpened='opened',promptJob=null,promptPending=false;"+slice('async function closeSettings()','function openSettings('),c);
  await vm.runInContext('closeSettings()',c);
  assert.equal(asked.length,1);assert.match(asked[0],/settings, meeting-type instructions, AI instructions/);assert(closed);
  asked.length=0;closed=false;vm.runInContext("settingsValues=()=>'opened';typePromptDirty=()=>false;promptDirty=()=>false",c);
  await vm.runInContext('closeSettings()',c);assert.equal(asked.length,0);assert(closed);
 }
 // Deleting a meeting with a calendar event is one question with three answers.
 {
  const del=slice("$('delete-meeting').onclick=","$('audio').pause()");
  assert.equal((del.match(/await ask\(/g)||[]).length,1);
  assert.match(del,/extra:'Delete meeting, keep event'/);assert.match(del,/calendar_event=answer===true&&hasEvent/);
 }
 console.log('Fewer questions PASS: named losses, value-based dialog changes, one Settings question, one delete question.');
})().catch(e=>{console.error(e);process.exitCode=1;});
