const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('web/app.js','utf8');
const extract=(a,b)=>source.slice(source.indexOf(a),source.indexOf(b,source.indexOf(a)));
(async()=>{
 const calls=[];let dialogOpen=false;
 const elements={
  'new-meeting':{onclick:()=>calls.push('new')},
  'settings-open':{},
  'open-find':{},
  'find-query':{value:'',focus(){calls.push('focus')},select(){calls.push('select')}},
 };
 const c=vm.createContext({
  document:{addEventListener:(type,fn)=>{c.__key=fn},querySelector:()=>dialogOpen?{}:null},
  $:id=>elements[id]||{},
  perform:fn=>Promise.resolve(fn()),
  openSettings:()=>calls.push('settings'),
  openFind:()=>calls.push('find'),
  view:'setup',
 });
 vm.runInContext(extract('function appKeys(','// Move the existing heading'),c);
 assert.equal(typeof c.__key,'function','appKeys must register a keydown listener');
 assert.equal(elements['new-meeting'].title,'New meeting (⌥⌘N)');
 assert.equal(elements['settings-open'].title,'Settings (⌘,)');
 assert.equal(elements['open-find'].title,'Search (⌘F)');
 const press=(key,opts={})=>c.__key({key,metaKey:true,ctrlKey:false,shiftKey:false,altKey:false,preventDefault:()=>calls.push('prevent'),...opts});
 press('n');await new Promise(setImmediate);
 assert.deepEqual(calls,['prevent','new'],'⌘N starts a new meeting');
 calls.length=0;press(',');assert.deepEqual(calls,['prevent','settings'],'⌘, opens settings');
 calls.length=0;press('f');await new Promise(setImmediate);
 assert.deepEqual(calls,['prevent','find'],'⌘F opens find from another view');
 calls.length=0;vm.runInContext('view="find"',c);press('f');
 assert.deepEqual(calls,['prevent','focus','select'],'⌘F on the find view refocuses the query');
 calls.length=0;press('x');assert.deepEqual(calls,[],'unrelated keys pass through');
 calls.length=0;press('f',{metaKey:false});assert.deepEqual(calls,[],'plain typing is untouched');
 calls.length=0;dialogOpen=true;press('n');assert.deepEqual(calls,[],'modal dialogs keep their focus');
 console.log('Shortcuts regression PASS: ⌘N new meeting, ⌘, settings, ⌘F find, dialogs and typing untouched.');
})().catch(e=>{console.error(e);process.exitCode=1;});
