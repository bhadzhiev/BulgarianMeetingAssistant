const fs=require('node:fs'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8'),css=fs.readFileSync('web/style.css','utf8');
const slice=(a,b)=>{const at=app.indexOf(a);assert.notEqual(at,-1,a);return app.slice(at,app.indexOf(b,at));};
// One meeting card in Library, Projects and Calendar.
assert.match(app,/if\(row\.provider==='meeting'\)\{list\.append\(meetingCard\(\{\.\.\.row,id:row\.external_id\},\{participants:row\.participants,onChange:loadConversations,select:/);
assert.match(app,/for\(const meeting of data\.meetings\)meetingList\.append\(meetingCard\(meeting,\{onChange:loadWorkspace\}\)\)/);
assert.match(app,/for\(const row of daily\)box\.append\(meetingCard\(row,\{variant:'calendar'/);
const card=slice('function meetingCard(','\n}\n');
// "+ Add project" replaces "Unassigned"; one project draws a thin line in its colour.
assert.match(card,/el\('summary','add-project','＋ Add project'\)/);assert.doesNotMatch(card,/Unassigned/);
assert.match(card,/if\(projects\.length===1&&projects\[0\]\.color\)\{card\.classList\.add\('has-project-line'\)/);
// The … menu holds the rare actions; the participant count opens the names; Calendar does not repeat the date.
assert.match(card,/rowMenu\('More actions for '\+m\.title,btn\('quiet','Open meeting'/);
assert.match(card,/el\('summary','',AtlantaUX\.count\(participants\.length,'participant'\)\)/);
assert.match(card,/if\(!compact\)facts\.push\('Meeting',dateTime\(/);
// Done is a manual mark: the menu toggles it through /done and the card shows a Done badge (2026-11-14).
assert.match(card,/btn\('quiet',m\.done\?'Mark as not done':'Mark as done'/);
assert.match(card,/api\('\/api\/meetings\/'\+m\.id\+'\/done',\{done:!m\.done\}\)/);
assert.match(card,/if\(m\.done\)meta\.append\(statusBadge\(\{tone:'ok',label:'Done'\}\)\)/);
assert.match(card,/rowMenu\('More actions for '\+m\.title,[^\n]*,change,done\)/);
// A status shows only when a meeting needs something, always with text.
const status=slice('function meetingStatus(','\n}\n');
assert.match(status,/'Processing stopped'/);assert.match(status,/'Notes need update'/);assert.match(status,/return null;/);
// Shared spacing: 16px inside, 8px between rows, 12px between cards.
assert.match(css,/\.entity-card\{display:flex;align-items:flex-start;gap:12px;padding:16px;margin:0 0 12px;/);
assert.match(css,/\.entity-main\{flex:1;min-width:0;display:flex;flex-direction:column;gap:8px\}/);
console.log('Meeting card PASS: one card in three views, Add project, project line, menu, participants, status, manual Done mark.');
