const fs=require('node:fs'),assert=require('node:assert/strict');
const js=fs.readFileSync('web/date-picker.js','utf8'),css=fs.readFileSync('web/style.css','utf8');
// English month names beside the English weekdays (the system locale gave Bulgarian months).
assert.match(js,/new Intl\.DateTimeFormat\('en-GB',\{month:'long'\}\)/);
// A scroll moves the calendar with its field; it closes only when the field leaves the window.
assert.match(js,/document\.addEventListener\('scroll',e=>\{if\(!active\|\|popup\.contains\(e\.target\)\)return;const r=active\.parentElement\.getBoundingClientRect\(\);if\(r\.bottom<0\|\|r\.top>innerHeight\)shut\(false\);else place\(\);\},true\)/);
assert.doesNotMatch(js,/document\.addEventListener\('scroll',e=>\{if\(active&&!popup\.contains\(e\.target\)\)shut\(false\);\},true\)/);
// Today is disabled, with a reason, when it is outside the allowed dates.
assert.match(js,/current\.disabled=!allowed\(today\(\)\);current\.title=current\.disabled\?'Today is outside the allowed dates':''/);
// Dialog button rules do not reach the calendar or the field button.
assert.match(css,/\.date-popup button,\.date-control \.date-trigger\{margin:0!important\}/);
console.log('Date picker PASS: English months, scroll follows the field, Today guard, no dialog margins.');
