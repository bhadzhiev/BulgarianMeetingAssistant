const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8'),html=fs.readFileSync('web/index.html','utf8');
const slice=(a,b)=>{const at=app.indexOf(a);assert.notEqual(at,-1,a);return app.slice(at,app.indexOf(b,at));};
const c=vm.createContext({URL});
vm.runInContext(slice('// Outside this Mac and its local network','function switchTab('),c);
const remote=vm.runInContext('remoteAPI',c),privacy=vm.runInContext('privacy',c);
// The same rule as app/local_ai.is_remote.
for(const url of ['http://127.0.0.1:1234/v1','http://localhost:1235/v1','http://192.168.1.20:1234/v1','http://10.0.0.5/v1','http://172.20.1.1/v1','http://studio.local:1234/v1','http://[::1]:8080/v1'])assert.equal(remote(url),false,url);
for(const url of ['https://api.moonshot.ai/v1','https://api.openai.com/v1','http://8.8.8.8/v1'])assert.equal(remote(url),true,url);
// A cloud endpoint is named in the privacy text; a local one keeps the local wording.
const base={transcription:'elevenlabs',summarizer:'local',transcript_correction:'local',auto_title:true,title_provider:'local',calendar_enabled:false};
assert.match(privacy({...base,local_ai_base_url:'https://api.moonshot.ai/v1'}),/Transcript text is sent to api\.moonshot\.ai for notes, titles\./);
assert.doesNotMatch(privacy({...base,local_ai_base_url:'http://127.0.0.1:1234/v1'}),/is sent to 127/);
assert.match(privacy({...base,transcription:'local',local_ai_base_url:'https://api.moonshot.ai/v1'}),/for notes, AI correction, titles\./);
assert.doesNotMatch(privacy({...base,transcription:'local',local_ai_base_url:'https://api.moonshot.ai/v1'}),/Notes use the configured API\./);
// The key field, its Forget button and the context field exist and reach the request.
for(const id of ['local-ai-api-key','forget-local-ai-key','local-ai-cloud-note','local-ai-context'])assert.match(html,new RegExp('id="'+id+'"'));
assert.match(app,/if\(\$\('local-ai-api-key'\)\.value\.trim\(\)\)body\.local_ai_api_key=\$\('local-ai-api-key'\)\.value\.trim\(\)/);
assert.match(app,/local_ai_context:Number\(\$\('local-ai-context'\)\.value\)/);
assert.doesNotMatch(html,/Local · Configured API/);
console.log('Configured API PASS: cloud detection, privacy text names the host, key and context fields.');

// The Settings footer names the cloud host too; it gets the API address from the form.
const fields=app.slice(app.indexOf('function settingsFields('),app.indexOf('\nfunction ',app.indexOf('function settingsFields(')+1));
assert.match(fields,/privacy\(\{[^}]*local_ai_base_url:\$\('local-ai-base-url'\)\.value/);
assert.match(app,/\$\('local-ai-base-url'\)\.addEventListener\('input',\(\)=>\{renderCloudNote\(\);settingsFields\(\);renderTaskMatching\(\);\}\)/);
// The settings body shrinks and scrolls, so the dialog never cuts off Save settings.
const css=fs.readFileSync('web/style.css','utf8');
assert.match(css,/\.settings-body\{flex:1 1 auto;min-height:120px;/);
console.log('Settings footer PASS: cloud host in the footer, Save settings stays visible.');
// A cloud API shows its temperature and context without advanced settings; Kimi rejects temperature 0.
assert.match(app,/\$\('settings-form'\)\.classList\.toggle\('cloud-api',remote\)/);
assert.match(css,/#settings-form\.simple\.cloud-api \.cloud-setting\{display:block\}/);
assert.equal((html.match(/class="advanced-setting cloud-setting"/g)||[]).length,2);
console.log('Cloud settings PASS: temperature and context show for a cloud API.');
