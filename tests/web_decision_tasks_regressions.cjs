const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8');
function node(tag,cls,text){return {tag,cls,text,children:[],attrs:{},value:'',isConnected:true,append(...x){this.children.push(...x)},replaceChildren(...x){this.children=x},setAttribute(k,v){this.attrs[k]=v},querySelectorAll(){return []},focus(){},showModal(){this.open=true},close(){this.open=false;this.onclose?.()}};}
const opened=[],drafts=[];
const decision={text:'Мигрираме базата',rationale:'Старата версия няма поддръжка',evidence_timestamp:'00:00:24'};
const detail={id:'m',minutes_revision:'v1',items:{d:{id:'d',kind:'decision',text:decision.text},t:{id:'t',kind:'task',text:'Планирай миграцията'}},decision_items:{'0':'d'},decision_tasks:{d:['t']}};
const c=vm.createContext({detail,state:{settings:{}},notesEditing:false,el:node,linkedText:n=>n,noteButtons:()=>[],reviewBadge:()=>'',sourceBlock:()=>'',noteExplanation:()=>null,
 AtlantaTasks:{meetingGroups:items=>items.map((task,index)=>({task,index,mentions:[task]}))},btn:(cls,text,fn)=>Object.assign(node('button',cls,text),{onclick:fn}),perform:fn=>fn(),openTaskPanel:async id=>opened.push(id),openManualTask:async (...args)=>drafts.push(args)});
vm.runInContext(app.slice(app.indexOf('function noteSection('),app.indexOf('\n// Old one-line tasks')),c);
const flatten=n=>[n,...(n?.children||[]).flatMap(x=>typeof x==='object'?flatten(x):[])];
(async()=>{
 c.input={decisions:[decision]};const row=vm.runInContext("noteSection(input,'decisions','Decisions',false)",c),all=flatten(row);
 assert(all.some(n=>n.attrs['data-decision-id']==='d'));await all.find(n=>n.text==='Task: Планирай миграцията').onclick();assert.deepEqual(opened,['t']);
 await all.find(n=>n.text==='Make task').onclick();assert.equal(drafts[0][0],'m');assert.equal(drafts[0][1].decisionSource.index,0);assert.equal(drafts[0][1].minutesRevision,'v1');assert.equal(drafts[0][1].details,decision.rationale);
 const nodes={'manual-task-dialog':node('dialog'),'manual-task-body':node('div'),'work-project':{value:''}},requests=[];
 const editor=vm.createContext({taskEvidenceTarget:null,renderTaskEvidenceContext(){},view:'tasks',contextProject:()=>'',el:node,$:id=>nodes[id],state:{meetings:[{id:'m',title:'Daily',project_id:'p'}],people:[]},personOptions:()=>[],crypto:{randomUUID:()=> 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'},option:(text,value)=>Object.assign(node('option','',text),{value}),fillProjects:(e,value)=>e.value=value,leaveEdits:async()=>true,validDates:()=>true,editorDirty:{set(){},clear(){},keys:()=>[]},requestDialogClose:async(d,fn)=>fn(),withDialogAction:async(d,fn)=>fn(),withEditorSave:async(box,fn)=>fn(),perform:async fn=>fn(),error(){},refreshAfterItemChange:async()=>{},showCreatedTask(){},revealTask(){},api:async(path,body)=>{requests.push({path,body});return {id:'t'}}});
 vm.runInContext(app.slice(app.indexOf('function btn('),app.indexOf('function option(')),editor);
 vm.runInContext(app.slice(app.indexOf('async function openManualTask('),app.indexOf("$('new-task').onclick=")),editor);
 editor.args=drafts[0][1];await vm.runInContext("openManualTask('m',args)",editor);
 const fields=Object.fromEntries(nodes['manual-task-body'].children.flatMap(n=>n.tag==='label'?[n]:n.children||[]).filter(n=>n.tag==='label').map(n=>[n.text,n.children[0]]));
 assert.equal(fields.Meeting.disabled,true);assert.equal(fields.Project.value,'p');assert.equal(fields.Description.value,decision.rationale);
 await nodes['manual-task-body'].children.at(-1).children.at(-1).onclick();
 assert.equal(requests[0].body.decision_source.text,decision.text);assert.equal(requests[0].body.minutes_revision,'v1');assert.equal(requests[0].body.evidence_timestamp,'00:00:24');assert(!requests[0].body.question_source);
 assert(app.includes("data.derived_sources?.[edge.to_id]"));assert(app.includes("origin.kind==='decision'?'Decision: ':'Question: '"));
 // A shared decision may belong to several meetings: open the occurrence this task came from.
 const sourceCode=app.slice(app.indexOf('for(const edge of data.graph?.relationships||[])',app.indexOf('async function openTaskPanel(')),app.indexOf("const from=el('select');",app.indexOf('async function openTaskPanel(')));
 const sourceNodes=node('div'),navigated=[];
 const links=vm.createContext({sources:sourceNodes,item:{id:'t',history:[{event:'created_from_decision',decision_id:'d',meeting_id:'chosen-meeting'}]},data:{items:[],derived_sources:{d:{id:'d',kind:'decision',text:'Migrate',origin:{meeting_id:'older-meeting'}}},meetings:{'chosen-meeting':{},'older-meeting':{}},graph:{relationships:[{kind:'implements',from_id:'t',to_id:'d'}]}},dialog:{close(){}},btn:(cls,text,fn)=>Object.assign(node('button',cls,text),{onclick:fn}),perform:fn=>fn(),leaveEdits:async()=>true,openMeetingDecision:async(d,mid)=>navigated.push(mid)});
 vm.runInContext(sourceCode,links);await sourceNodes.children[0].onclick();assert.deepEqual(navigated,['chosen-meeting']);
 console.log('Decision tasks PASS: meeting action, rationale, backlink, fixed meeting and guarded Create task payload.');
})().catch(e=>{console.error(e);process.exitCode=1});
