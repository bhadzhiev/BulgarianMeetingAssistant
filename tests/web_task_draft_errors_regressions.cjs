const fs=require('node:fs'),assert=require('node:assert/strict');
const src=fs.readFileSync('web/app.js','utf8');
// Generate draft once failed without a visible message: the error went to the page behind the modal dialog.
const start=src.indexOf('function editTaskDraft('),end=src.indexOf('function showCreatedTask(');const body=src.slice(start,end);
assert.ok(body.includes("let current;try{current=await api('/api/task-draft/preview',source);}catch(e){if(!closed){showError(note,e.message);status.textContent='The draft could not start.';}return;}"),'a preview error shows in the dialog');
assert.ok(body.includes("if(preview.ai_available===false){note.textContent=preview.ai_unavailable_reason;note.hidden=false;}"),'an AI that is not available says why');
console.log('Task draft errors PASS: errors show in the dialog.');
