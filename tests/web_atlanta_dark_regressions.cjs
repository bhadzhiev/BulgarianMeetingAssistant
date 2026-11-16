const fs=require('node:fs'),assert=require('node:assert/strict');
// Atlanta Dark (2026-11-16): neutral surfaces, restrained green, one colour per task state.
const css=fs.readFileSync('web/style.css','utf8'),app=fs.readFileSync('web/app.js','utf8');
for(const token of ['--paper:#0b0f0d','--side-bg:#101613','--modal:#171d19','--card:#171e1a','--field:#111713','--line:#344039','--ink:#e8eee9','--muted:#a7b3aa','--green:#50d68b','--accent-strong:#69e5a0','--ok-soft:#173825','--warn-soft:#3a2d19','--danger-soft:#3d2225','--info:#79afff','--backdrop:#000000a6'])assert(css.includes(token),token);
assert.doesNotMatch(css,/#54dc88/,'the Matrix green is gone');
assert.doesNotMatch(css,/repeating-linear-gradient\(0deg/,'no decorative sidebar texture');
// Passive labels are neutral; links use the info colour with low specificity so classed links keep theirs.
assert.match(css,/a:where\(:not\(\.button,\.primary,\.secondary\)\),\.exports a/);
assert.match(css,/\.manager-view-button\.manager-view-button\[aria-pressed=true\],\.segmented\.segmented button\.selected\{background:var\(--selected,var\(--surface-2\)\)/);
assert.match(css,/\.project-chip\.project-chip\{background:var\(--surface\)\}/);
// Task states carry data-state and one colour each.
for(const s of ['todo','in_progress','done','waiting','cancelled'])assert.match(css,new RegExp('\\[data-state='+s+'\\]\\{color:var\\(--state-'));
assert.match(app,/status\.setAttribute\?\.\('data-state',workflow\)/);assert.match(app,/stateFact\.setAttribute\('data-state',AtlantaTasks\.workflow\(item\)\)/);
assert.match(app,/const PROJECT_PALETTE=\['#79afff','#79c995','#d9c56f','#d97bac','#b69af5','#e6a36b','#64c7ba','#d98282','#929d96'\]/);
console.log('Atlanta Dark PASS: palette tokens, no Matrix green or texture, neutral labels and switches, state colours, project palette.');
