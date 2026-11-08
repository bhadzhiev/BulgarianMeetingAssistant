const fs=require('node:fs'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8'),html=fs.readFileSync('web/index.html','utf8');
const slice=(a,b='\n}\n')=>{const at=app.indexOf(a);assert.notEqual(at,-1,a);return app.slice(at,app.indexOf(b,at));};
// The Team card: Prepare 1:1, or Open draft when a draft exists; the last finalized review.
const card=slice('function teamCard(member,person){');
assert.match(card,/member\.draft\?actionBtn\('secondary small-action','Open draft'/);
assert.match(card,/'Prepare 1:1',\(\)=>openPrepareReview\(person\)/);
assert.match(card,/'Last 1:1 review · '\+date\(member\.last_finalized\.end\)/);
// The period dialog: Sofia times, [start, end).
assert.match(html,/Until \(not included\)<input id="team-review-end" type="datetime-local" required>/);
assert.match(html,/Times are in Europe\/Sofia\./);
// The review page: a draft is editable; Finalize asks first; a finalized review only gets a new version; notes stay editable.
const page=slice('function renderTeamReview(){');
assert.match(page,/body\.append\(view,text\);\}\n else body\.append\(markdownBlock\(r\.review_md\)\)/);
assert.match(page,/'Finalize this review\? The review text is then fixed\./);
assert.match(page,/if\(r\.status==='finalized'\)actions\.append\(actionBtn\('secondary','New version…'/);
assert.match(page,/api\('\/api\/team\/review\/notes'/);
assert.match(page,/'Discard this draft\? The next period does not change\.'/);
// Unsaved review text and notes block navigation.
assert.match(app,/'team-review':'1:1 review edit','team-notes':'conversation notes'/);
// Reviews: search by person and filter by status; a route opens one review.
assert.match(slice('function renderTeamReviews(){'),/\(!status\|\|r\.status===status\)&&\(!query\|\|reviewPersonName\(r\)\.toLocaleLowerCase\(\)\.includes\(query\)\)/);
assert.match(app,/if\(teamReviewId\)q\.set\('review',teamReviewId\)/);
// Export is a local Markdown file.
assert.match(slice('function exportTeamReview(r){'),/new Blob\(\[text\],\{type:'text\/markdown'\}\)/);
console.log('Team review PASS: Prepare 1:1, period, draft/finalize/version, notes, list, route, export.');
