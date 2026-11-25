const fs=require('node:fs'),assert=require('node:assert/strict'),vm=require('node:vm');
const app=fs.readFileSync('web/app.js','utf8');
const slice=(a,b)=>{const at=app.indexOf(a);assert.notEqual(at,-1,a);return app.slice(at,app.indexOf(b,at));};
// Overdue triage (2026-11-23): Select overdue picks the overdue tasks on the list; Set due date offers quick dates.
const iso=d=>d.toISOString().slice(0,10);
const c=vm.createContext({AtlantaUX:{iso},taskSelection:new Map(),taskSelecting:false,renderTasks(){c.renders=(c.renders||0)+1;},
 taskVisibleRows:[{id:'a',status:'open',due_date:'2026-11-20',revision:1},{id:'b',status:'open',due_date:'2026-11-30',revision:1},{id:'c',status:'done',due_date:'2026-11-01',revision:1},
  {id:'d',status:'open',due_date:'2026-11-02',acceptance_state:'proposed',revision:1},{id:'e',status:'open',due_date:'2026-11-03',dismissed:true,revision:1},
  {id:'f',status:'open',due_date:'2026-11-04',workflow_state:'cancelled',revision:1},{id:'g',status:'open',revision:1},{id:'h',status:'open',due_date:'2026-11-22',revision:2}]});
vm.runInContext(slice('let taskSelecting=false,bulkDefault','function renderBulkTasks(')+';this.overdueRows=overdueRows;this.quickDates=quickDates;this.selectOverdue=selectOverdue;this.state=()=>({taskSelecting,bulkDefault});',c);
assert.deepEqual(Array.from(c.overdueRows('2026-11-23'),t=>t.id),['a','h']);
c.overdueRows=c.overdueRows;
// Monday 2026-11-23: next Monday is a week later; Sunday 2026-11-29: next Monday is tomorrow.
assert.deepEqual(JSON.parse(JSON.stringify(c.quickDates(new Date(2026,10,23,12)))),[['Tomorrow','2026-11-24'],['Next Monday','2026-11-30'],['In a week','2026-11-30'],['In two weeks','2026-12-07']]);
assert.equal(c.quickDates(new Date(2026,10,29,12))[1][1],'2026-11-30');
const bulk=slice('function renderBulkTasks(','\n}\n');
assert.match(bulk,/'Select overdue · '\+late,selectOverdue,'Select the overdue tasks on this list and move their due date'/);
assert.match(bulk,/if\(\['due_date','waiting'\]\.includes\(action\.value\)\)for\(const \[label,day\] of quickDates\(\)\)/);
// Next steps (2026-11-25): Log progress, Waiting for a reply with a check date, Agree a new due date.
assert.match(app,/const OVERDUE_STEPS=\[\['update_note','Log progress'\],\['waiting','Waiting for a reply'\],\['due_date','Agree a new due date'\]\];/);
assert.match(bulk,/steps\.hidden=!overdueTriage;/);
assert.match(bulk,/const changes=action\.value==='waiting'\?\{workflow_state:'waiting',follow_up_date:value\.value\}:action\.value==='update_note'\?\{update_note:value\.value\.trim\(\)\}:/);
c.selectOverdue();assert.equal(vm.runInContext('overdueTriage',c),true);
assert.match(bulk,/if\(bulkDefault\)\{action\.value=bulkDefault;bulkDefault='';\}/);
// The change still goes through the confirmed bulk update.
assert.match(bulk,/await ask\(summary\+' for '\+body\.items\.length\+' selected tasks\?/);
console.log('Overdue triage PASS: Select overdue picks open overdue tasks; quick dates; the bulk confirmation stays.');
