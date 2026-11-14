const fs=require('node:fs'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8'),html=fs.readFileSync('web/index.html','utf8');
const slice=(a,b='\n}\n')=>{const at=app.indexOf(a);assert.notEqual(at,-1,a);return app.slice(at,app.indexOf(b,at));};
// The preview names the destination and shows the exact data; nothing starts without the approval box.
assert.match(html,/<details id="team-ai-data"><summary>The data that the AI gets<\/summary><pre id="team-ai-input"/);
assert.match(html,/<input id="team-ai-approve" type="checkbox"> I approve: send these records to this AI destination\./);
assert.match(html,/<button id="team-ai-start" class="primary" type="submit" disabled>/);
const open=slice('async function openTeamAI(r){');
assert.match(open,/\['Destination',/);assert.match(open,/if\(p\.remote\)box\.append\(el\('p','notice','This destination is outside this Mac\./);
assert.match(open,/\$\('team-ai-input'\)\.textContent=JSON\.stringify\(p\.batch_inputs,null,2\)/);
assert.match(app,/\$\('team-ai-start'\)\.disabled=!\$\('team-ai-approve'\)\.checked\|\|!teamAIPreview\?\.ai_available;/);
assert.match(app,/api\('\/api\/team\/review\/ai\/start',\{id:teamReview\.id,preview_token:teamAIPreview\.preview_token,approved:\$\('team-ai-approve'\)\.checked\}\)/);
// The page shows the progress with Stop, and an incomplete run blocks Finalize in words.
const page=slice('function renderTeamReview(){');
assert.match(page,/'The AI preparation is incomplete\. Run it again before you finalize; the finished parts are kept\.'/);
assert.match(page,/actionBtn\('quiet small-action','Stop'/);
assert.match(page,/actionBtn\('secondary','Prepare with AI…',\(\)=>openTeamAI\(r\)\)/);
console.log('Team AI PASS: preview, approval, progress, incomplete run.');
