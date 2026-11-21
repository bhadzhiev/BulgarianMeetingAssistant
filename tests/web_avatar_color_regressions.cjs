const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8'),css=fs.readFileSync('web/style.css','utf8');
const slice=(a,b)=>{const at=app.indexOf(a);assert.notEqual(at,-1,a);return app.slice(at,app.indexOf(b,at));};
// One avatar color per person (2026-11-20): the color comes from the name, the same in every list.
const node=(tag,cls='',text='')=>({tag,className:cls,textContent:text,style:{setProperty(k,v){this[k]=v;},removeProperty(k){delete this[k];}},title:''});
const c=vm.createContext({el:node});
vm.runInContext(slice('function speakerColor(','function initials(')+slice('function initials(','function speakerBadge('),c);
vm.runInContext(slice('function avatar(name)','\n'),c);
const color=n=>vm.runInContext('speakerColor',c)(n);
assert.match(color('Ivan Petrov'),/^hsl\(\d{1,3} 48% (28|34|40)%\)$/);
assert.equal(color('Ivan Petrov'),color('  ivan   PETROV '),'case and spaces do not change the color');
const names=['Ivan Petrov','Maria Georgieva','Petar Dimitrov','Elena Ivanova','Georgi Nikolov','Anna Stoyanova'];
assert.ok(new Set(names.map(color)).size===names.length,'different names get different colors');
const face=vm.runInContext("avatar('Maria Georgieva')",c);
assert.equal(face.style.background,color('Maria Georgieva'));assert.equal(face.style.color,'#fff');assert.equal(face.className,'speaker-badge');assert.equal(face.style['--avatar'],color('Maria Georgieva'),'the ring uses the same colour');
const nobody=vm.runInContext("avatar('')",c);assert.equal(nobody.style.background,'','no owner keeps the neutral badge');
// Every avatar uses the one function; the old eight tones are gone.
assert.match(app,/target\.className='speaker-badge'\+\(known\?'':name\?' new':' empty'\);paintAvatar\(target,known\|\|''\);/);
assert.doesNotMatch(app,/speakerTone|'tone-'/);assert.doesNotMatch(css,/\.tone-[0-7]\b/);
console.log('Avatar colors PASS: one color per name, the same in every list.');
