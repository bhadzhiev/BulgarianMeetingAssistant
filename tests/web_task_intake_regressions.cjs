const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
// One task dialog for every source (2026-11-14): a source-backed draft opens the same editor as a
// manual task — same fields, same AI actions, same Create task, plus the evidence link choice.
const src=fs.readFileSync('web/app.js','utf8');
function node(tag,cls,text){return {tag,cls,text,value:'',children:[],attrs:{},isConnected:true,append(...x){this.children.push(...x)},replaceChildren(...x){this.children=x},insertBefore(x,before){this.children.splice(this.children.indexOf(before),0,x)},setAttribute(k,v){this.attrs[k]=v},querySelectorAll(){return []},setCustomValidity(){},reportValidity(){},focus(){},showModal(){this.open=true},close(){this.open=false;this.onclose?.()}};}
function setup(aiAvailable=true){
 const nodes={'manual-task-dialog':node('dialog'),'manual-task-body':node('div'),'work-project':{value:''}},errors=[],requests=[];let fail=false;
 const c=vm.createContext({taskEvidenceTarget:null,renderTaskEvidenceContext(){},view:'tasks',contextProject:()=>'',el:node,$:id=>nodes[id],state:{meetings:[],people:[{id:'p1',name:'Иван'}],projects:{projects:[]}},personOptions:()=>[Object.assign(node('option','','Иван'),{value:'p1'})],crypto:{randomUUID:()=> 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'},
  itemsData:{items:[{id:'existing',kind:'task',text:'Current task',revision:7,acceptance_state:'accepted'}],graph:{relationships:[]}},
  option:(text,value)=>Object.assign(node('option','',text),{value}),fillProjects:(e,value)=>e.value=value,leaveEdits:async()=>true,validDates:()=>true,
  editorDirty:{set(){},clear(){},keys:()=>[]},requestDialogClose:async(d,fn)=>fn(),
  withDialogAction:async(d,fn)=>{if(d.busy)return;d.busy=true;try{return await fn()}finally{d.busy=false}},
  withEditorSave:async(box,fn)=>{box.inert=true;try{return await fn()}finally{box.inert=false}},
  perform:async fn=>{try{return await fn()}catch(e){errors.push(e.message)}},toast(){},error:message=>errors.push(message),showError:(n,m)=>{n.textContent=m;n.hidden=false;},refreshAfterItemChange:async()=>{},showCreatedTask(){},revealTask(){},
  ask:async()=>true,setTimeout(){},clearTimeout(){},
  api:async(path,body)=>{requests.push({path,body:JSON.parse(JSON.stringify(body))});if(fail)throw new Error('Network lost');return {item_id:'saved'};}});
 vm.runInContext(src.slice(src.indexOf('function btn('),src.indexOf('function option(')),c);
 vm.runInContext(src.slice(src.indexOf('async function openManualTask('),src.indexOf("$('new-task').onclick=")),c);
 const source={provider:'gmail',id:'thread',revision:'rev1'};
 const preview={ai_available:aiAvailable,ai_unavailable_reason:'AI is optional',target:{local_ai_model:'fixture',local_ai_base_url:'local'},preview_token:'approved',characters:40,source_excerpt:'Exact source'};
 const fields=()=>Object.fromEntries(nodes['manual-task-body'].children.flatMap(n=>n.tag==='label'?[n]:n.children||[]).filter(n=>n.tag==='label').map(n=>[n.text,n.children[0]]));
 const buttons=()=>nodes['manual-task-body'].children.at(-1).children;
 return {c,nodes,errors,requests,fields,buttons,source,preview,setFail:v=>fail=v,
  start:()=>vm.runInContext('openManualTask(null,{source,sourcePreview:preview})',Object.assign(c,{source,preview}))};
}
const tick=()=>new Promise(r=>setImmediate(r));
(async()=>{
 // Structured fields, optional owner/date, preserved network retries and the changed-payload guard.
 const a=setup(),done=a.start();await tick();await tick();const af=a.fields();
 af.Title.value='Title';af.Description.value='Context';af['Expected result'].value='Expected result';
 assert.deepEqual(a.buttons().map(b=>b.text),['Cancel','Draft with AI…','Improve with AI','Create task']);
 const save=a.buttons()[3];
 a.setFail(true);await save.onclick();assert(a.nodes['manual-task-dialog'].open);assert.equal(a.requests.length,1);
 af.Title.value='Changed after timeout';await save.onclick();assert.equal(a.requests.length,1,'uncertain result cannot retry a different task');
 af.Title.value='Title';a.setFail(false);await save.onclick();assert.equal(a.requests.length,2);
 assert.equal(JSON.stringify(a.requests[0].body),JSON.stringify(a.requests[1].body));
 assert.equal(a.requests[1].body.details,'Context');assert.equal(a.requests[1].body.completion_criteria,'Expected result');assert.equal(a.requests[1].body.owner,null);assert.equal(a.requests[1].body.due_date,null);
 assert.equal(a.requests[1].path,'/api/task-draft/create');assert.equal(a.requests[1].body.operation_id.length,32);assert.equal(await done,'saved');
 // Linking evidence to an existing task disables the fields and sends the target revision.
 const b=setup(),linked=b.start();await tick();await tick();const bf=b.fields();
 bf['Create or link'].value='existing';bf['Create or link'].onchange();
 assert(!b.buttons()[3].disabled);assert(bf.Description.disabled);assert.equal(b.buttons()[3].textContent,'Link evidence');
 await b.buttons()[3].onclick();assert.equal(await linked,'saved');assert.equal(b.requests[0].body.target_id,'existing');assert.equal(b.requests[0].body.target_revision,7);
 // An unavailable AI says why and keeps manual creation possible.
 const noAI=setup(false),manual=noAI.start();await tick();await tick();
 assert(noAI.buttons()[1].disabled,'Draft with AI is disabled without AI');
 const nf=noAI.fields();nf.Title.value='Manual without AI';nf.Title.oninput();assert(!noAI.buttons()[3].disabled);
 await noAI.buttons()[3].onclick();assert.equal(await manual,'saved');assert.equal(noAI.requests[0].body.title,'Manual without AI');
 // Cancel creates nothing and resolves empty.
 const d=setup(),cancelled=d.start();await tick();await tick();await d.buttons()[0].onclick();
 assert.equal(await cancelled,null);assert.equal(d.requests.length,0);
 console.log('Task intake PASS: one dialog for every source, structured fields, optional owner/date, preserved network retries, changed-payload guard, evidence linking and cancellation.');
})().catch(e=>{console.error(e);process.exitCode=1});
