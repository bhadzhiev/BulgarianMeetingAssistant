import unittest
from tests import test_manual_tasks
from app.work_graph import WorkGraph
from app.storage import atomic_json

class UIAuditFixTests(unittest.TestCase):
    setUp=test_manual_tasks.ManualTaskTests.setUp
    create=test_manual_tasks.ManualTaskTests.create

    def test_cancelled_work_is_not_a_matching_candidate(self):
        task=self.create(text='Провери резервното копие')
        self.service.update_item(task['id'],task['text'],dict(workflow_state='cancelled'),task['revision'])
        self.assertEqual(self.service.items.candidates('task',dict(task=task['text'],owner='Иван')),[])

    def test_unrelated_answer_does_not_hide_a_meeting_question(self):
        question='Кой потвърждава прозореца за миграцията?'
        atomic_json(self.service.library.directory(self.meeting)/'minutes.json',dict(summary=[],tasks=[],decisions=[],open_questions=[dict(text=question,evidence_timestamp='00:00:00')]))
        WorkGraph(self.service.items).question('Кой потвърди доставката?',answer='Мария получи пратката')
        self.assertEqual([q['text'] for q in self.service.item_list()['meeting_questions']],[question])

    def test_library_readiness_distinguishes_transcript_from_notes(self):
        directory=self.service.library.directory(self.meeting)
        atomic_json(directory/'transcript.json',[dict(start=0,end=1,text='Test',speaker=None)])
        rows=self.service.conversations.listing({})['rows']
        readiness=next(r for r in rows if r['external_id']==self.meeting)['readiness']
        self.assertEqual(readiness,dict(recording=False,transcript=True,notes=False))
        atomic_json(directory/'minutes.json',dict(summary=[],tasks=[],decisions=[],open_questions=[]))
        readiness=self.service.conversations.listing({})['rows'][0]['readiness']
        self.assertTrue(readiness['notes'])
