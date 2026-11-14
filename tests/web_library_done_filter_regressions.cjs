const fs=require('node:fs'),assert=require('node:assert/strict');
// Library filter by the manual Done mark (2026-11-15): a Status select that is sent, remembered,
// shown as a chip, counted as a filter and cleared by Reset filters.
const app=fs.readFileSync('web/app.js','utf8'),html=fs.readFileSync('web/index.html','utf8');
assert.match(html,/<label>Status<select id="conversation-done"><option value="">Done and not done<\/option><option value="not_done">Not done<\/option><option value="done">Done<\/option><\/select><\/label>/);
assert.match(app,/done:\$\('conversation-done'\)\.value,offset:/);
assert.match(app,/for\(const id of \['query','source','project','series','participant','from','to','done'\]\)values\[id\]/);
assert.match(app,/for\(const id of \['query','source','project','from','to','done'\]\)\$\('conversation-'\+id\)\.value=saved\[id\]/);
assert.match(app,/\['participant','Participant',''\],\['done','Status',''\]\]/);
assert.match(app,/const hasFilters=\['query','project','series','participant','from','to','done'\]/);
assert.match(app,/filtered=\['project','series','participant','from','to','done'\]/);
assert.match(app,/'conversation-to','conversation-done',/);
console.log('Library Done filter PASS: Status select, request, remembered, chip, empty state and reset.');
