const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('web/app.js','utf8');
const extract=(a,b)=>source.slice(source.indexOf(a),source.indexOf(b,source.indexOf(a)));
const select={children:[],dataset:{},value:'',hidden:false,disabled:false,replaceChildren(...nodes){this.children=nodes;}};
const c=vm.createContext({$:()=>select,option:(text,value)=>({text,value})});
vm.runInContext(extract('function renderDraftAssignee(','function updateDraftLink()'),c);
const people=[{id:'p1',name:'Synthetic One',login:'one',checked:true},{id:'p2',name:'Synthetic Two',login:'two',checked:false}];
// A confirmed owner with a GitHub username is the default.
c.renderDraftAssignee({people,assignee:'@two'},'issue');
assert.equal(select.value,'two');assert.equal(select.children.length,3);assert.match(select.children[2].text,/not checked/);
// A person's choice stays when the draft refreshes, also "No assignee".
select.dataset.chosen='one';c.renderDraftAssignee({people,assignee:'@two'},'issue');assert.equal(select.value,'one');
select.dataset.chosen='-';c.renderDraftAssignee({people,assignee:'@two'},'issue');assert.equal(select.value,'');
// Comments have no assignee; without people the control is disabled.
c.renderDraftAssignee({people,assignee:null},'comment');assert.equal(select.hidden,true);
select.dataset.chosen='';c.renderDraftAssignee({people:[],assignee:null},'issue');assert.equal(select.disabled,true);assert.equal(select.value,'');
console.log('GitHub draft assignee PASS: owner default, kept choice, comment hidden, empty list disabled.');
