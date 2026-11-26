const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const app = fs.readFileSync(path.join(root, 'web/app.js'), 'utf8');
const html = fs.readFileSync(path.join(root, 'web/index.html'), 'utf8');
const tasks = require('../web/task-model.js');

assert.match(html, /data-team-tab="attention">Needs me/);
assert.match(html, /id="tab-daily"[^>]+>After the daily/);
assert.match(app, /prepareScope=\{project:data\.project_id,series:result\.series_id,type:'daily'\}/);
assert.match(app, /openManualTask\(meeting\.id,\{text:row\.text.*mention:row\.index,minutesRevision:meeting\.minutes_revision/);
assert.match(app, /'update',\{task_id:task\.id,task_revision:task\.revision,changes\}/);
assert.equal(tasks.inView({workflow_state:'waiting',follow_up_date:'2099-01-01'},'followup',{today:'2026-11-21'}),false);
assert.equal(tasks.inView({workflow_state:'waiting'},'followup',{today:'2026-11-21'}),true);

function node(tag, cls, text) {
    return {tag, cls, text, children: [], append(...items) {this.children.push(...items);},
        replaceChildren(...items) {this.children = items;}, querySelectorAll() {return [];}};
}
const box = node('section');
const calls = [];
const context = vm.createContext({
    $: () => box,
    el: node,
    actionBtn: (cls, text, run) => Object.assign(node('button', cls, text), {run}),
    api: async (...args) => {calls.push(args);},
    view: 'detail',
    selected: 'a'.repeat(32),
    openMeeting: async () => {},
    sourceBlock: timestamp => node('span', '', timestamp),
});
vm.runInContext(app.slice(app.indexOf('function dailyTopicRows('), app.indexOf('function renderManagerAttention(')), context);
const descendants = item => [item, ...item.children.flatMap(descendants)];
(async () => {
    const meeting = {id:context.selected, daily_review:{status:'ready', revision:'source-revision', agenda_revision:'agenda-revision',
        series_id:'s1', topics:[{id:'q1',text:'Verify Q01'}], rows:[{field:'decisions',text:'Keep staging',key:'r',state:'pending',timestamp:'00:00:01'}],tasks:[],context:[{field:'today',person:'Maria',topic:'Integration',text:'Continue the tests',timestamp:'00:00:02'}]}};
    context.renderDailyAfter(meeting, false);
    assert.ok(descendants(box).some(item=>item.text==='00:00:01'));
    const person=descendants(box).find(item=>item.cls==='daily-person-group'&&item.children[0].text==='Maria');
    assert.ok(descendants(person).some(item=>item.text==='Integration · Plan'));
    assert.ok(descendants(box).some(item=>item.text==='Shared and unassigned'));
    await descendants(box).find(item=>item.text==='Mark discussed').run();
    assert.equal(calls[0][1].meeting_id, meeting.id);
    assert.equal(calls[0][1].revision, 'agenda-revision');
    await descendants(box).find(item=>item.text==='Confirm decision').run();
    assert.equal(calls[1][1].revision, 'source-revision');
    assert.equal(calls[1][1].key, 'r');
    context.renderDailyAfter({id:meeting.id, daily_review:{status:'stale'}}, false);
    assert.equal(descendants(box).some(item=>item.text==='Confirm decision'),false);
})().catch(error=>{console.error(error);process.exitCode=1;});
