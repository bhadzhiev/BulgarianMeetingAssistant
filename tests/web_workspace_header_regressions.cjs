const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('web/app.js','utf8');
class Node {
 constructor(id){this.id=id;this.children=[];this.dataset={};this.attrs={};this.tokens=new Set();this.classList={toggle:(key,on)=>on?this.tokens.add(key):this.tokens.delete(key)};}
 append(...nodes){for(const n of nodes){if(n.parentElement)n.parentElement.children=n.parentElement.children.filter(child=>child!==n);n.parentElement=this;this.children.push(n);}}
 prepend(n){this.append(n);this.children=[n,...this.children.filter(c=>c!==n)];}
 replaceChildren(){for(const n of this.children)n.parentElement=null;this.children=[];}
 querySelector(selector){return this.children.find(n=>selector==='.heading'&&n.heading)||null;}
 setAttribute(key,value){this.attrs[key]=value;}
}
const nodes=new Map(),get=id=>{if(!nodes.has(id))nodes.set(id,new Node(id));return nodes.get(id);};
const libraries=['conversations','calendar','find','analytics'];
for(const id of ['tasks','projects',...libraries]){const heading=get(id+'-heading');heading.heading=true;get(id).append(heading);}
get('tasks-heading').append(get('new-task'));get('project-toolbar').append(get('workspace-new'));get('header-action-home').append(get('header-import'));
let clicks=0;get('new-task').onclick=()=>clicks++;
const c=vm.createContext({$:get,LIBRARY_VIEWS:libraries,document:{querySelector:selector=>{assert.equal(selector,'main');return get('main');}}});
vm.runInContext(source.slice(source.indexOf('let mountedPageHeader='),source.indexOf('function show(which)')),c);
const show=key=>vm.runInContext(`syncPageHeader(${JSON.stringify(key)})`,c);
show('tasks');assert.equal(get('page-header').children[0],get('tasks-heading'));get('new-task').onclick();assert.equal(clicks,1);
show('projects');assert.equal(get('tasks-heading').parentElement,get('tasks'));assert.equal(get('workspace-new').parentElement,get('projects-heading'));show('projects');assert.equal(get('page-header').children.length,1);
for(const id of libraries){show(id);assert.equal(get('header-import').parentElement,get(id+'-heading'));assert.equal(get('page-header').children.length,1);assert.equal(get('workspace-new').parentElement,get('project-toolbar'));}
show('tasks');assert.equal(get('header-import').parentElement,get('header-action-home'));assert.equal(get('page-header').children[0],get('tasks-heading'));
show('setup');assert(get('page-header').hidden);assert.equal(get('page-header').children.length,0);assert(!get('main').tokens.has('compact-header'));assert.equal(get('tasks-heading').parentElement,get('tasks'));
for(const [message,status] of [['Connecting…','pending'],['● Connected to this Mac','connected'],['● Recording workspace','recording'],['Disconnected · check the desktop app','error']]){c.message=message;vm.runInContext('setConnection(message)',c);assert.equal(get('connection').dataset.status,status);assert.equal(get('connection').attrs['aria-label'],message);assert.equal(get('connection').title,message);}
console.log('Workspace header PASS: headings and actions retain identity through every view, setup restores them, and connection states remain accessible.');
