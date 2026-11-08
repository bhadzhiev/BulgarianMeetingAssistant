const fs=require('node:fs'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8'),html=fs.readFileSync('web/index.html','utf8');
const slice=(a,b='\n}\n')=>{const at=app.indexOf(a);assert.notEqual(at,-1,a);return app.slice(at,app.indexOf(b,at));};
// The dialog states the attribution rules and runs no AI.
assert.match(html,/Merging is not authorship\. Release and back-merge pull requests count once\. GitHub never adds to the task counts\. No AI runs\./);
// Discovery first; every repository starts checked and can be cleared; limitations show.
const open=slice('async function openTeamGitHub(r){');
assert.match(open,/api\('\/api\/team\/review\/github\/discover\?id='/);
assert.match(open,/check\.checked=true;check\.onchange=syncGitHubStart/);
assert.match(open,/for\(const text of f\.limitations\)box\.append\(el\('p','notice',text\)\)/);
assert.match(open,/'Collecting GitHub removes the AI part, because it may cite old records\./);
// Only the chosen repositories go to the job; progress with Stop; limitations stay on the review.
assert.match(app,/repositories:\[\.\.\.\$\('team-github-repos'\)\.querySelectorAll\('input:checked'\)\]\.map\(c=>c\.value\)/);
const page=slice('function renderTeamReview(){');
assert.match(page,/'GitHub · '\+ghJob\.status/);assert.match(page,/r\.coverage\?\.github\?\.limitations/);
// An evidence record of GitHub opens on GitHub.
assert.match(app,/github_review:'Review given'/);
assert.match(slice('function evidenceList(r){'),/'Open on GitHub '/);
console.log('Team GitHub PASS: discovery, scope, job, limitations, evidence link.');
