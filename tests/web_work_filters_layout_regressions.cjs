// My Work filters (approved 2026-11-19): search and profile beside the section tabs, views and status on one row,
// labelled filter fields, then Select tasks with the count and the order.
const fs=require('node:fs'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8'),html=fs.readFileSync('web/index.html','utf8'),css=fs.readFileSync('web/style.css','utf8');
assert.match(html,/<div class="work-tabs-row"><div id="work-tabs"[\s\S]*?<\/div><div id="work-tools" class="work-tools"><\/div><\/div>/,'search and profile sit beside the section tabs');
assert.match(html,/<div class="work-filter-row"><div id="manager-controls" class="manager-controls"><\/div><div id="status-filter" class="segmented" role="group" aria-label="Filter by status"><\/div><\/div>/,'views and status share one row');
for(const [label,id] of [['Source','task-source-select'],['Project','work-project'],['Owner','task-owner']])assert.match(html,new RegExp('<label class="[^"]*filter-field"><span>'+label+':</span><select id="'+id+'"'),label+' field has a visible label');
assert.match(app,/box\.append\(el\('span','','State:'\),field\)/,'the state field has a visible label');
assert.match(app,/tools\.append\(search,identity\)/);
assert.match(app,/\$\('work-tools'\)\?\.querySelector\('input\[type=search\]'\)/,'search keeps focus after a re-render');
assert.match(app,/\$\('status-filter'\)\.hidden=noKindItems\|\|inbox;/);
const bulk=app.slice(app.indexOf('function renderBulkTasks('),app.indexOf('function renderTasks('));
assert.match(bulk,/line\.firstChild\.append\('Showing ',el\('strong','',AtlantaUX\.count\(taskVisibleRows\.length,'task'\)\)\)/,'the count sits next to Select tasks');
assert.doesNotMatch(app.slice(app.indexOf('function renderTasks('),app.indexOf('const WORK_PANELS=')),/task-list-summary/,'the count is not repeated above the cards');
assert.match(css,/#tasks:has\(#items-panel\[hidden\]\) #work-tools\{display:none\}/,'the task tools hide on other sections');
console.log('Work filters layout PASS: tools beside the tabs, one status row, labelled fields, count beside Select tasks.');
