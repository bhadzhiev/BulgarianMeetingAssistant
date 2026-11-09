const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const src=fs.readFileSync('web/app.js','utf8');
// The open Gmail tab starts a sync when the cache is old or the last run did not finish, at most every 5 minutes.
const start=src.indexOf('const MAIL_CHECK_MS='),end=src.indexOf('\n}',src.indexOf('function mailSyncDue('))+2;
const c=vm.createContext({mailAutoSyncedAt:0});vm.runInContext(src.slice(start,end).replace('const MAIL_CHECK_MS','var MAIL_CHECK_MS'),c);
const now=Date.parse('2026-11-09T14:00:00Z'),min=60000,status=(o={})=>({connected:true,count:10,job:{running:false,status:'synced'},sync:{last_sync:(now-2*min)/1000},...o});
const due=s=>vm.runInContext('mailSyncDue',c)(s,now);
assert.equal(due(status()),false,'a sync 2 minutes ago is current');
assert.equal(due(status({sync:{last_sync:(now-6*min)/1000}})),true,'a sync 6 minutes ago is old');
assert.equal(due(status({job:{running:false,status:'continue'}})),true,'an unfinished sync continues');
assert.equal(due(status({count:0,sync:{}})),true,'an empty cache syncs');
assert.equal(due(status({connected:false,count:0})),false);
assert.equal(due(status({count:0,job:{running:true,status:'syncing'}})),false);
c.mailAutoSyncedAt=now-min;assert.equal(due(status({count:0})),false,'at most one automatic start every 5 minutes');
assert.ok(src.includes("setTimeout(()=>loadMail().catch(()=>{}),MAIL_CHECK_MS)"),'the quiet check shows no error');
console.log('Gmail auto sync PASS: stale, unfinished and empty caches sync; at most every 5 minutes.');
