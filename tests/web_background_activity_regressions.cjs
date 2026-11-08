const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8');
const slice=(a,b)=>{const at=app.indexOf(a);assert.notEqual(at,-1,a);return app.slice(at,app.indexOf(b,at));};
// A background job of a meeting shows its step and the meeting; an action that a person started wins.
const status={hidden:true,textContent:'',title:''},bar={hidden:true};
const c=vm.createContext({setTimeout,clearTimeout,state:{meetings:[]},$:id=>id==='activity'?bar:status});
vm.runInContext('let runningActions=0,activityTimer=null,activityLabel="";const BUSY_DELAY=250;'+slice('let foregroundShown=false','if(typeof document.getElementById')+slice('function renderBackgroundActivity(','\n}\n')+'\n}',c);
const run=code=>vm.runInContext(code,c);
run('renderBackgroundActivity()');assert.equal(status.hidden,true);
c.state.meetings=[{id:'a',title:'Weekly sync',status:'processing',progress:'Generating notes · part 1 of 2'},{id:'b',title:'Other',status:'ready',title_status:'generating'}];
run('renderBackgroundActivity()');assert.equal(status.hidden,false);assert.equal(status.textContent,'Generating notes · part 1 of 2 · Weekly sync · +1 more');
run('activityLabel="Save settings";foregroundShown=true;paintActivity()');assert.equal(status.textContent,'Save settings · in progress…');
run('runningActions=1;endActivity()');assert.equal(status.textContent,'Generating notes · part 1 of 2 · Weekly sync · +1 more');
c.state.meetings=[{id:'b',title:'Other',status:'ready',title_status:'generating'}];run('renderBackgroundActivity()');assert.equal(status.textContent,'Generating AI title · Other');
c.state.meetings=[];run('renderBackgroundActivity()');assert.equal(status.hidden,true);
// renderState keeps the line current on every state event; a click opens the meeting.
assert.match(app,/function renderState\(\) \{\n if\(typeof renderBackgroundActivity==='function'\)renderBackgroundActivity\(\);/);
assert.match(app,/addEventListener\('click',\(\)=>\{if\(!foregroundShown&&backgroundJob\)perform\(\(\)=>openMeeting\(backgroundJob\.id\)\);\}\)/);
console.log('Background activity PASS: job step and meeting, action priority, title generation, click opens the meeting.');
