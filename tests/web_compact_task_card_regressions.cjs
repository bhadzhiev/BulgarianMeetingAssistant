const fs=require('node:fs'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8'),css=fs.readFileSync('web/style.css','utf8');
const row=app.slice(app.indexOf('function globalTaskRow('),app.indexOf('function taskDescription('));
// The editor names the two text fields Title and Description.
// Since 2026-11-12 the description is always visible, under the title, in the editor and in the new task dialog.
assert.match(app,/box\.append\(label\('Title',area\),label\('Description',details\),label\('Expected result',criterion\),improveRow,core,/);
assert.match(app,/box\.append\(label\('Title',text\),label\('Description',details\),grid,actions\);/);
assert.match(row,/label\('Owner',owner\),label\('State',stateSelect\),label\('Due date',due\)/);
// The compact card: title, then the labelled fields with the owner's avatar, then the flags with the Emailed word.
assert.match(row,/const ownerField=quick\.firstElementChild;ownerField\.classList\.add\('compact-owner'\);owner\.before\(avatar\(item\.owner\|\|''\)\);/);
assert.match(row,/main\.replaceChildren\(head,quick,\.\.\.\(flags\.childNodes\.length\?\[flags\]:\[\]\)\);/);
assert.match(row,/const mailedFlag=emailMark\(item\);if\(mailedFlag\)flags\.append\(mailedFlag\);/);
assert.match(css,/:is\(#task-list,\.task-rows\)\.compact-list>\.tracked-task\.task-card\.compact-task\{margin:0 0 10px;padding:16px 18px;border:1px solid var\(--line\);border-radius:14px/);
assert.match(css,/\.compact-owner>\.speaker-badge\{position:absolute;/);
assert.match(css,/\.compact-flags>\.email-mark\{margin-left:auto;/);
console.log('Compact task card PASS: Title and Description labels, labelled fields with avatar, flags after the fields.');
