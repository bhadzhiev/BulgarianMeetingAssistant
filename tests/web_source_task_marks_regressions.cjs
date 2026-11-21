const fs=require('node:fs'),assert=require('node:assert/strict'),vm=require('node:vm');
const app=fs.readFileSync('web/app.js','utf8'),css=fs.readFileSync('web/style.css','utf8');
const slice=(a,b)=>{const at=app.indexOf(a);assert.notEqual(at,-1,a);return app.slice(at,app.indexOf(b,at));};
// A source with a task shows a green task mark in its row; the mark opens the task, the row still opens the source.
const code=slice('function itemSources(','\n')+'\n'+slice('let sourceTaskData=','// The marks follow the tasks');
const opened=[],c=vm.createContext({itemsData:null,perform:fn=>fn(),openTaskPanel:id=>opened.push(id),
 icon:()=>({kind:'icon'}),el:(tag,cls,text)=>{const n={tag,className:cls||'',textContent:text||'',children:[],attrs:{},append(...k){n.children.push(...k);},setAttribute(k,v){n.attrs[k]=v;}};return n;}});
vm.runInContext(code+';this.sourceTasks=sourceTasks;this.sourceTaskMark=sourceTaskMark;this.sourceTitle=sourceTitle;',c);
const task=(id,status,evidence,extra={})=>({id,kind:'task',status,text:'Task '+id,source_evidence:evidence,...extra});
c.itemsData={items:[task('a','open',['e1']),task('b','done',['e2']),task('c','open',['e3']),task('d','open',['e1'],{dismissed:true}),{id:'q',kind:'question',source_evidence:['e1']}],
 graph:{sources:[{id:'s1',provider:'github',external_id:'issue:7'},{id:'s2',provider:'gmail',external_id:'thread-1'},{id:'s3',provider:'github',external_id:'issue:7'}],
  source_evidence:[{id:'e1',source_id:'s1'},{id:'e2',source_id:'s2'},{id:'e3',source_id:'s3'}]}};
assert.deepEqual(Array.from(c.sourceTasks('github','issue:7'),t=>t.id),['a','c']);
assert.deepEqual(Array.from(c.sourceTasks('gmail','thread-1'),t=>t.id),['b']);
assert.equal(c.sourceTasks('github','issue:8').length,0);assert.equal(c.sourceTaskMark([]),null);
// Several tasks show a count; the mark opens the first open task and never the source behind it.
const mark=c.sourceTaskMark(c.sourceTasks('github','issue:7'));
assert.equal(mark.className,'row-task-link');assert.equal(mark.children[1].textContent,'2');assert.equal(mark.attrs['aria-label'],'2 tasks from this source. Open task: Task a');
let stopped=false;mark.onclick({stopPropagation:()=>stopped=true});assert.equal(stopped,true);assert.deepEqual(opened,['a']);
// Only closed tasks: a muted mark.
assert.equal(c.sourceTaskMark(c.sourceTasks('gmail','thread-1')).className,'row-task-link done');
// A new itemsData object rebuilds the index.
c.itemsData={...c.itemsData,items:[]};assert.equal(c.sourceTasks('github','issue:7').length,0);
// GitHub items, Gmail threads and Chat messages carry the mark; the marks follow every task reload.
assert.match(app,/sourceTitle\('strong',r\.title,sourceTasks\('github','issue:'\+r\.issue_id\)\)/);
assert.match(app,/sourceTitle\('span',t\.subject,sourceTasks\('gmail',t\.id\)\)/);
assert.match(app,/const taskMark=sourceTaskMark\(sourceTasks\('google_chat',m\.name\)\);if\(taskMark\)row\.append\(taskMark\)/);
assert.match(app,/itemsData=fresh; renderTasks\(\); refreshSourceTaskMarks\(\); \}/);
// The icon inside the row must not turn the grid row into a flex button.
assert.match(css,/\.source-row:has\(\.row-task-link\)\{display:grid;gap:12px\}/);
console.log('Source task marks PASS: GitHub, Gmail and Chat rows show their tasks; the mark opens the task.');
