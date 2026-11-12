// The AI stops at the meeting notes unless Settings → AI turns meeting tasks on (decision of 2026-11-12).
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8'),html=fs.readFileSync('web/index.html','utf8');
const slice=(start,end)=>{const i=app.indexOf(start);assert(i>=0,start);return app.slice(i,end?app.indexOf(end,i):undefined);};
// Settings: one switch, off unless saved on; task matching shows only with it.
assert.match(html,/<input id="meeting-task-ai" type="checkbox"> Let AI propose tasks from meeting notes and match them with existing tasks<\/label>/);
assert.match(app,/\$\('meeting-task-ai'\)\.checked=!!s\.meeting_task_ai;/);
assert.match(app,/meeting_task_ai:\$\('meeting-task-ai'\)\.checked,/);
assert.match(slice('function renderTaskMatching(){'),/\$\('task-matching-field'\)\.hidden=!\$\('meeting-task-ai'\)\.checked;/);
// A task line of the notes: hidden AI proposals show as plain lines, and Create task opens the editor for that line.
const row=slice('function taskRow(task,index,busy,mentions=[task]) {','\nfunction renderNotes(');
assert.match(row,/const handMade=!state\.settings\?\.meeting_task_ai;/);
assert.match(row,/item=handMade&&linked\?\.acceptance_state==='proposed'\?undefined:linked/);
assert.match(row,/if\(!item&&handMade\)\{const create=btn\('secondary small-action','Create task'\)/);
assert.match(row,/openManualTask\(detail\.id,\{text:task\.task\|\|'',details:task\.details\|\|'',owner:task\.owner\|\|'',due:task\.due_date\|\|'',mention:index\}\)/);
// The meeting checklist asks nothing about task links, owners or matching without AI meeting tasks.
const attention=slice('function renderAttention(busy){');
assert.match(attention,/if\(d\.task_matching\?\.status==='needs_permission'&&state\.settings\?\.meeting_task_ai\)/);
assert.match(attention,/if\(tasks&&state\.settings\?\.meeting_task_ai\)add\('info','Give an owner/);
// The editor for a line: prefilled, fixed to its meeting, no AI draft, and the request names the line.
function node(tag,cls,text){return {tag,cls,text,value:'',children:[],attrs:{},isConnected:true,append(...x){this.children.push(...x)},replaceChildren(...x){this.children=x},insertBefore(x,before){this.children.splice(this.children.indexOf(before),0,x)},setAttribute(k,v){this.attrs[k]=v},querySelectorAll(){return []},focus(){},showModal(){this.open=true},close(){this.open=false}};}
const nodes={'manual-task-dialog':node('dialog'),'manual-task-body':node('div'),'work-project':{value:''}},requests=[];
const c=vm.createContext({taskEvidenceTarget:null,renderTaskEvidenceContext(){},view:'detail',contextProject:()=>'',el:node,$:id=>nodes[id],state:{meetings:[{id:'meeting',title:'Daily',project_id:''}]},crypto:{randomUUID:()=>'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'},
 option:(text,value)=>Object.assign(node('option','',text),{value}),fillProjects:(e,value)=>e.value=value,leaveEdits:async()=>true,validDates:()=>true,editorDirty:{clear(){}},requestDialogClose:async(d,fn)=>fn(),
 withDialogAction:async(d,fn)=>fn(),withEditorSave:async(box,fn)=>fn(),perform:async fn=>fn(),toast(){},error(){},refreshAfterItemChange:async()=>{},showCreatedTask(){},revealTask(){},
 api:async(path,body)=>{requests.push({path,body});return {id:'task'};}});
vm.runInContext(app.slice(app.indexOf('function btn('),app.indexOf('function option(')),c);
vm.runInContext(slice('async function openManualTask(',"$('new-task').onclick="),c);
(async()=>{
 await vm.runInContext("openManualTask('meeting',{text:'Изпрати оферта',details:'До петък',owner:'Иван',due:'',mention:2})",c);
 const body=nodes['manual-task-body'],fields=Object.fromEntries(body.children.filter(n=>n.tag==='label').map(n=>[n.text,n.children[0]]));
 assert.deepEqual([fields.Task.value,fields.Description.value,fields.Owner.value,fields.Meeting.value,fields.Meeting.disabled],['Изпрати оферта','До петък','Иван','meeting',true]);
 const buttons=body.children.at(-1).children;assert.deepEqual(buttons.map(b=>b.text),['Cancel','Create task']);
 await buttons[1].onclick();
 assert.equal(requests[0].path,'/api/items/create');
 assert.deepEqual({...requests[0].body,request_id:''},{text:'Изпрати оферта',details:'До петък',owner:'Иван',due_date:null,meeting_id:'meeting',project_id:null,request_id:'',mention_index:2});
 console.log('Manual meeting tasks PASS: setting, Create task on a notes line, hidden proposals, quiet checklist, linked editor.');
})().catch(e=>{console.error(e);process.exitCode=1});
