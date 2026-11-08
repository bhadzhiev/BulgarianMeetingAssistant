const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8'),css=fs.readFileSync('web/style.css','utf8');
const slice=(a,b)=>{const at=app.indexOf(a);assert.notEqual(at,-1,a);return app.slice(at,app.indexOf(b,at));};
// The date and time stay on one line beside the event.
assert.match(css,/\.history-date\{flex:none;width:auto;min-width:118px;white-space:nowrap;/);
// Every event reads as words; a confirmation reads "Confirmed for".
const c=vm.createContext({});vm.runInContext(slice('const EVENT_LABELS=','\nfunction historyBlock'),c);
assert.equal(vm.runInContext('eventLabel',c)('meeting_review_confirm'),'Confirmed for');
assert.equal(vm.runInContext('eventLabel',c)('some_new_event'),'Some new event');
// A repeated event right after itself shows once, with the count; a change or a text is never folded.
const block=slice('function historyBlock(','\n}\n');
assert.match(block,/last\.times=\(last\.times\|\|1\)\+1;continue;/);
assert.match(block,/!Object\.keys\(event\.changes\|\|\{\}\)\.length&&!Object\.keys\(last\.changes\|\|\{\}\)\.length&&!event\.text&&!last\.text/);
assert.match(block,/' · '\+event\.times\+' times'/);
// A status change reads as its label.
assert.match(block,/name==='status'\?\(\{\.\.\.DECISION_LABELS,open:'Open',done:'Done'\}\)\[value\]\|\|value:/);
console.log('History PASS: one-line date, readable event names, repeated events folded with a count, status labels.');
