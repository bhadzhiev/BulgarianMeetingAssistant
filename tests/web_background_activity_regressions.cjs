const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8');
const slice=(a,b)=>{const at=app.indexOf(a);assert.notEqual(at,-1,a);return app.slice(at,app.indexOf(b,at));};
// A background job of a meeting shows its step and the meeting; an action that a person started wins.
const status={hidden:true,textContent:'',title:''},bar={hidden:true};
const c=vm.createContext({setTimeout,clearTimeout,state:{meetings:[]},answers:[],$:id=>id==='activity'?bar:status});
vm.runInContext('let runningActions=0,activityTimer=null,activityLabel="";const BUSY_DELAY=250;'+slice('let foregroundShown=false','if(typeof document.getElementById')+slice('// The other background jobs','async function perform('),c);
const run=code=>vm.runInContext(code,c);
run('renderBackgroundActivity()');assert.equal(status.hidden,true);
c.state.meetings=[{id:'a',title:'Weekly sync',status:'processing',progress:'Generating notes · part 1 of 2'},{id:'b',title:'Other',status:'ready',title_status:'generating'}];
run('renderBackgroundActivity()');assert.equal(status.hidden,false);assert.equal(status.textContent,'Generating notes · part 1 of 2 · Weekly sync · +1 more');
run('activityLabel="Save settings";foregroundShown=true;paintActivity()');assert.equal(status.textContent,'Save settings · in progress…');
run('runningActions=1;endActivity()');assert.equal(status.textContent,'Generating notes · part 1 of 2 · Weekly sync · +1 more');
c.state.meetings=[{id:'b',title:'Other',status:'ready',title_status:'generating'}];run('renderBackgroundActivity()');assert.equal(status.textContent,'Generating AI title · Other');
c.state.meetings=[];run('renderBackgroundActivity()');assert.equal(status.hidden,true);
// Other jobs (1:1 AI, prompt test, email AI, reports) stay in the same line until their own status ends.
(async()=>{
c.state.meetings=[];
run("trackJob('team-ai',{text:'Preparing the 1:1 with AI · Ana',open:()=>'review'})");assert.equal(status.hidden,false);assert.equal(status.textContent,'Preparing the 1:1 with AI · Ana');
assert.equal(run('backgroundJob.open()'),'review');
c.state.meetings=[{id:'b',title:'Other',status:'ready',title_status:'generating'}];run('renderBackgroundActivity()');assert.equal(status.textContent,'Generating AI title · Other · +1 more');
c.state.meetings=[];run("trackJob('team-ai',null)");assert.equal(status.hidden,true);
// A job with poll() is checked also when its page is closed: new text while it runs, gone at the end.
c.answers=['Email AI is reading a message · step 2',null];
run("trackJob('gmail-ai',{text:'Email AI is reading a message',poll:async()=>answers.shift()})");
await run('pollActivityJobs()');assert.equal(status.textContent,'Email AI is reading a message · step 2');
await run('pollActivityJobs()');assert.equal(status.hidden,true);
// A check that fails keeps the job; five failures in a row remove it.
run("trackJob('repo-report',{text:'Repository report',poll:async()=>{throw new Error('busy');}})");
for(let i=0;i<4;i++)await run('pollActivityJobs()');assert.equal(status.textContent,'Repository report');
await run('pollActivityJobs()');assert.equal(status.hidden,true);
run('clearTimeout(activityJobsTimer)');
// The families that report to the line.
for(const key of ['team-ai','team-github','gmail-ai','repo-report'])assert.match(app,new RegExp("trackJob\\('"+key+"'|trackTeamJob\\('"+key+"'"));
assert.match(fs.readFileSync('web/prompt-editor.js','utf8'),/trackJob\('prompt-test',result\.running&&/);
// A dialog opened after the line shows it again, above the dialog.
assert.match(app,/if\(dialog\.open&&records\.some\(r=>r\.target===dialog&&r\.attributeName==='open'\)\)raiseActivity\(\);/);
// renderState keeps the line current on every state event; a click opens the meeting.
assert.match(app,/function renderState\(\) \{\n if\(typeof renderBackgroundActivity==='function'\)renderBackgroundActivity\(\);/);
assert.match(app,/addEventListener\('click',\(\)=>\{if\(!foregroundShown&&backgroundJob\)perform\(backgroundJob\.open\);\}\)/);
console.log('Background activity PASS: job step and meeting, action priority, title generation, other AI jobs, polls and failures, click opens the job.');
})().catch(e=>{console.error(e);process.exitCode=1;});
