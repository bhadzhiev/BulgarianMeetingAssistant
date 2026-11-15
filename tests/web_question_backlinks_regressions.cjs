// Render the shared meeting question row, then follow its task and source links.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8');
function node(tag,cls,text){return {tag,cls,text,children:[],attrs:{},append(...x){this.children.push(...x)},setAttribute(k,v){this.attrs[k]=v},querySelectorAll(){return []}};}
const q={id:'q1',kind:'question',status:'open',text:'Who checks backup?',answer:null};
const detail={id:'m1',minutes_revision:'v1',items:{q1:q,t1:{id:'t1',kind:'task',text:'Check restore'}},question_items:{'open_questions:0':'q1'},question_tasks:{q1:['t1']}};
const opened=[],created=[],tabs=[];
const c=vm.createContext({detail,state:{settings:{}},notesEditing:false,el:node,compactAction:n=>n,linkedText:n=>n,noteButtons:()=>[],reviewBadge:()=>'',sourceBlock:()=>'',noteExplanation:()=>null,
 statusBadge:s=>node('span','',s.label),btn:(cls,text,fn)=>Object.assign(node('button',cls,text),{onclick:fn}),perform:fn=>fn(),
 openTaskPanel:async id=>opened.push(id),openManualTask:async (...args)=>created.push(args)});
const start=app.indexOf('function noteSection('),end=app.indexOf('\n// Old one-line tasks',start);
vm.runInContext(app.slice(start,end),c);
const flatten=n=>[n,...(n?.children||[]).flatMap(x=>typeof x==='object'?flatten(x):[])];
(async()=>{
 const minutes={open_questions:[{text:q.text,evidence_timestamp:'00:00:12'}]};
 let row=vm.runInContext("noteSection(input,'open_questions','Questions',false)",Object.assign(c,{input:minutes}));
 let all=flatten(row);assert(all.some(n=>n.attrs['data-question-id']==='q1'));
 await all.find(n=>n.text==='Task: Check restore').onclick();assert.deepEqual(opened,['t1']);
 await all.find(n=>n.text==='Make task').onclick();assert.equal(created[0][1].questionSource.index,0);assert.equal(created[0][1].minutesRevision,'v1');
 q.status='answered';q.answer='Ivan';row=vm.runInContext("noteSection(input,'open_questions','Questions',false)",c);all=flatten(row);
 assert(all.some(n=>n.text==='Answered'));assert(all.some(n=>n.text==='Ivan'));assert(!all.some(n=>n.text==='Make task'));
 // Jump to the actual question row, in either meeting tab, without replacing it with transcript navigation.
 const source=app.slice(app.indexOf('async function openMeetingQuestion('),app.indexOf('function questionOrigin('));
 let scrolled=false,highlighted=false;
 Object.assign(c,{openMeeting:async id=>opened.push(id),switchTab:t=>tabs.push(t),document:{querySelector:()=>({closest:()=>true,scrollIntoView(){scrolled=true},classList:{add(){highlighted=true},remove(){}}})},setTimeout:fn=>fn()});
 vm.runInContext(source,c);await vm.runInContext("openMeetingQuestion({id:'q1',origin:{meeting_id:'m1'}})",c);
 assert.equal(tabs.at(-1),'outcomes');assert(scrolled&&highlighted);
 console.log('Question backlinks PASS: actual task button, canonical answer, guarded source descriptor and focused meeting question.');
})().catch(e=>{console.error(e);process.exitCode=1});
