const fs=require('node:fs'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8');
// After the daily shows the rows that ask for an action first; other status lines wait under Context (2026-11-25).
const at=app.indexOf("const acts=row=>");assert.notEqual(at,-1);
const acts=eval(app.slice(at+'const acts='.length,app.indexOf(';',at)));
assert.equal(acts({field:'tasks'}),true);assert.equal(acts({field:'blockers'}),true);assert.equal(acts({field:'needs_decision'}),true);assert.equal(acts({field:'decisions'}),true);
assert.equal(acts({field:'updates',task_match:'t1'}),true,'an update that names an open task acts');
assert.equal(acts({field:'updates'}),false);assert.equal(acts({field:'open_questions'}),false);
assert.match(app,/const more=el\('details','daily-context'\);more\.open=!first\.length;/);
assert.match(app,/actionBtn\('quiet small-action','Mark all reviewed',async\(\)=>\{for\(const row of context\)await api\('\/api\/daily\/'\+meeting\.id\+'\/review',\{revision:daily\.revision,key:row\.key,action:'confirm'\}\);/);
assert.match(app,/el\('summary','','Status and context · '\+context\.length\)/);
// The update form preselects the matched task.
assert.match(app,/if\(!target\.value&&daily\.tasks\.some\(task=>task\.id===row\.task_match\)\)target\.value=row\.task_match;/);
console.log('Daily context PASS: action rows first; status lines under Context with Mark all reviewed; the matched task is preselected.');
