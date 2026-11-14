"""Question → task keeps its canonical question, project, source and guarded note identity."""
import copy
import unittest

from app.storage import atomic_json
from app.work_items import WorkItemConflict
from tests import test_manual_tasks


class QuestionTaskSourcesTests(unittest.TestCase):
    setUp = test_manual_tasks.ManualTaskTests.setUp
    create = test_manual_tasks.ManualTaskTests.create

    def seed(self, tasks=(), questions=None):
        minutes = dict(summary=[], tasks=list(tasks), decisions=[], open_questions=questions if questions is not None else [
            dict(text='Кой проверява възстановяването?', evidence_timestamp='00:00:12')])
        atomic_json(self.service.library.directory(self.meeting) / 'minutes.json', minutes)
        self.service._sync_items(self.meeting)
        return self.service.detail(self.meeting)

    def question_task(self, **extra):
        detail = self.service.detail(self.meeting)
        entry = detail['minutes']['open_questions'][0]
        source = dict(field='open_questions', index=0, text=entry['text'], evidence_timestamp=entry['evidence_timestamp'])
        return self.create(meeting_id=self.meeting, question_source=source, minutes_revision=detail['minutes_revision'], **extra)

    def track(self, **extra):
        return self.service.work_graph_action('question', dict(text='Кой проверява възстановяването?',
            source=dict(meeting_id=self.meeting, evidence_timestamp='00:00:12'), **extra))

    def test_question_task_backlinks_survive_reload_and_notes_edits(self):
        self.seed()
        task = self.question_task()
        detail = self.service.detail(self.meeting)
        question_id = detail['minutes']['open_questions'][0]['item_id']
        self.assertEqual(detail['question_items'], {'open_questions:0': question_id})
        self.assertEqual(detail['question_tasks'][question_id], [task['id']])
        self.assertEqual(task['links'][0]['evidence_timestamp'], '00:00:12')
        self.assertEqual(self.service.item_list()['meeting_questions'], [])
        # A retry is safe even though linking the question changed the notes revision.
        retry = dict(task['creation_payload'], request_id='a'*32)
        retry.pop('project_id')  # The original request omitted explicit project assignment.
        self.assertEqual(self.service.create_task(retry)['id'], task['id'])
        minutes = copy.deepcopy(detail['minutes'])
        minutes['open_questions'][0]['text'] = 'Уточнен въпрос за backup'
        atomic_json(self.service.library.directory(self.meeting) / 'minutes.json', minutes)
        self.service._sync_items(self.meeting)
        detail = self.service.detail(self.meeting)
        self.assertEqual(detail['question_tasks'][question_id], [task['id']])
        self.assertEqual(self.service.item_list()['meeting_questions'], [])
        from app.items import Registry
        reloaded = Registry(self.service.items.path)
        self.assertIn(question_id, reloaded.items)
        self.assertTrue(any(e['from_id'] == task['id'] and e['to_id'] == question_id for e in reloaded.data['relationships'].values()))

    def test_question_source_moment_survives_generated_notes_replacement(self):
        self.seed()
        task = self.question_task()
        self.seed(questions=[])
        self.assertEqual(self.service.items.items[task['id']]['links'][0]['evidence_timestamp'], '00:00:12')
        self.assertEqual(self.service.detail(self.meeting)['minutes']['tasks'][0]['evidence_timestamp'], '00:00:12')

    def test_tracking_inherits_project_and_task_inherits_meeting(self):
        self.seed()
        question = self.track()
        self.assertEqual(self.service.effective_project_ids(question), [self.project])
        self.assertEqual(self.track()['id'], question['id'])
        task = self.create(question_id=question['id'])
        self.assertEqual(task['links'][0]['meeting_id'], self.meeting)
        self.assertEqual(task['links'][0]['evidence_timestamp'], '00:00:12')
        self.assertEqual(self.service.effective_project_ids(task), [self.project])
        self.assertIn(task['id'], self.service.detail(self.meeting)['items'])

    def test_answered_question_stays_out_of_prepare_until_reopened(self):
        self.seed()
        q = self.track(answer='Иван, проверено е')
        self.assertEqual(self.service.prepare(project_id=self.project)['questions'], [])
        self.service.work_graph_action('question', dict(id=q['id'], revision=q['revision'], answer=None))
        self.assertEqual(len(self.service.prepare(project_id=self.project)['questions']), 1)

    def test_no_project_is_explicit_and_omission_still_inherits(self):
        unassigned = self.create(meeting_id=self.meeting, project_id=None)
        self.assertEqual(unassigned['project_ids'], [])
        self.assertEqual(self.service.effective_project_ids(unassigned), [])
        inherited = self.create(meeting_id=self.meeting, request_id='b'*32)
        self.assertEqual(self.service.effective_project_ids(inherited), [self.project])
        with self.assertRaises(WorkItemConflict):
            self.create(meeting_id=self.meeting, project_id=None, request_id='b'*32)

    def test_stale_task_line_cannot_attach_to_another_row(self):
        a = dict(task='Провери backup', evidence_timestamp='00:00:10', owner=None, deadline=None, due_date=None)
        b = dict(a, task='Поръчай лицензи', evidence_timestamp='00:00:40')
        detail = self.seed(tasks=[a, b], questions=[])
        self.seed(tasks=[b], questions=[])
        with self.assertRaises(WorkItemConflict):
            self.create(meeting_id=self.meeting, mention_index=0, minutes_revision=detail['minutes_revision'])
        self.assertEqual(self.service.tasks(), [])
        self.assertNotIn('item_id', self.service.detail(self.meeting)['minutes']['tasks'][0])

    def test_stale_question_creates_neither_question_nor_task(self):
        detail = self.seed()
        entry = detail['minutes']['open_questions'][0]
        self.seed(questions=[dict(text='Друг въпрос?', evidence_timestamp='00:00:12')])
        with self.assertRaises(WorkItemConflict):
            self.create(meeting_id=self.meeting, question_source=dict(field='open_questions', index=0,
                text=entry['text'], evidence_timestamp=entry['evidence_timestamp']), minutes_revision=detail['minutes_revision'])
        self.assertEqual(self.service.item_list()['items'], [])

    def test_tampered_source_with_current_revision_is_refused(self):
        detail = self.seed()
        with self.assertRaises(WorkItemConflict):
            self.create(meeting_id=self.meeting, question_source=dict(field='open_questions', index=0,
                text='Not this question', evidence_timestamp='00:00:12'), minutes_revision=detail['minutes_revision'])
        self.assertEqual(self.service.item_list()['items'], [])

    def test_track_then_make_from_notes_reuses_question(self):
        self.seed()
        q = self.track()
        self.question_task()
        questions = [i for i in self.service.item_list()['items'] if i['kind'] == 'question']
        self.assertEqual([i['id'] for i in questions], [q['id']])

    def test_legacy_tracked_question_is_resolved_without_saved_note_id(self):
        self.seed()
        from app.work_graph import WorkGraph
        q = WorkGraph(self.service.items).question('Кой проверява възстановяването?',
            source=dict(meeting_id=self.meeting, evidence_timestamp='00:00:12'), answer='Иван')
        self.assertEqual(self.service.detail(self.meeting)['question_items'], {'open_questions:0': q['id']})
        self.assertEqual(self.service.prepare(project_id=self.project)['questions'], [])

    def test_other_meeting_with_identical_text_is_not_marked_answered(self):
        self.seed()
        self.track(answer='Иван')
        second = self.service.library.create('Друг проект', 'in_person', self.service.settings)['id']
        atomic_json(self.service.library.directory(second) / 'minutes.json', self.service.detail(self.meeting)['minutes'] | {
            'open_questions': [dict(text='Кой проверява възстановяването?', evidence_timestamp='00:00:12')], 'tasks': []})
        self.assertEqual(self.service.detail(second)['question_items'], {})

    def test_missing_notes_revision_cannot_bypass_source_guard(self):
        self.seed(tasks=[dict(task='Провери backup', evidence_timestamp='00:00:10', owner=None, deadline=None, due_date=None)])
        with self.assertRaises(ValueError):self.create(meeting_id=self.meeting, mention_index=0)
        self.assertEqual(self.service.tasks(), [])

    def test_task_from_answered_question_is_refused(self):
        self.seed()
        q = self.track(answer='Иван')
        with self.assertRaises(WorkItemConflict):self.create(question_id=q['id'])
        self.assertEqual(self.service.tasks(), [])

    def test_rejected_long_question_leaves_no_in_memory_task(self):
        self.seed(questions=[dict(text='Question '*1500, evidence_timestamp='00:00:12')])
        with self.assertRaises(ValueError):self.question_task(text='Short task title')
        self.assertEqual(self.service.items.items, {})
        self.assertEqual(self.service.item_list()['items'], [])

    def test_shortened_task_keeps_long_original_question(self):
        original = 'Question '*150
        self.seed(questions=[dict(text=original, evidence_timestamp='00:00:12')])
        task = self.question_task(text='Short task title')
        question_id = self.service.detail(self.meeting)['question_items']['open_questions:0']
        self.assertEqual(self.service.items.items[question_id]['text'], original.strip())
        self.assertEqual(task['text'], 'Short task title')
