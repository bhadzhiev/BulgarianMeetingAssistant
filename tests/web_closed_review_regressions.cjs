const fs=require('node:fs'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8');
// A closed task shows its state but never counts as waiting for a review, and has no review badge.
assert.match(app,/const waiting=item=>\['needs_review','edited'\]\.includes\(item\.state\)&&!item\.closed,open=data\.items\.filter\(waiting\)\.length;/);
assert.match(app,/review-card'\+\(waiting\(item\)\?' review-pending':''\)/);
assert.match(app,/function workReviewBadge\(state,item\)\{return \['needs_review','edited'\]\.includes\(state\)&&!\(item&&item\.kind==='task'&&\(item\.status==='done'\|\|\['done','cancelled'\]\.includes\(item\.workflow_state\)\)\)/);
assert.equal((app.match(/workReviewBadge\(item\.review_state,item\)/g)||[]).length,3);
console.log('Closed review PASS: closed tasks never wait for a review and show no review badge.');
