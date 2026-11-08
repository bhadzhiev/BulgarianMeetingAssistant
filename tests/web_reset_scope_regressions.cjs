const fs=require('node:fs'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8'),html=fs.readFileSync('web/index.html','utf8');
const slice=(a,b='\n}\n')=>{const at=app.indexOf(a);assert.notEqual(at,-1,a);return app.slice(at,app.indexOf(b,at));};
// D02: Reset filters resets the filters and the task view and keeps the search; Clear all also clears the search.
const tasks=slice('function resetTaskFilters({all=false}={}){');
assert.match(tasks,/managerView='all';store\('manager-view','all'\);/);
assert.match(tasks,/if\(all\)\{store\('task-search',''\);/);
// "This is me" is who you are, not a filter.
assert.doesNotMatch(tasks,/managerSelf|manager-self/);
assert.match(html,/<button id="task-reset-filters" class="quiet" type="button">Reset filters<\/button><button id="task-clear-all" class="quiet" type="button">Clear all<\/button>/);
const library=slice('function resetConversationFilters({all=false}={}){');
assert.match(library,/\.\.\.\(all\?\['conversation-query'\]:\[\]\)/);
assert.match(html,/<button id="conversation-clear-all" class="quiet" type="button">Clear all<\/button>/);
// 0 results: the active conditions and an action for each scope.
const list=slice('function renderTasks() {');
assert.match(list,/box\.append\(el\('p','hint','Active: '\+conditions\.join\(' · '\)\)\);/);
for(const name of ['Reset filters','Clear search','Clear all'])assert.ok(list.includes("'"+name+"'"),name);
const conv=slice('function renderConversations(){');
for(const name of ['Reset filters','Clear search','Clear all'])assert.ok(conv.includes("'"+name+"'"),name);
console.log('Reset scope PASS: Reset filters keeps the search, Clear all clears it, This is me stays, 0 results offer each scope.');
