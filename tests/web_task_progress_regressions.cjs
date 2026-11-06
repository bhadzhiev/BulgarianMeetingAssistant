const assert=require('node:assert/strict'),P=require('../web/task-progress.js');
assert(P.mismatch('todo','closed').includes('stays open'));assert(P.mismatch('done','open').includes('Review'));assert.equal(P.mismatch('done','closed'),'');assert.equal(P.mismatch('waiting','open'),'');
assert(P.after({at:'2026-11-06T10:00:00+02:00'},'2026-11-06T07:59:00Z'));assert(!P.after({at:null},'2026-01-01'));assert(!P.after({at:'bad'},'2026-01-01'));
assert.equal(P.label({kind:'publication_unknown'}),'Publication outcome unknown — check before retrying');assert.equal(P.label({kind:'github_cross_referenced'}),'Related issue / PR');assert(P.label({kind:'publication_approved'}).includes('prepared'));
console.log('Task progress PASS: timeline vocabulary, timezone boundaries and explicit local/remote mismatch semantics.');
