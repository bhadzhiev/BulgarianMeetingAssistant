const fs=require('node:fs'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8'),css=fs.readFileSync('web/style.css','utf8');
const row=app.slice(app.indexOf('function globalTaskRow('),app.indexOf('function taskDescription('));
// Accepted list rows have a single editor destination, never inline state/owner/date mutations.
assert.doesNotMatch(row,/stateSelect|openTaskField|task-quick-fields|ownerFact\.onclick|dueFact\.onclick|stateFact\.onclick/);
assert.match(row,/meta\.append\(stateFact,priorityBadge,ownerFact\)/);
// Compact task cards (2026-11-20): icons, created and due dates with the tools; the project and the title; the last update and opened context; then the facts as plain text.
assert.match(row,/control\.classList\.add\('task-description-control'\)/);
assert.match(row,/control\.classList\.add\('task-sources-control','task-origin','task-link-icon'\)/,'the source icon opens the sources');
assert.match(row,/else if\(!nested\)tags\.append\(missingLink\('video','No linked meeting or source'\)\)/,'a card without sources shows a dimmed source icon');
assert.match(app,/function missingLink\(name,label\)\{const mark=el\('span','task-link-icon inactive'\);mark\.title=label;mark\.setAttribute\('aria-label',label\)/,'a dimmed icon keeps an accessible name');
assert.match(css,/\.task-tile \.task-link-icon\.inactive\{[^}]*opacity:\.6\}/,'missing links are dimmed to 60%');
assert.match(row,/else\{head\.append\(tags,tools\);main\.append\(head,title\);if\(box\)main\.append\(box\);main\.append\(panels,meta\);\}/,'the title stands alone; updates and expanded context stay above the facts line');
assert.match(css,/\.tracked-task\.task-tile\{display:grid;grid-template-columns:28px minmax\(0,1fr\);/);
assert.doesNotMatch(css,/\.task-tile-facts\{[^}]*border-top/,'no divider above the facts');
assert.match(row,/if\(!nested\)\{if\(item\.created[^\n]*tags\.append\(dueFact\);\}/,'the due date sits after the created date in the head');
assert.match(css,/\.task-tile-facts>\*\+\*::before\{content:'·'/,'dots separate the plain-text facts');
// The round control is the labelled Mark done button with Undo; selection replaces it while tasks are selected.
assert.match(row,/const finished=item\.status==='done',done=compactAction\(doneButton\(item\),finished\?'check':'circle'\);done\.classList\.add\('task-done-toggle'\)/);
console.log('Task card list PASS: read-only facts, origin and description controls, due date in the head, plain-text facts, Mark done circle.');
