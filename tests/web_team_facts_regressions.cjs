const fs=require('node:fs'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8'),html=fs.readFileSync('web/index.html','utf8');
const slice=(a,b='\n}\n')=>{const at=app.indexOf(a);assert.notEqual(at,-1,a);return app.slice(at,app.indexOf(b,at));};
// The period dialog says what happens: confirmed facts, no AI, nothing sent.
assert.match(html,/Atlanta collects the confirmed facts of the period from meetings, tasks and decisions\. No AI runs and nothing is sent anywhere\./);
const page=slice('function renderTeamReview(){');
// A first draft collects again after a question; a new version keeps its text.
assert.match(page,/actionBtn\('secondary','Refresh facts…',\(\)=>previewTeamFacts\(r\)\)/);
assert.match(slice('async function previewTeamFacts(r){'),/api\('\/api\/team\/review\/apply-collect'/);
// A draft reads like the review; Edit text opens the Markdown. The evidence follows the review.
assert.match(page,/btn\('secondary small-action team-edit-text','Edit text'\)/);
assert.match(page,/body\.append\(evidenceList\(r\)\)/);
assert.match(page,/' excluded from the analysis · '/);
// Each evidence record: id, kind, date, basis, quote, the moment and the work item.
const list=slice('function evidenceList(r){');
assert.match(list,/head\.append\(el\('strong','',e\.id\),el\('span','',EVIDENCE_LABELS\[e\.kind\]\|\|e\.kind\)/);
assert.match(list,/listenButton\(ref\.meeting_id,stampSeconds\(ref\.timestamp\)/);
assert.match(list,/'Open the work item'/);
console.log('Team facts PASS: dialog text, collect again, edit toggle, evidence list.');
