const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const app=fs.readFileSync('web/app.js','utf8');
const start=app.indexOf(" const sourceSelect=$('task-source-select');");assert(start>=0);
const end=app.indexOf('\n',start+1),select={replaceChildren(...options){this.options=options;}};
let saved,rendered=0;const ctx={sourceFilter:'gmail',$:()=>select,option:(label,value)=>({label,value}),store:(key,value)=>{saved=[key,value]},renderTasks:()=>{rendered++}};
vm.runInNewContext(app.slice(start,end),ctx);assert.equal(select.value,'gmail');assert.equal(select.options.length,7);assert.ok(select.options.some(({value})=>value==='agentmail'));
select.value='github';select.onchange();assert.equal(ctx.sourceFilter,'github');assert.deepEqual(saved,['tasks-source','github']);assert.equal(rendered,1);
console.log('Task source dropdown PASS: existing filter restores and changes persist.');
