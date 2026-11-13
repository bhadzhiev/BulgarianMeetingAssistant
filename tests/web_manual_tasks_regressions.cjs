const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const src=fs.readFileSync('web/app.js','utf8');
function node(tag,cls,text){return {tag,cls,text,value:'',children:[],attrs:{},isConnected:true,append(...x){this.children.push(...x)},replaceChildren(...x){this.children=x},insertBefore(x,before){this.children.splice(this.children.indexOf(before),0,x)},setAttribute(k,v){this.attrs[k]=v},querySelectorAll(){return []},focus(){},showModal(){this.open=true},close(){this.open=false}};}
function setup(){
 const nodes={'manual-task-dialog':node('dialog'),'manual-task-body':node('div'),'work-project':{value:'project'}},errors=[],requests=[];let finish;
 const c=vm.createContext({taskEvidenceTarget:null,renderTaskEvidenceContext(){},view:'tasks',contextProject:()=> 'project',el:node,$:id=>nodes[id],state:{meetings:[{id:'meeting',title:'Daily',project_id:'project'}],people:[{id:'p1',name:'Иван'}]},personOptions:()=>[Object.assign(node('option','','Иван'),{value:'p1'})],crypto:{randomUUID:()=> 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'},
  option:(text,value)=>Object.assign(node('option','',text),{value}),fillProjects:(e,value)=>e.value=value,
  leaveEdits:async()=>true,validDates:()=>true,editorDirty:{clear(){}},requestDialogClose:async(d,fn)=>fn(),
  withDialogAction:async(d,fn)=>{if(d.busy)return;d.busy=true;try{return await fn()}finally{d.busy=false}},
  withEditorSave:async(box,fn)=>{box.inert=true;try{return await fn()}finally{box.inert=false}},
  perform:async fn=>{try{return await fn()}catch(e){errors.push(e.message)}},toast(){},error:message=>errors.push(message),refreshAfterItemChange:async()=>{},
  api:(path,body)=>{requests.push({path,body:JSON.parse(JSON.stringify(body))});return new Promise((res,rej)=>finish=(error)=>error?rej(error):res({id:'task'}))}});
 vm.runInContext(src.slice(src.indexOf('function btn('),src.indexOf('function option(')),c);
 vm.runInContext(src.slice(src.indexOf('async function openManualTask('),src.indexOf("$('new-task').onclick=")),c);
 return {c,nodes,errors,requests,finish:e=>finish(e),fields:()=>Object.fromEntries(nodes['manual-task-body'].children.flatMap(n=>n.tag==='label'?[n]:n.children||[]).filter(n=>n.tag==='label').map(n=>[n.text,n.children[0]])),actions:()=>{const buttons=nodes['manual-task-body'].children.at(-1).children;assert.deepEqual(buttons.map(b=>b.text),['Cancel','Draft with AI…','Improve with AI','Create task']);return [buttons.find(b=>b.text==='Create task'),buttons.find(b=>b.text==='Cancel')];}};
}
(async()=>{
 const projectContext=setup();vm.runInContext("view='projects';contextProject=()=> 'workspace-project';",projectContext.c);await vm.runInContext('openManualTask()',projectContext.c);assert.equal(projectContext.fields().Project.value,'workspace-project');
 const f=setup();await vm.runInContext("openManualTask('meeting')",f.c);const fields=f.fields(),[save,cancel]=f.actions();
 assert.equal(fields.Meeting.value,'meeting');assert.equal(fields.Project.value,'project');
 fields.Title.value='Провери Kubernetes backup';fields.Owner.value='p1';fields['Due date'].value='2026-11-10';
 const pending=save.onclick();await Promise.resolve();await save.onclick();assert.equal(f.requests.length,1);assert(f.nodes['manual-task-body'].inert);
 const body=f.requests[0].body;assert.equal(body.text,'Провери Kubernetes backup');assert.equal(body.owner,'Иван');assert.equal(body.meeting_id,'meeting');assert.equal(body.project_id,'project');assert.equal(body.request_id.length,32);
 f.finish();await pending;assert.equal(f.nodes['manual-task-dialog'].open,false);
 const g=setup();await vm.runInContext('openManualTask()',g.c);g.fields().Title.value='Самостоятелна задача';
 let job=g.actions()[0].onclick();await Promise.resolve();g.finish(new Error('Network lost'));await job;assert(g.nodes['manual-task-dialog'].open);assert.equal(g.fields().Title.value,'Самостоятелна задача');
 job=g.actions()[0].onclick();await Promise.resolve();assert.deepEqual(g.requests[0].body,g.requests[1].body);assert.equal(g.requests[1].body.meeting_id,null);g.finish();await job;
 const h=setup();await vm.runInContext('openManualTask()',h.c);h.fields().Title.value='Task';job=h.actions()[0].onclick();await Promise.resolve();h.finish(Object.assign(new Error('Busy meeting'),{status:400}));await job;h.fields().Title.value='Edited after validation';job=h.actions()[0].onclick();await Promise.resolve();assert.equal(h.requests.length,2);h.finish();await job;
 console.log('Manual task editor PASS: routing, standalone tasks, duplicate clicks, lost-response retries and validation recovery.');
})().catch(e=>{console.error(e);process.exitCode=1});
