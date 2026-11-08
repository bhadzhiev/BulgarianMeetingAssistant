const fs=require('node:fs'),assert=require('node:assert/strict');
const css=fs.readFileSync('web/style.css','utf8');
const tail=css.slice(css.indexOf('/* One field scale'));
// Fields match the buttons: 32px standard, 28px compact in task rows and editors; the Type chip keeps its size.
assert.match(tail,/select:not\(\.scope-chip\):not\(\.date-popup-head select\)\{\n box-sizing:border-box!important;height:32px!important;min-height:32px!important;font-size:13px!important/);
assert.match(tail,/:is\(\.task-quick-fields,\.tracked-meta,\.task-editor,\.task-bottom,\.work-proposal,\.tracked-edit-bar\) :is\(input:not\(\[type=checkbox\]\):not\(\[type=radio\]\),select\),\n\.segment \.speaker,\.tracked-owner-input\{\n height:28px!important/);
// Mixed rows and button-like disclosures use the same heights.
assert.match(tail,/:root\{--control-h:32px\}/);
assert.match(tail,/details\.github-menu>summary\{box-sizing:border-box;height:28px;min-height:28px/);
console.log('Field scale PASS: 32px fields beside 32px buttons, 28px in task rows, Filters and GitHub match.');
