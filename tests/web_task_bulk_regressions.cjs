const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const src=fs.readFileSync('web/app.js','utf8');
(async()=>{
 let finish;const requests=[],body={request_id:'a'.repeat(32),items:[{id:'one',revision:1}],changes:{workflow_state:'waiting'}};
 const c=vm.createContext({AtlantaUX:require('../web/ux.js'),$:()=>({}),api:(path,payload)=>{requests.push({path,payload});return new Promise((resolve,reject)=>finish=e=>e?reject(e):resolve({count:1}));},withEditorSave:async(_,fn)=>fn(),renderBulkTasks(){},toast(){},refreshAfterItemChange:async()=>{}});
 vm.runInContext('let bulkSaving=false,bulkPending=null,taskSelection=new Map();'+src.slice(src.indexOf('async function sendBulkTasks('),src.indexOf('function renderBulkTasks(')),c);c.body=body;
 vm.runInContext('bulkPending=body;taskSelection.set("one",body.items[0]);',c);
 const first=vm.runInContext('sendBulkTasks(body)',c);await vm.runInContext('sendBulkTasks(body)',c);assert.equal(requests.length,1,'double click cannot submit twice');
 finish(new Error('Network lost'));await assert.rejects(first);assert.equal(vm.runInContext('bulkPending.request_id',c),body.request_id);assert(!vm.runInContext('bulkSaving',c));
 const retry=vm.runInContext('sendBulkTasks(bulkPending)',c);assert.deepEqual(requests[0],requests[1]);finish();await retry;assert.equal(vm.runInContext('taskSelection.size',c),0);assert.equal(vm.runInContext('bulkPending',c),null);
 vm.runInContext('bulkPending=body;taskSelection.set("one",body.items[0]);',c);const conflict=vm.runInContext('sendBulkTasks(body)',c);finish(Object.assign(new Error('Changed'),{status:409}));await assert.rejects(conflict);assert.equal(vm.runInContext('taskSelection.size',c),0);assert.equal(vm.runInContext('bulkPending',c),null);
 console.log('Bulk task UI PASS: duplicate submission guard, exact uncertain retry and conflict resets.');
})().catch(e=>{console.error(e);process.exitCode=1});
