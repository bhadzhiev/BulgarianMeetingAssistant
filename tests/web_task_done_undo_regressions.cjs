const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const src=fs.readFileSync('web/app.js','utf8'),Tasks=require('../web/task-model.js');
const plain=x=>JSON.parse(JSON.stringify(x));
const slice=(a,b)=>src.slice(src.indexOf(a),src.indexOf(b,src.indexOf(a)));
function node(tag,cls,text){return {tag,cls,text,hidden:false,disabled:false,children:[],append(...x){this.children.push(...x)},replaceChildren(...x){this.children=x}};}
function setup(){
 const toastBox=node('div'),requests=[],timers=[];
 const c=vm.createContext({el:node,$:()=>toastBox,document:{createTextNode:t=>({text:t})},AtlantaTasks:Tasks,validDates:()=>true,
  setTimeout:fn=>{timers.push(fn);return timers.length;},clearTimeout(){},refreshAfterItemChange:async()=>{},
  perform:async fn=>fn(),api:async(path,body)=>{requests.push({path,body});return {id:'t1',text:'Restore backup',revision:body.revision+1};}});
 vm.runInContext(src.slice(src.indexOf('function btn('),src.indexOf('function option(')),c);
 vm.runInContext(slice('let toastTimer=null;','function knownSpeaker(')+slice('async function changeWithUndo(','async function changeItem(')+slice('async function changeItem(','// A new mention'),c);
 return {c,toastBox,requests,undo:()=>toastBox.children.find(n=>n.text==='Undo')};
}
(async()=>{
 // Mark done saves the done state at once and offers Undo that restores the earlier state, not To do.
 const f=setup();const button=vm.runInContext("doneButton({id:'t1',text:'Restore backup',revision:4,status:'open',workflow_state:'waiting'})",f.c);
 assert.equal(button.text,'Mark done');await button.onclick();
 assert.deepEqual(plain(f.requests[0].body),{text:'Restore backup',revision:4,changes:{workflow_state:'done'}});
 assert.equal(f.toastBox.hidden,false);assert.ok(f.undo(),'Undo is offered');
 f.undo().onclick();await new Promise(setImmediate);
 assert.deepEqual(plain(f.requests[1].body),{text:'Restore backup',revision:5,changes:{workflow_state:'waiting'}});

 // A done task offers Reopen and needs no Undo.
 const g=setup();const reopen=vm.runInContext("doneButton({id:'t1',text:'Restore backup',revision:2,status:'done',workflow_state:'done'})",g.c);
 assert.equal(reopen.text,'Reopen');await reopen.onclick();assert.deepEqual(plain(g.requests[0].body.changes),{workflow_state:'todo'});

 // No task row marks a task done with an unlabelled checkbox; Skip and Dismiss offer Undo.
 for(const [start,end] of [['function globalTaskRow(','function decisionRow('],['function taskRow(','function renderNotes('],['$(\'prepare-tasks\').replaceChildren(','// A daily goes']]){
  const body=slice(start,end);assert.ok(!body.includes("'Mark task as done'"),start);assert.ok(!/done\.type='checkbox'/.test(body),start);
 }
 assert.ok(slice('function globalTaskRow(','function decisionRow(').includes("el('span','','Select')"),'the select box has a visible label');
 assert.equal((src.match(/changeWithUndo\(item,\{dismissed:true\}/g)||[]).length,3,'Skip proposal twice and Dismiss offer Undo');
 assert.ok(slice('function taskRow(','function renderNotes(').includes("actions.append(doneButton(item,busy),edit,remove);main.append(actions);}else main.append(edit);"),'a proposal has no done control and no Delete');
 console.log('Task done/undo PASS: Mark done with Undo restores the earlier state, Reopen, no unlabelled done checkboxes, Skip and Dismiss Undo.');
})().catch(e=>{console.error(e);process.exitCode=1;});
