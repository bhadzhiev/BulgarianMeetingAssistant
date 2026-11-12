const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8'),css=fs.readFileSync('web/style.css','utf8');
// A decision shows why it was taken and an open question what is known about it (2026-11-13).
const start=app.indexOf('const EXPLANATIONS='),end=app.indexOf('function noteSection(');
const made=[];const context={el:(tag,cls,text)=>{const node={tag,cls,text};made.push(node);return node;},linkedText:(node,text)=>Object.assign(node,{text})};
vm.runInNewContext(app.slice(start,end)+';this.noteExplanation=noteExplanation;',context);
const {noteExplanation}=context;
assert.equal(noteExplanation('decisions',{text:'A',rationale:'Ана: по-евтин е.'}).text,'Ана: по-евтин е.');
assert.equal(noteExplanation('decisions',{text:'A',rationale:null}).text,'No reason was given in the meeting.');
assert.equal(noteExplanation('decisions',{text:'A'}),null,'notes from before the field show nothing');
assert.equal(noteExplanation('open_questions',{text:'Q',context:null}),null,'a question without context shows nothing');
assert.equal(noteExplanation('open_questions',{text:'Q',context:'Борис попита.'}).text,'Борис попита.');
assert.equal(noteExplanation('summary',{text:'S',rationale:'x'}),null);
// The notes editor edits them; an empty one is removed, not saved as "no reason".
assert.match(app,/label\.append\(el\('span','',name==='rationale'\?'Reason':'Context'\),why\)/);
assert.match(app,/why\.oninput=\(\)=>\{if\(why\.value\.trim\(\)\)item\[name\]=why\.value;else delete item\[name\];markNotes\(\);\};/);
// The review of new AI notes shows a changed reason.
assert.match(app,/item\.rationale&&'Reason: '\+item\.rationale,item\.context&&'Context: '\+item\.context/);
for(const name of ['.note-explanation{','.note-explanation-editor'])assert.ok(css.includes(name),name+' is styled');
console.log('Notes explanations PASS: reasons of decisions and context of open questions.');
