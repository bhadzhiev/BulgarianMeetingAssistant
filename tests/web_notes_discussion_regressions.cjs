const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8'),css=fs.readFileSync('web/style.css','utf8');
// The details of the meeting by topic (2026-11-13): saved like the other notes, but no list of statements.
assert.match(app,/observations:'Private observations',discussion:'Discussion'\};/);
assert.match(app,/const ITEM_FIELDS=Object\.keys\(FIELD_TITLES\)\.filter\(field=>!\['tasks','discussion'\]\.includes\(field\)\);/);
assert.match(app,/const NOTE_FIELDS=\[[^\]]*'observations','discussion'\];/);
// It shows after the summary when it has topics, and always in the editor.
assert.match(app,/noteSection\(minutes,'summary','Summary',busy\),\.\.\.\(minutes\.discussion\?\.length\|\|notesEditing\?\[discussionSection\(minutes,busy\)\]:\[\]\)/);
assert.match(app,/AtlantaUX\.count\(topics\.length,'topic'\)/);
assert.match(app,/AtlantaUX\.count\(topic\.points\.length,'point'\)/);
assert.match(app,/noteButtons\(topic\.points,index,text,busy,'Discussion'\)/);
assert.match(app,/btn\('secondary small-action','＋ Add point'\)/);
assert.match(app,/btn\('secondary','＋ Add topic'\)/);
// Saving drops empty points and empty topics; a topic without a name keeps its points.
const start=app.indexOf('function cleanDiscussion('),end=app.indexOf('\n',start);
const context={};vm.runInNewContext(app.slice(start,end)+';this.cleanDiscussion=cleanDiscussion;',context);
const p=text=>({text,evidence_timestamp:null,review:'verified'});
assert.deepEqual(JSON.parse(JSON.stringify(context.cleanDiscussion([{topic:' Мрежа ',points:[p('A'),p('  ')]},{topic:'Празна',points:[p('')]},{topic:' ',points:[p('B')]}]))),
 [{topic:'Мрежа',points:[p('A')]},{topic:'Other',points:[p('B')]}]);
assert.match(app,/if\(detail\.minutes\.discussion\)detail\.minutes\.discussion=cleanDiscussion\(detail\.minutes\.discussion\);/);
// The review of new AI notes shows a topic as one change.
assert.match(app,/field==='discussion'\?item\.topic\+': '\+item\.points\.map\(point=>point\.text\)\.join\(' · '\)/);
for(const name of ['.discussion-topic','.discussion-points','.discussion-editor'])assert.ok(css.includes(name),name+' is styled');
console.log('Notes discussion PASS: topics with points, editor, cleanup and review text.');
