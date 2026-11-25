const fs=require('node:fs'),assert=require('node:assert/strict'),vm=require('node:vm');
const app=fs.readFileSync('web/app.js','utf8');
const at=app.indexOf('function renderTaskEmail(data){'),body=app.slice(at,app.indexOf("\n $('task-email-subject').value=data.subject",at))+'\n}';
// The current people are preselected with one address each; an older draft's recipients are an explicit choice (2026-11-25).
const node=(tag,cls='',text='')=>{const n={tag,className:cls,textContent:text,children:[],checked:false,value:'',append(...k){n.children.push(...k);},prepend(...k){n.children.unshift(...k);},replaceChildren(){n.children=[];},querySelectorAll(){return n.children.flatMap(c=>c.children||[]).filter(c=>c.tag==='input');}};return n;};
const people=node('div'),extra={value:'x'},dirty=[];
const c=vm.createContext({$:id=>id==='task-email-people'?people:extra,el:node,btn:(cls,label)=>node('button',cls,label),emptyNote:t=>node('p','',t),editorDirty:{set:(k,v)=>dirty.push(k)}});
vm.runInContext(body+';this.render=renderTaskEmail;',c);
const recipients=[{name:'Ana',email:'ana@example.test',involved:true,suggested:true},{name:'Ana',email:'ana.home@example.test',involved:true,suggested:false},{name:'Old owner',email:'old@example.test',involved:false,suggested:false}];
const checked=()=>people.children.filter(l=>l.children?.[0]?.tag==='input').filter(l=>l.children[0].checked).map(l=>l.children[0].value);
c.render({recipients,draft:null});assert.deepEqual(checked(),['ana@example.test']);assert.equal(extra.value,'');
c.render({recipients,draft:{to:['old@example.test','partner@example.test']}});
assert.deepEqual(checked(),['ana@example.test'],'a draft does not choose the recipients');
const note=people.children[0];assert.match(note.textContent,/^The Gmail draft goes to old@example\.test, partner@example\.test\./);
note.children[1].onclick();assert.deepEqual(checked(),['old@example.test']);assert.equal(extra.value,'partner@example.test');
c.render({recipients,draft:{to:['Ana@Example.test']}});assert.equal(people.children[0].className.includes('task-email-draft-recipients'),false,'same recipients need no note');
console.log('Task email recipients PASS: current people with one address each; draft recipients only on request.');
