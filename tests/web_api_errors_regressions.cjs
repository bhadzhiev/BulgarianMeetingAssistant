const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('web/app.js','utf8');
const context=vm.createContext({});vm.runInContext(source.slice(source.indexOf('async function readApiResponse('),source.indexOf('async function api(')),context);
const response=(status,text)=>({status,ok:status>=200&&status<300,text:async()=>text});
(async()=>{
 for(const value of ['Open the app using its launcher.','{"error":"Invalid app session or origin"}']){context.response=response(403,value);await assert.rejects(vm.runInContext('readApiResponse(response)',context),e=>e.status===403&&e.message.includes('Open Atlanta again')&&!e.message.includes('Unexpected token'));}
 context.response=response(400,'{"error":"Choose a repository"}');await assert.rejects(vm.runInContext('readApiResponse(response)',context),e=>e.status===400&&e.message==='Choose a repository');
 for(const [status,text] of [[200,'<html>Not JSON</html>'],[502,'Bad gateway']]){context.response=response(status,text);await assert.rejects(vm.runInContext('readApiResponse(response)',context),e=>e.status===status&&!e.message.includes('Unexpected token')&&!e.message.includes('<html>'));}
 context.response=response(200,'{"saved":true}');assert.equal((await vm.runInContext('readApiResponse(response)',context)).saved,true);
 // Dismissal hides only the message, preserves editor contents, restores focus,
 // and permits a subsequent error to appear in the same alert.
 const target={hidden:true,children:[],classList:{add(){}},replaceChildren(...nodes){this.children=nodes;}};
 const editor={value:'Unsaved task',isConnected:true,focus(){this.focused=true;}};
 const c=vm.createContext({document:{activeElement:editor},btn:(cls,text)=>({cls,text,setAttribute(k,v){this[k]=v;}}),el:(tag,cls,text)=>({tag,cls,text}),target});
 vm.runInContext(source.slice(source.indexOf('function showError('),source.indexOf('function error(')),c);c.message='First failure';vm.runInContext('showError(target,message)',c);assert(!target.hidden);assert.equal(target.children[1]['aria-label'],'Dismiss error');target.children[1].onclick();assert(target.hidden);assert.equal(editor.value,'Unsaved task');assert(editor.focused);
 c.message='Second failure';vm.runInContext('showError(target,message)',c);assert(!target.hidden);assert.equal(target.children[0].text,'Second failure');
 console.log('API errors PASS: plain and JSON session failures, malformed responses, preserved server errors, independent dismissal and retained editor text.');
})().catch(e=>{console.error(e);process.exitCode=1;});
