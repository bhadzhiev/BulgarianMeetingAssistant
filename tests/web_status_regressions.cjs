const fs=require('node:fs'),assert=require('node:assert/strict');
const Status=require('../web/status.js'),source=fs.readFileSync('web/app.js','utf8'),page=fs.readFileSync('web/index.html','utf8');
// Each group answers one question; one state name never means two things.
assert.deepEqual(Object.keys(Status.GROUPS),['storage','review','external','verification']);
for(const group of Object.values(Status.GROUPS))for(const [label,tone] of Object.values(group))assert(label&&['ok','warn','danger','muted'].includes(tone));
assert.equal(Status.label('storage','saved'),'Saved on this Mac');assert(page.includes(Status.label('storage','saved')));
assert.equal(Status.publication({state:'failed',result:{offline:true}}).label,'Offline — will not retry without approval');
assert.equal(Status.publication({state:'failed',result:{status:403}}).label,'Not sent');
assert.equal(Status.publication({state:'verified',result:{}}).group,'verification');
for(const state of ['approved','sending','unknown','created','failed','cancelled','abandoned'])assert.equal(Status.publication({state,result:{}}).group,'external');
assert.equal(Status.verification({verification:'github'}).label,'Verified');assert.equal(Status.verification({verification:'offline'}).tone,'warn');assert.equal(Status.verification({}).state,'unchecked');
assert.throws(()=>Status.status('review','maybe'));
// A second top-level declaration silently replaces the first one in the browser.
const names=[...source.matchAll(/^(?:async )?function (\w+)\(/gm)].map(m=>m[1]),seen=new Set(),duplicates=names.filter(n=>seen.has(n)||!seen.add(n));
assert.deepEqual(duplicates,[]);
// Labels come from the vocabulary, not from literals in app.js.
for(const literal of ["'Needs review'","'Edited · needs confirmation'","'Outcome unknown","'Verified in GitHub"])assert(!source.includes(literal),literal);
console.log('Status regression PASS: one vocabulary, separate groups, no duplicate functions.');
