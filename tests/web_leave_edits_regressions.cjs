const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const UX=require('../web/ux.js'),source=fs.readFileSync('web/app.js','utf8');
const extract=(a,b)=>source.slice(source.indexOf(a),source.indexOf(b,source.indexOf(a)));
const tick=()=>new Promise(setImmediate);
function context({notes=false,stay=false,wait=false}={}){
 const requests=[];let resolveFetch;
 const c=vm.createContext({structuredClone,readers:UX.requests(),editorDirty:UX.dirtyRegistry(),
  ask:async()=>!stay,toast:()=>{},editorHeartbeat:()=>{},
  api:path=>{requests.push(path);return wait?new Promise(resolve=>resolveFetch=resolve):Promise.resolve({id:'B',transcript:[{text:'B saved'}]});},
  $:()=>({open:false}),renderDetail:()=>{},show:()=>{},renderLibrary:()=>{},setItemEditing:()=>{}});
 vm.runInContext(`let state={active:null},view='detail',selected='A',meetingLoadSequence=0,detailChangedWhileEditing=false,
  detail={id:'A',transcript:[{text:'unsaved transcript'}],minutes:{summary:'unsaved notes'}},
  dirtyTranscript=${!notes},dirtyNotes=${notes},itemEditing=false,speakerNaming=false,
  transcriptEditing=${!notes},notesEditing=${notes},transcriptBaseline=[{text:'saved transcript'}],
  notesBase={summary:'saved notes'},lastTasks='',lastFingerprint='',questionFilter='',questionLimit=0;`
  +extract('function hasEdits()','// The desktop window')
  +extract('async function leaveEdits()','// The active recording')
  +extract('async function openMeeting(','function renderState()'),c);
 return {c,requests,resolve:data=>resolveFetch(data)};
}
(async()=>{
 for(const notes of [false,true]){
  const {c}=context({notes});assert.equal(await vm.runInContext('openMeeting("B")',c),true);
  assert.equal(vm.runInContext('selected',c),'B');assert.equal(vm.runInContext('hasEdits()',c),false);
 }
 const stayed=context({stay:true});assert.equal(await vm.runInContext('openMeeting("B")',stayed.c),false);
 assert.equal(stayed.requests.length,0);assert.equal(vm.runInContext('detail.transcript[0].text',stayed.c),'unsaved transcript');
 assert.equal(vm.runInContext('dirtyTranscript',stayed.c),true);
 const discarded=context();assert.equal(await vm.runInContext('leaveEdits()',discarded.c),true);
 assert.equal(vm.runInContext('detail.transcript[0].text',discarded.c),'saved transcript');
 assert.equal(vm.runInContext('transcriptEditing',discarded.c),false);
 const discardedNotes=context({notes:true});await vm.runInContext('leaveEdits()',discardedNotes.c);
 assert.equal(vm.runInContext('detail.minutes.summary',discardedNotes.c),'saved notes');
 const racing=context({wait:true});const navigation=vm.runInContext('openMeeting("B")',racing.c);await tick();
 vm.runInContext('dirtyTranscript=true;detail.transcript[0].text="new typing"',racing.c);
 racing.resolve({id:'B'});assert.equal(await navigation,false);
 assert.equal(vm.runInContext('selected',racing.c),'A');assert.equal(vm.runInContext('detail.transcript[0].text',racing.c),'new typing');
 const saving=context();vm.runInContext('editorDirty.set("saving",true)',saving.c);
 assert.equal(await vm.runInContext('openMeeting("B")',saving.c),false);assert.equal(saving.requests.length,0);
 console.log('Leave edits PASS: accepted navigation, Stay, baseline restoration, new typing and pending save protection.');
})().catch(e=>{console.error(e);process.exitCode=1;});
