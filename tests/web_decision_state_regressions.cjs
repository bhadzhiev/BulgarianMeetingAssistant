const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8');
const slice=(a,b)=>{const at=app.indexOf(a);assert.notEqual(at,-1,a);return app.slice(at,app.indexOf(b,at));};

// One badge per decision; the review state is part of it, never a second badge beside "Accepted".
const c=vm.createContext({el:(tag,cls,text)=>({tag,cls,text})});
vm.runInContext(slice('const DECISION_LABELS=','function decisionBadge(')+slice('function decisionBadge(','\n'),c);
const state=item=>JSON.parse(JSON.stringify(vm.runInContext('decisionState',c)(item)));
assert.deepEqual([state({status:'accepted',review_state:'confirmed'}).label,state({status:'accepted',review_state:'confirmed'}).action],['Accepted',null]);
assert.deepEqual([state({status:'accepted',review_state:'needs_review'}).label,state({status:'accepted',review_state:'needs_review'}).action],['Accepted · check again','Confirm decision']);
assert.equal(state({status:'accepted',review_state:'edited'}).cls,'recheck');
assert.deepEqual([state({status:'proposed',review_state:'needs_review'}).label,state({status:'proposed',review_state:'needs_review'}).action],['Proposed','Accept decision']);
assert.deepEqual([state({status:'superseded',review_state:'needs_review'}).label,state({status:'superseded'}).action],['Replaced',null]);
assert.equal(state({status:'accepted',review_state:null}).label,'Accepted');
// A decision hidden in My Work asks for nothing in the notes or in Needs attention.
assert.deepEqual([state({status:'accepted',review_state:'needs_review',dismissed:true}).label,state({status:'proposed',dismissed:true}).action],['Hidden in My Work',null]);

// The notes and My Work use the single badge; neither adds the separate review badge for a decision.
const notes=slice('function noteSection(','\nfunction ');
assert.match(notes,/if\(decision\) meta\.append\(decisionBadge\(decision\)\)/);
assert.match(notes,/meta\.append\(decision\?'':reviewBadge\(item,busy\)/);
const row=slice('function decisionRow(','async function loadTasks(');
assert.match(row,/meta\.append\(decisionBadge\(item\)\)/);assert.doesNotMatch(row,/workReviewBadge/);

// Needs attention counts with the same state and names both cases in plain words.
const attention=slice('// The same state as the decision badges','// Each meeting type asks');
assert.match(attention,/decisionState\(item\)\.cls/);
assert.match(attention,/'Accept '\+AtlantaUX\.count\(proposedDecisions,'decision'\)\+' that the AI proposed'/);
assert.match(attention,/'Check '\+AtlantaUX\.count\(recheckDecisions,'accepted decision'\)\+' again after a change'/);
assert.doesNotMatch(app,/'Confirm '\+decisions\+/);
console.log('Decision state PASS: one badge, Accepted · check again, Proposed, Needs attention uses the same state.');
