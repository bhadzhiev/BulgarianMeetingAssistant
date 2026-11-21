const assert = require('node:assert/strict');
const tasks = require('../web/task-model.js');

const archived = new Set(['old']);
assert.equal(tasks.inActiveProjects({effective_project_ids: ['old']}, archived), false);
assert.equal(tasks.inActiveProjects({effective_project_ids: ['old', 'ongoing']}, archived), true);
assert.equal(tasks.inActiveProjects({effective_project_ids: []}, archived), true);
assert.equal(tasks.isOpen({status: 'done'}), false);
assert.equal(tasks.isOpen({status: 'open', workflow_state: 'cancelled'}), false);
const dated = [
    {id: 'future', due_date: '2026-11-29'},
    {id: 'normal', due_date: '2026-11-28'},
    {id: 'critical', due_date: '2026-11-28', priority: 'critical'},
    {id: 'late', due_date: '2026-11-20'},
    {id: 'undated'},
];
assert.deepEqual(tasks.focusSuggestions(dated, '2026-11-21').map(item => item.id), ['late', 'critical', 'normal']);
assert.equal(tasks.completedAt({created: '2026-10-01', history: [
    {at: '2026-11-01', changes: {status: ['open', 'done']}},
    {at: '2026-11-04', changes: {status: ['done', 'open']}},
    {at: '2026-11-12', changes: {workflow_state: ['todo', 'done']}},
    {at: '2026-11-20', changes: {text: ['Original', 'Edited']}},
]}), '2026-11-12');
const child = {id: 'child', parent_task_id: 'parent'};
const parent = {id: 'parent'};
assert.deepEqual(tasks.historyPage([child, {id: 'other'}, parent], 1), [child, parent]);
assert.deepEqual(tasks.historyPage([child], 1), [child]);
