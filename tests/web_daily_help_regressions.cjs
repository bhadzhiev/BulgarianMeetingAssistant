const fs=require('node:fs'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8');
// A promise to help is separate from the review of a daily line (2026-11-23): the update form stays for a pending line.
assert.match(app,/if\(row\.help\)actions\.append\(el\('span','hint daily-help',row\.help\.state==='promise'\?'You promised to help':'Help provided'\)\);/);
assert.match(app,/if\(row\.help\?\.state==='promise'\)actions\.append\(actionBtn\('secondary small-action','Mark help provided',\(\)=>review\(row,'helped'\)\)\);\n  else if\(row\.quote&&\['tasks','updates','blockers'\]\.includes\(row\.field\)&&row\.state!=='changed'\)\{/);
assert.doesNotMatch(app,/row\.state==='promise'|row\.state==='helped'/);
assert.match(app,/if\(row\.state==='pending'&&row\.field!=='decisions'&&row\.quote&&daily\.tasks\.length\)\{/);
console.log('Daily help PASS: a promise to help keeps the line open for a task update.');
