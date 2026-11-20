const fs=require('node:fs'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8');
const row=app.slice(app.indexOf('function globalTaskRow('),app.indexOf('function taskDescription('));
assert.doesNotMatch(row,/task-quick-fields|openTaskFields|stateSelect|editFact|stateFact.onclick|ownerFact.onclick|dueFact.onclick/);
// The one direct change on a card (2026-11-19): the round Mark done control, with Undo in the toast.
assert.match(row,/compactAction\(doneButton\(item\),finished\?'check':'circle'\)/);
for(const field of ['stateFact','dueFact','ownerFact'])assert.match(row,new RegExp(field+"=el\\('span'"));
assert.match(row,/meta\.append\(stateFact,priorityBadge,ownerFact\)/);
assert.match(row,/const title=actionBtn\([^\n]+openTaskPanel\(item.id\)/);
assert.match(row,/'Open task',\(\)=>openTaskPanel\(item.id\)/);
assert.match(row,/actions\.prepend\(timeline\)/);
console.log('Task list PASS: static facts, one task editor, no inline mutations, timeline remains accessible.');
