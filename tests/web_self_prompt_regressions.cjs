const fs=require('node:fs'),assert=require('node:assert/strict'),vm=require('node:vm');
const app=fs.readFileSync('web/app.js','utf8');
const slice=(a,b)=>{const at=app.indexOf(a);assert.notEqual(at,-1,a);return app.slice(at,app.indexOf(b,at));};
// "Are you …?": the connected Google account names the likely person; one click confirms it (2026-11-23).
const saved={},c=vm.createContext({managerSelf:'',state:{google:{account:' Ana@Example.test '},people:[{id:'p1',name:'Ben',emails:['ben@example.test']},{id:'p2',name:'Ana',emails:['ana@example.test']}]},
 stored:k=>saved[k]||'',store:(k,v)=>{saved[k]=v;},
 el:(tag,cls,text)=>{const n={tag,className:cls||'',textContent:text||'',children:[],append(...k){n.children.push(...k);}};return n;},
 btn:(cls,label)=>({className:cls,textContent:label})});
vm.runInContext(slice('function likelySelf(','let managerView=')+';this.likelySelf=likelySelf;this.selfPrompt=selfPrompt;this.me=()=>managerSelf;',c);
assert.equal(c.likelySelf().id,'p2');
let renders=0;const box=c.selfPrompt(()=>renders++);
assert.equal(box.children[0].textContent,'Are you Ana? My tasks and Results to check use your profile.');
box.children[1].onclick();assert.equal(c.me(),'p2');assert.equal(saved['manager-self'],'p2');assert.equal(renders,1);
assert.equal(c.likelySelf(),null,'no question once a profile is chosen');
// Not me hides the question for that person; no match or no account asks nothing.
vm.runInContext("managerSelf=''",c);const again=c.selfPrompt(()=>renders++);again.children[2].onclick();
assert.equal(saved['manager-self-declined'],'p2');assert.equal(c.selfPrompt(()=>{}),null);
c.state.google.account='';delete saved['manager-self-declined'];assert.equal(c.likelySelf(),null);
c.state.google.account='nobody@example.test';assert.equal(c.likelySelf(),null);
// My Work shows it above the task views; Team's Needs me above its profile select.
assert.match(app,/const prompt=\$\('self-prompt'\),ask=itemKind==='task'\?selfPrompt\(renderTasks\):null;/);
assert.match(app,/const ask=selfPrompt\(\(\)=>perform\(loadTeam\)\);if\(ask\)box\.append\(ask\);box\.append\(select\);/);
// Questions: the empty state counts the questions from notes and opens them.
assert.match(app,/' from meeting notes '\+\(fromNotes===1\?'waits':'wait'\)\+' below: track the ones that still need an answer\.'/);
assert.match(app,/candidates\.open=!open\.length;/);
assert.match(app,/' · '\+\(itemsData\.meeting_questions\.length\)\+' from notes'/);
console.log('Self prompt PASS: the Google account suggests the profile; Not me hides it; questions from notes are counted and open.');
