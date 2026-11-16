const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const src=fs.readFileSync('web/app.js','utf8');
class Node{constructor(tag,cls,text){Object.assign(this,{tag,cls,textContent:text,children:[],value:'',checked:false,disabled:false,hidden:false});}append(...v){this.children.push(...v);}prepend(v){this.children.unshift(v);}replaceChildren(...v){this.children=v;}querySelectorAll(){return this.children;}}
const nodes={},el=(...v)=>new Node(...v),$=id=>nodes[id]??=el('div'),requests=[],answers=[],dirty=[];
const data={tasks:[{id:'root',text:'Main'}],available_tasks:[{id:'root',text:'Main'},{id:'a',text:'Child A',parent_task_id:'root'},{id:'b',text:'Child B',parent_task_id:'root'}],subject:'Subject',body:'Original'};
$('task-email-body').value='Original';$('task-email-subject').value='Subject';$('task-email-people').children=[Object.assign(el('input'),{value:'owner@example.test',checked:true})];
const c=vm.createContext({el,$,Set,btn:(cls,text,fn)=>Object.assign(el('button',cls,text),{onclick:fn}),taskEmailRecipients:()=>['owner@example.test','extra@example.test'],perform:fn=>fn(),withDialogAction:async(d,fn)=>fn(),taskEmailMeeting:null,taskEmailItems:['root'],toast(){},editorDirty:{set(...v){dirty.push(v);}},ask:async()=>answers.shift(),api:async(path,body)=>{requests.push({path,body});return {...data,tasks:data.available_tasks.filter(t=>body.item_ids.includes(t.id)),recipients:[{email:'owner@example.test'}]};},renderTaskEmail:()=>{}});
vm.runInContext(src.slice(src.indexOf('function renderTaskEmailChoices('),src.indexOf('function renderTaskEmail(data)')),c);c.data=data;
(async()=>{
 vm.runInContext('renderTaskEmailChoices(data)',c);
 const list=$('task-email-selected'),labels=list.children.filter(n=>n.tag==='label');
 assert.equal(labels.length,3);assert(labels[0].children[0].checked);assert(!labels[1].children[0].checked,'related children are opt-in');
 labels[1].children[0].checked=true;labels[1].children[0].onchange();assert($('task-email-save').disabled);assert($('task-email-copy').disabled);
 $('task-email-body').value='My edited text';answers.push(false);await $('task-email-apply-selection').onclick();assert.equal(requests.length,0,'declined replacement keeps edits');
 answers.push(true);await $('task-email-apply-selection').onclick();assert.deepEqual([...requests[0].body.item_ids],['root','a']);
 assert.equal($('task-email-extra').value,'extra@example.test','manual recipients survive rebuilding');assert.equal(dirty.length,1);
 vm.runInContext('renderTaskEmailChoices(data)',c);$('task-email-selected').children[0].onclick();assert(!$('task-email-apply-selection').hidden,'select all requests an explicit rebuild');
 console.log('Subtask email PASS: explicit selection, pending-save guard, replacement confirmation and recipient preservation.');
})().catch(e=>{console.error(e);process.exitCode=1});
