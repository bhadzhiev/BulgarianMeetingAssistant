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
assert.match(html, /id="task-email-agentmail-send"[^>]* hidden>Send from Atlanta</);
assert.match(app, /\$\('task-email-agentmail-send'\)\.hidden=!taskEmailAgentInbox/);

async function testSendConfirmation() {
    const fields = new Map(), confirmations = [], requests = [];
    let confirmed = false;
    const context = vm.createContext({
        $: id => {
            if (!fields.has(id)) fields.set(id, {});
            return fields.get(id);
        },
        perform: action => action(),
        withDialogAction: (_dialog, action) => action(),
        taskEmailRecipients: () => ['recipient@example.test'],
        taskEmailAgentInbox: 'test@agentmail.to',
        taskEmailItems: ['task-1'],
        ask: async message => { confirmations.push(message); return confirmed; },
        api: async (path, body) => { requests.push([path, body]); return {to: body.to}; },
        editorDirty: {clear() {}},
        refreshAfterItemChange: async () => {},
        toast() {},
    });
    context.$('task-email-subject').value = 'Reviewed subject';
    context.$('task-email-body').value = 'Reviewed text';
    context.$('task-email-dialog').close = () => {};
    vm.runInContext(app.slice(app.indexOf("$('task-email-agentmail-send').onclick"),
        app.indexOf("$('task-email-save').onclick")), context);

    await context.$('task-email-agentmail-send').onclick();
    assert.match(confirmations[0], /test@agentmail\.to to recipient@example\.test/);
    assert.equal(requests.length, 0);
    confirmed = true;
    await context.$('task-email-agentmail-send').onclick();
    assert.deepEqual(JSON.parse(JSON.stringify(requests)), [
        ['/api/task-email/send-agentmail', {
            item_ids: ['task-1'], inbox: 'test@agentmail.to', to: ['recipient@example.test'],
            subject: 'Reviewed subject', body: 'Reviewed text',
        }],
    ]);
}


// Start with a failed task-model script, then open the AgentMail editor through the normal source action.
(async () => {
    await testSendConfirmation();
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
