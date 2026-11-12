const fs=require('node:fs'),assert=require('node:assert/strict'),Tasks=require('../web/task-model.js');
const app=fs.readFileSync('web/app.js','utf8'),css=fs.readFileSync('web/style.css','utf8');
// Tasks by owner: the order of first appearance, one owner for other letter case, no owner last.
const groups=[{task:{task:'A',owner:'Ана'}},{task:{task:'B',owner:null}},{task:{task:'C',owner:'Борис'}},{task:{task:'D',owner:'ана '}}];
const owners=Tasks.ownerGroups(groups,({task})=>task.owner);
assert.deepEqual(owners.map(o=>[o.owner,o.groups.map(g=>g.task.task)]),[['Ана',['A','D']],['Борис',['C']],['',['B']]]);
assert.deepEqual(Tasks.ownerGroups([],g=>g).map(o=>o.owner),[]);
// The linked task's owner wins over what the notes said, and one owner needs no headings.
assert.match(app,/AtlantaTasks\.ownerGroups\(shown,\(\{task\}\)=>detail\.items\?\.\[task\.item_id\]\?\.owner\|\|task\.owner\)/);
assert.match(app,/if\(owners\.length>1\)\{const head=el\('h4','owner-group'\)/);
// The overview: named speakers only, the counts open the tasks and decisions.
assert.match(app,/function notesOverview\(minutes\)/);
assert.match(app,/filter\(name=>name&&!\/\^SPEAKER\[ _-\]\?\\d\+\$\/i\.test\(name\)\)/);
assert.match(app,/'open question'\]\]/);
assert.match(app,/holds\.onclick=\(\)=>switchTab\('outcomes'\)/);
assert.match(app,/if\(!notesEditing\)\$\('notes'\)\.append\(notesOverview\(minutes\)\)/);
assert.match(app,/'AI notes from the recording of '\+date\(detail\.created\)\+'\. Each point links to the moment it comes from\./);
for(const name of ['.notes-overview','.owner-group','.notes-footer'])assert.ok(css.includes(name),name+' is styled');
console.log('Notes overview PASS: who was present, counts, tasks by owner and the source note.');
