const fs=require('node:fs'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8'),css=fs.readFileSync('web/style.css','utf8');
const row=app.slice(app.indexOf('function globalTaskRow('),app.indexOf('function taskDescription('));
// The editor names the two text fields Title and Description.
// Since 2026-11-12 the description is always visible, under the title, in the editor and in the new task dialog.
// Task forms (2026-11-20): the content on the left, the task parameters on the right, the actions in the footer.
assert.match(app,/box\.append\(taskFormLayout\(\[label\('Title',area\),tabs\.bar,\.\.\.tabs\.panels\],/);
assert.match(app,/describe\.append\(label\('Description',details\),improveRow\)/);
assert.match(app,/\['details','Details',\[describe,label\('Expected result',criterion\),progress,sourcesSection\]\]/);
assert.match(app,/parts\.push\(label\('Title',text\),label\('Description',details\),label\('Expected result',criterion\)\);/);
assert.match(app,/parts\.push\(status,note\);box\.append\(taskFormLayout\(parts,\[grid\]\),actions\);/);
assert.match(app,/function taskFormLayout\(main,side\)\{[^\n]*el\('h3','task-side-title','Task parameters'\)/);
assert.match(css,/\.task-panel-layout\{display:grid;grid-template-columns:minmax\(0,1fr\) 340px;/);
// The list is read-only; the title and Open task action open the full editor.
assert.match(row,/ownerFact=el\('span','task-fact owner-fact'\)/);
assert.match(row,/actionBtn\('quiet task-open','Open task',\(\)=>openTaskPanel\(item.id\)\)/);
assert.doesNotMatch(row,/task-quick-fields|stateSelect|rowActions/);
assert.match(row,/const mailed=emailMark\(item\);if\(mailed\)tags\.append\(mailed\);else if\(!nested\)tags\.append\(missingLink\('mail','No Gmail draft'\)\)/,'the saved-email mark is a tag of the card; a card without a draft shows a dimmed envelope');
assert.match(css,/\.task-title-line>\.email-mark\{flex:none;/);
console.log('Compact task list PASS: one editor, read-only facts and a stable saved-email mark.');
