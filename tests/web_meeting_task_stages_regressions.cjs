const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('web/app.js','utf8');
function node(tag,cls='',text=''){return {tag,cls,text,children:[],attrs:{},setAttribute(k,v){this.attrs[k]=v;},append(...v){this.children.push(...v);},prepend(...v){this.children.unshift(...v);}};}
const walk=n=>[n,...(n.children||[]).filter(n=>n&&typeof n==='object').flatMap(walk)];
const created=[],changed=[];
const saved={id:'saved',kind:'task',text:'Saved task',status:'open',owner:'Maria',acceptance_state:'accepted',links:[{meeting_id:'m'}]},proposal={...saved,id:'proposal',text:'Proposal',acceptance_state:'proposed'};
const c=vm.createContext({el:node,btn:(cls,text,onclick)=>Object.assign(node('button',cls,text),{onclick}),state:{settings:{meeting_task_ai:false},task_summary:{today:'2026-11-16'}},detail:{id:'m',items:{saved,proposal}},AtlantaTasks:{STATES:{todo:'To do'},workflow:()=> 'todo'},date:v=>v,dueInfo:()=>['overdue','Overdue'],avatar:()=>node('span'),workReviewBadge:()=>'',reviewBadge:()=>'',sourceBlock:()=>node('div'),doneButton:()=>node('button','','Mark done'),icon:()=>node('svg'),workflowIcon:()=> 'circle',compactAction:(n,icon,options)=>Object.assign(n,{labelVisible:options?.label===true}),githubActions:()=>node('div'),perform:fn=>fn(),openManualTask:(...args)=>created.push(args),changeItem:(...args)=>changed.push(args),openTaskInbox(){},changeWithUndo(){}});
vm.runInContext(source.slice(source.indexOf('function taskRow('),source.indexOf('function meetingTaskEmailButton(')),c);
function render(task,busy=false){c.task=task;c.busy=busy;const row=vm.runInContext('taskRow(task,0,busy)',c);return {row,nodes:walk(row)};}
(async()=>{
 const note={task:'Check the environments',owner:'Maria',due_date:'2026-11-10'};
 let {row,nodes}=render(note);assert.equal(row.attrs['data-task-stage'],'suggestion');assert(!row.cls.includes('overdue'),'an uncreated suggestion is not an overdue task');
 assert(nodes.some(n=>n.text==='Suggestion from notes'));assert(nodes.some(n=>n.text==='Not in My Work · create a task to track it'));
 assert(nodes.some(n=>n.text==='Suggested owner: Maria'));assert(nodes.some(n=>n.text==='Suggested due: 2026-11-10'));
 assert(!nodes.some(n=>n.cls==='meeting-task-state'));
 const create=nodes.find(n=>n.text==='Create task in My Work…');assert(create.labelVisible);await create.onclick();assert.equal(created.length,1);assert.equal(created[0][1].mention,0);assert.equal(changed.length,0,'opening the editor does not accept a task');
 assert(render({...note,due_date:null,deadline:'петък'}).nodes.some(n=>n.text==='Suggested deadline: петък'));
 assert(!render({...note,due_date:null,deadline:'петък'}).nodes.some(n=>n.text==='No deadline proposed'));
 assert(render(note,true).nodes.find(n=>n.text==='Create task in My Work…').disabled);
 ({row,nodes}=render({item_id:'saved',task:'Saved task'}));assert.equal(row.attrs['data-task-stage'],'task');assert(nodes.some(n=>n.text==='Task in My Work'));assert(nodes.some(n=>n.cls==='meeting-task-state'));assert(!nodes.some(n=>n.text==='Create task in My Work…'));
 ({row,nodes}=render({item_id:'proposal',task:'Proposal'}));assert.equal(row.attrs['data-task-stage'],'suggestion','hidden proposals stay uncreated note suggestions when AI task proposals are off');
 vm.runInContext('state.settings.meeting_task_ai=true',c);
 ({row,nodes}=render({item_id:'proposal',task:'Proposal'}));assert.equal(row.attrs['data-task-stage'],'proposal');assert(nodes.some(n=>n.text==='Waiting for acceptance in Inbox'));assert(!nodes.some(n=>n.cls==='meeting-task-state'));
 const accept=nodes.find(n=>n.text==='Accept into My Work');assert(accept.labelVisible);await accept.onclick();assert.equal(changed[0][1].acceptance_state,'accepted');
 assert(render({task:'Possible duplicate',link:true}).nodes.some(n=>n.text==='Possible task match'));
 console.log('Meeting task stages PASS: saved task, pending proposal, uncreated suggestion, labelled actions and no premature state changes.');
})().catch(e=>{console.error(e);process.exitCode=1});
