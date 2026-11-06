const assert=require('node:assert/strict'),M=require('../web/task-model.js');
const people=[{id:'me',name:'Bo',aliases:['B']}],context={self:'me',people,today:'2026-11-06'};
const item={text:'Backup',status:'open',manual:['owner'],owner:'B',assigned_by_person_id:'me'};
assert(M.inView(item,'mine',context));assert(!M.inView(item,'delegated',context));
assert(M.inView({...item,owner:'Maria'},'delegated',context));assert(!M.inView(item,'mine',{...context,self:''}));
assert(!M.inView({...item,manual:[]},'mine',context),'AI owner name alone cannot establish a confirmed assignment');
assert(M.inView({...item,follow_up_date:'2026-11-05'},'followup',context));assert(!M.inView({...item,workflow_state:'done',follow_up_date:'2026-11-05'},'followup',context));
assert(M.inView({...item,workflow_state:'waiting'},'followup',context));
assert(M.inView({...item,acceptance_state:'proposed'},'inbox',context));assert(!M.inView({...item,acceptance_state:'proposed'},'all',context));
assert(!M.inView(item,'all',{...context,search:'unrelated'}));assert(M.inView({...item,details:'Restore database'},'all',{...context,search:'database'}));
assert.equal(M.workflow({status:'done'}),'done');assert.equal(M.workflow({status:'open'}),'todo');
console.log('Task manager PASS: responsibilities, confirmed identities, follow-up, proposals, search and legacy state projection.');

assert(!M.inView({...item,acceptance_state:'proposed',dismissed:true},'inbox',context));
assert(M.inView({...item,acceptance_state:'proposed',dismissed:true},'inbox',{...context,proposalFilter:'dismissed'}));
assert(!M.inView({...item,acceptance_state:'proposed',snoozed_until:'2026-11-10'},'inbox',context));
assert(M.inView({...item,acceptance_state:'proposed',snoozed_until:'2026-11-10'},'inbox',{...context,proposalFilter:'snoozed'}));

const first={at:'2026-11-05T09:00:00Z',event:'progress_update',text:'Testing'},last={at:'2026-11-06T09:00:00Z',event:'progress_update',text:'Waiting for access'};
assert.deepEqual(M.lastUpdate({history:[last,{at:'2026-11-07',event:'changed'},first]}),last);
assert.equal(M.lastUpdate({history:[]}),null);
assert(M.personMatches({owner:'Maria',requester_person_id:'ivan',follower_person_id:'me'},{requester:'ivan',follower:'me'}));
assert(!M.personMatches({owner:'Maria',requester_person_id:null},{requester:'ivan'}));
assert(M.personMatches({requester_person_id:null},{requester:'__none__'}));
const selected=new Map([['visible',{id:'visible',revision:1}],['hidden',{id:'hidden',revision:2}],['proposal',{id:'proposal',revision:3}]]);
const kept=M.visibleSelection(selected,[{id:'visible',revision:9},{id:'proposal',acceptance_state:'proposed'}]);
assert.deepEqual([...kept.keys()],['visible']);assert.equal(kept.get('visible').revision,1,'SSE must not silently replace the selected revision');
console.log('Stage 3 PASS: latest progress, requester/follower filters and visible-only selection with original revisions.');

assert.equal(M.lastUpdate({history:[{event:'progress_update',at:'2026-11-06T10:00:00Z',text:'First'},{event:'progress_update',at:'2026-11-06T10:00:00Z',text:'Second'}]}).text,'Second','same-second history order determines the latest update');
