const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const src=fs.readFileSync('web/app.js','utf8');
// Owner choices: my team first, then the others; each group in alphabetical order (Bulgarian collation).
const start=src.indexOf('function inTeam('),end=src.indexOf('function personOptions(',start);
const c=vm.createContext({AtlantaUX:{iso:()=> '2026-11-09'},state:{people:[
 {id:'1',name:'Яна',team:[{start:'2026-01-01',end:null}]},{id:'2',name:'Борис',team:[]},{id:'3',name:'Ангел',team:[{start:'2026-01-01',end:null}]},
 {id:'4',name:'Виктор',team:[{start:'2025-01-01',end:'2026-01-01'}]},{id:'5',name:'Алекс'}]}});
vm.runInContext(src.slice(start,end),c);
const groups=JSON.parse(JSON.stringify(vm.runInContext('peopleByTeam()',c)));
assert.deepEqual(groups.team.map(p=>p.name),['Ангел','Яна']);
assert.deepEqual(groups.others.map(p=>p.name),['Алекс','Борис','Виктор'],'a person who left the team is with the others');
// Every owner picker uses the grouped list.
assert.equal((src.match(/option\('No owner',''\),\.\.\.personOptions\(/g)||[]).length,3);
console.log('Owner order PASS: team first, then the others, each alphabetical.');
