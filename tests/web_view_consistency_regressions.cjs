const fs=require('node:fs'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8'),css=fs.readFileSync('web/style.css','utf8');
// Every view with a plain heading uses the compact top bar, also the first screen.
assert.match(app,/const compact=\['setup','importing','prepare','tasks','projects',\.\.\.LIBRARY_VIEWS\]\.includes\(which\)/);
assert.match(app,/else syncPageHeader\(view\);\n \}finally\{routing=false;syncRoute\(true\);\}/);
// The connection status is a dot in every view, the meeting included.
assert.doesNotMatch(css,/\.compact-header #connection/);assert.match(css,/main #connection\{position:relative;flex:none;width:26px/);
// A card heading keeps its actions together on the right.
assert.match(css,/\.card-heading>:first-child\{margin-right:auto!important\}/);
// A project hides its long hints but never an empty state.
assert.match(app,/function emptyNote\(text\) \{ return el\('p', 'hint empty-note', text\); \}/);
assert.match(css,/#workspace-content>\.hint:not\(\.empty-note\)\{display:none\}/);
// Task and conversation titles use the text colour, not the quiet button grey.
assert.match(css,/\.tracked-text\.task-title,\.conversation-title\{color:var\(--ink\)\}/);
// A generated title joins the date line; pending and failed titles keep their own line.
assert.match(app,/const titleNote=d\.title_status==='generated'&&!d\.title_error;if\(titleNote\)\$\('detail-date'\)\.textContent\+=' · AI title';/);
// The My Work subtitle describes the shown tab; task counts never replace it on other tabs.
assert.match(app,/function taskSummary\(text\)\{if\(\['task','decision'\]\.includes\(workTab\)\)\$\('tasks-summary'\)\.textContent=text;\}/);
const render=app.slice(app.indexOf('function renderTasks('),app.indexOf('\nfunction ',app.indexOf('function renderTasks(')+10));
assert.doesNotMatch(render,/\$\('tasks-summary'\)\.textContent=/);
assert.match(app,/questions:\(\)=>AtlantaUX\.count\(\(itemsData\?\.meeting_questions\|\|\[\]\)\.length,'question'\)\+' from meeting notes · '/);
console.log('View consistency PASS: one header style, status dot, grouped actions, empty states, title colours, tab subtitles.');
