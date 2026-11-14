const fs=require('node:fs'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8'),html=fs.readFileSync('web/index.html','utf8');
// One name for the queue everywhere: the view, the heading and the hints all say Inbox.
assert.match(app,/\['inbox','Inbox'\]/,'the task view is called Inbox');
assert.match(app,/el\('h2','','Inbox'\)/,'the screen heading is Inbox');
assert.doesNotMatch(app,/Proposed actions/,'the old heading is gone');
assert.match(app,/This may be an existing task\. It waits in My Work → Inbox\./);
// The dead Suggestions tab and its panel are gone; old routes and buttons land in the Inbox view.
assert.doesNotMatch(html,/data-work-tab="suggested"/,'no hidden Suggestions tab');
assert.doesNotMatch(html,/id="work-suggested"/,'no vestigial suggested panel');
assert.match(app,/function openTaskInbox\(\)\{managerView='inbox';store\('manager-view','inbox'\);workTab='task';inboxOnPurpose=true;return \$\('open-tasks'\)\.onclick\(\);\}/);
// My Work opens on All tasks instead of an empty saved Inbox; a link to the Inbox still opens it.
assert.match(app,/if\(managerView==='inbox'&&!inboxOnPurpose&&!waiting\)\{managerView='all';store\('manager-view','all'\);\}inboxOnPurpose=false;/);
// Without AI meeting items the Inbox holds source suggestions, and its words say so.
assert.match(app,/'Suggestions from Gmail, Google Chat and GitHub wait here for your decision\./);
assert.match(app,/'New suggestions arrive after each source sync\.'/);
assert.match(app,/AtlantaUX\.count\(proposalListEl\.children\.length,'suggestion'\)\+' from sources'/);
assert.doesNotMatch(html,/Each task appears once/);
assert.match(app,/if\(q\.get\('tab'\)==='suggested'\)await openTaskInbox\(\)/,'old suggested routes still land in the Inbox');
assert.doesNotMatch(app,/showWorkTab\('suggested'\)/);
assert.ok(!app.includes("$('work-suggested')"),'no code moves proposal lists into the removed panel');
// Two grouped queues: meeting matches and proposed tasks from meetings first, then source suggestions.
assert.match(app,/meetingProposalListEl\.append\(meetingMatchCard/,'meeting matches render in the meetings queue');
assert.match(app,/el\('h3','work-section','From meetings · '\+/);
assert.match(app,/el\('h3','work-section','From connected sources · '\+/);
assert.match(html,/id="meeting-proposal-list"/);
// "This is me" does not apply to the Inbox.
assert.match(app,/label\.hidden=managerView==='inbox'/);
console.log('Inbox structure PASS: one name, two grouped queues, dead Suggestions tab gone, old routes keep working.');
