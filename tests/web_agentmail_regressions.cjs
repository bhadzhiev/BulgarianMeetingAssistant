const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
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


// Start with a failed task-model script, then open the AgentMail editor through the normal source action.
(async () => {
    const scripts = [], calls = [], errors = [];
    let closeDraft;
    const context = vm.createContext({
        taskDraftPending: false, taskEvidenceTarget: null, itemsData: null,
        el: () => ({remove() { this.removed = true; }}),
        document: {head: {append(script) { scripts.push(script); }}},
        toast: message => errors.push(message),
        error: message => errors.push(message),
        api: async (url, body) => {
            calls.push([url, body]);
            return url === '/api/items' ? {items: []} : {ai_available: false};
        },
        openManualTask: (_id, options) => {
            assert.equal(options.source.provider, 'agentmail');
            return new Promise(resolve => { closeDraft = resolve; });
        },
    });
    vm.runInContext(app.slice(app.indexOf('let taskModelLoading='), app.indexOf('// Improve with AI')), context);
    const source = {provider: 'agentmail', id: '<test@agentmail.to>', revision: 'first'};
    const button = {disabled: false};

    const failure = context.suggestTask(button, source);
    const expectedFailure = assert.rejects(failure, /Task controls could not load/);
    assert.equal(scripts.length, 1);
    scripts[0].onerror();
    await expectedFailure;
    assert.equal(button.disabled, false);
    assert.equal(calls.length, 0);

    const capture = context.suggestTask(button, source);
    const loading = context.ensureTaskModel();
    assert.equal(scripts.length, 2);
    assert.equal(scripts[1].src, '/task-model.js');
    vm.runInContext(fs.readFileSync(path.join(root, 'web/task-model.js'), 'utf8'), context);
    scripts[1].onload();
    await loading;
    await capture;
    assert.ok(scripts.every(script => script.removed));
    assert.deepEqual(calls.map(([url]) => url), ['/api/items', '/api/task-draft/preview']);
    assert.equal(calls[1][1], source);
    closeDraft(null);
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(button.disabled, false);
    assert.deepEqual(errors, []);
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
