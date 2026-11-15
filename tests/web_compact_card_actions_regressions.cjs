// Execute the shared controls: names/handlers survive icon conversion and facts are not actions.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8');
class Node{
 constructor(tag,cls='',text=''){this.tag=tag;this.className=cls;this.text=text;this.children=[];this.attrs={};this.classList={add:(...xs)=>this.className+=' '+xs.join(' ')};}
 get textContent(){return this.text+this.children.map(x=>x.textContent||'').join('');}
 set textContent(value){this.text=value;this.children=[];}
 append(...xs){this.children.push(...xs);}replaceChildren(...xs){this.text='';this.children=[];this.append(...xs);}setAttribute(k,v){this.attrs[k]=v;}
}
let calls=0,saves=0,fail=false;
const item={review:'ai'},c=vm.createContext({el:(...a)=>new Node(...a),icon:name=>new Node('svg',name),notesEditing:false,detail:{minutes:{summary:[item]}},structuredClone,
 statusBadge:s=>new Node('span','status',s.label),perform:fn=>fn(),saveMinutes:async()=>{saves++;if(fail)throw Error('Conflict');}});
vm.runInContext(app.slice(app.indexOf('function btn('),app.indexOf('// Inline SVG icons')),c);
vm.runInContext(app.slice(app.indexOf('function compactAction('),app.indexOf('function option(')),c);
vm.runInContext(app.slice(app.indexOf('function reviewBadge('),app.indexOf('// Edit or delete one statement')),c);
const button=new Node('button','danger-text','Delete');button.disabled=true;button.onclick=()=>calls++;
c.button=button;vm.runInContext("compactAction(button,'trash')",c);
assert.equal(button.attrs['aria-label'],'Delete');assert.equal(button.title,'Delete');assert.equal(button.textContent,'Delete');assert.equal(button.disabled,true);button.onclick();assert.equal(calls,1);
assert.equal(button.children[0].className,'trash');assert.equal(button.children[1].className,'sr-only');
let moment;Object.assign(c,{segmentAt:()=>({speaker:'Ivan',text:'Check the backup',start:4,end:8}),detail:{minutes:{summary:[item]},files:[]},showMoment:s=>moment=s});
vm.runInContext(app.slice(app.indexOf('function sourceBlock('),app.indexOf('let notesBase=')),c);
const source=vm.runInContext("sourceBlock('00:00:04')",c);assert.equal(source.children[0].textContent,'00:00:04');assert.equal(source.children[1].tag,'details');assert.equal(source.children[1].children[0].attrs['aria-label'],'Source quotation');assert(source.children[1].children[1].textContent.includes('Check the backup'));source.children[1].children[1].onclick();assert.equal(moment,'00:00:04');
const linked=new Node('button','','Linked task');linked.onclick=()=>calls++;c.linked=linked;const context=vm.runInContext("cardContext('Tasks · 1','taskAdd',[linked],{text:true})",c);assert.equal(context.tag,'details');assert(!context.open);assert.equal(context.children[0].attrs['aria-label'],'Tasks · 1');assert.equal(context.children[0].children[1].className,'');assert.equal(context.children[1],linked);linked.onclick();assert.equal(calls,2);
assert(!/compactAction\((?:make|create),'taskAdd',\{label:true\}/.test(app),'task actions never show a text caption');assert(!app.includes("compactAction(ordered.confirm,'verified',{label:true})"));
c.addTask=new Node('button','','Add another task');const addTask=vm.runInContext("compactAction(addTask,'taskAdd')",c);assert.equal(addTask.attrs['aria-label'],'Add another task');assert.equal(addTask.children[1].className,'sr-only','Add another task has no visible caption');
c.panelHost=new Node('div');const firstPanel=vm.runInContext("cardDisclosure('Source quotation','quote',[linked],panelHost)",c),secondPanel=vm.runInContext("cardDisclosure('Description','notes',[newText],panelHost)",Object.assign(c,{newText:new Node('p','','Full description')}));assert(c.panelHost.hidden);firstPanel.onclick();assert.equal(firstPanel.attrs['aria-expanded'],'true');assert.equal(c.panelHost.hidden,false);secondPanel.onclick();assert.equal(firstPanel.attrs['aria-expanded'],'false');assert.equal(secondPanel.attrs['aria-expanded'],'true');assert.equal(c.panelHost.children[0].hidden,true);secondPanel.onclick();assert(c.panelHost.hidden);
const mark=vm.runInContext("statusMark('verified','Checked against the source')",c);
assert.equal(mark.tag,'span');assert.equal(mark.attrs['aria-label'],'Checked against the source');assert.equal(mark.onclick,undefined);
assert.notEqual(vm.runInContext("workflowIcon('waiting')",c),vm.runInContext("workflowIcon('done')",c));
(async()=>{
 c.item=item;let review=vm.runInContext('reviewBadge(item,false)',c);
 assert.equal(review.children[0].textContent,'Needs check');assert.equal(item.review,'ai');
 await review.children[1].onclick();assert.equal(item.review,'verified');assert.equal(saves,1);
 review=vm.runInContext('reviewBadge(item,false)',c);assert.equal(review.children[0].tag,'span');assert.equal(review.children[0].attrs['aria-label'],'Checked against the source');assert.equal(review.children[1].attrs['aria-label'],'Undo check');
 fail=true;await assert.rejects(review.children[1].onclick(),/Conflict/);assert.equal(item.review,'verified','failed writes restore the previous review');
 fail=false;await review.children[1].onclick();assert.equal(item.review,'ai');
 assert.equal(vm.runInContext('reviewBadge(item,true)',c).children[1].disabled,true);
 console.log('Compact card controls PASS: accessible icons, handlers and disabled state preserved, passive status, source check/undo and failed-save rollback.');
})().catch(e=>{console.error(e);process.exitCode=1});
