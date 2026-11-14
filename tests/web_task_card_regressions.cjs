const fs=require('node:fs'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8');
const row=app.slice(app.indexOf('function globalTaskRow('),app.indexOf('function decisionRow('));
// The quick fields start closed, open with one button, and stay open after the refresh that a save causes.
assert.match(app,/const openTaskFields=new Set\(\);\nfunction globalTaskRow\(/);
assert.match(row,/quick\.hidden=!openTaskFields\.has\(item\.id\)/);
assert.match(row,/toggle\.textContent=open\?'Hide quick fields':'Quick fields'/);
assert.match(row,/toggle\.setAttribute\('aria-expanded',String\(open\)\)/);
assert.match(row,/if\(open\)openTaskFields\.add\(item\.id\);else openTaskFields\.delete\(item\.id\)/);
// Mark done, Add update, Timeline and Edit stay on the card; only the fields open with Edit.
assert.match(row,/rowActions\.append\(done,addUpdate\)/);
assert.doesNotMatch(row,/fieldActions/);
// An owner name without a People entry says so in plain words.
assert.match(row,/' · not in People'/);assert.doesNotMatch(row,/current name/);
// A matching People entry is selected instead of a second option with the same name; Undo restores the plain name.
assert.match(row,/const ownerPerson=!oldOwner&&item\.owner\?personFor\(item\.owner\):null/);
assert.match(row,/if\(!oldOwner&&item\.owner&&!ownerPerson\)/);
assert.match(row,/ownerUndo=item\.owner_person_id\?\{owner_person_id:item\.owner_person_id\}:item\.owner\?\{owner_person_id:null,owner:item\.owner\}/);
console.log('Task card PASS: fields closed by default, one toggle, open state kept, plain owner label.');
