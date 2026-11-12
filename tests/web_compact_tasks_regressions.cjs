const fs=require('node:fs'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8'),css=fs.readFileSync('web/style.css','utf8');
const slice=(a,b='\n}\n')=>{const at=app.indexOf(a);assert.notEqual(at,-1,a);return app.slice(at,app.indexOf(b,at));};
// P02, changed 2026-11-12: one fixed order. What the task is, then who and when, then progress; rare people fields in a section.
const panel=slice('async function openTaskPanel(');
assert.match(panel,/core\.append\(label\('Owner',owner\),label\('State',workflow\),label\('Project',project\),label\('Due date',due\),label\('Next follow-up',follow\)\);/);
assert.match(panel,/const peopleSection=section\('More people',coField,people\),sourcesSection=section\('Sources and GitHub'\),historySection=section\('History'\);/);
assert.match(panel,/box\.append\(label\('Title',area\),label\('Description',details\),label\('Expected result',criterion\),core,[^;]*progress,peopleSection,sourcesSection,historySection,footer\);/);
// No field moves: the follow-up date and the expected result keep one place, and the evidence choice shows only when there is evidence.
assert.doesNotMatch(panel,/placeFollow|placeCriterion|detailsSection/);
assert.match(panel,/if\(evidenceRows\.length\)progress\.append\(label\('Evidence for this update',updateEvidence\)\);/);
// The heading names the action; the title shows once, in its field.
assert.match(panel,/el\('h2','task-card-title',item\.acceptance_state==='proposed'\?'Proposed task':'Edit task'\)/);
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
console.log('Compact tasks PASS: fixed editor order, compact list by default, cards view, selection on request, narrow rows.');
