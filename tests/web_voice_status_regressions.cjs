const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('web/app.js','utf8'),start=source.indexOf('function renderVoiceStatus(){'),end=source.indexOf('function renderSpeakerSettings()',start);
const nodes={},node=id=>nodes[id]||(nodes[id]={value:'',options:[],selectedOptions:[],classList:{toggle(){}},replaceChildren(...options){this.options=options;}});
node('settings-dialog').open=true;
const state={speakers:['Same unchanged names'],diarization:{available:true},devices:[],settings:{},active:null};
const noop=()=>{},context=vm.createContext({state,$:node,AtlantaUX:require('../web/ux.js'),syncSpeakers:noop,syncProjects:noop,desktopStatus:'',lastDevices:JSON.stringify([]),option:(text,value)=>({textContent:text,value}),pending:false,renderReadiness:noop,renderRecordMore:noop,privacy:()=>'',renderTranscriptionTiming:noop,renderGoogleStatus:noop,calendarConnected:()=>false,lastGoogleConnected:false,view:'setup',renderRecordingBar:noop,renderLibrary:noop,renderCaptureSetup:noop});
vm.runInContext(source.slice(start,end),context);
const renderStart=source.indexOf('function renderState() {'),renderEnd=source.indexOf('const MARKER_LABELS=',renderStart);vm.runInContext(source.slice(renderStart,renderEnd),context);
// Drive the real state renderer, with unchanged speaker names and an open settings panel.
for(const [job,label,disabled] of [[{running:true,done:0,total:2,failed:0},'Learning voices · 0 of 2 meetings',true],[{running:true,done:1,total:2,failed:0},'Learning voices · 1 of 2 meetings',true],[{running:false,done:2,total:2,failed:0},'Learned voices from 2 meetings',false]]){state.voices=job;vm.runInContext('renderState()',context);assert.equal(node('voice-status').textContent,label);assert.equal(node('learn-voices').disabled,disabled);}
console.log('Voice status PASS: real state rendering updates progress and completion without changing speaker names.');
