const fs=require('node:fs'),assert=require('node:assert/strict');
const app=fs.readFileSync('web/app.js','utf8'),backend=fs.readFileSync('app/review_queue.py','utf8');
// The queue tells the UI when the Review tab cannot confirm yet: the notes wait for an update.
assert.match(backend,/review_blocked=bool\(meeting\.get\('notes_need_refresh'\)\)/);
// A blocked row explains the wait instead of offering a dead-end button.
assert.match(app,/if\(row\.items&&!row\.review_blocked\)add\('warn'/);
assert.match(app,/\+' wait for review after the notes update'/);
assert.ok(!app.includes("if(row.items)add('warn',AtlantaUX.count(row.items,'item')+' to confirm or dismiss','Review items'"),'the unguarded Review items line is gone');
// The Review tab names the next step instead of only disabling the buttons.
assert.match(app,/btn\('secondary small-action','Update notes'\)/);
assert.match(app,/update\.onclick=\(\)=>perform\(async\(\)=>\{switchTab\('transcript'\);\$\('primary-action'\)/);
console.log('Review queue PASS: blocked rows route to the notes update, actionable rows keep the Review items button.');
