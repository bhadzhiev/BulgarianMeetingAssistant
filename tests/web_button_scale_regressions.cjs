const fs=require('node:fs'),assert=require('node:assert/strict');
const css=fs.readFileSync('web/style.css','utf8');
// Two button sizes: standard 32px/13px for actions and "…" menus, small 28px/12px inside rows.
const tail=css.slice(css.indexOf('/* One button scale'));
assert.match(tail,/:is\(button,a\.button\):is\(\.primary,\.secondary,\.danger,\.danger-text\):not\(\.quiet\):not\(\.small-action\):not\(#start\)/);
assert.match(tail,/\.menu>summary\.overflow-trigger\{\n box-sizing:border-box!important;min-height:32px!important;height:32px!important;padding:0 14px!important;font-size:13px!important/);
assert.match(tail,/:is\(button,a\):is\(\.small-action\),\n\.task-more>summary\.overflow-trigger[^{]*\{\n box-sizing:border-box!important;min-height:28px!important;height:28px!important;padding:0 10px!important;font-size:12px!important/);
// The scale is the last word: no later rule sets another button height.
const after=tail.slice(tail.indexOf('@media(max-width:480px)'));
assert.doesNotMatch(after.slice(after.indexOf('}}')+2),/min-height:\d+px[^}]*\}[^]*button/);
console.log('Button scale PASS: 32px standard, 28px in rows, Start recording keeps its size.');
