const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const src=fs.readFileSync('web/app.js','utf8'),html=fs.readFileSync('web/index.html','utf8');
// Two top-level functions with one name silently replace each other; the follow-up email once did that.
const names={};for(const m of src.matchAll(/^(?:async )?function ([A-Za-z0-9_$]+)\(/gm))names[m[1]]=(names[m[1]]||0)+1;
assert.deepEqual(Object.entries(names).filter(([,n])=>n>1),[],'every top-level function name is unique');
// The meeting menu and the dialog exist, and the dialog closes through the shared dirty-edit guard.
assert.ok(html.includes('<button id="followup-email">Follow-up email…</button>'));
for(const id of ['followup-dialog','followup-people','followup-extra','followup-subject','followup-body','followup-ai','followup-save','followup-connect','followup-cancel'])assert.ok(html.includes('id="'+id+'"'),id);
assert.ok(src.includes("'followup-dialog':{close:'followup-close',cancel:'followup-cancel'}"));
assert.ok(src.includes("const ACTIONS=['process','correct','summarize','recover','edit-title','generate-title','sync-calendar','followup-email','delete-meeting'];"));
// Recipients: checked people plus typed addresses, lower case and without duplicates.
const start=src.indexOf('function followupEmailRecipients('),end=src.indexOf('function renderFollowupEmail(',start);
const people=[{value:'maria@example.test'},{value:'guest@example.test'}];
const c=vm.createContext({$:id=>id==='followup-people'?{querySelectorAll:()=>people}:{value:'Boss@Example.test, maria@example.test; '}});
vm.runInContext(src.slice(start,end),c);
assert.deepEqual(JSON.parse(JSON.stringify(vm.runInContext('followupEmailRecipients()',c))),['maria@example.test','guest@example.test','boss@example.test']);
console.log('Follow-up email PASS: unique function names, menu, dialog guard and recipient list.');
