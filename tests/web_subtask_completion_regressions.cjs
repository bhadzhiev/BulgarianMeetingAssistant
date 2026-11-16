const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('web/app.js','utf8'),requests=[],answers=[];
const c=vm.createContext({beginActivity(){},endActivity(){},actionWrites:0,actionFailures:0,AtlantaTasks:require('../web/task-model.js'),ask:async()=>answers.shift(),readApiResponse:async response=>response,offerVocabulary(){},fetch:async(path,options)=>{requests.push({path,options});return path==='/api/items'?{items:[{id:'a',parent_task_id:'abc',workflow_state:'todo'}]}:{id:'abc'};}});
vm.runInContext(source.slice(source.indexOf('async function api(path,body)'),source.indexOf('// The desktop window',source.indexOf('async function api(path,body)'))),c);
(async()=>{
 answers.push(false);await assert.rejects(vm.runInContext("api('/api/items/abc',{changes:{workflow_state:'done'}})",c),e=>e.cancelled===true);
 assert.equal(requests.length,1,'completion reads current children even from a meeting with no My Work snapshot');
 answers.push(true);await vm.runInContext("api('/api/items/abc',{changes:{workflow_state:'done'}})",c);
 assert.equal(JSON.parse(requests.at(-1).options.body).confirm_subtasks,true);
 console.log('Subtask completion PASS: fresh hierarchy, quiet cancellation and explicit completion acknowledgement.');
})().catch(e=>{console.error(e);process.exitCode=1});
