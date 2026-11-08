const fs=require('node:fs'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8'),css=fs.readFileSync('web/style.css','utf8'),html=fs.readFileSync('web/index.html','utf8'),dates=fs.readFileSync('web/date-picker.js','utf8');
const slice=(a,b='\n}\n')=>{const at=app.indexOf(a);assert.notEqual(at,-1,a);return app.slice(at,app.indexOf(b,at));};
// A01: a save of one part of a 1:1 review keeps the unsaved edits of the other parts.
const page=slice('function renderTeamReview(){');
assert.match(page,/if\(teamDrafts\.id!==r\.id\)teamDrafts=\{id:r\.id\};/);
assert.match(page,/if\(drafts\.notes_md!==undefined&&drafts\.notes_md!==r\.notes_md\)\{notes\.value=drafts\.notes_md;editorDirty\.set\('team-notes',true\);\}/);
assert.match(page,/if\(drafts\.review_md!==undefined&&draft&&drafts\.review_md!==r\.review_md\)\{text\.value=drafts\.review_md;editorDirty\.set\('team-review',true\);\}/);
assert.match(page,/agreementsCard\(r,drafts\)/);assert.match(page,/previousAgreementsCard\(r\.previous_agreements,drafts\)/);
const card=slice('function agreementsCard(r,drafts={}){');
assert.match(card,/rows=structuredClone\(drafts\.agreements\|\|r\.agreements\|\|\[\]\)/);assert.match(card,/delete drafts\.agreements;editorDirty\.clear\('team-agreements'\)/);
// The last 1:1 has its own unsaved flag, so a save of this review's goals does not clear it.
assert.match(slice('function previousAgreementsCard(previous,drafts={}){'),/editorDirty\.set\('team-previous',edited\)/);
assert.match(app,/'team-previous':'states of the last 1:1'/);
// A discard of all edits also discards the review drafts.
assert.match(slice('async function leaveEdits() {'),/teamDrafts=\{\};/);
// A03: the hidden attribute beats the button scale, which has an id selector and !important.
assert.match(css,/\[hidden\]:not\(#hidden-a\):not\(#hidden-b\)\{display:none!important\}/);
assert.ok(css.lastIndexOf('[hidden]:not(#hidden-a)')>css.indexOf('display:inline-flex!important'));
// A04: the filter groups wrap in a narrow window.
assert.match(css,/@media\(max-width:600px\)\{\n \.segmented\{display:flex;flex-wrap:wrap;max-width:100%\}/);
// A07: every editor dialog has a name from its title.
for(const [dialog,title] of [['settings-dialog','settings-title'],['excerpt-dialog','excerpt-title'],['manual-task-dialog','manual-task-title'],['task-panel','task-panel-title']])
 assert.match(html,new RegExp('<dialog id="'+dialog+'" aria-labelledby="'+title+'"'));
assert.match(html,/<h2 id="settings-title">Settings<\/h2>/);assert.match(html,/<h2 id="excerpt-title">/);
assert.match(app,/manualTitle\.id='manual-task-title'/);assert.match(app,/panelTitle\.id='task-panel-title'/);
// The question dialog reads its message through aria-describedby; its buttons name the choice.
for(const id of [...html.matchAll(/<dialog id="([^"]+)"([^>]*)>/g)].filter(m=>m[1]!=='ask-dialog'))assert.match(id[2],/aria-label/,id[1]+' has a name');
// A08: the date field and its calendar button follow a label that changes.
assert.match(dates,/const naming=\(\)=>\{const label=input\.getAttribute\('aria-label'\)\|\|labels\[0\]\?\.textContent\.trim\(\)\|\|'Date';display\.setAttribute\('aria-label',label\);trigger\.setAttribute\('aria-label','Open calendar for '\+label\);\};/);
assert.match(dates,/watch\.observe\(node,\{childList:true,characterData:true,subtree:true\}\)/);
// A09: the configured API is not called local.
for(const text of ['Local AI model','Local text AI','shared Local AI','local notes'])assert.ok(!html.includes(text)&&!app.includes(text),text);
console.log('Audit fixes PASS: 1:1 drafts kept, hidden wins, narrow filters, dialog names, date labels, API terms.');
