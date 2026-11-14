const fs=require('node:fs'),assert=require('node:assert/strict');
const src=fs.readFileSync('web/app.js','utf8');
// Draft with AI once failed without a visible message: the error went to the page behind the modal dialog.
// The unified task dialog keeps its own status and error nodes, so the message shows where the person looks.
const start=src.indexOf('async function openManualTask('),end=src.indexOf("$('new-task').onclick=");const body=src.slice(start,end);
assert.ok(body.includes("let current;try{current=await api('/api/task-draft/preview',src);}catch(e){if(!closed){showError(note,e.message);status.textContent='The draft could not start.';}return;}"),'a preview error shows in the dialog');
assert.ok(body.includes("note.textContent=current.ai_unavailable_reason;note.hidden=false;"),'an AI that is not available says why');
assert.ok(body.includes("showError(note,e.message);status.textContent='Generation failed. Write the task manually or try again.';"),'a failed generation keeps the draft editable');
assert.ok(body.includes("showError(note,state.error+' You can still write the task manually.');"),'a job error shows in the dialog');
assert.ok(body.includes("note.hidden=true;controls();"),'a new attempt clears the previous error');
console.log('Task draft errors PASS: errors show in the unified task dialog.');
