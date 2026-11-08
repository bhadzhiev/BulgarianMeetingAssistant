const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8'),UX=require('../web/ux.js');
const slice=(a,b)=>{const at=app.indexOf(a);assert.notEqual(at,-1,a);return app.slice(at,app.indexOf(b,at));};
// The status line: an action that a person started wins; otherwise the summary of the job registry on the server.
const status={hidden:true,textContent:'',title:'',classes:new Set()},bar={hidden:true};
status.classList={toggle:(n,on)=>on?status.classes.add(n):status.classes.delete(n)};
const answers=[];
const c=vm.createContext({setTimeout,clearTimeout,AtlantaUX:UX,api:async()=>answers.shift(),$:id=>id==='activity'?bar:id==='activity-status'?status:null});
vm.runInContext('let runningActions=0,activityTimer=null,activityLabel="";const BUSY_DELAY=250;'+slice('let foregroundShown=false','if(typeof document.getElementById')+slice('// Background jobs come from one registry','function openJob('),c);
const run=code=>vm.runInContext(code,c);
(async()=>{
 const job=(id,state,label,extra={})=>({id,state,label,phase:'',error:null,progress:null,target:{view:'meeting',id:'m1'},...extra});
 run('renderBackgroundActivity()');assert.equal(status.hidden,true);
 // One running job: its own words, with its step and progress.
 answers.push({jobs:[job('team_ai:a','running','Preparing the 1:1 with AI · Ana',{phase:'Preparing part 1 of 2',progress:{done:0,total:2}})],summary:{running:1}});
 await run('refreshJobs()');run('clearTimeout(jobsTimer)');
 assert.equal(status.textContent,'Preparing the 1:1 with AI · Ana · Preparing part 1 of 2 · 0 of 2');assert(!status.classes.has('failed'));
 // A failure is never hidden by a running or a completed job: the counts show both, in the failed tone.
 answers.push({jobs:[job('p:1','failed','Testing AI instructions',{error:'No'}),job('m:1','running','Processing · Weekly'),job('r:1','completed','Repository report')],summary:{running:1,failed:1,completed:1}});
 await run('refreshJobs()');run('clearTimeout(jobsTimer)');
 assert.equal(status.textContent,'1 job running · 1 job failed');assert(status.classes.has('failed'));
 // Only completed jobs: no summary, no false "all done".
 answers.push({jobs:[job('r:1','completed','Repository report')],summary:{completed:1}});
 await run('refreshJobs()');assert.equal(status.hidden,true);
 // An action that a person started wins over the summary.
 answers.push({jobs:[job('m:1','running','Processing · Weekly')],summary:{running:1}});await run('refreshJobs()');run('clearTimeout(jobsTimer)');
 run('activityLabel="Save settings";foregroundShown=true;paintActivity()');assert.equal(status.textContent,'Save settings · in progress…');
 run('runningActions=1;endActivity()');assert.equal(status.textContent,'Processing · Weekly');
 // The registry is the only source: no job list in the browser, and every family asks it.
 assert.doesNotMatch(app,/trackJob|activityJobs/);
 assert.match(app,/function renderState\(\) \{\n[^\n]*\n if\(typeof refreshJobs==='function'\)refreshJobs\(\);/);
 assert.match(app,/addEventListener\('click',\(\)=>\{if\(!foregroundShown&&backgroundJob\)perform\(backgroundJob\.open\);\}\)/);
 assert.match(fs.readFileSync('web/prompt-editor.js','utf8'),/refreshJobs\(\);/);
 assert.match(fs.readFileSync('web/index.html','utf8'),/<div id="jobs-panel" popover="auto" role="dialog" aria-label="Background jobs"><\/div>/);
 assert.match(app,/actionBtn\('quiet small-action','Dismiss',async\(\)=>\{jobsData=await api\('\/api\/jobs\/dismiss',\{id:job\.id\}\)/);
 // A dialog opened after the line shows it again, above the dialog.
 assert.match(app,/if\(dialog\.open&&records\.some\(r=>r\.target===dialog&&r\.attributeName==='open'\)\)raiseActivity\(\);/);
 console.log('Background activity PASS: one registry, job summary, failures never hidden, action priority, dismiss.');
})().catch(e=>{console.error(e);process.exitCode=1;});
