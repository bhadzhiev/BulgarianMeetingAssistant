const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const src=fs.readFileSync('web/app.js','utf8'),html=fs.readFileSync('web/index.html','utf8'),progress=fs.readFileSync('web/task-progress.js','utf8');
// The dialog exists and closes through the shared dirty-edit guard.
for(const id of ['task-email-dialog','task-email-people','task-email-extra','task-email-subject','task-email-body','task-email-save','task-email-connect','task-email-cancel'])assert.ok(html.includes('id="'+id+'"'),id);
assert.ok(src.includes("'task-email-dialog':{close:'task-email-close',cancel:'task-email-cancel'}"));
// One task from its card, its editor and its … menu; several tasks from the selection bar in one email.
assert.equal((src.match(/'Send by email…'/g)||[]).length,3);
assert.ok(src.includes("openTaskEmail([...taskSelection.keys()])"));
assert.ok(src.includes("api('/api/task-email/draft',{item_ids:taskEmailItems,"));
// The history names the event in words.
assert.ok(src.includes("email_draft:'Email draft saved in Gmail'"));assert.ok(progress.includes("email_draft:'Email draft saved in Gmail'"));
// The envelope shows only for a task with a saved draft; the compact row has the icon only.
const start=src.indexOf('function emailMark('),end=src.indexOf('let taskEmailItems',start);
class Node{constructor(cls){this.className=cls;this.children=[];this.attrs={};}append(...n){this.children.push(...n);}setAttribute(k,v){this.attrs[k]=v;}}
const c=vm.createContext({el:(t,cls)=>new Node(cls),icon:()=>'svg',dateTime:v=>v,document:{createTextNode:t=>t}});
vm.runInContext(src.slice(start,end),c);
assert.equal(vm.runInContext('emailMark({})',c),null);
const mark=vm.runInContext("emailMark({email_draft:{saved_at:'09.11.2026',to:['a@b.test']}})",c);
assert.deepEqual(mark.children,['svg','Gmail draft']);assert.ok(mark.title.includes('a@b.test'));
assert.deepEqual(vm.runInContext("emailMark({email_draft:{saved_at:'x',to:[]}},{compact:true})",c).children,['svg']);
console.log('Task email PASS: dialog, three entry points, history label and envelope mark.');
