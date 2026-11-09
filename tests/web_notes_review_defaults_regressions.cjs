const fs=require('node:fs'),assert=require('node:assert/strict');
const src=fs.readFileSync('web/app.js','utf8');
// Updated notes: a removal of an unchecked AI statement is preselected, so a reworded statement does not stay twice.
// A removal of a task or decision, or of a checked statement, waits for a person.
const rule=src.match(/box\.checked=(change\.kind==='added'[^;]*);/);assert.ok(rule,'the default rule exists');
const checked=new Function('change','checked','field','return '+rule[1]);
assert.equal(checked({kind:'added'},false,'summary'),true);
assert.equal(checked({kind:'changed'},false,'summary'),true);
assert.equal(checked({kind:'changed'},true,'summary'),false);
assert.equal(checked({kind:'removed'},false,'summary'),true);
assert.equal(checked({kind:'removed'},false,'open_questions'),true);
assert.equal(checked({kind:'removed'},true,'summary'),false);
assert.equal(checked({kind:'removed'},false,'tasks'),false);
assert.equal(checked({kind:'removed'},false,'decisions'),false);
console.log('Notes review defaults PASS: safe removals preselected, tasks and decisions wait for a person.');
