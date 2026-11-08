const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('web/app.js','utf8');
const extract=(a,b)=>source.slice(source.indexOf(a),source.indexOf(b,source.indexOf(a)));
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));

class Control{
 constructor(tag,type=''){this.tag=tag;this.type=type;this.classes=new Set();this.attrs={};this.isConnected=true;this.visible=true;}
 get classList(){const c=this.classes;return {add:n=>c.add(n),remove:n=>c.delete(n),contains:n=>c.has(n)};}
 setAttribute(k,v){this.attrs[k]=v;}removeAttribute(k){delete this.attrs[k];}
 matches(selector){return selector.split(',').some(s=>s===this.tag||s===`[type=${this.type}]`);}
 closest(selector){return this.matches(selector)?this:null;}
 getClientRects(){return this.visible?[{}]:[];}
}

function context(){
 const listeners={},activity={hidden:true},status={hidden:true,textContent:''},errors=[];
 const c=vm.createContext({setTimeout,clearTimeout,errors,
  document:{addEventListener:(type,fn)=>{listeners[type]=fn;}},
  $:id=>{assert.ok(['activity','activity-status'].includes(id),id);return id==='activity'?activity:status;},
  clearError:()=>{},error:message=>errors.push(message)});
 vm.runInContext(extract('// A pressed control shows','function hasEdits()'),c);
 // A user press: the capture listener runs first, then the control's own handler.
 const press=(control,handler,type='click')=>{listeners[type]({target:control,submitter:type==='submit'?control:undefined});return handler();};
 const write=()=>vm.runInContext('actionWrites++',c);
 return {c,press,write,activity,status,errors};
}

(async()=>{
 // A slow action shows a spinner and the top bar, then a check mark after a saved change.
 {
  const {c,press,write,activity,status}=context(),button=new Control('button');button.textContent=' Import file ';let finish;
  const done=press(button,()=>vm.runInContext('perform',c)(()=>new Promise(r=>finish=r)));
  assert.equal(button.classes.has('is-busy'),false,'no flicker for fast actions');assert.equal(status.hidden,true);
  await wait(300);
  assert.equal(button.classes.has('is-busy'),true);assert.equal(button.attrs['aria-busy'],'true');assert.equal(activity.hidden,false);
  // The status names the action in the words of its button.
  assert.equal(status.hidden,false);assert.equal(status.textContent,'Import file · in progress…');
  vm.runInContext('activityStep',c)('Importing the transcript');assert.equal(status.textContent,'Importing the transcript · in progress…');
  write();finish();await done;
  assert.equal(button.classes.has('is-busy'),false);assert.equal(activity.hidden,true);assert.equal(status.hidden,true);assert.equal(button.classes.has('is-done'),true);
 }
 // A second press of the same button does not start the action again.
 {
  const {c,press}=context(),button=new Control('button');let runs=0,finish;
  const action=()=>vm.runInContext('perform',c)(()=>{runs++;return new Promise(r=>finish=r);});
  const first=press(button,action);press(button,action);press(button,action);
  assert.equal(runs,1);finish();await first;press(button,action);assert.equal(runs,2);finish();
 }
 // A select applies every change, also while an earlier change still loads.
 {
  const {c,press}=context(),select=new Control('select');let runs=0;
  const action=()=>vm.runInContext('perform',c)(()=>{runs++;return wait(20);});
  await Promise.all([press(select,action,'change'),press(select,action,'change')]);assert.equal(runs,2);
 }
 // A nested perform() does not take the pressed control, so it is not dropped as a second press.
 {
  const {c,press}=context(),button=new Control('button');let inner=0;
  const perform=vm.runInContext('perform',c);
  await press(button,()=>perform(async()=>{await perform(async()=>{inner++;});}));assert.equal(inner,1);
 }
 // No check mark without a change, after an error, or when the button is gone.
 {
  const {c,press,write,errors}=context(),perform=vm.runInContext('perform',c);
  const read=new Control('button');await press(read,()=>perform(async()=>{}));assert.equal(read.classes.has('is-done'),false);
  const failed=new Control('button');await press(failed,()=>perform(async()=>{write();throw new Error('Server down');}));
  assert.equal(failed.classes.has('is-done'),false);assert.deepEqual(errors,['Server down']);
  const gone=new Control('button');await press(gone,()=>perform(async()=>{write();gone.isConnected=false;}));assert.equal(gone.classes.has('is-done'),false);
 }
 // A form submit marks its submit button.
 {
  const {c,press,write}=context(),submit=new Control('button','submit');
  await press(submit,()=>vm.runInContext('perform',c)(async()=>write()),'submit');
  assert.equal(submit.classes.has('is-done'),true);
 }
 // api() counts each request with a body as a change.
 assert.match(extract('async function api(path,body)','}'),/if\(body!==undefined\)actionWrites\+\+/);
 console.log('Busy feedback PASS: delayed spinner and bar, double press ignored, selects always apply, nested calls run, check mark only after a saved change.');
})().catch(e=>{console.error(e);process.exitCode=1;});
