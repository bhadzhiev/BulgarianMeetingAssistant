const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),Tasks=require('../web/task-model.js');
const first={item_id:'t',task:'Check rollout',evidence_timestamp:'00:00:01'},second={item_id:'t',task:'Check it again',evidence_timestamp:'00:00:09'},other={item_id:'other',task:'Check rollout'},unlinked={task:'Check rollout'};
const input=[first,second,other,unlinked],groups=Tasks.meetingGroups(input);
assert.equal(groups.length,3);assert.deepEqual(groups[0].mentions,[first,second]);assert.equal(groups[1].index,2);assert.equal(groups[2].index,3);assert.equal(input.length,4);
function node(tag,cls='',text=''){return {tag,cls,text,children:[],attrs:{},setAttribute(k,v){this.attrs[k]=v},append(...x){this.children.push(...x)},prepend(...x){this.children.unshift(...x)}};}
const walk=n=>[n,...(n.children||[]).filter(n=>n&&typeof n==='object').flatMap(walk)];
const item={id:'t',text:'Check rollout',kind:'task',owner:null,status:'open',acceptance_state:'accepted',review_state:'confirmed',links:[{meeting_id:'m'}]};
const c=vm.createContext({el:node,btn:(cls,text,onclick)=>Object.assign(node('button',cls,text),{onclick}),icon:()=>node('svg'),workflowIcon:()=> 'clock',AtlantaTasks:{STATES:{waiting:'Waiting'},workflow:()=> 'waiting'},compactAction:n=>n,detail:{id:'m',items:{t:item}},state:{task_summary:{today:'2026-11-06'}},dueInfo:()=>['normal','No date'],avatar:()=>node('span'),workReviewBadge:s=>node('span','review',s),
 reviewBadge:()=>{throw new Error('Canonical tasks must not expose a second note Checked button')},sourceBlock:stamp=>node('button','source',stamp),doneButton:()=>node('button'),rowMenu:()=>node('details'),githubActions:()=>node('div'),perform:fn=>fn(),mentions:[first,second],task:first});
const source=fs.readFileSync('web/app.js','utf8');vm.runInContext(source.slice(source.indexOf('let cardPanelSequence='),source.indexOf('function option(')),c);vm.runInContext(source.slice(source.indexOf('function taskRow('),source.indexOf('function renderNotes(')),c);
const rendered=vm.runInContext('taskRow(task,0,false,mentions)',c),nodes=walk(rendered);
assert.equal(nodes.filter(n=>n.cls==='review').length,1);assert.equal(nodes.find(n=>n.cls==='review').text,'confirmed');
assert.deepEqual(nodes.filter(n=>n.cls==='source').map(n=>n.text),['00:00:01','00:00:09']);assert.ok(nodes.some(n=>n.text==='2 mentions in this meeting'));
assert(nodes.some(n=>n.cls==='meeting-task-state'&&n.text==='Waiting'));
assert(nodes.find(n=>n.cls==='tracked-meta').children.some(n=>n.tag==='div'),'GitHub shares the facts row');
assert.match(source,/if\(owners\.length>1\)row\.classList\.add\('owner-grouped'\)/);
item.details='Full description stays available';c.taskDescription=text=>node('p','task-description',text);
const described=vm.runInContext('taskRow(task,0,false,mentions)',c),describedNodes=walk(described);
const facts=describedNodes.find(n=>n.cls==='tracked-meta'),description=facts.children.find(n=>n.text==='Description'),panels=describedNodes.find(n=>n.cls==='card-expansions');
assert(description&&panels.hidden,'description starts closed, with its control on the facts line');
assert(walk(panels).some(n=>n.text==='Full description stays available'),'full description is preserved in the expansion row');description.onclick();assert.equal(panels.hidden,false);assert.equal(description.attrs['aria-expanded'],'true');assert(facts.children.includes(description),'opening the description does not move the control');description.onclick();assert.equal(panels.hidden,true);
console.log('Meeting task groups PASS: one card per ID, all evidence kept, distinct IDs/unlinked mentions preserved and one canonical review badge.');
