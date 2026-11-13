const fs=require('node:fs'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8'),html=fs.readFileSync('web/index.html','utf8'),css=fs.readFileSync('web/style.css','utf8');
// A tab of its own, private, after Notes (2026-11-13).
assert.match(html,/<button id="tab-notes"[^>]*>Notes<\/button><button id="tab-team" role="tab" aria-selected="false">Team analysis<\/button>/);
assert.match(html,/<div id="team-analysis-panel" class="card" hidden>.*PRIVATE · NOT IN NOTES OR EXPORTS.*<button id="team-analysis-run"/);
assert.match(app,/\['team','team-analysis-panel'\]/);
assert.match(app,/\['review','outcomes','notes','team','analytics'\]\.includes\(tab\)/);
assert.match(app,/renderNotes\(busy\); renderTeamAnalysis\(busy\);/);
// The four parts of the analysis, in the order that the person asked for.
const order=['Work behavior by person','Communication and team dynamics','Discourse: words, wording and implied meanings','Coaching: your management practice'].map(t=>app.indexOf("teamSection('"+t+"'"));
assert.ok(order.every(i=>i>0)&&order.every((v,i)=>!i||v>order[i-1]),'sections in order');
assert.match(app,/\[\['ownership','Ownership'\],\['proactivity','Proactivity'\],\['reporting','Reporting'\]\]/);
assert.match(app,/\[\['keep','Keep'\],\['change','Change'\],\['develop','Develop'\]\]/);
// One confirmed Analyze: the dialog names the model and the size, and the unnamed speakers.
assert.match(app,/await api\('\/api\/team-analysis\/preview',\{meeting_id:meetingId\}\)/);
assert.match(app,/if\(!\(await ask\('Analyze the team in this meeting\?/);
assert.match(app,/'Not named yet: '\+preview\.unnamed\.join/);
assert.match(app,/await api\('\/api\/team-analysis\/generate',\{meeting_id:meetingId,self_name:state\.settings\.self_name\|\|''\}\)/);
// The person chooses their own name among the speakers; unnamed speakers get a warning; a stale analysis says so.
assert.match(app,/await api\('\/api\/settings',\{self_name:select\.value\}\)/);
assert.match(app,/'Name the speakers first: '/);
assert.match(app,/The transcript changed after this analysis\./);
assert.match(app,/if\(row\.evidence_timestamp\)li\.append\(stampButton\(row\.evidence_timestamp\)\)/);
assert.match(app,/in two steps: the people, then the team and the coaching\. A thinking model can take up to 20 minutes for each step\./);
for(const name of ['.team-person','.team-observations','.team-section'])assert.ok(css.includes(name),name+' is styled');
console.log('Team analysis PASS: private tab, four sections, one confirmed Analyze, own name, moments.');
