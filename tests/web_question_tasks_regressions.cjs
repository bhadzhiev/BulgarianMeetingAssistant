// Make task on an unanswered question (2026-11-14): the meeting notes line, the tracked question in
// My Work and the meeting candidates all open the same task dialog, and the task keeps the link.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8');
const slice=(start,end)=>{const i=app.indexOf(start);assert(i>=0,start);return app.slice(i,end?app.indexOf(end,i):undefined);};
// The meeting notes: an unresolved question line offers Make task with its source moment.
const section=slice('function noteSection(minutes,field,title,busy,hint) {','\n// Old one-line tasks');
assert.match(section,/if\(\['open_questions','needs_decision'\]\.includes\(field\)&&!decision\)\{const make=btn\('secondary small-action','Make task'\)/);
assert.match(section,/openManualTask\(detail\.id,\{text:item\.text,evidence:item\.evidence_timestamp\|\|null\}\)/);
// A tracked question in My Work offers Make task while open, and shows the tasks that came from it.
const card=slice('function trackedQuestionCard(q){','\n// The questions in meeting notes');
assert.match(card,/if\(q\.status!=='answered'\)\{const make=el\('button','secondary small-action','Make task'\)/);
assert.match(card,/openManualTask\(null,\{text:q\.text,question:q\}\)/);
assert.match(card,/edge\.kind==='derives_from'&&edge\.to_id===q\.id/);
assert.match(card,/openTaskPanel\(task\.id\)/);
// A question candidate from meeting notes offers Make task with its meeting and moment.
const candidates=slice('function renderMeetingQuestions(target){');
assert.match(candidates,/btn\('secondary small-action','Make task',\(\)=>perform\(\(\)=>openManualTask\(q\.meeting_id,\{text:q\.text,evidence:q\.evidence_timestamp\|\|null\}\)\)\)/);

// The unified dialog sends the question link and the source moment to the server.
function node(tag,cls,text){return {tag,cls,text,value:'',children:[],attrs:{},isConnected:true,append(...x){this.children.push(...x)},replaceChildren(...x){this.children=x},insertBefore(x,before){this.children.splice(this.children.indexOf(before),0,x)},setAttribute(k,v){this.attrs[k]=v},querySelectorAll(){return []},setCustomValidity(){},reportValidity(){},focus(){},showModal(){this.open=true},close(){this.open=false;this.onclose?.()}};}
const nodes={'manual-task-dialog':node('dialog'),'manual-task-body':node('div'),'work-project':{value:''}},requests=[];
const c=vm.createContext({taskEvidenceTarget:null,renderTaskEvidenceContext(){},view:'tasks',contextProject:()=>'',el:node,$:id=>nodes[id],state:{meetings:[{id:'meeting',title:'Daily',project_id:''}],people:[]},personOptions:()=>[],crypto:{randomUUID:()=> 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'},
 option:(text,value)=>Object.assign(node('option','',text),{value}),fillProjects:(e,value)=>e.value=value,leaveEdits:async()=>true,validDates:()=>true,editorDirty:{set(){},clear(){},keys:()=>[]},requestDialogClose:async(d,fn)=>fn(),
 withDialogAction:async(d,fn)=>fn(),withEditorSave:async(box,fn)=>fn(),perform:async fn=>fn(),toast(){},error(){},refreshAfterItemChange:async()=>{},showCreatedTask(){},revealTask(){},
 itemsData:{items:[],graph:{relationships:[]}},
 api:async(path,body)=>{requests.push({path,body:JSON.parse(JSON.stringify(body))});return {id:'task'};}});
vm.runInContext(app.slice(app.indexOf('function btn('),app.indexOf('function option(')),c);
vm.runInContext(slice('async function openManualTask(',"$('new-task').onclick="),c);
(async()=>{
 await vm.runInContext("openManualTask(null,{text:'Ще мигрираме ли базата?',question:{id:'question1'}})",c);
 let fields=Object.fromEntries(nodes['manual-task-body'].children.flatMap(n=>n.tag==='label'?[n]:n.children||[]).filter(n=>n.tag==='label').map(n=>[n.text,n.children[0]]));
 assert.equal(fields.Title.value,'Ще мигрираме ли базата?');
 await nodes['manual-task-body'].children.at(-1).children.at(-1).onclick();
 assert.equal(requests[0].path,'/api/items/create');assert.equal(requests[0].body.question_id,'question1');
 await vm.runInContext("openManualTask('meeting',{text:'Кой пише офертата?',evidence:'00:12:30'})",c);
 await nodes['manual-task-body'].children.at(-1).children.at(-1).onclick();
 assert.equal(requests[1].body.evidence_timestamp,'00:12:30');assert.equal(requests[1].body.meeting_id,'meeting');
 console.log('Question to task PASS: Make task on notes lines, tracked questions and candidates; the link and the moment reach the server.');
})().catch(e=>{console.error(e);process.exitCode=1});
