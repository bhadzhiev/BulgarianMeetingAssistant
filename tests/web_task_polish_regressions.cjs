const fs=require('node:fs'),assert=require('node:assert/strict');
const src=fs.readFileSync('web/app.js','utf8'),py=fs.readFileSync('app/task_draft.py','utf8');
// Improve with AI suggests sharper fields in the new-task dialog and in the task editor; the person reviews before saving (2026-11-14).
assert.equal((src.match(/Improve with AI/g)||[]).length,4,'two buttons, the consent confirm and the helper comment mention Improve with AI');
assert.ok(src.includes("provider:'task_edit'"),'the suggestion goes through the task_edit provider');
assert.ok(src.includes('Send the current card to '),'sending the card asks for consent first');
assert.ok(src.includes('The result is a suggestion you review before saving.'),'the consent names the review boundary');
assert.ok(src.includes("api('/api/task-draft/cancel',{id:job.id})"),'closing the dialog cancels the suggestion job');
assert.ok(src.includes('toast(\'Suggestion applied · review it before saving\')'),'applying the suggestion asks for review, not trust');
// The suggestion never writes: create() rejects task_edit, and the panel only fills the editor fields.
assert.ok(py.includes("if body.get('provider')=='task_edit':raise ValueError"),'task_edit can never create or change a task');
assert.ok(py.includes('POLISH_SYSTEM'),'the polish prompt is separate from the draft prompt');
const panel=src.slice(src.indexOf('async function openTaskPanel('),src.indexOf('// Native close and recovery'));
assert.ok(panel.includes("btn('quiet small-action','Improve with AI')"),'the task editor offers Improve with AI');
assert.ok(panel.includes('criterion.value=result.completion_criteria||criterion.value'),'an empty suggestion never wipes a filled field');
const manual=src.slice(src.indexOf('async function openManualTask('),src.indexOf("$('new-task').onclick"));
assert.ok(manual.includes("btn('secondary','Improve with AI')"),'the new-task dialog offers Improve with AI');
assert.ok(manual.includes("context:goal?'Project goal: '+goal:''"),'a chosen project goal travels as context');
console.log('Task polish PASS: consent before sending, suggestion never writes, empty fields are kept, both forms offer it.');
