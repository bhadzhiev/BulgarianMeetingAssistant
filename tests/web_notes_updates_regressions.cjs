const fs=require('node:fs'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8');
// Updates on work in progress: a notes section like the others, shown only when it has content or in edit mode.
assert.match(app,/decisions:'Decisions',updates:'Updates on work in progress'/);
assert.match(app,/const NOTE_FIELDS=\['summary','decisions','updates',/);
assert.match(app,/if\(minutes\.updates\?\.length\|\|notesEditing\)\$\('outcomes'\)\.append\(noteSection\(minutes,'updates','Updates on work in progress',busy,/);
console.log('Notes updates PASS: updates section in notes, hidden when empty, editable like other items.');
