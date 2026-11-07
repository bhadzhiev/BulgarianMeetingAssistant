const fs=require('node:fs'),assert=require('node:assert/strict');
const source=fs.readFileSync('web/app.js','utf8');
// The handler text from its start to the next handler of the same control row.
const handler=(start,end)=>{const at=source.indexOf(start);assert.notEqual(at,-1,start);return source.slice(at,source.indexOf(end,at+start.length));};

// A control that saves at once says so and offers Undo.
const instant={
 'question answered':handler("toggle.onchange=()=>perform(","const main=el('div')"),
 'task state, owner and dates':handler("const commit=(input,previous,changes,message,undo)","const addUpdate="),
 'review project':handler("project.onchange=()=>perform(","const projectLabel="),
 'review destination':handler("destination.onchange=()=>perform(","const destinationLabel="),
 'series type':handler("type.onchange=()=>perform(async()=>{const previous=entry.type","line.insertBefore(type,rename)"),
 'project color':handler("color.onchange=()=>perform(","line.insertBefore(color,rename)"),
};
for(const [name,code] of Object.entries(instant))assert.match(code,/undoToast\(|changeWithUndo\(/,name+' must offer Undo');
// Every quick task field passes its own message and the value that Undo restores.
const task=instant['task state, owner and dates'];
for(const [field,undo] of [['stateSelect','{workflow_state:AtlantaTasks.workflow(item)}'],['owner','ownerUndo'],['due','{due_date:item.due_date||null}'],['follow','{follow_up_date:item.follow_up_date||null}']]){
 const line=task.split('\n').find(l=>l.trimStart().startsWith(field+'.onchange='));assert(line,field);assert(line.includes(','+undo+')'),field+' restores its old value');
}
// A failed save puts the checkbox back.
assert.match(instant['question answered'],/catch\(e\)\{toggle\.checked=!answered;throw e;\}/);

// The meeting type asks before it changes anything when notes exist.
const type=handler("type.onchange=()=>perform(async()=>{\n  const value=type.value","const typeLabel=");
const asked=type.indexOf("await ask('Change the meeting type"),saved=type.indexOf('await setType(value)');
assert(asked>0&&saved>asked,'the question comes before the save');
assert.match(type,/extra:'Change type only'/);
assert.match(type,/if\(!answer\)\{type\.value=previous;return;\}/);
assert.match(type,/undoToast\('Meeting type: '/);

console.log('Undo saves PASS: six instant-save controls offer Undo, the meeting type asks before it saves.');
