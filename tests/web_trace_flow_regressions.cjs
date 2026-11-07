const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('web/app.js','utf8');
function el(tag,cls='',text=''){return {tag,cls,text,attrs:{},children:[],append(...nodes){this.children.push(...nodes)},replaceChildren(...nodes){this.children=nodes},setAttribute(k,v){this.attrs[k]=v}};}
const walk=n=>[n,...(n.children||[]).filter(n=>typeof n==='object').flatMap(walk)];
const opened=[];
const context=vm.createContext({el,STATUS_LABELS:{},date:d=>d,time:s=>String(s),stampSeconds:()=>0,
 workspaceData:{items:[{id:'t1',kind:'task'}]},perform:async fn=>fn(),openTaskPanel:async id=>opened.push(['task',id]),
 openMeeting:async id=>opened.push(['meeting',id]),showSeconds:()=>{},listenButton:()=>el('button','play'),openAttachment:async()=>{},
 show:()=>{throw new Error('Task trace must open the card directly')},loadTasks:async()=>{},showWorkTab:()=>{}});
vm.runInContext(source.slice(source.indexOf('function btn('),source.indexOf('function option(')),context);
 vm.runInContext(source.slice(source.indexOf('const TRACE_STAGES='),source.indexOf("let timelineView='chains';")),context);
const task={kind:'task',label:'Подготовка на тестова среда за мобилното приложение и описание на стъпките за новия колега',ref:{item_id:'t1'}};
const stageNodes=Array.from({length:8},(_,i)=>({kind:'meeting',label:'Планиране на миграцията към новия сървър за отчети '+i,ref:{meeting_id:'m'+i}}));
context.chain={stages:{conversation:stageNodes,decision:[],task:[task],github:[],code:[]}};
const card=vm.runInContext('traceCard(chain)',context),nodes=walk(card);
assert.equal(nodes.filter(n=>n.cls==='trace-stage').length,2,'Only linked stages consume columns');
assert.ok(nodes.find(n=>n.cls==='trace-missing').text.includes('Decision · Issue / PR · Code change'));
const more=nodes.find(n=>n.cls.includes('trace-expand'));
assert.equal(nodes.filter(n=>n.cls==='trace-step').length,7);
more.onclick();assert.equal(walk(card).filter(n=>n.cls==='trace-step').length,9);assert.equal(more.attrs['aria-expanded'],'true');
more.onclick();assert.equal(walk(card).filter(n=>n.cls==='trace-step').length,7);assert.equal(more.attrs['aria-expanded'],'false');
const taskButton=nodes.find(n=>n.title===task.label);assert.ok(taskButton);assert.equal(walk(taskButton).find(n=>n.cls==='trace-label').text,task.label);
(async()=>{await taskButton.onclick();assert.deepEqual(opened,[['task','t1']]);
 const meeting=nodes.find(n=>n.title===stageNodes[0].label);await meeting.onclick();assert.deepEqual(opened.at(-1),['meeting','m0']);
 context.external={kind:'issue',label:'GitHub issue',ref:{url:'https://github.com/example/repo/issues/1'}};
 const link=vm.runInContext('traceNode(external)',context);assert.equal(link.tag,'a');assert.equal(link.rel,'noopener noreferrer');assert.equal(link.href,context.external.ref.url);
 console.log('Trace flow PASS: sparse stages, full titles, accessible expansion and direct task/meeting navigation.');
})().catch(e=>{console.error(e);process.exitCode=1});
