const fs=require('node:fs'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8'),css=fs.readFileSync('web/style.css','utf8');
const row=app.slice(app.indexOf('function globalTaskRow('),app.indexOf('function taskDescription('));
// The editor names the two text fields Title and Description.
// Since 2026-11-12 the description is always visible, under the title, in the editor and in the new task dialog.
assert.match(app,/box\.append\(label\('Title',area\),label\('Description',details\),label\('Expected result',criterion\),improveRow,core,/);
assert.match(app,/parts\.push\(label\('Title',text\),label\('Description',details\),label\('Expected result',criterion\),grid\);/);
assert.match(app,/parts\.push\(status,note,actions\);box\.append\(\.\.\.parts\);/);
// The list is read-only; the title and Open task action open the full editor.
assert.match(row,/ownerFact=el\('span','task-fact owner-fact'\)/);
assert.match(row,/actionBtn\('quiet task-open','Open task',\(\)=>openTaskPanel\(item.id\)\)/);
assert.doesNotMatch(row,/task-quick-fields|stateSelect|rowActions/);
assert.match(row,/if\(mailed\)titleLine\.append\(mailed\)/);
assert.match(css,/\.task-title-line>\.email-mark\{flex:none;/);
console.log('Compact task list PASS: one editor, read-only facts and a stable saved-email mark.');
