const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8'),css=fs.readFileSync('web/style.css','utf8');
const slice=(a,b)=>{const at=app.indexOf(a);assert.notEqual(at,-1,a);return app.slice(at,app.indexOf(b,at));};
// Task editor tabs (2026-11-20): Details, Subtasks and History & activity group the parts the editor already had.
const panel=slice('async function openTaskPanel(','\n}\n');
assert.match(panel,/taskTabs\(\[\['details','Details',\[describe,label\('Expected result',criterion\),progress,sourcesSection\]\],\.\.\.\(hierarchy\?\.childNodes\.length\?\[\['subtasks','Subtasks',\[hierarchy\]\]\]:\[\]\),\['history','History & activity',\[historySection\]\]\]\)/,'a proposed task has no Subtasks tab');
assert.match(panel,/tabs\.count\('subtasks',children\.filter\(t=>AtlantaTasks\.workflow\(t\)==='done'\)\.length\+'\/'\+children\.length\)/,'Subtasks shows done of all');
assert.match(panel,/tabs\.count\('history',String\(timeline\.querySelectorAll\('\.task-timeline-event'\)\.length\|\|''\)\)/,'History shows the number of saved events');
assert.match(panel,/const wrong=tabs\.panels\.find\(panel=>panel\.querySelector\(':invalid,\[aria-invalid=true\]'\)\);if\(wrong\)tabs\.show\(wrong\.dataset\.tab\);/,'an error opens its tab');
assert.equal(panel.match(/box\.append\(taskFormLayout\(/g).length,1,'the editor adds its layout once');
// Behaviour: one panel shows; the tabs are an accessible tablist with arrow keys.
{
 const node=(tag,cls='',text='')=>({tag,className:cls,textContent:text,children:[],attrs:{},dataset:{},hidden:false,tabIndex:0,append(...k){this.children.push(...k);},setAttribute(k,v){this.attrs[k]=v;},focus(){c.document.activeElement=this;}});
 const c=vm.createContext({el:node,btn:(cls,text,fn)=>Object.assign(node('button',cls,text),{onclick:fn}),document:{activeElement:null}});
 vm.runInContext(slice('function taskTabs(','function taskFormClose('),c);
 const tabs=vm.runInContext("taskTabs([['details','Details',[]],['subtasks','Subtasks',[]],['history','History & activity',[]]])",c);
 const [details,subtasks,history]=tabs.bar.children;
 assert.equal(tabs.bar.attrs.role,'tablist');assert.deepEqual(Array.from(tabs.bar.children,t=>t.attrs.role),['tab','tab','tab']);
 assert.deepEqual(Array.from(tabs.panels,p=>p.hidden),[false,true,true]);assert.equal(details.attrs['aria-selected'],'true');assert.equal(subtasks.tabIndex,-1);
 history.onclick();assert.deepEqual(Array.from(tabs.panels,p=>p.hidden),[true,true,false]);assert.equal(history.attrs['aria-controls'],tabs.panels[2].id);
 history.focus();let prevented=false;tabs.bar.onkeydown({key:'ArrowRight',preventDefault(){prevented=true;}});assert.ok(prevented);assert.equal(c.document.activeElement,details);assert.equal(tabs.panels[0].hidden,false);
 tabs.count('subtasks','1/3');assert.equal(subtasks.children[0].textContent,'1/3');assert.equal(subtasks.children[0].hidden,false);tabs.count('history','');assert.equal(history.children[0].hidden,true);
}
assert.match(css,/#task-panel \.task-tab\[aria-selected=true\]\{color:var\(--green\);border-bottom-color:var\(--green\)\}/);
console.log('Task editor tabs PASS: Details, Subtasks and History & activity, counts, errors open their tab, arrow keys.');
