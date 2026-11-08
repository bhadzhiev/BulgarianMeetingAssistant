const fs=require('node:fs'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8'),css=fs.readFileSync('web/style.css','utf8');
const slice=(a,b)=>{const at=app.indexOf(a);assert.notEqual(at,-1,a);return app.slice(at,app.indexOf(b,at));};
const row=slice('function globalTaskRow(','\nfunction ');
// A task is a shared card: project chips beside the title, one project draws its line.
assert.match(row,/row=el\('div','tracked-task entity-card task-card '\+kind\)/);
assert.match(row,/if\(projects\.length===1&&projects\[0\]\.color\)\{row\.classList\.add\('has-project-line'\)/);
assert.match(row,/const head=el\('div','entity-top'\),chips=el\('div','entity-chips'\);for\(const project of projects\)chips\.append\(projectChip\(project\)\);head\.append\(title,chips\);/);
// Owner, state and due date in one row; the last update is one line.
assert.match(row,/meta\.append\(who,el\('span','task-state',stateName\),el\('span','due-label '\+kind,label\)/);
assert.match(row,/const last=el\('p','task-last-line'\)/);assert.doesNotMatch(row,/markdownBlock\(update\.text\)/);
// An AI proposal: Accept, Edit, Skip.
assert.match(row,/actions\.append\(accept,edit,skip\)/);
// Overdue is a red badge, not a pink card.
assert.match(css,/\.tracked-task\.task-card\.overdue,\.tracked-task\.task-card\.today\{background:var\(--card\)/);
assert.match(css,/\.tracked-task\.task-card \.due-label\.overdue\{background:var\(--danger-soft\);color:var\(--danger-ink\)\}/);
// Review: text and state first, then kind and owner, a short quote, and Confirm · Edit · Skip.
const review=slice('async function openMeetingReview(','// The publication state');
assert.match(review,/row=el\('section','entity-card review-card'/);
assert.match(review,/head\.append\(el\('p','review-text',item\.text\),state\)/);
assert.match(review,/for\(const button of \[ordered\.confirm,showEdit\?edit:null,ordered\.dismiss,ordered\.restore\]\)if\(button\)actions\.append\(button\)/);
assert.match(css,/\.review-card \.review-evidence blockquote\{margin:0;flex:1;min-width:0;display:-webkit-box;-webkit-line-clamp:2/);
console.log('Task and Review cards PASS: shared card, project line, one meta row, one-line update, Accept·Edit·Skip, Confirm·Edit·Skip.');
