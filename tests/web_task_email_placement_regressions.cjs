// Execute the actual task-card builder: the draft envelope has one stable home in every layout.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8');
class Node{
 constructor(tag,cls='',text=''){this.tag=tag;this.className=cls;this.textContent=text;this.children=[];this.attrs={};this.dataset={};this.style={setProperty(){}};this.classList={add:(...c)=>{this.className+=' '+c.join(' ')},remove(){},replace(){}};}
 append(...nodes){for(const n of nodes){if(n instanceof Node){if(n.parent)n.parent.children=n.parent.children.filter(x=>x!==n);n.parent=this;}this.children.push(n);}}
 prepend(...nodes){for(const n of nodes.reverse()){if(n instanceof Node){if(n.parent)n.parent.children=n.parent.children.filter(x=>x!==n);n.parent=this;}this.children.unshift(n);}}
 before(n){const p=this.parent;p.children.splice(p.children.indexOf(this),0,n);n.parent=p;}
 replaceChildren(...nodes){for(const n of this.children)if(n instanceof Node)n.parent=null;this.children=[];this.append(...nodes);}
 closest(){return null;}focus(){this.focused=true;}
 setAttribute(k,v){this.attrs[k]=v;}removeAttribute(k){delete this.attrs[k];}
 get childNodes(){return this.children;}get firstElementChild(){return this.children.find(n=>n instanceof Node);}get lastElementChild(){return this.children.filter(n=>n instanceof Node).at(-1);}
}
const el=(...args)=>new Node(...args),button=(cls,text,fn)=>Object.assign(el('button',cls,text),{onclick:fn});
const c=vm.createContext({el,btn:button,actionBtn:button,state:{people:[]},projectList:()=>[],taskCoAssignees:()=>[],avatar:()=>el('span','speaker-badge'),
 dueInfo:()=>['none','No due date'],AtlantaTasks:{STATES:{todo:'To do'},workflow:()=> 'todo',lastUpdate:i=>i.update},workReviewBadge:()=>'',
 dateTime:x=>x,icon:()=>el('svg','icon'),document:{createTextNode:t=>t},itemsData:{meetings:{}},itemProviders:()=>new Set(),daysBetween:()=>0,date:x=>x,taskMeetingList:()=>null,sourceChips:()=>el('div'),
 personOptions:()=>[],option:(text,value)=>Object.assign(el('option','',text),{value}),personFor:()=>null,openTaskFields:new Set(),openTaskFieldKinds:new Map(),doneButton:()=>button('secondary','Mark done'),itemActions:()=>el('div')});
 vm.runInContext(app.slice(app.indexOf('function compactAction('),app.indexOf('function option(')),c);
 vm.runInContext(app.slice(app.indexOf('function cardDetails('),app.indexOf('function decisionRow(')),c);
vm.runInContext(app.slice(app.indexOf('function emailMark('),app.indexOf('let taskEmailItems')),c);
vm.runInContext(app.slice(app.indexOf('function globalTaskRow('),app.indexOf('function taskDescription(')),c);
const flatten=n=>[n,...(n.children||[]).filter(x=>x instanceof Node).flatMap(flatten)];
for(const nested of [false,true])for(const withUpdate of [false,true]){
 const item={id:'t',kind:'task',text:'Провери backup',owner:null,links:[],status:'open',acceptance_state:'accepted',email_draft:{saved_at:'2026-11-15',to:['a@example.test']},update:withUpdate?{text:'Backup checked',at:'2026-11-15'}:null};
 c.item=item;c.nested=nested;
 const row=vm.runInContext("globalTaskRow(item,'2026-11-15',{select:false,nested})",c),all=flatten(row),marks=all.filter(n=>n.className==='email-mark');
 const state=all.find(n=>n.className==='task-fact task-state');
 // A subtask row shows the owner and the due date only; the main card shows every fact once, read-only.
 if(nested)assert.equal(state,undefined);else{assert.equal(state.tag,'span');assert.equal(state.onclick,undefined);}assert(!all.some(n=>n.tag==='select'||n.tag==='input'||n.className==='task-quick-fields'));
 const open=all.find(n=>n.attrs['aria-label']==='Open task');assert(open,'the task has an explicit open action');
 assert.equal(marks.length,1);assert.equal(marks[0].parent.className,'task-tile-tags');
 assert.equal(marks[0].parent.parent.className,nested?'task-tile-line':'entity-top task-tile-head');
 assert.equal(marks[0].children.length,nested?1:2,'a subtask row shows only the envelope');
 assert(marks[0].attrs['aria-label'].includes('Email draft saved in Gmail'));
 assert(!all.filter(n=>['tracked-meta task-tile-facts','task-update'].includes(n.className)).some(n=>n.children.includes(marks[0])));
}
console.log('Task draft placement PASS: one accessible envelope in the card tags, main card and subtask row, with/without updates.');
