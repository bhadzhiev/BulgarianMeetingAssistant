const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8'),css=fs.readFileSync('web/style.css','utf8');
const slice=(a,b)=>{const at=app.indexOf(a);assert.notEqual(at,-1,a);return app.slice(at,app.indexOf(b,at));};
const row=slice('function globalTaskRow(','function decisionRow(');
// A task is a title and a description: the card, the meeting task and the review card show the description.
assert.match(app,/function taskDescription\(text\)\{const node=el\('p','task-description',text\);node\.title=text;return node;\}/);
assert.match(row,/cardDisclosure\('Description','notes',\[taskDescription\(description\)\],panels\)/);
assert.match(slice('function taskRow(','function renderNotes('),/meta\.append\(cardDisclosure\('Description','notes',\[taskDescription\(description\)\],panels\)\)/);
assert.match(app,/if\(item\.details\)meta\.append\(cardContext\('Description','notes',\[taskDescription\(item\.details\)\]\)\)/);
// An update of the notes shows a new description as part of the task change.
assert.match(app,/function changeText\(field,item\) \{ return field==='tasks'\?\[item\.task,item\.details,item\.owner,/);
assert.match(css,/\.task-description\{[^}]*-webkit-line-clamp:3/);
// The last update is one line with an icon, date and text; the draft indicator is a tag of the card, never in its update.
assert.match(row,/box\.append\(icon\('update'\),el\('span','task-last-when',dateTime\(update\.at\)\),last\)/);
assert.match(row,/if\(mailed\)tags\.append\(mailed\)/);
assert.doesNotMatch(row,/(?:meta|box|flags)\.append\(mailed\)/);
// Meetings are rows; the other sources keep their chips.
assert.match(row,/linked=taskMeetingList\(item,itemsData\.meetings\),others=sourceChips\(item,itemsData\.meetings,\{withMeetings:false\}\)/);
assert.match(row,/meta\.append\(stateFact,priorityBadge,ownerFact\)/);
assert.doesNotMatch(row,/meta\.append\(chips\)/);
// Context controls sit with Open task in the card tools; the shared disclosure helper owns separate, exclusive panels.
assert.match(row,/contextTools=el\('div','task-context-tools'\)/);
assert.match(row,/cardDisclosure\('Sources','link'/);
assert.match(row,/tools\.append\(contextTools,open\)/);
assert.doesNotMatch(row,/el\('details','(?:task-card-sources|card-description)'\)/);
assert.match(css,/\.task-card \.tracked-meta>\.task-context-tools\{[^}]*display:inline-flex;[^}]*flex:0 0 auto/);
// Mutations are inside the task editor; the card opens it and has one direct Mark done circle.
assert.match(row,/'Open task',\(\)=>openTaskPanel\(item.id\)/);
assert.doesNotMatch(row,/stateSelect/);
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
// Legacy task variants retain their styling; compact controls override the spacing in the shared card.
assert.match(css,/\.tracked-task\.task-card \.tracked-main>\.task-row-actions\{[^}]*border-top:1px solid var\(--line\)/);
assert.match(css,/\.task-row-actions \.task-timeline\{margin-left:auto\}/);
assert.match(css,/\.task-update\{[^}]*background:var\(--surface\)/);
console.log('Task card layout PASS: description, update box, meeting rows, main Mark done.');
