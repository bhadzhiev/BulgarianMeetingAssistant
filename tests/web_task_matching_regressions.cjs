const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8'),html=fs.readFileSync('web/index.html','utf8');
const slice=(a,b='\n}\n')=>{const at=app.indexOf(a);assert.notEqual(at,-1,a);return app.slice(at,app.indexOf(b,at));};
// The permission (option b): one checkbox for the address of a remote API; it names the host and what is sent.
assert.match(html,/<input id="task-matching-allow" type="checkbox">/);
const render=slice('function renderTaskMatching(){');
assert.match(render,/allow\.closest\('label'\)\.hidden=!remote;/);
assert.match(render,/'Send task context to '\+host\+' to match meeting tasks with existing tasks'/);
assert.match(render,/Proposed and hidden tasks, email and chat text are never sent\./);
// Another address clears the permission; saving sends the address only for a remote API.
assert.match(render,/if\(remote&&url!==state\?\.settings\?\.task_matching_target&&document\.activeElement!==allow\)allow\.checked=false;/);
assert.match(app,/task_matching_target:\$\('task-matching-allow'\)\.checked&&remoteAPI\(\$\('local-ai-base-url'\)\.value\)\?\$\('local-ai-base-url'\)\.value\.trim\(\):'',/);
// The privacy text says it when the permission is on.
const ctx=vm.createContext({URL});vm.runInContext(slice('function remoteAPI(url){','\nfunction privacy')+slice('function privacy(s) {','\nfunction switchTab'),ctx);
const base={transcription:'local',summarizer:'local',transcript_correction:'none',title_provider:'none',local_ai_base_url:'https://api.moonshot.ai/v1'};
assert.match(vm.runInContext('privacy',ctx)({...base,task_matching_target:'https://api.moonshot.ai/v1'}),/Titles and short updates of similar existing tasks are sent to api\.moonshot\.ai for task matching\./);
assert.doesNotMatch(vm.runInContext('privacy',ctx)({...base,task_matching_target:''}),/task matching/);
console.log('Task matching PASS: permission per address, host named, cleared on address change, privacy text.');
