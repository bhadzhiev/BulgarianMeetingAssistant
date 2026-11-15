const fs=require('node:fs'),assert=require('node:assert/strict');
// Type and form scale (2026-11-16): one size per role, 40px controls in forms, compact scales kept in lists and rows.
const css=fs.readFileSync('web/style.css','utf8');
assert.match(css,/#page-header \.heading h1\{font-size:24px;font-weight:600;/);
assert.match(css,/dialog :is\(#task-panel-title,#manual-task-title,\.dialog-head>h2,\.dialog-head>h3,h2\.dialog-head,h3\.dialog-head\)\{font-size:21px;font-weight:600;/);
assert.match(css,/\.card-heading h2,dialog section>h3,dialog \.task-section>summary\{font-size:16px;font-weight:600;/);
assert.match(css,/dialog label,#record-form label\{font-size:13px;font-weight:500\}/);
assert.match(css,/:where\(dialog,#record-form\) select:not\(\.scope-chip\)[^{]*\{\n height:40px!important;min-height:40px!important;padding-left:12px;border-width:1px;border-radius:8px!important\}/);
assert.match(css,/@media\(min-width:481px\)\{\n:is\(dialog,#record-form\) :is\([^{]*\.dialog-foot button:not\(\.small-action\):not\(\.quiet\)\)\{\n min-height:40px!important;height:40px!important;padding:0 16px!important;/);
assert.match(css,/:is\(#task-panel,#manual-task-dialog,dialog\) textarea:not\(\[aria-label=Title\]\)\{min-height:96px\}/);
// Compact task rows and editors keep their 28px fields beside small buttons, even inside a dialog.
assert.match(css,/:not\(:is\(\.task-quick-fields,\.tracked-meta,\.task-editor,\.task-bottom,\.work-proposal,\.tracked-edit-bar\) select\)/);
assert.match(css,/:is\(\.task-quick-fields,\.tracked-meta,\.task-editor,\.task-bottom,\.work-proposal,\.tracked-edit-bar\) :is\(input:not\(\[type=checkbox\]\):not\(\[type=radio\]\),select\),\n\.segment \.speaker,\.tracked-owner-input\{\n height:28px!important;/);
console.log('Type and form scale PASS: 24/21/16/13 type scale, 40px form controls, 96px text areas, compact rows kept.');
