const assert=require('assert'),fs=require('fs'),path=require('path');
const root=path.join(__dirname,'..'),app=fs.readFileSync(path.join(root,'web/app.js'),'utf8'),css=fs.readFileSync(path.join(root,'web/style.css'),'utf8');
const row=app.slice(app.indexOf('function globalTaskRow('),app.indexOf('function dueShort('));
// The project closes the facts row (approved 2026-11-21); the title has no chips beside it.
assert.match(row,/meta\.append\(stateFact,priorityBadge,ownerFact\);[\s\S]*if\(chips\.childNodes\.length\)meta\.append\(chips\);/,'the project chip follows the owner on the facts row');
assert.doesNotMatch(app,/task-tile-title-line/,'the title line wrapper is gone');
assert.doesNotMatch(css,/task-tile-title-line/,'no styles remain for the title line');
const section=css.slice(css.indexOf('/* Task card badges (approved 2026-11-21)'),css.indexOf('/* Task forms (approved 2026-11-20)'));
assert.ok(section.length>100,'the badge section sits before the task form styles');
// One role per colour, in both themes.
for(const tone of ['rose','amber','sky','emerald','zinc'])assert.equal((section.match(new RegExp('--tone-'+tone+':#','g'))||[]).length,2,tone+' has a light and a dark value');
assert.match(section,/\.task-priority\.critical\{--tone:var\(--tone-rose\)\}/);
assert.match(section,/\.task-priority\.high\{--tone:var\(--tone-amber\)\}/);
assert.match(section,/\.task-priority\.normal\{--tone:var\(--tone-emerald\)\}/);
assert.match(section,/\[data-state=in_progress\][^{]*\{--tone:var\(--tone-sky\)\}/);
assert.match(section,/\[data-state=done\]\{--tone:var\(--tone-emerald\)\}/);
assert.match(section,/\.due-label\.overdue[^{]*\{color:var\(--tone-rose\)\}/);
assert.match(section,/\.due-label\.today[^{]*\{color:var\(--tone-amber\)\}/);
// Badges share one shape; due dates are coloured text without a box.
assert.match(section,/padding:2px 8px;font-size:\.75rem;[^}]*border-radius:6px/);
assert.doesNotMatch(section,/\.due-label[^{]*\{[^}]*background:(?!transparent)/,'due dates have no background');
// A done task keeps its title readable but quiet.
assert.match(section,/work-card-closed[^{]*\.task-title\{text-decoration:none;color:var\(--tone-zinc\)\}/);
console.log('task card badges regressions ok');
// Project colours keep their hue at the palette's lightness, so a dark or pale pick stays readable (2026-11-21).
const vm=require('vm'),toneSrc=app.slice(app.indexOf('function projectTone('),app.indexOf('function projectChip('));
const ctx={};vm.runInNewContext(toneSrc+';this.projectTone=projectTone;',ctx);
assert.equal(ctx.projectTone('nope'),null);
assert.deepEqual({...ctx.projectTone('#0042aa')},{dark:'hsl(217 70% 70%)',light:'hsl(217 60% 34%)'},'a dark blue is lifted in the dark theme');
assert.deepEqual({...ctx.projectTone('#e2b33c')},{dark:'hsl(43 70% 70%)',light:'hsl(43 60% 34%)'},'a pale yellow is darkened in the light theme');
assert.equal(ctx.projectTone('#929d96').dark,'hsl(142 8% 70%)','a grey stays grey');
assert.match(section,/\.project-chip\{--tone:currentColor;color:var\(--project-light,var\(--text-2\)\)\}/);
assert.match(section,/prefers-color-scheme:dark\)\{\.task-tile \.task-tile-facts \.project-chip\{color:var\(--project-dark/);
assert.doesNotMatch(row,/chip\.style\.color=project\.color/,'the raw picker colour is not used as text');
// The avatar ring uses the person's own colour.
assert.match(app,/node\.style\.setProperty\('--avatar',color\)/);
assert.match(section,/\.tracked-owner \.speaker-badge\{box-shadow:0 0 0 2px var\(--card\),0 0 0 3px var\(--avatar,var\(--line-strong\)\)\}/);
console.log('project tone and avatar ring ok');
