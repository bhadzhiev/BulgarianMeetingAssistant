const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const UX=require('../web/ux.js'),source=fs.readFileSync('web/app.js','utf8');
const extract=(a,b)=>source.slice(source.indexOf(a),source.indexOf(b,source.indexOf(a)));
const tick=()=>new Promise(setImmediate);
function element(tag,cls,text){return {tag,cls,text,children:[],value:'',disabled:false,inert:false,isConnected:true,append(...nodes){this.children.push(...nodes)},replaceChildren(...nodes){this.children=nodes},setAttribute(){},querySelectorAll(){return []},click(){return this.onclick?.()}};}
function setup({failure=false,catalogError=false}={}){
 let finish,submitted,loads=0;const errors=[],dirty=UX.dirtyRegistry();
 const c=vm.createContext({el:element,editorDirty:dirty,AtlantaUX:UX,Date,setTimeout,clearTimeout,dateTime:value=>value,
  option:(label,value)=>({label,value}),toast(){},editorHeartbeat(){},perform:async fn=>{try{return await fn();}catch(e){errors.push(e.message);}},loadWorkspace:async()=>{loads++},
  api:(path,body)=>{
   if(path==='/api/github/repos/status')return Promise.resolve({repositories:[{full_name:'example/cached'}],current:!catalogError,complete:true,checked_at:new Date().toISOString(),job:{running:false}});
   if(path==='/api/github/repos/sync')return Promise.reject(new Error('rate limited'));
   submitted=JSON.parse(JSON.stringify(body));return new Promise((resolve,reject)=>finish=()=>failure?reject(new Error('conflict; draft kept')):resolve({repositories:submitted.repositories}));
  }});
 vm.runInContext(extract('async function withEditorSave(','function markNotes()')+extract('function repositoryEditor(project){','async function loadWorkspace()'),c);
 const box=vm.runInContext('repositoryEditor({id:"project",repositories:[]})',c),[input,list,add,save]=box.children[2].children;
 return {c,box,input,list,add,save,dirty,errors,submitted:()=>submitted,finish:()=>finish(),loads:()=>loads};
}
(async()=>{
 const f=setup();await tick();assert.equal(f.list.children[0].value,'example/cached');
 f.input.value='example/first';f.input.oninput();assert(f.dirty.has());assert(!f.save.disabled);
 const job=f.save.onclick();assert(f.box.inert);assert(f.input.disabled&&f.add.disabled&&f.save.disabled);
 f.add.onclick();const double=f.save.onclick();await double;
 assert.deepEqual(f.submitted().repositories,['example/first']);assert.deepEqual(f.submitted().expected_repositories,[]);
 f.finish();await job;assert.equal(f.loads(),1);assert(!f.dirty.has());assert(!f.box.inert);
 const failed=setup({failure:true});failed.input.value='example/keep';failed.add.onclick();const writing=failed.save.onclick();failed.finish();await writing;
 assert(failed.dirty.has());assert(!failed.input.disabled);assert(!failed.box.inert);assert.equal(failed.loads(),0);assert.match(failed.errors[0],/draft kept/);
 const offline=setup({catalogError:true});await tick();await tick();assert.equal(offline.list.children[0].value,'example/cached');assert.match(offline.box.children[4].textContent,/rate limited/);assert.equal(offline.box.children[3].disabled,false);
 // A workspace request started before typing cannot replace the repository editor after it becomes dirty.
 let resolveWorkspace;const c=vm.createContext({editorDirty:UX.dirtyRegistry(),api:()=>new Promise(r=>resolveWorkspace=r),$:()=>({value:'project'}),renderWorkspace:()=>{throw new Error('Must keep editor')},fillProjects(){},option(){},syncRoute(){}});
 vm.runInContext('let workspaceSequence=0,view="projects",workspaceData={version:"original"},state={projects:{}};'+extract('async function loadWorkspace(){','function renderWorkspace(){'),c);
 const loading=vm.runInContext('loadWorkspace()',c);c.editorDirty.set('project-repositories',true);resolveWorkspace({project_id:'project',projects:[]});await loading;
 assert.equal(vm.runInContext('workspaceData.version',c),'original');
 console.log('Repository editor PASS: pending input included, save frozen/deduplicated, failures preserve draft, stale workspace and catalog failures keep edits.');
})().catch(e=>{console.error(e);process.exitCode=1;});
