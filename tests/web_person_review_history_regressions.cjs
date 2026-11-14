const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('web/app.js','utf8'),html=fs.readFileSync('web/index.html','utf8');
function fn(name){const a=source.indexOf('function '+name+'(');assert(a>=0,name);return source.slice(a,source.indexOf('\n}',a)+2);}
const c=vm.createContext({Set});vm.runInContext(fn('currentReviewRows')+'\n'+fn('openReviewAgreements'),c);
const rows=[{id:'new-version',status:'draft',supersedes:'current',agreements:[{id:'a',status:'open',text:'Copy'}]},
 {id:'current',status:'finalized',agreements:[{id:'a',status:'done'},{id:'b',status:'open',owner:'manager'}]},
 {id:'old-version',status:'superseded',agreements:[{id:'a',status:'open'}]},
 {id:'earlier',status:'finalized',agreements:[{id:'c',status:'open',owner:'person'}]}];
c.rows=rows;
assert.deepEqual(JSON.parse(vm.runInContext('JSON.stringify(currentReviewRows(rows).map(r=>r.id))',c)),['current','earlier']);
assert.deepEqual(JSON.parse(vm.runInContext('JSON.stringify(openReviewAgreements(rows).map(r=>[r.id,r.review_id]))',c)),[['b','current'],['c','earlier']]);
assert.match(fn('teamCard'),/openTeamPerson\(person.id\)/);
assert.match(source,/q.set\('person',teamHistoryPersonId\)/);
assert.match(fn('renderTeamHistory'),/History order/);
assert.match(fn('renderTeamHistory'),/Continue preparation/);
assert.match(fn('renderTeamReview'),/Person’s history/);
assert.match(fn('renderTeamReview'),/acknowledge_overlap/);
assert.match(fn('previewTeamFacts'),/preview-collect/);assert.match(fn('previewTeamFacts'),/apply-collect/);
assert.match(fn('privateContextCard'),/observation_ids/);assert.match(fn('privateContextCard'),/Include this private context in the next AI preview/);
assert.match(fn('reviewConversationCard'),/conversation_at:date.value\|\|null/);
assert.match(fn('agreementRow'),/Expected result of agreement/);assert.match(fn('agreementRow'),/link-task/);
assert.match(fn('privatePreparationCard'),/excluded from Markdown exports/);
assert.doesNotMatch(fn('exportTeamReview'),/private_preparation|private_evidence|r.context/);
assert.match(html,/id="team-history-person"/);assert.match(html,/id="team-context-dialog"/);
console.log('Person review history PASS: versions, open agreements, routes, private context, explicit refresh and checks.');
// A rapid person switch clears the previous actions before starting the asynchronous history read.
(async()=>{
 let release;const pending=new Promise(resolve=>release=resolve),paint=[];
 const ctx=vm.createContext({$(){return {};},leaveEdits:()=>true,show(){},renderLibrary(){},renderTeamHistory(){paint.push(ctx.teamHistoryPersonId);},loadTeam:()=>pending});
 vm.runInContext("let teamHistoryPersonId='old',teamHistoryRows=[{person_id:'old'}],teamHistoryLoading=false,teamHistoryError='',teamTab='reviews',teamReviewId='',teamReview=null,dirtyTranscript=false,dirtyNotes=false,selected=null;\nasync "+fn('openTeamPerson'),ctx);
 const switching=vm.runInContext("openTeamPerson('new')",ctx);await Promise.resolve();
 assert.equal(vm.runInContext('teamHistoryLoading',ctx),true);assert.equal(vm.runInContext('teamHistoryRows.length',ctx),0);
 assert.equal(vm.runInContext('teamHistoryPersonId',ctx),'new');release();await switching;
 assert.match(fn('renderTeamHistory'),/if\(teamHistoryLoading\)/);
 assert.match(fn('openTeamReview'),/!readers.current\(request\)/);
 assert.match(fn('agreementRow'),/if\(row.task_id\)return openTaskPanel\(row.task_id\)/);
 console.log('Person switch PASS: stale actions cleared while loading; review reads respect navigation.');
})().catch(e=>{console.error(e);process.exit(1);});
