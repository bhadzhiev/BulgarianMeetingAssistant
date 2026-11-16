const fs=require('node:fs'),assert=require('node:assert/strict');
const source=fs.readFileSync('web/app.js','utf8');
// The handler text from its start to the next handler of the same control row.
const handler=(start,end)=>{const at=source.indexOf(start);assert.notEqual(at,-1,start);return source.slice(at,source.indexOf(end,at+start.length));};

// A control that saves at once says so and offers Undo.
const instant={
 'review project':handler("project.onchange=()=>perform(","const projectLabel="),
 'review destination':handler("destination.onchange=()=>perform(","const destinationLabel="),
 'series type':handler("type.onchange=()=>perform(async()=>{const previous=entry.type","line.insertBefore(type,rename)"),
 'project color':handler("color.onchange=()=>perform(","line.insertBefore(color,rename)"),
};
for(const [name,code] of Object.entries(instant))assert.match(code,/undoToast\(|changeWithUndo\(/,name+' must offer Undo');
// Task facts no longer save instantly: edits happen in the task editor, with its existing Undo.
assert.doesNotMatch(handler('function globalTaskRow(','function taskDescription('),/stateFact.onclick|ownerFact.onclick|dueFact.onclick|stateSelect/);
// The punctuation-based question checkbox no longer creates an instant-save workflow.
assert.doesNotMatch(source,/toggle\.onchange=\(\)=>perform\(/);

// The meeting type asks before it changes anything when notes exist.
const type=handler("type.onchange=()=>perform(async()=>{\n  const value=type.value","const typeLabel=");
const asked=type.indexOf("await ask('Change the meeting type"),saved=type.indexOf('await setType(value)');
assert(asked>0&&saved>asked,'the question comes before the save');
assert.match(type,/extra:'Change type only'/);
assert.match(type,/if\(!answer\)\{type\.value=previous;return;\}/);
assert.match(type,/undoToast\('Meeting type: '/);

console.log('Undo saves PASS: five instant-save controls offer Undo, the meeting type asks before it saves.');
