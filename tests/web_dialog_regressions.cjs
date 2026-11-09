const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const UX=require('../web/ux.js'),source=fs.readFileSync('web/app.js','utf8'),html=fs.readFileSync('web/index.html','utf8');
const extract=(a,b)=>source.slice(source.indexOf(a),source.indexOf(b,source.indexOf(a)));
const tick=()=>new Promise(setImmediate);
function fixture(){
 const elements=new Map(),listeners={},answers=[],notices=[];
 const document={activeElement:null,addEventListener:(kind,fn)=>{(listeners[kind]??=[]).push(fn);}};
 function element(id){if(!elements.has(id))elements.set(id,{id,tagName:id.endsWith('dialog')||['task-panel','conversation-reader'].includes(id)?'DIALOG':'DIV',open:true,inert:false,isConnected:true,children:[],value:'',hidden:false,
  attrs:{},setAttribute(k,v){this.attrs[k]=v;},removeAttribute(k){delete this.attrs[k];},prepend(x){this.children.unshift(x);},focus(){document.activeElement=this;},
  close(){this.open=false;for(const fn of listeners.close||[])fn({target:this});},onclick(){this.calls=(this.calls||0)+1;},onsubmit(){this.calls=(this.calls||0)+1;},
 });return elements.get(id);}
 const c=vm.createContext({document,$:element,editorDirty:UX.dirtyRegistry(),ask:async()=>answers.length?answers.shift():true,
  toast:x=>notices.push(x),editorHeartbeat:()=>{},el:()=>({setAttribute(){},remove(){}}),perform:async fn=>fn()});
 vm.runInContext(extract('// Dialog lifecycle:','// Expose only safe runtime metadata'),c);
 const policies=JSON.parse(vm.runInContext('JSON.stringify(dialogPolicies)',c));
 for(const [id,p] of Object.entries(policies))if(p.close)element(p.close).onclick=()=>element(id).close();
 vm.runInContext(source.slice(source.indexOf('// All static modal controls are registered once')),c);
 return {c,e:element,listeners,answers,notices};
}
(async()=>{
 const f=fixture(),policies=JSON.parse(vm.runInContext('JSON.stringify(dialogPolicies)',f.c));
 const ids=[...html.matchAll(/<dialog id="([^"]+)"/g)].map(m=>m[1]);
 assert.deepEqual(Object.keys(policies).sort(),ids.sort(),'Every actual modal needs an explicit policy');assert.equal(ids.length,24);
 const htmlIds=new Set([...html.matchAll(/id="([^"]+)"/g)].map(m=>m[1]));
 for(const p of Object.values(policies))for(const id of [p.close,p.cancel,p.form,...(p.actions||[]),...(p.otherClose||[])].filter(Boolean))assert(htmlIds.has(id),'Missing dialog control '+id);
 for(const [id,p] of Object.entries(policies)){
  if(!p.close)continue;
  const d=f.e(id),close=f.e(p.close);d.open=true;
  // The actual dismiss callbacks in the app close their own dialog. Simulate that operation here.
  vm.runInContext('dialogPolicies['+JSON.stringify(id)+'].dismiss=()=>$( '+JSON.stringify(id)+' ).close()',f.c);
  if(!p.custom&&!p.transient){
   f.c.editorDirty.set('dialog:'+id,true);f.answers.push(false);
   assert.equal(await vm.runInContext(`requestDialogClose($('${id}'),dialogPolicies['${id}'].dismiss)`,f.c),false);assert.equal(d.open,true,id+' stays open after Keep editing');
   f.answers.push(true);
  }
  const event={target:d,preventDefault(){this.prevented=true;},stopImmediatePropagation(){}};
  f.listeners.cancel[0](event);await tick();assert.equal(d.open,false,id+' Escape closes through the same policy');
  assert.equal(event.prevented,true);assert(!f.c.editorDirty.keys().includes('dialog:'+id));
  d.open=true;await close.onclick();assert.equal(d.open,false,id+' close button uses the same policy');
  if(p.cancel){d.open=true;await f.e(p.cancel).onclick();assert.equal(d.open,false,id+' footer Cancel uses the same dismissal policy');
   if(!p.custom&&!p.transient){d.open=true;f.c.editorDirty.set('dialog:'+id,true);f.answers.push(false);await f.e(p.cancel).onclick();assert(d.open,id+' footer preserves edits after Keep editing');f.answers.push(true);await f.e(p.cancel).onclick();assert(!d.open,id+' footer closes after explicit discard');}
  }
 }
 // Only one discard question, even on repeated close gestures.
 const pending=fixture();let answer;pending.c.ask=()=>new Promise(r=>answer=r);pending.c.editorDirty.set('dialog:person-dialog',true);
 const a=vm.runInContext("requestDialogClose($('person-dialog'),()=>$('person-dialog').close())",pending.c);
 const b=vm.runInContext("requestDialogClose($('person-dialog'),()=>{throw new Error('second close')})",pending.c);
 answer(false);assert.equal(await a,false);assert.equal(await b,false);
 // The dynamic manual-task editor also has a real Escape dismiss callback.
 const manual=fixture();manual.c.editorDirty.set('dialog:manual-task-dialog',true);manual.answers.push(false);
 const escapeManual={target:manual.e('manual-task-dialog'),preventDefault(){},stopImmediatePropagation(){}};
 manual.listeners.cancel[0](escapeManual);await tick();assert(manual.e('manual-task-dialog').open);
 manual.answers.push(true);manual.listeners.cancel[0](escapeManual);await tick();assert(!manual.e('manual-task-dialog').open);
 // The new-project prompt must also close with Escape without a missing callback.
 const project=fixture();const escapeProject={target:project.e('project-dialog'),preventDefault(){this.prevented=true;},stopImmediatePropagation(){}};
 project.listeners.cancel[0](escapeProject);await tick();assert(escapeProject.prevented);assert(!project.e('project-dialog').open);
 // A typed project name is an edit: Escape and Cancel ask first, and Keep editing keeps it.
 assert.equal(policies['project-dialog'].transient,undefined);assert.equal(policies['project-dialog'].cancel,'project-cancel');
 const typed=fixture();typed.e('project-dialog').open=true;typed.c.editorDirty.set('dialog:project-dialog',true);typed.answers.push(false);
 typed.listeners.cancel[0]({target:typed.e('project-dialog'),preventDefault(){},stopImmediatePropagation(){}});await tick();assert(typed.e('project-dialog').open,'Escape keeps the typed project name');
 typed.answers.push(false);await typed.e('project-cancel').onclick();assert(typed.e('project-dialog').open,'Cancel keeps the typed project name');
 typed.answers.push(true);await typed.e('project-cancel').onclick();assert(!typed.e('project-dialog').open);
 // An in-flight save owns the modal. Double submit/close/Escape cannot bypass it.
 for(const id of ids.filter(id=>policies[id].form||policies[id].actions?.length)){
  const x=fixture();let finish,calls=0;x.c.action=()=>{calls++;return new Promise(r=>finish=r);};
  const job=vm.runInContext(`withDialogAction($('${id}'),action)`,x.c);assert.equal(x.e(id).inert,true);assert.equal(x.e(id).attrs['aria-busy'],'true');
  await vm.runInContext(`withDialogAction($('${id}'),action)`,x.c);assert.equal(calls,1);
  assert.equal(await vm.runInContext(`requestDialogClose($('${id}'),()=>$('${id}').close())`,x.c),false);
  const escape={target:x.e(id),preventDefault(){this.prevented=true;},stopImmediatePropagation(){}};x.listeners.cancel[0](escape);assert(escape.prevented);assert(x.e(id).open);
  finish();await job;assert(!x.e(id).inert);assert(!x.c.editorDirty.has());
 }
 const failed=fixture();failed.c.action=async()=>{throw new Error('network failed');};
 await assert.rejects(vm.runInContext("withDialogAction($('person-dialog'),action)",failed.c),/network failed/);
 assert(failed.e('person-dialog').open);assert(!failed.e('person-dialog').inert);assert(!failed.c.editorDirty.has());
 // Exercise real ask(): two concurrent callers must receive their own independent answer.
 const nodes={};for(const id of ['ask-dialog','ask-input','ask-message','ask-ok','ask-cancel','ask-extra'])nodes[id]={value:'',focus(){},select(){}};
 let shown=0;nodes['ask-dialog'].showModal=function(){assert(!this.open);this.open=true;shown++;};nodes['ask-dialog'].close=function(value){this.returnValue=value;this.open=false;this.onclose();};
 const q=vm.createContext({$:id=>nodes[id]});vm.runInContext(extract('let askQueue=','$(\'ask-input\').onkeydown'),q);
 const one=vm.runInContext("ask('First')",q),two=vm.runInContext("ask('Second',{value:'name'})",q);await tick();assert.equal(shown,1);assert.equal(nodes['ask-message'].textContent,'First');
 nodes['ask-dialog'].close('cancel');assert.equal(await one,false);await tick();assert.equal(shown,2);assert.equal(nodes['ask-message'].textContent,'Second');
 nodes['ask-input'].value='edited';nodes['ask-dialog'].close('ok');assert.equal(await two,'edited');
 // A third choice answers 'extra'; the button hides again for an ordinary question.
 const three=vm.runInContext("ask('Type',{ok:'Change and make new notes',extra:'Change type only'})",q);await tick();
 assert.equal(nodes['ask-extra'].hidden,false);assert.equal(nodes['ask-extra'].textContent,'Change type only');
 nodes['ask-dialog'].close('extra');assert.equal(await three,'extra');
 const four=vm.runInContext("ask('Plain')",q);await tick();assert.equal(nodes['ask-extra'].hidden,true);nodes['ask-dialog'].close('extra');assert.equal(await four,false);
 console.log('Dialogs PASS: all 17 policies, close/Escape parity, queued confirmations, save exclusion, error recovery and dirty cleanup.');
})().catch(e=>{console.error(e);process.exitCode=1;});
