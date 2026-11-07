const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const src=fs.readFileSync('web/app.js','utf8'),html=fs.readFileSync('web/index.html','utf8');
const slice=(a,b)=>src.slice(src.indexOf(a),src.indexOf(b,src.indexOf(a)));
// Settings → Projects offers its own way to create a project, so an empty library is not a dead end.
const panel=html.match(/data-tab="projects"[\s\S]*?id="project-list"/)[0];
assert.ok(panel.includes('id="settings-new-project"'),'Settings → Projects has a New project button');
assert.ok(src.includes("emptyNote('No projects yet. Choose ＋ New project.')"),'the empty text points to the button, not to a meeting');
(async()=>{
 const buttons={},calls=[];let spec={name:'Platform',color:'#5b8def'};
 const c=vm.createContext({state:{projects:[]},lastProjects:'x',$:id=>(buttons[id]=buttons[id]||{}),perform:fn=>fn(),leaveEdits:async()=>true,
  askProject:async()=>spec,api:async(path,body)=>{calls.push([path,body]);return {id:'p1',projects:[{id:'p1',name:body.name}]};},
  syncProjects:()=>calls.push('sync'),renderProjectSettings:()=>calls.push('render'),fillProjects(){},option(){},loadWorkspace:async()=>calls.push('workspace')});
 vm.runInContext(src.slice(src.indexOf('async function createProject('),src.indexOf('\n',src.indexOf("$('settings-new-project').onclick="))),c);
 await buttons['settings-new-project'].onclick();
 assert.deepEqual(JSON.parse(JSON.stringify(calls)),[['/api/projects/create',spec],'sync','render']);
 assert.deepEqual(JSON.parse(JSON.stringify(c.state.projects)),[{id:'p1',name:'Platform'}]);
 // Cancel creates nothing.
 calls.length=0;spec=null;await buttons['settings-new-project'].onclick();assert.deepEqual(calls,[]);
 // Projects → New project uses the same code.
 spec={name:'Ops',color:'#000000'};await buttons['workspace-new'].onclick();
 assert.deepEqual(JSON.parse(JSON.stringify(calls)),[['/api/projects/create',spec],'sync','workspace']);
 console.log('Settings projects PASS: New project in Settings, empty text points to it, cancel creates nothing, one shared create path.');
})().catch(e=>{console.error(e);process.exitCode=1;});
