const fs=require('node:fs'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8'),html=fs.readFileSync('web/index.html','utf8');
const slice=(a,b)=>{const at=app.indexOf(a);assert.notEqual(at,-1,a);return app.slice(at,app.indexOf(b,at));};

// My Work → Questions shows the questions of meeting notes before the tracked ones.
const panel=slice("const questions=$('work-questions');",'\n}');
assert.match(panel,/renderMeetingQuestions\(questions\);[\s\S]*'Tracked questions'/);
const rows=slice('function renderMeetingQuestions(','\n}\n');
assert.match(rows,/itemsData\.meeting_questions/);
assert.match(rows,/q\.kind==='decide'\?\{tone:'warn',label:'Needs your decision'\}:\{tone:'muted',label:'Open question'\}/);
// Answer and Track keep the meeting and the moment of the question.
assert.match(rows,/graphAction\('question',\{text:q\.text,source,answer\}\)/);
assert.match(rows,/graphAction\('question',\{text:q\.text,source\}\)/);
assert.match(rows,/listenButton\(q\.meeting_id,stampSeconds\(q\.evidence_timestamp\)/);
assert.match(html,/Open questions from your meeting notes, and the questions that you track\./);
console.log('Meeting questions PASS: My Work shows note questions, Answer and Track keep the source.');
