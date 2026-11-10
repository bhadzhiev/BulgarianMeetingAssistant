const fs=require('node:fs'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8'),html=fs.readFileSync('web/index.html','utf8');
// A project's saved conversations are a visible tab, not only an item in the More menu.
assert.match(html,/<button role="tab" data-section="conversations">Conversations<\/button>/);
assert.doesNotMatch(html,/data-project-section="conversations"/);
// The Gmail and Chat readers show which projects hold the thread; saving refreshes them.
assert.match(app,/attachExternal\('gmail',thread\.id\)\);showReaderProjects\('gmail',thread\.id,attach,request\)/);
assert.match(app,/showReaderProjects\('google_chat',key,attach,null\)/);
assert.match(app,/'Projects: '\+projects\.map\(p=>p\.name\)\.join\(', '\)\+' · Change…'/);
assert.equal((app.match(/refreshReaderProjects\(\);/g)||[]).length,2);
// Saving project links on a snapshot always says what happened and offers the project.
assert.match(app,/toast\(ids\.length\?'Project links saved · '\+projectNames\(ids\):'Project links removed'\)/);
assert.match(app,/'Open in '\+project\.name/);
console.log('Attach feedback PASS: visible Conversations tab, reader project chips, save messages and project links.');
