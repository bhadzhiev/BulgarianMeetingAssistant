const fs=require('node:fs'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8');
const slice=(a,b='\n}\n')=>{const at=app.indexOf(a);assert.notEqual(at,-1,a);return app.slice(at,app.indexOf(b,at));};
// A changed source: a finalized review suggests a new version; a draft suggests Collect again.
const page=slice('function renderTeamReview(){');
assert.match(page,/const changes=r\.source_changes\|\|\[\];/);
assert.match(page,/' changed after this review was collected\.'\+\(r\.status==='finalized'\?' Make a new version to correct it\.':' Collect the facts again to update it\.'\)/);
// A rename shows the current name and the name of the review's time.
assert.match(slice('function reviewPersonName(review){'),/now\+' \(then '\+review\.person_name\+'\)'/);
assert.match(slice('function teamReviewCard(review){'),/reviewPersonName\(review\)\+' · 1:1 review'/);
console.log('Team compare PASS: source changes, rename.');
