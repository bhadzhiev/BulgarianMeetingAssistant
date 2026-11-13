const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const src=fs.readFileSync('web/app.js','utf8'),html=fs.readFileSync('web/index.html','utf8'),css=fs.readFileSync('web/style.css','utf8');
// The project goal is optional free text (≤500) that travels with the project name to the AI task matching.
const dialog=html.match(/<dialog id="project-dialog"[\s\S]*?<\/dialog>/)[0];
assert.ok(dialog.includes('id="project-goal"'),'New project dialog has a goal field');
assert.ok(dialog.includes('maxlength="500"'),'the goal field caps at 500 characters like the backend');
assert.ok(dialog.includes('The goal goes with the project name when the AI matches work to projects.'),'the hint says where the goal goes');
assert.ok(src.includes("$('project-goal').value=''"),'askProject clears a previous goal');
assert.ok(src.includes("goal:$('project-goal').value.trim()"),'askProject returns the goal with the name and color');
(async()=>{
 // goalBlock shows the goal, edits it inline and saves through the shared change action.
 const el=(tag,cls,text)=>({tag,className:cls,textContent:text??'',children:[],setAttribute(){},append(...n){this.children.push(...n);},replaceChildren(...n){this.children=n;},focus(){}});
 const btn=(cls,text,fn)=>({type:'button',className:cls,textContent:text,onclick:fn,children:[]});
 const calls=[];let rendered=0;
 const c=vm.createContext({el,btn,perform:fn=>fn(),state:{projects:[]},api:async(path,body)=>{calls.push([path,body]);return {projects:[{id:'p1',name:'Platform',goal:body.value}]};},
  syncProjects:()=>calls.push('sync'),renderProjectSettings:()=>{rendered++;calls.push('render');},toast:()=>{},lastProjects:'x'});
 const goalBlock=vm.runInContext(src.slice(src.indexOf('const goalBlock=project=>'),src.indexOf('for(const project of projectList())'))+';goalBlock',c);
 const block=goalBlock({id:'p1',name:'Platform',goal:'Ship the sync rework'});
 assert.equal(block.className,'project-goal');assert.equal(block.children[0].textContent,'Ship the sync rework');
 const empty=goalBlock({id:'p1',name:'Platform'});
 assert.ok(empty.children[0].textContent.startsWith('No goal yet.'),'a goal-less project explains what the goal is for');
 await block.children[1].onclick(); // Edit goal
 const area=block.children[0];assert.equal(area.maxLength,500);assert.equal(area.value,'Ship the sync rework');
 area.value='  Deliver the sync rework this quarter  ';
 await block.children[1].children[0].onclick(); // Save
 assert.deepEqual(JSON.parse(JSON.stringify(calls)),[['/api/projects/change',{kind:'projects',id:'p1',action:'goal',value:'  Deliver the sync rework this quarter  '}],'sync','render']);
 assert.equal(JSON.parse(JSON.stringify(c.state.projects))[0].goal,'  Deliver the sync rework this quarter  ');
 console.log('Project goal PASS: dialog field and hint, askProject returns the goal, Settings block shows, edits and saves inline.');
})().catch(e=>{console.error(e);process.exitCode=1;});
