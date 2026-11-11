const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('web/app.js','utf8');
const slice=(a,b)=>source.slice(source.indexOf(a),source.indexOf(b,source.indexOf(a)));
// The Inbox answers to single keys; each actionable button carries a data-kb key.
assert.match(source,/if\(kb\)b\.dataset\.kb=kb;/,'proposal buttons carry data-kb keys');
for(const key of ['accept','snooze','dismiss','restore'])assert.ok(source.includes(",'"+key+"')"),'a button is registered for '+key);
const made=[];
const card=()=>({classList:{toggle:(name,on)=>made.push(['focus',on])},scrollIntoView:()=>{},querySelector:sel=>({disabled:false,click:()=>made.push(['click',sel])})});
const meetingCards=[card(),card()],sourceCards=[card()];
const c=vm.createContext({
 document:{addEventListener:(type,fn)=>{c.__key=fn},querySelector:()=>null},
 $:()=>null,
 view:'tasks',workTab:'task',managerView:'inbox',
 meetingProposalListEl:{querySelectorAll:()=>meetingCards},
 proposalListEl:{querySelectorAll:()=>sourceCards},
});
vm.runInContext(slice('let proposalCursor=-1;','// A tracked question'),c);
const key=name=>c.__key({key:name,preventDefault:()=>made.push(['prevent',name]),target:{}});
const active=()=>{const batch=made.splice(0).filter(m=>m[0]==='focus');return batch.findIndex(m=>m[1]);};
key('j');assert.equal(active(),0,'j chooses the first card');
key('j');assert.equal(active(),1,'j moves down');
key('k');assert.equal(active(),0,'k moves back up');
key('a');
assert.deepEqual(made.filter(m=>m[0]==='click'),[['click','[data-kb="accept"]']],'a clicks the Accept button of the chosen card');
made.length=0;
key('j');assert.equal(active(),1,'j moves to the second meeting card');
key('j');assert.equal(active(),2,'j crosses into the connected-sources cards');
key('j');assert.equal(active(),2,'j stays at the last card');
made.length=0;
c.managerView='mine';
key('a');
assert.deepEqual(made,[],'plain task views ignore the proposal keys');
console.log('Proposal keys PASS: j/k move across both Inbox sections, a/s/d/r hit the data-kb buttons, other views ignore the keys.');
