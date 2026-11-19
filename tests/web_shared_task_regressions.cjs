const fs=require('node:fs'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8');
const slice=(a,b='\n}\n')=>{const at=app.indexOf(a);assert.notEqual(at,-1,a);return app.slice(at,app.indexOf(b,at));};
// The card: the owner and up to three more avatars, "+N", and a Shared badge with the roles in the title.
const row=slice('function globalTaskRow(');
assert.match(row,/const co=taskCoAssignees\(item\),ownerName=item\.owner\|\|'No owner';/);
assert.match(row,/if\(co\.length\)who\.append\(el\('span','task-owner-more','\+'\+co\.length\)\)/);
assert.match(row,/'Owner: '/);assert.match(row,/' · Also working on it: '/);
// The owner filter finds a shared task under each person on it.
assert.match(app,/owners=\[\.\.\.new Set\(tasks\.flatMap\(taskPeopleNames\)\)\]/);
assert.match(app,/taskPeopleNames\(t\)\.includes\(\$\('task-owner'\)\.value\)/);
// The panel: a manual list of the others; the owner is not in it; the whole list goes at once, owner first.
const panel=slice('async function openTaskPanel(');
assert.match(panel,/el\('div','assignee-choices'\)/);
assert.match(panel,/const syncCo=\(\)=>\{for\(const c of coChecks\)\{const own=c\.value===owner\.value;/);
assert.match(panel,/changes\.assignee_person_ids=\[owner\.value,\.\.\.co\]/);
assert.match(panel,/'Choose the owner from People before you add others to the task\.'/);
// History and the timeline name the people of a list change.
assert.match(app,/assignee_person_ids:'Assignees'/);
// The profile shows the shared tasks apart from the commitments.
assert.match(app,/list\('Also working on \(shared tasks\)',profile\.shared,/);
console.log('Shared task PASS: avatars, Shared badge, owner filter, panel list, history, profile.');
