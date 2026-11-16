const fs=require('node:fs'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8'),css=fs.readFileSync('web/style.css','utf8');
const row=app.slice(app.indexOf('function globalTaskRow('),app.indexOf('function taskDescription('));
// Accepted list rows have a single editor destination, never inline state/owner/date mutations.
assert.doesNotMatch(row,/stateSelect|openTaskField|task-quick-fields|ownerFact\.onclick|dueFact\.onclick|stateFact\.onclick/);
assert.match(row,/meta\.append\(ownerFact,stateFact,priorityBadge,dueFact\)/);
// Missing descriptions or sources do not move the other control into its slot.
assert.match(row,/control\.classList\.add\('task-description-control'\)/);
assert.match(row,/control\.classList\.add\('task-sources-control'\)/);
assert.match(css,/\.task-list-row \.task-description-control\{grid-column:1;grid-row:1\}/);
assert.match(css,/\.task-list-row \.task-sources-control\{grid-column:2;grid-row:1\}/);
assert.match(css,/grid-template-columns:190px 80px 80px minmax\(160px,1fr\) 64px/);
assert.match(css,/border-bottom:1px solid color-mix\(in srgb,var\(--ink\) 9%,transparent\)/);
assert(row.indexOf("main.append(box)")<row.indexOf('main.append(panels)'),'updates and expanded context remain inside the row');
assert.match(css,/task-list-row>.tracked-main\{width:auto;/,'content does not inherit the legacy selection-column width');
assert.match(css,/compact-task\.task-list-row:has\(\.task-pick\)\{grid-template-columns:24px minmax\(0,1fr\) 28px\}/,'selection preserves a real content column');
console.log('Flat task list PASS: read-only facts, aligned tracks and disclosure slots, complete-row dividers and selection sizing.');
