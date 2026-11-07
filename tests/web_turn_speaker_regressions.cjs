const fs=require('node:fs'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8');
const slice=(a,b)=>{const at=app.indexOf(a);assert.notEqual(at,-1,a);return app.slice(at,app.indexOf(b,at));};

// A change in one meeting never opens the many-meeting reprocess dialog; the banner offers the update.
const editor=slice('function openTurnSpeakerEditor(','\n}\n');
assert.doesNotMatch(editor,/offerReprocess/);
assert.match(editor,/defer_analysis:false/);
assert.match(editor,/'Speaker saved for this turn\. Talk time is updated\.'/);
const save=slice("$('save-transcript').onclick=",'\n');
assert.doesNotMatch(save,/offerReprocess/);
// The banner shows its button; earlier it was made but never added.
const banner=slice('function transcriptRefreshBanner(','\n}');
assert.match(banner,/if\(!busy\)banner\.append\(button\)/);
console.log('Turn speaker PASS: no reprocess dialog for one meeting, the banner shows Update notes & tasks.');
