const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('web/app.js','utf8');
const extract=(a,b)=>source.slice(source.indexOf(a),source.indexOf(b,source.indexOf(a)));
const tick=()=>new Promise(setImmediate);
function element(tag,cls,text){return {tag,cls,text,children:[],value:'',disabled:false,hidden:false,dataset:{},append(...nodes){this.children.push(...nodes)},replaceChildren(...nodes){this.children=nodes},setAttribute(){}};}
function setup(projects){
 const box=element('div'),calls=[],editors=[];let drafts=0,refreshes=0;
 const c=vm.createContext({el:element,option:(text,value)=>({text,value}),$:()=>box,projectList:()=>projects,draftResource:{kind:'item',id:'task1'},
  api:async(path,body)=>{calls.push([path,body]);return {};},perform:fn=>fn(),renderDraft:async()=>{drafts++;},refreshAfterItemChange:async()=>{refreshes++;},
  repositoryEditor:(project,options)=>{editors.push([project,options]);return element('section','project-repos');}});
 vm.runInContext(extract('function renderDraftRouting(','function updateDraftLink()'),c);
 return {c,box,calls,editors,drafts:()=>drafts,refreshes:()=>refreshes};
}
(async()=>{
 // A task without a project: the dialog offers the projects and assigns the chosen one.
 let t=setup([{id:'p1',name:'Platform'}]);
 t.c.renderDraftRouting({repositories:[],projects:[],revision:4});
 assert.equal(t.box.hidden,false);
 const [choose,apply]=t.box.children[1].children;
 assert.equal(apply.disabled,true);choose.value='p1';choose.onchange();assert.equal(apply.disabled,false);
 await apply.onclick();await tick();
 assert.equal(JSON.stringify(t.calls[0]),JSON.stringify(['/api/work/project',{id:'task1',revision:4,project_ids:['p1']}]));
 assert.equal(t.drafts(),1);assert.equal(t.refreshes(),1);
 // A project without repositories: the dialog opens the repository editor for it.
 t=setup([{id:'p1',name:'Platform'}]);
 t.c.renderDraftRouting({repositories:[],projects:[{id:'p1',name:'Platform',repositories:[]}]});
 assert.equal(t.editors.length,1);assert.equal(t.editors[0][1].open,true);
 await t.editors[0][1].onSaved();assert.equal(t.drafts(),1);
 // The same routing does not rebuild the editor, so staged links stay.
 t.c.renderDraftRouting({repositories:[],projects:[{id:'p1',name:'Platform',repositories:[]}]});
 assert.equal(t.editors.length,1);
 // Linked repositories: nothing to fix.
 t=setup([]);t.c.renderDraftRouting({repositories:['org/repo'],projects:[{id:'p1',name:'Platform',repositories:['org/repo']}]});
 assert.equal(t.box.hidden,true);assert.equal(t.editors.length,0);
 console.log('GitHub draft routing PASS: project choice, repository linking, stable editor, hidden when routed.');
})().catch(error=>{console.error(error);process.exit(1);});
