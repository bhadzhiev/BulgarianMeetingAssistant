const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('web/app.js','utf8');
function setup(){const answers=[],questions=[],dirty=new Set();let active,closed=false,saved=0,finish;
 const original={isConnected:true,replaceWith(form){active=form;}};
 function el(tag){return {tag,children:[],value:'',disabled:false,append(...nodes){this.children.push(...nodes);},setAttribute(){},focus(){},replaceWith(node){assert.equal(node,original);closed=true;},click(){if(!this.disabled)return this.onclick();}};}
 const c=vm.createContext({el,editorDirty:{keys:()=>[...dirty],set:key=>dirty.add(key),clear:key=>dirty.delete(key)},perform:fn=>fn(),ask:async message=>{questions.push(message);return answers.shift();},original,save:()=>{saved++;return new Promise(r=>finish=r);}});
 vm.runInContext(source.slice(source.indexOf('function inlineEdit('),source.indexOf('function editDeleteButtons(')),c);vm.runInContext("inlineEdit(original,'Original',save)",c);
 return {answers,questions,area:active.children[0],cancel:active.children[1].children[0],save:active.children[1].children[1],closed:()=>closed,saved:()=>saved,finish:()=>finish()};}
(async()=>{const f=setup();f.area.value='Unsaved';f.answers.push(false);await f.cancel.onclick();assert(!f.closed());assert.equal(f.area.value,'Unsaved');
 f.answers.push(true);let prevented=false,stopped=false;f.area.onkeydown({key:'Escape',preventDefault(){prevented=true},stopPropagation(){stopped=true}});await new Promise(setImmediate);assert(f.closed());assert(prevented&&stopped);assert.equal(f.questions.length,2);
 const g=setup();g.area.value='Changed';const pending=g.save.onclick();assert(g.cancel.disabled);await g.cancel.click();assert(!g.closed());assert.equal(g.saved(),1);g.finish();await pending;assert(!g.cancel.disabled);
 console.log('Cancel editing PASS: Keep editing preserves text, Escape shares confirmation, and saves cannot be interrupted by Cancel.');
})().catch(e=>{console.error(e);process.exitCode=1;});
