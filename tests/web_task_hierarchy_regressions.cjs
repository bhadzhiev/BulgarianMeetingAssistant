const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const src=fs.readFileSync('web/app.js','utf8');
class Node{
 constructor(tag,cls,text){Object.assign(this,{tag,className:cls,textContent:text,children:[],value:'',checked:false,disabled:false,hidden:false,attrs:{}});}
 append(...nodes){for(const n of nodes){this.children.push(n);if(this.tag==='select'&&n.tag==='option'&&!this.value)this.value=n.value;}}
 replaceChildren(...nodes){this.children=nodes;}
 setAttribute(k,v){this.attrs[k]=v;}
 focus(){} showModal(){this.open=true;} close(){this.open=false;}
 querySelectorAll(){return this.children.flatMap(n=>[...(n.tag==='input'?[n]:[]),...(n.querySelectorAll?.()||[])]);}
}
const el=(...args)=>new Node(...args),nodes={},$=id=>nodes[id]??=el('div');
const task=(id,extra={})=>({id,kind:'task',text:'Task '+id,revision:1,status:'open',acceptance_state:'accepted',...extra});
const data={items:[task('root'),task('a',{parent_task_id:'root'}),task('b'),task('c',{owner:'Maria'}),task('proposal',{acceptance_state:'proposed'}),task('hidden',{dismissed:true})]},requests=[],opened=[];
const context=vm.createContext({el,$,itemsData:data,AtlantaTasks:require('../web/task-model.js'),Set,Map,btn:(cls,text,fn)=>Object.assign(el('button',cls,text),{onclick:fn}),option:(text,value)=>Object.assign(el('option','',text),{value}),date:v=>v,leaveEdits:async()=>true,toast(){},perform:fn=>fn(),withDialogAction:async(d,fn)=>fn(),editorDirty:{clear(){},set(){}},taskSelection:new Map(),crypto:{randomUUID:()=>'f'.repeat(32)},refreshAfterItemChange:async()=>{},openTaskPanel:async id=>opened.push(id),api:async(path,body)=>{if(!body)return data;requests.push({path,body});return {parent_id:'new'};},globalTaskRow:item=>el('card','',item.id)});
vm.runInContext(src.slice(src.indexOf('function hierarchyTasks('),src.indexOf('async function openTaskPanel(')),context);
(async()=>{
 await vm.runInContext("openTaskHierarchy({parentId:'root'})",context);
 const body=$('task-hierarchy-body'),list=body.children.find(n=>n.className==='hierarchy-picker-list');
 assert.equal(list.children.length,2,'only independent accepted visible tasks can be added');
 assert($('task-hierarchy-save').disabled);
 const search=body.children.find(n=>n.attrs['aria-label']==='Search existing tasks');search.value='Maria';search.oninput();
 const all=body.children.find(n=>n.tag==='button');all.onclick();await $('task-hierarchy-save').onclick();
 assert.deepEqual(JSON.parse(JSON.stringify(requests[0].body.items)),[{id:'c',revision:1}]);
 assert.equal(requests[0].body.parent_id,'root');assert.equal(requests[0].body.parent_revision,1);
 await vm.runInContext("openTaskHierarchy({childIds:['b']})",context);
 const title=$('task-hierarchy-body').children.find(n=>n.attrs['aria-label']==='New main task title');title.value='New programme';title.oninput();
 await $('task-hierarchy-save').onclick();assert.equal(requests[1].body.new_parent_title,'New programme');
 assert.equal(requests[1].body.items[0].id,'b');
 const tree=vm.runInContext("renderTaskTree(itemsData.items.slice(0,3),'2026-11-16',{})",context);
 assert.equal(tree.length,2,'child appears once beneath its main task');
 assert.equal(tree[0].children[1].children[1].textContent,'a');
 const filtered=vm.runInContext("renderTaskTree([itemsData.items[1]],'2026-11-16',{})",context);assert.equal(filtered[0].textContent,'a','child stays visible when its parent is filtered out');
 const card=vm.runInContext("taskHierarchyBadge(itemsData.items[0])",context);assert.equal(card.textContent,'0 / 1 subtasks done');
 console.log('Task hierarchy PASS: eligible picker, search/select, atomic create payload, revision checks and filtered tree.');
})().catch(e=>{console.error(e);process.exitCode=1});
