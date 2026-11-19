const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8');
const slice=(a,b)=>{const at=app.indexOf(a);assert.notEqual(at,-1,a);return app.slice(at,app.indexOf(b,at));};

// rowMenu puts its buttons into a closed menu with a label, and a choice closes it.
{
 const listeners=[],node=(tag,cls='',text='')=>{const n={tag,className:cls,textContent:text,children:[],attrs:{},open:false,
  classList:{removed:[],remove(...names){this.removed.push(...names);}},append(...kids){this.children.push(...kids);},
  setAttribute(k,v){this.attrs[k]=v;},addEventListener(type,fn){this['on'+type]=fn;}};return n;};
 const c=vm.createContext({el:node,document:{addEventListener:(type,fn)=>listeners.push([type,fn]),querySelectorAll:()=>[]}});
 vm.runInContext(slice('function rowMenu(','function editDeleteButtons('),c);
 const remove=node('button','quiet danger-text','Delete');
 const menu=vm.runInContext('rowMenu',c)('More actions for this task',remove);
 assert.equal(menu.className,'menu row-menu');assert.equal(menu.children[0].attrs['aria-label'],'More actions for this task');
 assert.equal(menu.children[1].children[0],remove);assert.deepEqual(remove.classList.removed,['quiet','small-action','secondary']);
 menu.open=true;menu.children[1].onclick();assert.equal(menu.open,false);
 vm.runInContext('rowMenu',c)('Second');assert.equal(listeners.length,1,'one document listener for every menu');
}
// Edit and Delete are direct icon controls on notes lines and meeting tasks.
assert.match(slice('function noteButtons(','\nfunction '),/return \[compactAction\(edit,'edit'\),compactAction\(remove,'trash'\)\];/);
assert.match(slice('function editDeleteButtons(','function itemActions('),/return \[compactAction\(edit,'edit'\),compactAction\(remove,'trash'\)\];/);
assert.match(slice('function taskRow(','function renderNotes('),/actions\.append\(compactAction\(doneButton\(item,busy\),item\.status==='done'\?'restore':'check'\),compactAction\(edit,'edit'\),compactAction\(remove,'trash'\)\)/);
// My Work decisions keep their actions in the same menu as tasks, so the text has the width.
assert.match(slice('function decisionRow(','async function loadTasks('),/const menuActions=itemActions\(item,row,\{direct:true\}\);if\(item\.status!=='proposed'\)menuActions\.prepend\(change\);more\.append\(trigger,menuActions\);row\.append\(more\)/);
// Projects use the My Work rows for tasks and decisions, without the bulk selection box.
const workspace=slice('function renderWorkspace(){','\nfunction ');
assert.match(workspace,/if\(full\.kind==='task'\)return globalTaskRow\(full,today,\{select:false\}\)/);
assert.match(workspace,/if\(full\.kind==='decision'\)return decisionRow\(full,byId\)/);
assert.equal((workspace.match(/box\.append\(workCard\(item\)\)/g)||[]).length,2);
assert.match(app,/function globalTaskRow\(item,today,\{select=true,showProject=true,nested=false\}=\{\}\)/);
assert.match(app,/if\(select&&item\.acceptance_state!=='proposed'&&!item\.dismissed\)/);
// The overview heading counts every item, and a button opens the rest.
assert.match(workspace,/if\(rows\.length>5\)box\.append\(actionBtn\('secondary small-action workspace-show-all','All '\+title\.toLowerCase\(\)\+' in Work →'/);
console.log('One task card PASS: row menu, direct Edit/Delete, wide decisions, shared rows in Projects, Show all.');
