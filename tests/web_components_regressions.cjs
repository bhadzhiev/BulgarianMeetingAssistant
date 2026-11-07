const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('web/app.js','utf8');
const nodes=new Map(),calls=[],errors=[];
const node=id=>{if(!nodes.has(id))nodes.set(id,{value:'',open:false,focus(){},select(){},showModal(){assert(!this.open);this.open=true;},close(value){this.returnValue=value;this.open=false;this.onclose();}});return nodes.get(id);};
const context=vm.createContext({document:{createElement:tag=>({tagName:tag.toUpperCase()})},$:node,
 perform:async fn=>{try{return await fn();}catch(e){errors.push(e);}},openMeeting:async id=>calls.push(['meeting',id]),graphAction:async(action,body)=>calls.push([action,body.text])});
vm.runInContext(source.slice(source.indexOf('function el('),source.indexOf('function option(')),context);
// Use a VM deadline: WebKit optimizes an accidental tail-recursive helper into
// an endless loop rather than the RangeError seen in Node.
const empty=vm.runInContext("emptyNote('No saved meetings <yet>')",context,{timeout:500});
assert.equal(empty.tagName,'P');assert.equal(empty.className,'hint');assert.equal(empty.textContent,'No saved meetings <yet>');
(async()=>{
 const button=vm.runInContext("btn('secondary','Open',()=>openMeeting('one'),'Open meeting')",context);assert.equal(button.type,'button');assert.equal(button.title,'Open meeting');await button.onclick();
 const open=vm.runInContext("openMeetingBtn('Meeting','two')",context);assert.equal(open.type,'button');await open.onclick();
 const action=vm.runInContext("actionBtn('primary','Run',()=>openMeeting('three'))",context);await action.onclick();
 assert.deepEqual(calls,[['meeting','one'],['meeting','two'],['meeting','three']]);calls.length=0;
 const start=source.indexOf('let askQueue='),end=source.indexOf('let taskDraftPending=',start);
 vm.runInContext(source.slice(start,end),context);
 const handler=source.split('\n').find(line=>line.startsWith("$('new-work-question').onclick="));assert(handler);vm.runInContext(handler,context);
 const tick=()=>new Promise(setImmediate);
 const cancelled=node('new-work-question').onclick();await tick();assert(node('ask-dialog').open);assert.equal(node('ask-input').hidden,false);assert.equal(node('ask-input').value,'');node('ask-dialog').close('cancel');await cancelled;assert.equal(calls.length,0);
 const added=node('new-work-question').onclick();await tick();node('ask-input').value='Кой ще провери deployment-а?';node('ask-dialog').close('ok');await added;
 assert.deepEqual(calls,[['question','Кой ще провери deployment-а?']]);assert.equal(errors.length,0);
 const reopened=node('new-work-question').onclick();await tick();assert.equal(node('ask-input').value,'');node('ask-dialog').close('cancel');await reopened;
 console.log('Shared UI components and New question regression checks passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
