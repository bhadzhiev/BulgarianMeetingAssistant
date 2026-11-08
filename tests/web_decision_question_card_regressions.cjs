const fs=require('node:fs'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8'),css=fs.readFileSync('web/style.css','utf8');
const slice=(a,b)=>{const at=app.indexOf(a);assert.notEqual(at,-1,a);return app.slice(at,app.indexOf(b,at));};
// A decision: the shared card; only the waiting action is visible, Mark as proposed and Restore are in the … menu.
const decision=slice('function decisionRow(','async function loadTasks(');
assert.match(decision,/row=el\('div','tracked-task decision entity-card task-card '\+item\.status\)/);
assert.match(decision,/if\(item\.status==='proposed'\)meta\.append\(change\)/);
assert.match(decision,/if\(item\.status!=='proposed'\)menuActions\.prepend\(change\)/);
// Questions: the shared card, a status badge, Mark answered… and Reopen; Edit and Delete share the … menu.
const notes=slice('function renderMeetingQuestions(','\n}\n');
assert.match(notes,/el\('div','entity-card question-card meeting-question'\)/);assert.match(notes,/'Mark answered…'/);
const tracked=slice('function trackedQuestionCard(q){','\n}\n');
// A project shows a tracked question with the same card as My Work.
assert.match(app,/if\(full\.kind==='question'&&byId\[item\.id\]\)return trackedQuestionCard\(full\)/);
assert.match(tracked,/statusBadge\(q\.status==='answered'\?\{tone:'ok',label:'Answered'\}:\{tone:'muted',label:'Open'\}\)/);
assert.match(tracked,/q\.status==='answered'\?'Reopen':'Mark answered…'/);
assert.match(tracked,/menu\.querySelector\('\.menu-items'\)\?\.prepend\(edit\)/);
// The … column has one width and the menu floats: a closed <details> sized an auto column in WebKit.
assert.match(css,/\.tracked-task\.task-card\{display:flex;align-items:flex-start;gap:12px\}/);
assert.match(css,/\.tracked-task\.task-card>\.task-more>\.tracked-actions\{position:absolute;right:0;top:calc\(100% \+ 6px\);z-index:30/);
console.log('Decision and question cards PASS: shared card, waiting action only, Mark answered/Reopen, one … column.');
