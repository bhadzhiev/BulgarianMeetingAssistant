const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('web/app.js','utf8'),html=fs.readFileSync('web/index.html','utf8');
const applied=[],requests=[];
const state={people:[{id:'one',name:'Мария Петрова',aliases:['Мария']},{id:'two',name:'Иван',aliases:[]}],speakers:['Мария Петрова','Иван']};
const el=tag=>({tag,children:[],append(...items){this.children.push(...items);},setAttribute(){}});
const c=vm.createContext({state,el,option:(text,value)=>({text,value}),perform:fn=>fn(),toast(){},api:async(...args)=>requests.push(args),detail:{id:'meeting-a'}});
for(const name of ['personFor','knownSpeaker','participantLabel']){
 const start=source.indexOf('function '+name+'(');assert(start>=0);
 vm.runInContext(source.slice(start,source.indexOf('\n',start)),c);
}
vm.runInContext('let pendingSpeaker=null;'+source.slice(source.indexOf('function thisIs('),source.indexOf('function renderVoiceStatus(')),c);
assert.equal(vm.runInContext("personFor('мария').id",c),'one');
assert.equal(vm.runInContext("knownSpeaker('Мария')",c),'Мария Петрова');
assert.equal(vm.runInContext("personFor('SPEAKER_00')",c),null);
assert.equal(vm.runInContext("participantLabel('SPEAKER_00')",c),'Participant 1');
assert.equal(vm.runInContext("participantLabel('SPEAKER_01')",c),'Participant 2');
(async()=>{
 c.apply=async name=>{applied.push(name);return true;};
 const before=JSON.stringify(state.people);
 const select=vm.runInContext("thisIs('Иван',false,apply)",c);select.value='one';await select.onchange();
 assert.deepEqual(applied,['Мария Петрова']);assert.equal(JSON.stringify(state.people),before);
 assert.equal(requests.length,0,'Choosing a person must not create a global alias');
 const generic=vm.runInContext("thisIs('SPEAKER_00',false,apply)",c);generic.value='two';await generic.onchange();
 assert.deepEqual(applied,['Мария Петрова','Иван']);
 state.people.push({id:'three',name:'Мария Иванова',aliases:['Мария']});
 assert.equal(vm.runInContext("personFor('Мария')",c),null);
 assert.equal(vm.runInContext("knownSpeaker('Мария')",c),null);
 for(const id of ['speaker-list','new-speaker','add-speaker'])assert(!html.includes('id="'+id+'"'),'Separate speaker register control remains: '+id);
 assert(!html.includes('SPEAKER_02 after you name it'));
 assert(html.includes('id="people-list"'));assert(html.includes('Optional voice matching'));
 console.log('Unified People PASS: aliases, local speaker assignment, ambiguity, and a single directory.');
})().catch(error=>{console.error(error);process.exitCode=1;});
