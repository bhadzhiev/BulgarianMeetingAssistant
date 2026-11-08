const fs=require('node:fs'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8');
const slice=(a,b='\n}\n')=>{const at=app.indexOf(a);assert.notEqual(at,-1,a);return app.slice(at,app.indexOf(b,at));};
// Actions and goals: saved by the manager, editable after Finalize; an action can start a task draft.
const card=slice('function agreementsCard(r,drafts={}){');
assert.match(card,/'Only what you save here counts\./);
assert.match(card,/api\('\/api\/team\/review\/agreements',\{id:r\.id,revision:teamReview\.revision,agreements:rows\.filter\(x=>x\.text\.trim\(\)\)\}\)/);
assert.match(slice('function agreementRow('),/openManualTask\(null,\{text:row\.text,owner:row\.owner==='person'\?person:'',due:row\.due_date\|\|''\}\)/);
assert.match(app,/async function openManualTask\(meetingId=null,\{text:startText='',owner:startOwner='',due:startDue=''\}=\{\}\)\{/);
// The last 1:1: each action and goal with its state, saved to that review.
assert.match(slice('function previousAgreementsCard(previous,drafts={}){'),/api\('\/api\/team\/review\/agreements',\{id:previous\.review_id,revision:previous\.revision,agreements:rows\}\)/);
// Delete is explicit, names what goes and that archives keep their copies.
const page=slice('function renderTeamReview(){');
assert.match(page,/'Delete review…'/);
assert.match(page,/This cannot be undone\. Earlier backup archives keep their copies until you delete them\./);
assert.match(page,/agreementsCard\(r,drafts\)/);
// Unsaved actions and goals block navigation; the export has them.
assert.match(app,/'team-agreements':'actions and goals'/);
assert.match(slice('function exportTeamReview(r){'),/## Agreed actions and goals/);
console.log('Team protect PASS: actions and goals, last 1:1, delete, export.');
