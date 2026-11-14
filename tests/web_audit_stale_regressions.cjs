const assert=require('node:assert/strict'),model=require('../web/task-model.js');
const proposal={text:'Fresh proposal',acceptance_state:'proposed'};
assert.equal(model.inView(proposal,'inbox',{today:'2026-11-15',proposalFilter:'stale'}),false);
assert.equal(model.inView(proposal,'inbox',{today:'2026-11-15',proposalFilter:'pending'}),true);
console.log('Stale excludes fresh registry proposals.');
