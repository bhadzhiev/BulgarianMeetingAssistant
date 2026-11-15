const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
// Confirmations (2026-11-16): risky actions ask first (danger for destructive ones); other changes show the result with Undo.
const src=fs.readFileSync('web/app.js','utf8');
const slice=(a,b)=>{const at=src.indexOf(a);assert.notEqual(at,-1,a);return src.slice(at,src.indexOf(b,at));};
// Undo of an Edit task save restores exactly the changed fields; the progress note stays as history.
const c=vm.createContext({AtlantaTasks:{workflow:i=>i.workflow_state||'todo'}});
vm.runInContext(slice('function taskEditUndo(','\nasync function openTaskPanel('),c);
const item={text:'Old title',details:'Old details',completion_criteria:'',due_date:'2026-11-20',follow_up_date:null,workflow_state:'in_progress',owner_person_id:'p1',assignee_person_ids:['p1'],project_ids:['a']};
const undo=c.taskEditUndo(item,{text:'New title',details:'Old details',completion_criteria:'',due_date:'2026-11-30',workflow_state:'cancelled',owner_person_id:'p2',project_ids:['b'],update_note:'Waiting for parts'});
assert.deepEqual(JSON.parse(JSON.stringify(undo)),{text:'Old title',due_date:'2026-11-20',workflow_state:'in_progress',owner_person_id:'p1',project_ids:['a']});
// An inherited project comes back as inherited (null), a name-only owner comes back as that name.
const inherited=c.taskEditUndo({text:'T',owner:'Мария'},{text:'T',project_ids:['b'],owner_person_id:'p2'});
assert.deepEqual(JSON.parse(JSON.stringify(inherited)),{owner_person_id:null,owner:'Мария',project_ids:null});
assert.deepEqual(JSON.parse(JSON.stringify(c.taskEditUndo(item,{text:'Old title',details:'Old details',completion_criteria:'',update_note:'Only a note'}))),{});
// Risky actions ask first.
const panel=slice('async function openTaskPanel(','\n}\n');
assert.match(panel,/if\(changes\.workflow_state==='cancelled'&&!\(await ask\('Cancel this task\? It leaves active work\. You can reopen it later\.',\{ok:'Cancel task',cancel:'Keep task',danger:true\}\)\)\)return;/);
assert.match(panel,/undoToast\(changes\.workflow_state==='cancelled'\?'Task cancelled':note\?'Task saved · update added':'Task saved'/);
assert.match(src,/stateSelect\.onchange=\(\)=>perform\(async\(\)=>\{if\(stateSelect\.value==='cancelled'&&!\(await ask\('Cancel this task\?/);
assert.match(src,/A merge cannot be undone\.',\{ok:'Merge',danger:true\}\)\)\)return;await api\('\/api\/items\/'\+item\.id\+'\/merge'/);
assert.match(src,/danger:action\.value==='workflow_state'&&value\.value==='cancelled'\}\)\)\)return;/);
// Other changes: a result message with Undo.
assert.match(src,/undoToast\('Saved',\(\)=>perform\(async\(\)=>\{await api\('\/api\/items\/'\+saved\.id,\{text:saved\.text,revision:saved\.revision,changes:\{text:item\.text\}\}\)/);
assert.match(src,/finished\?changeWithUndo\(item,\{workflow_state:'todo'\},'Reopened: '\+item\.text,\{workflow_state:'done'\}\)/);
console.log('Risky confirmations and Undo PASS: cancel and merge ask first, saves and reopen offer Undo, Undo restores only changed fields.');
