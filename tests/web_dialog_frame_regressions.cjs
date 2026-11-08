const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8'),css=fs.readFileSync('web/style.css','utf8');
const slice=(a,b)=>{const at=app.indexOf(a);assert.notEqual(at,-1,a);return app.slice(at,app.indexOf(b,at));};

// The first visible child of a dialog's content is its title, the last its button bar; both stay in view.
class Node{constructor(cls,kids=[]){this.cls=cls;this.children=kids;this.shown=true;this.classList={contains:name=>name===cls};}getClientRects(){return this.shown?[{}]:[];}
 matches(sel){return sel.split(',').some(s=>s.trim()===this.cls||s.trim()==='.'+this.cls);}}
const c=vm.createContext({});vm.runInContext(slice('const DIALOG_HEAD=','function frameDialog(')+';this.parts=dialogParts;',c);
const head=new Node('card-heading'),body=new Node('p'),foot=new Node('review-footer'),form=new Node('form',[head,body,foot]);
let parts=c.parts({children:[form]});assert.equal(parts.head,head);assert.equal(parts.foot,foot);
// A message without a title (ask) and a body without a button bar (viewer) mark only what they have.
parts=c.parts({children:[new Node('p'),foot]});assert.equal(parts.head,null);assert.equal(parts.foot,foot);
parts=c.parts({children:[head,body]});assert.equal(parts.head,head);assert.equal(parts.foot,null);
// A hidden last child is not the bar.
const hiddenFoot=new Node('review-footer');hiddenFoot.shown=false;parts=c.parts({children:[head,body,hiddenFoot]});assert.equal(parts.foot,null);
// An open date calendar inside the dialog is not its title, content or buttons.
parts=c.parts({children:[form,new Node('date-popup')]});assert.equal(parts.head,head);assert.equal(parts.foot,foot);
assert.match(slice('function dialogParts(','function revealInDialog('),/dialog\.id==='settings-dialog'\|\|!dialog\.open/);
// The bars are opaque and cover the dialog padding beside them, so no scrolled text shows through.
assert.match(css,/dialog \.dialog-head\{position:sticky;top:0;z-index:4;background:var\(--card\);box-shadow:0 calc\(-1 \* var\(--dialog-pad-top\)\) 0 var\(--card\)\}/);
assert.match(css,/dialog \.dialog-foot\{position:sticky;bottom:0;z-index:4;background:var\(--card\);box-shadow:0 var\(--dialog-pad-bottom\) 0 var\(--card\)\}/);
// The task panel bar had a negative margin from one rule and bottom:0 from another; text showed under it.
assert.match(css,/#task-panel \.task-card-footer\{position:sticky;bottom:0;background:var\(--card\);margin:8px 0 0;padding:14px 0;/);
assert.doesNotMatch(css,/#task-draft-dialog \.review-footer\{position:sticky/);
assert.match(app,/const panelHead=el\('div','task-panel-head'\)/);
console.log('Dialog frame PASS: title and buttons stay in view, bars cover the padding, task panel bar fixed.');
