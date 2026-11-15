const fs=require('node:fs'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8'),css=fs.readFileSync('web/style.css','utf8');
const row=app.slice(app.indexOf('function globalTaskRow('),app.indexOf('function taskDescription('));
// The editor names the two text fields Title and Description.
// Since 2026-11-12 the description is always visible, under the title, in the editor and in the new task dialog.
assert.match(app,/box\.append\(label\('Title',area\),label\('Description',details\),label\('Expected result',criterion\),improveRow,core,/);
assert.match(app,/parts\.push\(label\('Title',text\),label\('Description',details\),label\('Expected result',criterion\),grid\);/);
assert.match(app,/parts\.push\(status,note,actions\);box\.append\(\.\.\.parts\);/);
assert.match(row,/label\('Owner',owner\),label\('State',stateSelect\),label\('Due date',due\)/);
// The compact card: title/tools, editable facts and on-demand fields. The draft icon stays next to the title.
assert.match(row,/titleLine\.append\(title\);if\(mailed\)titleLine\.append\(mailed\);head\.append\(titleLine,chips\)/);
assert.doesNotMatch(row,/flags\.append\(mailed/);
assert.match(css,/\.task-title-line>\.email-mark\{flex:none;/);
assert.doesNotMatch(css,/\.compact-flags>\.email-mark/);
console.log('Compact task card PASS: Title and Description labels, editable facts, direct tools and compact spacing.');
assert.match(row,/ownerFact=btn\('fact-control owner-fact'\)/);
assert.match(row,/rowActions\.append\(compactAction\(done/);
assert.match(css,/padding:10px 12px;margin:0 0 6px/);
