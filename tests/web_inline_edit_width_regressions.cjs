const fs=require('node:fs'),assert=require('node:assert/strict');
const src=fs.readFileSync('web/app.js','utf8'),css=fs.readFileSync('web/style.css','utf8');
// An inline edit next to project chips once kept the narrow width of a flex item and hid most of the text.
assert.ok(css.includes('.entity-top>.inline-editor{flex:1 1 0;min-width:0}'),'the editor takes the width of the title');
assert.ok(css.includes('.inline-editor>.tracked-edit{display:block;width:100%;max-height:60vh}'),'the field fills the editor');
// The field grows to its text when it opens, so the whole text is in view.
const start=src.indexOf('function inlineEdit('),end=src.indexOf('\n}',start);
assert.ok(src.slice(start,end).includes("area.style.height=area.scrollHeight+2+'px'"));
console.log('Inline edit width PASS: full width next to chips, height fits the text.');
