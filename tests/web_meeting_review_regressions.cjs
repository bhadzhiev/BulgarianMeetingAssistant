const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const src=fs.readFileSync('web/app.js','utf8');
function node(tag,cls,text){return {tag,cls,text,type:'',disabled:false,children:[],attrs:{},append(...x){this.children.push(...x.filter(v=>typeof v==='object'))},replaceChildren(...x){this.children=x},setAttribute(k,v){this.attrs[k]=v},querySelector(){return null}};}
const walk=n=>[n,...(n.children||[]).flatMap(walk)];
const row=(over={})=>Object.assign({id:'task',kind:'task',text:'Shared task',state:'needs_review',content:'c',evidence:[],can_dismiss:true,dismiss_blocked_reason:null,confirmed_in:[]},over);
async function render(item){
 const box=node('div'),opened=[],requests=[];
 const c=vm.createContext({detail:{id:'today'},editorDirty:{keys:()=>[],set(){},clear(){}},$:()=>box,el:node,
  api:async(path,body)=>{requests.push({path,body});return {source:'s',summary:[],items:[item]};},
  AtlantaStatus:{label:()=>'Changed',status:(k,s)=>({tone:'x',label:s})},statusBadge:s=>node('span','',s.label),
  reviewRouting:()=>node('div'),listenButton:()=>node('button'),stampButton:()=>node('button'),
  perform:async fn=>fn(),openMeeting:async id=>opened.push(['meeting',id]),openTaskPanel:async id=>opened.push(['task',id]),
  leaveEdits:async()=>true,show(){},loadTasks:async()=>{},showWorkTab(){}});
 vm.runInContext('let reviewShownFor=null,lastTasks="";'+src.slice(src.indexOf('async function openMeetingReview('),src.indexOf('// The publication state')),c);
 await vm.runInContext('openMeetingReview()',c);
 const nodes=walk(box),buttons=nodes.filter(n=>n.tag==='button');
 return {nodes,opened,requests,button:label=>buttons.find(b=>b.text===label),texts:nodes.map(n=>n.text).filter(Boolean)};
}
(async()=>{
 // A proposal with no current confirmation keeps Dismiss.
 const free=await render(row());
 assert.ok(free.button('Dismiss · hide everywhere'));assert.equal(free.button('Open task'),undefined);

 // A current confirmation in another meeting: no Dismiss, the meeting is named and opens, Open task replaces Dismiss.
 const elsewhere=await render(row({can_dismiss:false,dismiss_blocked_reason:'confirmed_elsewhere',confirmed_in:[{meeting_id:'prev',title:'Previous planning'}]}));
 assert.equal(elsewhere.button('Dismiss · hide everywhere'),undefined);
 assert.ok(elsewhere.texts.some(t=>t.startsWith('Already confirmed in another meeting.')&&t.includes('Cancel task')));
 await elsewhere.button('Previous planning').onclick();assert.deepEqual(elsewhere.opened.at(-1),['meeting','prev']);
 await elsewhere.button('Open task').onclick();assert.deepEqual(elsewhere.opened.at(-1),['task','task']);
 assert.ok(elsewhere.button('Confirm locally'));

 // An accepted task (for example after a transcript correction): no other meeting is claimed, the text names Cancel task.
 const accepted=await render(row({can_dismiss:false,dismiss_blocked_reason:'accepted_task'}));
 assert.equal(accepted.button('Dismiss · hide everywhere'),undefined);assert.ok(accepted.button('Open task'));
 assert.ok(accepted.texts.includes('This task is already accepted. If it no longer applies, open the task and choose Cancel task.'));
 assert.ok(!accepted.texts.some(t=>t.includes('another meeting')));

 // The task panel action has the same name as the text that points to it.
 assert.ok(src.includes("el('button','danger-action','Cancel task…')"));
 console.log('Meeting review PASS: Dismiss only when allowed, confirming meeting link, Open task, and Cancel task wording.');
})().catch(e=>{console.error(e);process.exitCode=1;});
