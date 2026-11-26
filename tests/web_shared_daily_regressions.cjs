const fs=require('node:fs'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8');
// A daily offers open tasks across projects. A search by title, project or owner replaces the owner groups (2026-11-26).
const at=app.indexOf('const taskLabel=');assert.notEqual(at,-1);
const taskLabel=eval(app.slice(at+'const taskLabel='.length,app.indexOf(';\n',at)));
assert.equal(taskLabel({text:'Check backups',projects:['Ops','Web'],owner:'Ben'}),'Check backups · Ops, Web · Ben');
assert.equal(taskLabel({text:'Check backups',projects:[]}),'Check backups · No project');
assert.match(app,/search\.placeholder='Search title, project or owner';/);
assert.doesNotMatch(app,/group\.label=owner\|\|'No owner'/);
assert.doesNotMatch(app,/Choose a project with open tasks to apply an update\./);
console.log('Shared daily PASS: tasks across projects, found by title, project or owner.');
