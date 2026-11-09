const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const src=fs.readFileSync('web/app.js','utf8');
// A manual task was saved but hidden by the "Meetings" source filter. Now My Work clears the filters and scrolls to it.
const start=src.indexOf('function revealTask('),end=src.indexOf('function showCreatedTask(');
function run(visible){
 const calls=[],row={dataset:{itemId:'new'},classList:{add:c=>calls.push('add '+c),remove(){}},scrollIntoView:()=>calls.push('scroll')};
 const c=vm.createContext({view:'tasks',itemKind:'task',itemsData:{items:[{id:'new',acceptance_state:'accepted'}]},taskVisibleRows:visible?[{id:'new'}]:[],
  resetTaskFilters:o=>calls.push('reset '+JSON.stringify(o)),toast:m=>calls.push('toast '+m),setTimeout(){},$:()=>({querySelectorAll:()=>[row]})});
 vm.runInContext(src.slice(start,end),c);vm.runInContext("revealTask('new')",c);return calls;
}
assert.deepEqual(run(false),['reset {"all":true}','toast Filters cleared to show the new task','scroll','add just-created']);
assert.deepEqual(run(true),['scroll','add just-created'],'visible: no filter change');
// Both create paths reveal the task; the manual dialog offers Open task.
assert.ok(src.includes('revealTask(created.item_id)'));assert.ok(src.includes("showCreatedTask(item.id);\n  try{await refreshAfterItemChange();revealTask(item.id);}"));
// A task without a meeting sorts by its creation date, not last.
assert.ok(src.includes("(item.created||'').slice(0,10)].sort().at(-1)"));
console.log('Reveal task PASS: hidden new task clears filters, scrolls and highlights.');
