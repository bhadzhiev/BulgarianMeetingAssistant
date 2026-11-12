const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8'),css=fs.readFileSync('web/style.css','utf8');
const slice=(a,b)=>{const at=app.indexOf(a);assert.notEqual(at,-1,a);return app.slice(at,app.indexOf(b,at));};
// V01: one contract for every floating menu, also the task menus.
assert.match(app,/const FLOATING_MENUS='details\.menu,details\.task-more';/);
{
 const menus=[],listeners={};
 const menu=(inner=null)=>({open:true,contains:x=>x===inner,querySelector:()=>({focus(){this.focused=true;}})});
 const c=vm.createContext({document:{querySelectorAll:()=>menus,addEventListener:(t,f)=>{listeners[t]=f;}},window:{}});
 vm.runInContext(slice('const FLOATING_MENUS','// A menu opens below its trigger.'),c);
 const task=menu(),meeting=menu();menus.push(task,meeting);
 // A click outside closes every menu.
 listeners.click({target:{closest:()=>null}});assert.equal(task.open,false);assert.equal(meeting.open,false);
 // Escape closes the menu, keeps the dialog open and returns the focus.
 task.open=true;let prevented=false;listeners.keydown({key:'Escape',preventDefault(){prevented=true;}});assert.equal(task.open,false);assert(prevented);
 // No open menu: Escape stays with the dialog.
 prevented=false;listeners.keydown({key:'Escape',preventDefault(){prevented=true;}});assert.equal(prevented,false);
 // A click inside one menu keeps it and closes the other.
 task.open=meeting.open=true;listeners.click({target:{closest:s=>s==='details.menu,details.task-more'?task:null}});assert.equal(task.open,true);assert.equal(meeting.open,false);
}
// V02: a menu flips above its trigger and moves to stay in the window.
const place=slice('function placeMenu(menu){','\n}\n');
assert.match(place,/pop\.style\.bottom='calc\(100% \+ 6px\)'/);assert.match(place,/pop\.style\.transform='translateX\('/);
assert.match(app,/document\.addEventListener\('toggle',event=>\{const menu=event\.target;if\(!menu\.matches\?\.\(FLOATING_MENUS\)\|\|!menu\.open\)return;closeMenus\(menu\);placeMenu\(menu\);\},true\);/);
// V03: one selected quality profile; Maximum privacy shows that it is in effect.
const mark=slice('function markProfile(){','\n}\n');
assert.match(mark,/const chosen=\['fast','balanced','best'\]\.find\(fits\);/);
assert.match(mark,/b\.classList\.toggle\('selected',!privacy&&on\);b\.classList\.toggle\('in-effect',privacy&&on\)/);
assert.match(css,/\.profile\.in-effect strong::after\{content:'✓ In effect'/);
// V04: a task without a project says so.
// Since 2026-11-12 the task editor names the current projects in its Project field, not in a separate line.
assert.match(app,/option\(currentProjects\.length\?currentProjects\.join\(', '\):'No project','keep'\)/);
// V05: Settings keeps more room for its fields.
assert.match(css,/#settings-form>\.card-heading\{margin-bottom:6px!important\}/);
assert.match(css,/#settings-form \.settings-footer\{display:flex;flex-wrap:wrap;align-items:center;gap:6px 12px;padding:10px 0 14px\}/);
assert.match(css,/#settings-form>\.tabs\.settings-groups\{display:flex!important;flex:none;flex-wrap:nowrap;overflow-x:auto;gap:14px\}/);
// P01: the month keeps the height of its grid.
assert.match(css,/\.calendar-layout\{align-items:start\}/);
console.log('Visual review PASS: menu contract, menu placement, profile state, empty project, Settings room, calendar.');
