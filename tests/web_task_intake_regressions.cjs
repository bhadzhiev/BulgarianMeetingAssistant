const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('web/app.js','utf8');
function setup(aiAvailable=true){
 const nodes=new Map(),requests=[],storage=new Map();let fail=false;
 const field=id=>{if(!nodes.has(id))nodes.set(id,{value:'',checked:false,disabled:false,open:false,textContent:'',replaceChildren(){},focus(){},setCustomValidity(){},reportValidity(){},showModal(){this.open=true},close(){this.open=false;this.onclose?.()},querySelector(){return {}}});return nodes.get(id);};
 const dirty=new Set();
 const c=vm.createContext({$:field,state:{people:[]},itemsData:{items:[{id:'existing',kind:'task',text:'Current task',revision:7,acceptance_state:'accepted'}]},
  crypto:{randomUUID:()=> 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'},el(){return {}},option:(name,value)=>({name,value}),contextProject:()=>'',fillProjects:(f,v)=>f.value=v,
  store:(k,v)=>storage.set(k,v),localStorage:{getItem:k=>storage.get(k)||null,removeItem:k=>storage.delete(k)},
  editorDirty:{set:k=>dirty.add(k),clear:k=>dirty.delete(k),keys:()=>[...dirty]},validDates:()=>true,
  perform:fn=>fn(),ask:async()=>true,showCreatedTask(){},refreshAfterItemChange:async()=>{},error(){},setTimeout(){},clearTimeout(){},
  api:async(path,body)=>{requests.push({path,body});if(fail)throw new Error('Network lost');return {item_id:'saved'};}});
 vm.runInContext(source.slice(source.indexOf('function editTaskDraft('),source.indexOf('function showCreatedTask(')),c);
 const preview={ai_available:aiAvailable,ai_unavailable_reason:'AI is optional',target:{local_ai_model:'fixture',local_ai_base_url:'local'},preview_token:'approved',characters:40,source_excerpt:'Exact source'};
 return {field,requests,c,start:()=>{c.input={provider:'manual',id:'b'.repeat(32),source_text:'Capture source'};c.preview=preview;return vm.runInContext('editTaskDraft(input,preview)',c)},fail:v=>fail=v};
}
(async()=>{
 const a=setup(),done=a.start();a.field('task-draft-text').value='Title';a.field('task-draft-text').oninput();a.field('task-draft-details').value='Context';a.field('task-draft-criterion').value='Expected result';
 a.fail(true);await a.field('task-draft-save').onclick();assert(a.field('task-draft-dialog').open);assert.equal(a.field('task-draft-text').value,'Title');
 a.field('task-draft-text').value='Changed after timeout';await a.field('task-draft-save').onclick();assert.equal(a.requests.length,1,'uncertain result cannot retry a different task');
 a.field('task-draft-text').value='Title';a.fail(false);await a.field('task-draft-save').onclick();assert.equal(await done,'saved');assert.equal(a.requests.length,2);assert.equal(JSON.stringify(a.requests[0].body),JSON.stringify(a.requests[1].body));
 assert.equal(a.requests[1].body.details,'Context');assert.equal(a.requests[1].body.completion_criteria,'Expected result');assert.equal(a.requests[1].body.owner,null);assert.equal(a.requests[1].body.due_date,null);
 const b=setup(),linked=b.start();b.field('task-draft-link').value='existing';b.field('task-draft-link').onchange();assert(!b.field('task-draft-save').disabled);assert(b.field('task-draft-details').disabled);await b.field('task-draft-save').onclick();assert.equal(await linked,'saved');assert.equal(b.requests[0].body.target_revision,7);
 const noAI=setup(false),manual=noAI.start();assert(noAI.field('task-draft-generate').disabled);assert.equal(noAI.field('task-draft-target').textContent,'AI is optional');noAI.field('task-draft-text').value='Manual without AI';noAI.field('task-draft-text').oninput();assert(!noAI.field('task-draft-save').disabled);await noAI.field('task-draft-save').onclick();assert.equal(await manual,'saved');
 const d=setup(),cancelled=d.start();await d.field('task-draft-cancel').onclick();assert.equal(await cancelled,null);assert.equal(d.requests.length,0);
 console.log('Task intake PASS: structured fields, optional owner/date, preserved network retries, changed-payload guard, evidence linking and cancellation.');
})().catch(e=>{console.error(e);process.exitCode=1});
