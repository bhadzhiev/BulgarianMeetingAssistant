const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8'),html=fs.readFileSync('web/index.html','utf8');
const slice=(a,b)=>{const at=app.indexOf(a);assert.notEqual(at,-1,a);return app.slice(at,app.indexOf(b,at));};
// The same rule as the server: accepted, visible tasks without a description.
{
 const c=vm.createContext({});vm.runInContext(slice('function untitledTask(','\nlet taskTitleRun'),c);const f=vm.runInContext('untitledTask',c);
 assert.equal(f({kind:'task',text:'Да провери бекъпа',acceptance_state:'accepted'}),true);
 assert.equal(f({kind:'task',text:'Да провери бекъпа',acceptance_state:'proposed'}),false,'a proposal is never sent');
 assert.equal(f({kind:'task',text:'Да провери бекъпа',dismissed:true}),false,'a hidden task is never sent');
 assert.equal(f({kind:'task',text:'Бекъп',details:'Пълен бекъп'}),false);
 assert.equal(f({kind:'decision',text:'Решение'}),false);
}
// My Work shows the button only while such tasks exist, with their count.
assert.match(slice('function renderTasks() {','\n}'),/const untitled=\(itemsData\.items\|\|\[\]\)\.filter\(untitledTask\)\.length;\$\('task-titles-open'\)\.hidden=!untitled;/);
assert.match(html,/<button id="task-titles-open" type="button" class="secondary" hidden>Add titles<\/button>/);
// The dialog says what goes where before anything is sent, and nothing changes until Apply.
assert.match(html,/Nothing changes until you apply the titles you keep\./);
assert.match(app,/'Atlanta sends the text of '\+AtlantaUX\.count\(preview\.count,'task'\)/);
assert.match(app,/api\('\/api\/task-titles\/start',\{approved:true,preview_token:taskTitlePreview\.preview_token\}\)/);
assert.match(app,/filter\(t=>t\.check\.checked&&t\.title\.value\.trim\(\)\)\.map\(t=>\(\{id:t\.row\.id,revision:t\.row\.revision,text:t\.row\.text,title:t\.title\.value\.trim\(\)\}\)\)/);
// Closing the dialog stops a run that still writes titles.
assert.match(app,/\$\('task-titles-dialog'\)\.addEventListener\('close',\(\)=>\{if\(taskTitleRun\)api\('\/api\/task-titles\/cancel'/);
// The meeting task does not repeat its old wording when it is the description now.
assert.match(slice('function taskRow(','function renderNotes('),/if\(item&&item\.text!==task\.task&&String\(item\.details\|\|''\)\.trim\(\)!==task\.task\.trim\(\)\)/);
console.log('Task titles PASS: same rule as the server, approved start, apply only kept titles, no repeated wording.');
