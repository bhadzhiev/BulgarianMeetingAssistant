const fs=require('node:fs'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8');
// A shared daily without a project offers tasks across projects, grouped by owner with the line's owner first (2026-11-25).
assert.match(app,/const label=task=>task\.text\+\(daily\.project_id\?'':task\.project\?' · '\+task\.project:''\),owners=\[\.\.\.new Set\(daily\.tasks\.map\(task=>task\.owner\|\|''\)\)\];/);
assert.match(app,/owners\.sort\(\(a,b\)=>\(b===\(row\.owner\|\|''\)\)-\(a===\(row\.owner\|\|''\)\)\|\|!a-!b\|\|a\.localeCompare\(b\)\)/);
assert.match(app,/const group=el\('optgroup'\);group\.label=owner\|\|'No owner';/);
assert.doesNotMatch(app,/Choose a project with open tasks to apply an update\./);
// The sort puts the line's owner first and tasks without an owner last.
const row={owner:'Ben'},sort=list=>list.sort((a,b)=>(b===(row.owner||''))-(a===(row.owner||''))||!a-!b||a.localeCompare(b));
assert.deepEqual(sort(['','Ana','Ben','Cleo']),['Ben','Ana','Cleo','']);
console.log('Shared daily PASS: tasks across projects grouped by owner, the line owner first.');
