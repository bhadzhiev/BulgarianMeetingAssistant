const fs=require('node:fs'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8'),css=fs.readFileSync('web/style.css','utf8');
const slice=(a,b='\n}\n')=>{const at=app.indexOf(a);assert.notEqual(at,-1,a);return app.slice(at,app.indexOf(b,at));};
// P02: the editor opens with the main fields; the rest is in sections that name their filled values.
const panel=slice('async function openTaskPanel(');
assert.match(panel,/core\.append\(label\('Owner',owner\),label\('Task state',workflow\),label\('Due date',due\)\);/);
assert.match(panel,/section\('Details',label\('Details',details\)\),peopleSection=section\('People and follow-up',coField,people\),sourcesSection=section\('Sources and GitHub'\),historySection=section\('History'\)/);
assert.match(panel,/box\.append\(label\('Task',area\),core,[^;]*label\('Add an update',update\),label\('Evidence for this update',updateEvidence\),detailsSection,peopleSection,sourcesSection,historySection,footer\);/);
// A set follow-up date or a waiting task keeps the follow-up beside the main fields; a set expected result shows at once.
assert.match(panel,/const placeFollow=\(\)=>\{if\(follow\.value\|\|workflow\.value==='waiting'\)core\.append\(followField\);else people\.append\(followField\);\};/);
assert.match(panel,/const placeCriterion=\(\)=>\{if\(item\.completion_criteria\)core\.after\(criterionField\);else detailsSection\.append\(criterionField\);\};/);
// An error opens its section; Timeline opens History.
assert.match(panel,/if\(part\.querySelector\(':invalid,\[aria-invalid=true\]'\)\)part\.open=true;/);
assert.match(panel,/historySection\.open=true;timeline\.scrollIntoView/);
assert.match(css,/#task-panel \.task-section\[open\]>summary \.task-section-summary\{display:none\}/);
// P03: the compact list is the default view; the cards stay as the other view.
assert.match(app,/localStorage\.getItem\('task-density'\)==='cards'\?'cards':'compact'/);
assert.match(slice('function renderBulkTasks(){'),/\[\['compact','Compact'\],\['cards','Cards'\]\]/);
const row=slice('function globalTaskRow(');
assert.match(row,/compactMenu=\[addUpdate,timeline,nextCheck\];/);assert.match(row,/if\(!showProject\)chips\.replaceChildren\(\);/);
assert.match(row,/if\(compactMenu\)actions\.prepend\(\.\.\.compactMenu\);/);
// Selection starts on request in the compact view.
assert.match(app,/select:!compact\|\|taskSelecting\|\|taskSelection\.size>0,showProject:!project\.value/);
assert.match(slice('function renderBulkTasks(){'),/taskSelecting\?'Done selecting':'Select tasks'/);
// A narrow window: the title on top, the owner on its own line, then state and due date.
assert.match(css,/\.tracked-task\.task-card\.compact-task \.task-quick-fields>label:first-child\{grid-column:1 \/ -1\}/);
// The calendar button inside the task menu does not close the menu.
assert.match(app,/\.task-more>\.tracked-actions>button'\)\)closeMenus\(\)/);
console.log('Compact tasks PASS: short editor with sections, compact list by default, cards view, selection on request, narrow rows.');
