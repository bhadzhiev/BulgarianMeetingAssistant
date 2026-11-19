const fs=require('node:fs'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8'),css=fs.readFileSync('web/style.css','utf8');
const row=app.slice(app.indexOf('function globalTaskRow('),app.indexOf('function taskDescription('));
// Accepted list rows have a single editor destination, never inline state/owner/date mutations.
assert.doesNotMatch(row,/stateSelect|openTaskField|task-quick-fields|ownerFact\.onclick|dueFact\.onclick|stateFact\.onclick/);
assert.match(row,/meta\.append\(ownerFact,stateFact,priorityBadge,dueFact\)/);
// Task cards (2026-11-19): tags and tools, the title, the last update and opened context, then the facts with the due date on the right.
assert.match(row,/control\.classList\.add\('task-description-control'\)/);
assert.match(row,/control\.classList\.add\('task-sources-control','task-origin'\)/,'the origin chip opens the sources');
assert.match(row,/else\{head\.append\(tags,chips,tools\);main\.append\(head,title\);if\(box\)main\.append\(box\);main\.append\(panels,meta\);\}/,'updates and expanded context stay above the facts line');
assert.match(css,/\.tracked-task\.task-tile\{display:grid;grid-template-columns:28px minmax\(0,1fr\);/);
assert.match(css,/\.task-tile-facts\{display:flex;[^}]*border-top:1px solid var\(--line-soft\)\}/,'a divider separates the content from the facts');
assert.match(css,/\.task-tile-facts>\.due-label\{margin-left:auto\}/,'the due date sits on the right');
// The round control is the labelled Mark done button with Undo; selection replaces it while tasks are selected.
assert.match(row,/const finished=item\.status==='done',done=compactAction\(doneButton\(item\),finished\?'check':'circle'\);done\.classList\.add\('task-done-toggle'\)/);
console.log('Task card list PASS: read-only facts, origin and description controls, facts divider, due date on the right, Mark done circle.');
