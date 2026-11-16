const fs=require('node:fs'),assert=require('node:assert/strict'),vm=require('node:vm');
const app=fs.readFileSync('web/app.js','utf8'),css=fs.readFileSync('web/style.css','utf8');
const card=app.slice(app.indexOf('function globalTaskRow('),app.indexOf('function decisionRow('));
const badge=card.slice(card.indexOf(" const priority=item.priority"),card.indexOf(' const update=AtlantaTasks.lastUpdate'));
for(const [priority,label] of [['critical','Critical'],['high','High'],['normal','Normal'],['low','Low'],[undefined,'Normal']]){
 const nodes=[],c=vm.createContext({item:{priority},el:(tag,cls,text)=>({tag,cls,text,setAttribute(k,v){this[k]=v}}),meta:{append(n){nodes.push(n)}}});
 vm.runInContext(badge,c);assert.equal(nodes[0].text,label);assert.equal(nodes[0]['aria-label'],'Priority: '+label);
}
const undo=app.slice(app.indexOf('function taskEditUndo('),app.indexOf('\n}',app.indexOf('function taskEditUndo('))+2);
const c=vm.createContext({AtlantaTasks:{workflow:i=>i.workflow_state||'todo'}});vm.runInContext(undo,c);
assert.equal(vm.runInContext("taskEditUndo({priority:'high'},{priority:'low'}).priority",c),'high');
assert.equal(vm.runInContext("taskEditUndo({},{priority:'critical'}).priority",c),'normal');
assert.match(app,/if\(priority.value!==\(item.priority\|\|'normal'\)\)changes.priority=priority.value/);
assert.match(css,/\.task-priority\.critical\{color:var\(--red\)\}/);
assert.match(css,/\.task-priority\.high\{color:var\(--warn-ink\)\}/);
console.log('Task priority PASS: labels, legacy fallback, editor changes and Undo.');
