const fs=require('node:fs'),assert=require('node:assert/strict');
const src=fs.readFileSync('web/app.js','utf8'),Progress=require('../web/task-progress.js');
// An update that a meeting added by itself says so, and a person can remove it.
assert.equal(Progress.label({kind:'progress_update',by:'ai'}),'Update from the meeting (added by AI)');
assert.equal(Progress.label({kind:'progress_update',by:'user'}),'Progress update');
assert.equal(Progress.label({kind:'meeting_update_removed'}),'Update from the meeting removed');
assert.ok(src.includes("if(event.kind==='progress_update'&&event.by==='ai'){const remove=btn('quiet small-action','Remove this update')"));
assert.ok(src.includes("api('/api/items/'+item.id+'/meeting-update/remove',{meeting_id:event.meeting_id,evidence_timestamp:event.timestamp||null,text:event.text})"));
console.log('Meeting update PASS: AI label, removal label and Remove button.');
