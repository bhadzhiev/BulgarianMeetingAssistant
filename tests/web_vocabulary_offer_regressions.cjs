const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const src=fs.readFileSync('web/app.js','utf8'),css=fs.readFileSync('web/style.css','utf8');
// A save that returns vocabulary suggestions offers them one at a time, in a box that the save toast does not replace.
assert.ok(src.includes("if(data&&Array.isArray(data.vocabulary_suggestions)&&data.vocabulary_suggestions.length)offerVocabulary(data.vocabulary_suggestions);"));
const start=src.indexOf('let vocabularyOffers=[];'),end=src.indexOf('function showCreatedTask(');
class Node{constructor(c,t){this.className=c;this.text=t;this.children=[];this.hidden=false;}append(...n){this.children.push(...n);}replaceChildren(...n){this.children=n;}setAttribute(){}}
const nodes={},calls=[];
const c=vm.createContext({el:(t,c,x)=>new Node(c,x),document:{getElementById:id=>nodes[id]||null,body:{append:n=>{nodes[n.id]=n;}}},
 perform:fn=>fn(),api:async(p,b)=>{calls.push([p,b]);},toast:m=>calls.push(['toast',m])});
vm.runInContext(src.slice(start,end),c);
vm.runInContext("offerVocabulary([{term:'example.org',variant:'Ex Am Pull'}]);offerVocabulary([{term:'ATLAS',variant:null},{term:'example.org',variant:'Ex Am Pull'}])",c);
const box=nodes['vocabulary-offer'];
assert.equal(box.children[0].text,'Add “example.org” (heard as “Ex Am Pull”) to the vocabulary?');
assert.equal(vm.runInContext('vocabularyOffers.length',c),2,'the same offer is not queued twice');
(async()=>{
 await box.children[1].onclick();
 assert.equal(JSON.stringify(calls[0]),JSON.stringify(['/api/vocabulary/add',{term:'example.org',variant:'Ex Am Pull'}]));
 assert.equal(box.children[0].text,'Add “ATLAS” to the vocabulary?');
 box.children[2].onclick();assert.equal(box.hidden,true);assert.equal(calls.filter(x=>x[0]==='/api/vocabulary/add').length,1);
 assert.ok(css.includes('.vocabulary-offer{position:fixed;bottom:80px'));
 console.log('Vocabulary offer PASS: queued once, Add saves, Not now skips.');
})();
