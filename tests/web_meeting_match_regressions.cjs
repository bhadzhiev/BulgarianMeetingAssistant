const fs=require('node:fs'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8');
const card=app.slice(app.indexOf('function meetingMatchCard('),app.indexOf('async function graphAction('));
// One main action for each type; link is evidence only.
assert.match(app,/const MATCH_PRIMARY=\{existing_mention:\['link','Link to this task'\],existing_update:\['update','Add the update'\],proposed_change:\['change','Apply the checked changes'\],uncertain:\['link','Link to the chosen task'\]\};/);
// The secondary actions: Link only (when the main one adds more), Other task…, New task (for a task), Reject.
for(const label of ["'Link only'","'Other task…'","'New task'","'Reject'"])assert.ok(card.includes(label),label);
assert.match(card,/if\(m\.field==='tasks'\)actions\.append\(actionBtn\('secondary small-action','New task'/);
// What was said, the evidence, the suggested task with its facts, and why.
assert.match(card,/el\('p','hint','Said in the meeting'\)/);assert.match(card,/el\('blockquote','',ev\.quote\)/);assert.match(card,/'Why: '\+m\.reason/);
// Field changes: unchecked boxes with the current and the proposed value; only the checked ones go.
assert.match(card,/document\.createTextNode\(\(\{owner:'Owner',due_date:'Due date',workflow_state:'State'\}\)\[c\.field\]\+': '\+show\(c\.field,now\)\+' → '\+show\(c\.field,c\.value\)\)/);
assert.doesNotMatch(card,/check\.checked=true/);
// The update text can be edited before it goes to the history.
assert.match(card,/'Update to add to the task history'/);
// Every choice carries the task revision that the person saw.
assert.match(card,/task_id:t\.id,task_revision:t\.revision/);
// The list routes meeting matches to this card, and they use their own endpoint.
assert.match(app,/if\(p\.origin==='meeting_match'&&p\.match\)\{list\.append\(meetingMatchCard\(p,evidence\[p\.evidence_id\]\)\);continue;\}/);
assert.match(card,/graphAction\('meeting-review',/);
// A task in the meeting notes points to For review instead of the old link review.
assert.match(app,/This may be an existing task\. It waits in My Work → For review\./);
assert.match(fs.readFileSync('desktop_app.py','utf8'),/elif path == '\/api\/work\/meeting-review':/);
console.log('Meeting match PASS: one main action per type, evidence and reason, unchecked changes, editable update, revision, own endpoint.');
