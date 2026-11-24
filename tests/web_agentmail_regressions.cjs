const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const app = fs.readFileSync(path.join(root, 'web/app.js'), 'utf8');
const html = fs.readFileSync(path.join(root, 'web/index.html'), 'utf8');

assert.match(html, /data-work-tab="agentmail"/);
assert.match(html, /id="agentmail-key" type="password"/);
assert.match(app, /field\.value='';\s*await api\('\/api\/agentmail\/connect'/);
assert.match(app, /provider:'agentmail',inbox,id,revision:row\.revision/);
assert.match(app, /'Create task…'.*'Add update to task…'/);
assert.match(app, /if\(agentMailSource\)\{draft\.hidden=true;improve\.hidden=true;\}/);
assert.match(app, /payload\.link_update=updateText\.value\.trim\(\)/);
