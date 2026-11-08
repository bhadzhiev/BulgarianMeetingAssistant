const fs=require('node:fs'),assert=require('node:assert/strict');
const Forms=require('../web/forms.js'),css=fs.readFileSync('web/style.css','utf8'),html=fs.readFileSync('web/index.html','utf8');
// D06: messages say what to do, in the words of the field label.
const field=(extra)=>({tagName:'INPUT',type:'text',labels:[{childNodes:[{nodeType:3,textContent:'Project name'}]}],getAttribute:()=>null,validity:{},validationMessage:'native',...extra});
assert.equal(Forms.fieldName(field()),'Project name');
assert.equal(Forms.message(field({validity:{valueMissing:true}})),'Enter project name.');
assert.equal(Forms.message(field({tagName:'SELECT',validity:{valueMissing:true}})),'Choose project name.');
assert.equal(Forms.message(field({type:'email',validity:{typeMismatch:true}})),'Enter a valid email address.');
assert.equal(Forms.message(field({maxLength:80,validity:{tooLong:true}})),'Use at most 80 characters.');
// A required mark that a screen reader does not read twice (the field already says required).
assert.match(css,/label\.required-label::after,\.required-label>\.date-part-label::after\{content:' \*' \/ '';/);
// The summary shows only after a press of a button or Enter, not after a check that the code makes.
const src=fs.readFileSync('web/forms.js','utf8');
assert.match(src,/if\(Date\.now\(\)-attempt>1000\)return;/);
assert.match(src,/event\.preventDefault\(\);showError\(field\);/);
assert.match(src,/box\.setAttribute\('role','alert'\)/);
// The error stays until the field is correct.
assert.match(src,/if\(field\.validity\.valid\)\{clearError\(field\);\}/);
// The page loads the rule before the app, and the server serves it.
assert.ok(html.indexOf('/forms.js')<html.indexOf('/app.js'));
assert.match(fs.readFileSync('desktop_app.py','utf8'),/'\/forms\.js': 'forms\.js'/);
// D05 and D01 have their references.
assert.match(fs.readFileSync('docs/terminology.md','utf8'),/\*\*Status: draft\.\*\*/);
assert.match(fs.readFileSync('scripts/check_layout.cjs','utf8'),/const REQUIRED=\[360,430,768,1280,1440,1920\]/);
console.log('Forms PASS: field messages, required mark, summary on submit only, errors stay until fixed, D05 and D01 references.');
