const fs=require('node:fs'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8');
const card=app.slice(app.indexOf('function linkCard('),app.indexOf('function evidenceBlock('));
// Same task links the meeting as evidence; only the fields that a person checks change.
assert.match(card,/\['same','Same task','primary','Links this meeting as evidence\. Only the checked fields change\. The status stays\.'\]/);
assert.doesNotMatch(app,/Same task · update/);
// Each field that the meeting said differently: current → said, unchecked. An edited field only says that it stays.
assert.match(card,/line\.append\(box,document\.createTextNode\(label\+': '\+show\(now\)\+' → '\+show\(said\)\)\)/);
assert.doesNotMatch(card,/box\.checked=true/);
assert.match(card,/if\(\(item\.manual\|\|\[\]\)\.includes\(name\)\)\{changes\.append\(el\('p','hint',label\+' stays '\+show\(now\)\+' · you edited it'\)\);continue;\}/);
// The revision that the person saw goes with the choice, so a changed item is a conflict.
assert.match(card,/resolve\(action,item\.id,\{revision:item\.revision,\.\.\.\(action==='same'&&kind==='task'\?\{fields:checks\.filter\(c=>c\.checked\)\.map\(c=>c\.value\)\}:\{\}\)\}\)/);
// The text says what found the candidates: text similarity, not AI.
assert.match(app,/These mentions have wording close to existing items \(text similarity\)\./);
assert.doesNotMatch(app,/The AI found mentions/);
assert.match(fs.readFileSync('desktop_app.py','utf8'),/body\.get\('item_id'\), body\.get\('fields'\), body\.get\('revision'\)\)/);
console.log('Link review PASS: Same task links only, checked fields change, edited fields stay, revision conflict, honest wording.');
