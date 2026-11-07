const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const src=fs.readFileSync('web/app.js','utf8');
function el(tag,cls='',text=''){return {tag,cls,text,children:[],append(...x){this.children.push(...x)}};}
const c=vm.createContext({el,AtlantaUX:require('../web/ux.js'),FIELD_TITLES:{}});
vm.runInContext(src.slice(src.indexOf('function consolidationProof('),src.indexOf('\n}\n',src.indexOf('function consolidationProof('))+2),c);
// A failed consolidation shows a plain warning instead of merge evidence.
const note=vm.runInContext("consolidationProof({status:'failed',parts:3,error:'bad response',groups:{},candidates:[]})",c);
assert.equal(note.tag,'p');assert.ok(note.cls.includes('warning'));
assert.match(note.text,/^Some statements may appear twice\. The AI could not merge the repeated statements of 3 parts of this long meeting\./);assert.match(note.text,/Generate new AI notes/);
// The technical reason stays out of the text and goes into the tooltip.
assert.doesNotMatch(note.text,/bad response/);assert.equal(note.title,'Technical reason: bad response');
// A completed one still shows the evidence block.
assert.equal(vm.runInContext("consolidationProof({status:'completed',merged:0,groups:{},candidates:[]})",c).tag,'details');
console.log('Consolidation warning PASS: failed merge shows a plain warning with the reason in its tooltip; completed merge keeps the evidence block.');
