const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8'),css=fs.readFileSync('web/style.css','utf8');
const slice=(a,b)=>{const at=app.indexOf(a);assert.notEqual(at,-1,a);return app.slice(at,app.indexOf(b,at));};
const row=slice('function globalTaskRow(','function decisionRow(');
// The first line of the details is a subtitle under the title.
assert.match(row,/const subtitle=String\(item\.details\|\|''\)\.split\('\\n'\)/);
assert.match(row,/main\.append\(head,\.\.\.\(subtitle\?\[el\('p','task-subtitle',subtitle\)\]:\[\]\),meta\)/);
// The last update is a box with its label, date and text; Emailed goes into the box when there is an update.
assert.match(row,/box\.append\(el\('span','task-update-label','Last update'\),el\('span','task-last-when',dateTime\(update\.at\)\),last\);if\(mailed\)box\.append\(mailed\)/);
assert.match(row,/if\(mailed&&!update\)meta\.append\(mailed\)/);
// Meetings are rows; the other sources keep their chips.
assert.match(row,/linked=taskMeetingList\(item,itemsData\.meetings\),others=sourceChips\(item,itemsData\.meetings,\{withMeetings:false\}\)/);
// Mark done is the main action with a check; Timeline and Edit are quiet.
assert.match(row,/if\(item\.status!=='done'\)\{done\.classList\.replace\('secondary','primary'\);done\.prepend\(icon\('check'\)\);\}/);
assert.match(row,/actionBtn\('quiet small-action task-timeline','Timeline'/);
// taskMeetingList: one row per meeting in date order, a deleted meeting in plain words, the moment without 00: hours.
{
 const node=(tag,cls='',text='')=>({tag,className:cls,textContent:text,children:[],append(...k){this.children.push(...k);}});
 const c=vm.createContext({el:node,icon:name=>node('svg','icon '+name),date:v=>'D'+v,stampSeconds:s=>s.split(':').reduce((a,b)=>a*60+Number(b),0),
  actionBtn:(cls,text)=>node('button',cls,text),listenButton:(id,sec,{label,className})=>node('button','listen '+className,label+'@'+sec),openMeeting:()=>{},switchTab:()=>{}});
 vm.runInContext(slice('function taskMeetingList(','function meetingChips('),c);
 const meetings={b:{title:'Second',date:'2026-11-09'},a:{title:'First',date:'2026-11-03'}};
 const box=vm.runInContext('taskMeetingList',c)({links:[{meeting_id:'b',evidence_timestamp:'00:20:19'},{meeting_id:'a'},{meeting_id:'gone'}]},meetings);
 assert.equal(box.children[0].textContent,'Linked meetings · 3');
 const rows=box.children.slice(1);
 assert.deepEqual(rows.map(r=>r.children[1].textContent),['A deleted meeting','First','Second']);
 assert.equal(rows[2].children[3].textContent,'20:19@1219');assert.equal(rows[1].children[3].tag,'span');
 assert.equal(vm.runInContext('taskMeetingList',c)({links:[]},meetings),null);
}
// The card styles: actions under a divider, Timeline pushed right, the update box on the surface color.
assert.match(css,/\.tracked-task\.task-card \.tracked-main>\.task-row-actions\{[^}]*border-top:1px solid var\(--line\)/);
assert.match(css,/\.task-row-actions \.task-timeline\{margin-left:auto\}/);
assert.match(css,/\.task-update\{[^}]*background:var\(--surface\)/);
console.log('Task card layout PASS: subtitle, update box, meeting rows, main Mark done.');
