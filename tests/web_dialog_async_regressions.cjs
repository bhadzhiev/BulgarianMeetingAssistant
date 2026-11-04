const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8'),prompts=fs.readFileSync('web/prompt-editor.js','utf8');
const slice=(s,a,b)=>s.slice(s.indexOf(a),s.indexOf(b,s.indexOf(a)));
const tick=()=>new Promise(setImmediate);
(async()=>{
 // A slow previous profile must never overwrite the person opened after it.
 const nodes=new Map(),pending={},rendered=[];
 const $=id=>{if(!nodes.has(id))nodes.set(id,{open:false,value:'',replaceChildren(){},showModal(){this.open=true;}});return nodes.get(id);};
 const c=vm.createContext({$,state:{people:[{id:'a',name:'A',aliases:[],emails:[]},{id:'b',name:'B',aliases:[],emails:[]}]},
  renderPersonIdentities(){},renderProfile:p=>rendered.push(p.person.id),api:path=>new Promise(r=>pending[path]=r)});
 vm.runInContext("let personEditing=null,personGitHub=null,personSequence=0,pendingSpeaker=null;"+slice(app,'async function openPerson(id)','function renderProfile(profile)'),c);
 const a=vm.runInContext("openPerson('a')",c),b=vm.runInContext("openPerson('b')",c);
 pending['/api/people/profile?id=b']({person:{id:'b'}});await b;pending['/api/people/profile?id=a']({person:{id:'a'}});await a;assert.deepEqual(rendered,['b']);
 // Closing Settings during the start request cancels the late-created test instead of attaching it to another editor.
 let start,polled=0;const requests=[],els=new Map();
 const field=id=>{if(!els.has(id))els.set(id,{open:true,value:'',textContent:''});return els.get(id);};
 const q=vm.createContext({$:field,ask:async()=>true,perform:async fn=>fn(),promptBusy(){},promptError(){},invalidatePromptTest(){},clearTimeout(){},
  promptDirty:()=>false,editorDirty:{clear(){}},pollPromptTest:()=>{polled++;},
  api:(path,body)=>{requests.push([path,body]);return path==='/api/prompts/test/start'?new Promise(r=>start=r):Promise.resolve({});}});
 vm.runInContext("let promptPreview={preview_token:'preview'},promptPending=false,promptLaunch=0,promptJob=null,promptTimer=null,promptOriginal='';"+
  slice(prompts,'async function leavePromptEditor()','function invalidatePromptTest()')+
  slice(prompts,"$('prompt-test').onclick=","$('prompt-reprocess').onclick="),q);
 const request=vm.runInContext("$('prompt-test').onclick()",q);await tick();assert.equal(requests.length,1);
 await vm.runInContext('leavePromptEditor()',q);field('settings-dialog').open=false;start({id:'late-job'});await request;
 assert(requests.some(([path,body])=>path==='/api/prompts/test/cancel'&&body.id==='late-job'));assert.equal(polled,0);assert.equal(vm.runInContext('promptJob',q),null);
 // The explicit Cancel button must work before the start response has returned too.
 requests.length=0;field('settings-dialog').open=true;vm.runInContext("promptPreview={preview_token:'preview2'}",q);
 const second=vm.runInContext("$('prompt-test').onclick()",q);await tick();await vm.runInContext("$('prompt-cancel').onclick()",q);start({id:'cancelled-before-start-returned'});await second;
 assert(requests.some(([path,body])=>path==='/api/prompts/test/cancel'&&body.id==='cancelled-before-start-returned'));assert.equal(polled,0);
 const settingsForm={};let writes=0;
 const settings=vm.createContext({$:()=>settingsForm,settingsTab:'recording',perform:async fn=>fn(),leaveTypePrompt:async()=>false,leavePromptEditor:async()=>{throw new Error('Cancelled type edits must stop Settings save');},api:()=>{writes++;}});
 vm.runInContext(app.split('\n').find(line=>line.startsWith("$('settings-form').onsubmit=")),settings);
 await settingsForm.onsubmit({preventDefault(){}});assert.equal(writes,0);
 console.log('Dialog async PASS: stale person profiles ignored; late AI starts cancelled on editor close and Cancel.');
})().catch(e=>{console.error(e);process.exitCode=1;});
