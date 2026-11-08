const fs=require('node:fs'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8'),css=fs.readFileSync('web/style.css','utf8');
const slice=(a,b='\n}\n')=>{const at=app.indexOf(a);assert.notEqual(at,-1,a);return app.slice(at,app.indexOf(b,at));};
// Gmail, Chat and saved snapshots: one shared card in Library and in Projects.
const card=slice('function conversationCard(row,');
assert.match(card,/el\('article','entity-card conversation-card'/);
assert.match(card,/summary=el\('summary','add-project','＋ Add project'\)/);
assert.match(card,/projects\.length\?'Change projects…':'Add to a project…'/);
assert.match(card,/meta\.append\(originChip\(kind\)\)/);
assert.match(card,/el\('p','entity-preview'\+\(excerpt\?' quote':''\),row\.preview\)/);
assert.match(card,/listenButton\(row\.locator\.meeting_id,row\.locator\.start/);
assert.match(app,/function attachmentCard\(row\)\{return conversationCard\(row,\{onChange:loadWorkspace\}\);\}/);
assert.match(app,/list\.append\(conversationCard\(row,\{onChange:loadConversations\}\)\)/);
// Project cards: the project line and no row of zero counts.
assert.match(app,/\.filter\(\(\[n\]\)=>n\)\.map\(\(\[n,label\]\)=>AtlantaUX\.count\(n,label\)\)/);
assert.match(css,/\.project-card\.has-project-line\{border-left:3px solid var\(--project-color\)\}/);
// Projects keep the project colour for chips and project lines.
assert.match(app,/map\(\(\{id,name,color\}\)=>\(\{\.\.\.known\.get\(id\),id,name,\.\.\.\(color\?\{color\}:\{\}\)\}\)\)/);
// People: one useful identity on the row.
const identity=slice('function personIdentity(person){');
assert.match(identity,/github\|\|\(aliases\[0\]\?'Also '\+aliases\[0\]:''\)\|\|emails\[0\]/);
// Sources, search results, follow-up and findings use the shared card.
assert.match(slice('function sourceCard(source){'),/el\('article','entity-card source-card'\)/);
assert.match(slice('function resultRow(result) {'),/el\('article','entity-card result-card '\+result\.kind\)/);
assert.match(app,/const card=el\('article','entity-card followup-card'\)/);
const finding=slice('function findingCard(f,r,busy){');
assert.match(finding,/'AI inference'/);assert.match(finding,/el\('details','finding-evidence'\)/);assert.match(finding,/'Suggest a task'/);
// A card without bulk selection has no empty selection column.
assert.match(app,/row\.append\(\.\.\.\(select\?\[marks\]:\[\]\),main\)/);
// Prepare me shows a known task with the My Work card.
assert.match(app,/const card=globalTaskRow\(full,today,\{select:false\}\),facts=card\.querySelector\('\.tracked-meta'\)/);
console.log('Source cards PASS: Gmail/Chat/snapshots, projects, people, sources, search, follow-up, findings.');
