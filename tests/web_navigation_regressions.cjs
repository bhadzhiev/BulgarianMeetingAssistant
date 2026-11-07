const fs=require('node:fs'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8'),css=fs.readFileSync('web/style.css','utf8');
const slice=(a,b)=>{const at=app.indexOf(a);assert.notEqual(at,-1,a);return app.slice(at,app.indexOf(b,at));};
// After a delete the Library opens, not a new recording; an active recording stays in front.
const del=slice("$('delete-meeting').onclick=","toast('Meeting deleted')");
assert.match(del,/await openConversations\(\)/);assert.doesNotMatch(del,/show\(state\?\.active\?'recording':'setup'\)/);
assert.match(del,/if\(state\.active\)\{selected=state\.active\.id;show\('recording'\)/);
// A link to a deleted meeting opens the Library with a reason; other errors still surface.
const route=slice('async function applyRoute(){',"else if(target==='work')");
assert.match(route,/catch\(e\)\{if\(e\.status!==404\)throw e;await openConversations\(\);error\('This meeting is no longer on this Mac/);
// Layout: one line for the library link, room for a three-answer question.
assert.match(app,/btn\('quiet library-all','All meetings →'\)/);
assert.match(css,/\.library-all\{[^}]*white-space:nowrap/);
assert.match(css,/#ask-dialog:has\(#ask-extra:not\(\[hidden\]\)\)\{width:min\(620px,94vw\)\}/);
console.log('Navigation PASS: Library after delete, deleted links explained, one-line library link, wide three-answer question.');
