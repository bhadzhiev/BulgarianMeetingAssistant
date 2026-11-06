const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const src=fs.readFileSync('web/app.js','utf8');
function el(tag,cls='',text=''){return {tag,cls,text,children:[],append(...nodes){this.children.push(...nodes)}};}
const walk=n=>[n,...n.children.filter(n=>typeof n==='object'&&n.children).flatMap(walk)],calls=[];
const c=vm.createContext({el,projectList:()=>[{id:'p',name:'Platform'}],document:{createTextNode:text=>({text})},perform:fn=>fn(),graphAction:async(...args)=>calls.push(args)});
vm.runInContext(src.slice(src.indexOf('function projectAssignment('),src.indexOf('// Saved links between work items')),c);
c.item={id:'task',revision:7,project_ids:null,effective_project_ids:[]};let box=vm.runInContext('projectAssignment(item)',c),nodes=walk(box);
assert.ok(nodes.find(n=>n.cls==='hint').text.startsWith('No project inherited.'));
const actions=nodes.find(n=>n.cls.includes('project-assignment-actions'));assert.equal(actions.children.length,2);assert.equal(actions.children[0].cls,'primary small-action');
nodes.find(n=>n.tag==='input').checked=true;
(async()=>{await actions.children[0].onclick();assert.equal(JSON.stringify(calls[0]),JSON.stringify(['project',{id:'task',revision:7,project_ids:['p']}]));await actions.children[1].onclick();assert.equal(calls[1][1].project_ids,null);
c.item.project_ids=[];box=vm.runInContext('projectAssignment(item)',c);assert.match(walk(box).find(n=>n.cls==='hint').text,/^Manual assignment/);
c.item.project_ids=null;c.item.effective_project_ids=['p'];box=vm.runInContext('projectAssignment(item)',c);assert.equal(walk(box).find(n=>n.cls==='hint').text,'Inherited from linked meetings');
console.log('Project assignment PASS: grouped actions, explicit save, inherited vs manual projects and unchanged revision-checked payloads.');})().catch(e=>{console.error(e);process.exitCode=1});
