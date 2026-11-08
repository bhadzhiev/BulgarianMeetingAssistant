import unittest

from app import task_matching as tm

MEETING = dict(id='m2', created='2026-11-05T10:00:00+02:00', duration=3600, project_id='p1')


def task(key, text, **extra):
    base = dict(id=key, kind='task', text=text, owner='Иван', status='open', workflow_state='todo', acceptance_state='accepted',
                created='2026-11-01T09:00:00+02:00', revision=3, links=[dict(meeting_id='m1')], history=[], effective_project_ids=['p1'])
    base.update(extra)
    return base


def notes(*tasks, updates=()):
    return dict(tasks=[dict(task=t, owner='Иван', due_date=None, quote=None, evidence_timestamp='00:00:01') for t in tasks],
                updates=[dict(text=u, quote=None, evidence_timestamp='00:00:02') for u in updates])


class SelectTests(unittest.TestCase):
    def test_only_accepted_visible_tasks_that_existed_at_the_meeting(self):
        tasks = [task('a', 'Подготви офертата за клиента'),
                 task('proposed', 'Подготви офертата за клиента', acceptance_state='proposed'),
                 task('hidden', 'Подготви офертата за клиента', dismissed=True),
                 task('later', 'Подготви офертата за клиента', created='2026-11-07T09:00:00+02:00'),
                 task('own', 'Подготви офертата за клиента', links=[dict(meeting_id='m2')]),
                 task('old', 'Подготви офертата за клиента', status='done',
                      history=[dict(at='2026-10-01T09:00:00+02:00', changes=dict(status=['open', 'done']))]),
                 task('recent', 'Подготви офертата за клиента', status='done',
                      history=[dict(at='2026-11-03T09:00:00+02:00', changes=dict(status=['open', 'done']))])]
        data = tm.select(tasks, notes('Подготви офертата за клиента до петък'), MEETING)
        self.assertEqual(sorted(c['id'] for c in data['existing_tasks']), ['a', 'recent'])

    def test_no_candidate_means_no_request(self):
        self.assertIsNone(tm.select([task('a', 'Смени батериите на UPS')], notes('Подготви офертата за клиента'), MEETING))
        self.assertIsNone(tm.select([], notes(), MEETING))

    def test_limits_per_mention_per_meeting_and_tokens(self):
        many = [task(f'k{i}', f'Подготви офертата за клиента вариант {i}') for i in range(40)]
        data = tm.select(many, notes('Подготви офертата за клиента', 'Подготви офертата за клиента нов', 'Подготви офертата за клиента още',
                                     'Подготви офертата за клиента пак', 'Подготви офертата за клиента финал'), MEETING)
        self.assertTrue(all(len(m['candidate_ids']) <= tm.PER_MENTION for m in data['mentions']))
        self.assertLessEqual(len(data['existing_tasks']), tm.PER_MEETING)
        self.assertLessEqual(tm.tokens(data), tm.TOKEN_BUDGET)
        # Every candidate of a mention was sent.
        sent = {c['id'] for c in data['existing_tasks']}
        self.assertTrue(all(set(m['candidate_ids']) <= sent for m in data['mentions']))

    def test_a_long_candidate_is_cut_and_later_records_are_not_known(self):
        item = task('a', 'Подготви офертата за клиента', completion_criteria='дума ' * 200,
                    history=[dict(at='2026-11-02T09:00:00+02:00', event='progress_update', text='Чакаме цени'),
                             dict(at='2026-11-08T09:00:00+02:00', event='progress_update', text='Изпратена')])
        [candidate] = tm.select([item], notes('Подготви офертата за клиента'), MEETING)['existing_tasks']
        self.assertLessEqual(len(candidate['expected_result']), tm.DETAIL_LIMIT + 1)
        self.assertEqual([u['text'] for u in candidate['updates']], ['Чакаме цени'])
        self.assertEqual(candidate['state_note'], 'current; it changed after the meeting')
        self.assertEqual(candidate['revision'], 3)

    def test_updates_are_mentions_too(self):
        data = tm.select([task('a', 'Миграция на базата данни')], notes(updates=['Миграцията на базата данни е наполовина']), MEETING)
        self.assertEqual([m['id'] for m in data['mentions']], ['u0'])


class ValidateTests(unittest.TestCase):
    DATA = dict(mentions=[dict(id='t0', candidate_ids=['a', 'b']), dict(id='u0', candidate_ids=['a'])], existing_tasks=[])

    def row(self, **extra):
        base = dict(mention_id='t0', type='existing_mention', task_id='a', reason='Same offer', update_text=None, changes=[])
        base.update(extra)
        return base

    def test_answers_must_refer_to_what_was_sent(self):
        result = tm.validate(dict(matches=[
            self.row(),
            self.row(mention_id='u0', type='existing_update', task_id='x', update_text='Наполовина'),  # not a candidate
            self.row(mention_id='zz'),                                                                    # unknown mention
        ]), self.DATA)
        self.assertEqual([m['mention_id'] for m in result['matches']], ['t0'])
        self.assertEqual([r['reason'] for r in result['rejected']], ['a task that was not a candidate of this mention', 'unknown or repeated mention'])

    def test_types_need_their_parts(self):
        result = tm.validate(dict(matches=[
            self.row(type='existing_update', update_text='  '),
            self.row(mention_id='u0', type='proposed_change', changes=[dict(field='due_date', value='2026-13-40')]),
        ]), self.DATA)
        self.assertEqual(result['matches'], [])
        good = tm.validate(dict(matches=[
            self.row(type='proposed_change', changes=[dict(field='due_date', value='2026-11-20'), dict(field='workflow_state', value='waiting')]),
            self.row(mention_id='u0', type='new_task', task_id=None)]), self.DATA)
        self.assertEqual([m['type'] for m in good['matches']], ['proposed_change', 'new_task'])
        self.assertEqual(good['matches'][0]['changes'][0], dict(field='due_date', value='2026-11-20'))
        with self.assertRaisesRegex(ValueError, 'expected shape'):
            tm.validate(dict(answer='?'), self.DATA)

    def test_a_new_task_has_no_task_id(self):
        result = tm.validate(dict(matches=[self.row(type='new_task', task_id='a')]), self.DATA)
        self.assertEqual(result['rejected'][0]['reason'], 'a new or uncertain match has no task')


if __name__ == '__main__':
    unittest.main()
