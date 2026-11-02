const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const UX=require('../web/ux.js');
assert.equal(UX.count(0,'conversation'),'0 conversations');assert.equal(UX.count(1,'conversation'),'1 conversation');assert.equal(UX.count(2,'meeting'),'2 meetings');assert.equal(UX.count(1,'meeting'),'1 meeting');
const source=fs.readFileSync('web/app.js','utf8'),start=source.indexOf('function selectedTranscriptRange(){'),end=source.indexOf("document.addEventListener('selectionchange'",start);
let inside=true,selected=[1,2],collapsed=false,text='selected text';
const range={commonAncestorContainer:{},intersectsNode:node=>selected.includes(Number(node.dataset.segmentIndex))};
const root={contains:()=>inside,querySelectorAll:()=>[0,1,2,3].map(index=>({dataset:{segmentIndex:String(index)}}))};
const context=vm.createContext({view:'detail',transcriptEditing:false,$:()=>root,window:{getSelection:()=>({rangeCount:1,isCollapsed:collapsed,toString:()=>text,getRangeAt:()=>range})}});
vm.runInContext(source.slice(start,end),context);
const read=()=>JSON.parse(JSON.stringify(vm.runInContext('selectedTranscriptRange()',context)));
assert.deepEqual(read(),{first:1,last:2});selected=[3,2];assert.deepEqual(read(),{first:2,last:3});
inside=false;assert.equal(read(),null);inside=true;collapsed=true;assert.equal(read(),null);collapsed=false;text=' ';assert.equal(read(),null);text='selection';context.transcriptEditing=true;assert.equal(read(),null);context.transcriptEditing=false;context.view='tasks';assert.equal(read(),null);
console.log('Layout flow regressions PASS: singular counts and source-bound transcript selection, including reversed ranges and edit/other-view guards.');

const routeStart=source.indexOf('function currentRoute(){'),routeEnd=source.indexOf('// A new view adds',routeStart);
const routes=vm.createContext({URLSearchParams,view:'projects',workspaceSection:'work',workspaceWorkKind:'task',$:()=>({value:'platform'}),LIBRARY_VIEWS:['conversations','find','analytics']});
vm.runInContext(source.slice(routeStart,routeEnd),routes);
let url=new URL(vm.runInContext('currentRoute()',routes),'http://localhost');assert.equal(url.searchParams.get('project'),'platform');assert.equal(url.searchParams.get('kind'),'task');assert.equal(url.searchParams.get('section'),'work');
routes.workspaceSection='decision';url=new URL(vm.runInContext('currentRoute()',routes),'http://localhost');assert.equal(url.searchParams.get('section'),'decision');routes.view='importing';assert.equal(vm.runInContext('currentRoute()',routes),'/?view=importing');
console.log('Navigation regressions PASS: project kind filters and existing section/import routes.');

const progressNodes={'processing-details':{hidden:false},'processing-time':{hidden:false,textContent:''}},progress=vm.createContext({detail:{status:'ready'},view:'setup',$:id=>progressNodes[id],time:n=>String(n)});
const progressStart=source.indexOf('function renderProcessingTime(){'),progressEnd=source.indexOf('setInterval(',progressStart);vm.runInContext(source.slice(progressStart,progressEnd),progress);vm.runInContext('renderProcessingTime()',progress);assert.equal(progressNodes['processing-details'].hidden,true);progress.detail.processing_stage='Complete';vm.runInContext('renderProcessingTime()',progress);assert.equal(progressNodes['processing-details'].hidden,false);assert.match(progressNodes['processing-time'].textContent,/Complete/);
console.log('Detail first-paint regression PASS: no empty or stale processing disclosure during view transitions.');
