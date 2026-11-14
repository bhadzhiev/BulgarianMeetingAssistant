const fs=require('node:fs'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8'),html=fs.readFileSync('web/index.html','utf8');
const slice=(a,b='\n}\n')=>{const at=app.indexOf(a);assert.notEqual(at,-1,a);return app.slice(at,app.indexOf(b,at));};
// Team: its own entry under My Work, two tabs, and a route.
assert.ok(html.indexOf('id="open-team"')>html.indexOf('id="open-tasks"')&&html.indexOf('id="open-team"')<html.indexOf('id="open-conversations"'));
assert.match(html,/data-team-tab="members">My team<\/button><button role="tab" data-team-tab="reviews">Reviews<\/button>/);
assert.match(app,/else if\(view==='team'\)\{q\.set\('view','team'\);if\(teamHistoryPersonId\)q\.set\('person',teamHistoryPersonId\);if\(teamReviewId\)q\.set\('review',teamReviewId\);else if\(teamTab!=='members'\)q\.set\('tab',teamTab\);\}/);
assert.match(app,/else if\(target==='team'\)\{const review=q\.get\('review'\);/);
assert.match(app,/for\(const id of \['setup','recording','detail','tasks','team',/);
// Members: active and former, a project filter, a clear empty screen, and leave/rejoin in the … menu.
const render=slice('function renderTeam(){');
assert.match(render,/m\.active===\(teamStatus==='active'\)&&\(!project\|\|m\.project_ids\.includes\(project\)\)/);
assert.match(render,/'Your team is empty'/);assert.match(render,/Adding a person starts no analysis/);
const card=slice('function teamCard(member,person){');
assert.match(card,/'Leave the team…'/);assert.match(card,/'Rejoin the team…'/);assert.match(card,/'team period'/);
// A change sends the person revision and replaces the local People list.
assert.match(app,/api\('\/api\/team\/membership',\{id:chosen\.id,revision:/);
assert.match(app,/state\.people=result\.people;teamData=result\.team;/);
console.log('Team PASS: navigation, tabs, route, active/former, project filter, leave and rejoin.');
