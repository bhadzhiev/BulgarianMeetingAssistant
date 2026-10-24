import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest

from app.service import MeetingService
from app.storage import atomic_json
from meeting_assistant import llm_prompt, minutes_schema, save_minutes, validate_minutes
from tests.test_calendar import FakeGoogle
from tests.test_http import HTTPTests

PROJECT=Path(__file__).resolve().parents[1]
OLD=dict(summary=['Резюме'],decisions=[],open_questions=[],
         tasks=[dict(task='Изпрати оферта',owner='Иван',deadline='петък',evidence_timestamp='00:00:00')])


def new_minutes():
    return dict(summary=['Резюме'],decisions=['Решение'],next_steps=['Следваща среща'],needs_decision=['Бюджет?'],
        open_questions=[],observations=['Срокът изглежда нереалистичен [00:00:00]'],
        tasks=[dict(task='Изпрати оферта',owner='Иван',deadline='петък',due_date='2026-10-30',status='open',evidence_timestamp='00:00:00')])


class MinutesFormatTests(unittest.TestCase):
    def test_old_notes_get_new_fields(self):
        minutes=json.loads(json.dumps(OLD));validate_minutes(minutes)
        self.assertEqual(minutes['next_steps'],[]);self.assertEqual(minutes['observations'],[])
        self.assertEqual((minutes['tasks'][0]['status'],minutes['tasks'][0]['due_date']),('open',None))
    def test_invalid_status_date_or_unknown_field_is_rejected(self):
        for change in [dict(status='later'),dict(due_date='30.10.2026'),dict(due_date='2026-02-30'),dict(extra=1)]:
            minutes=new_minutes();minutes['tasks'][0].update(change)
            with self.assertRaises(ValueError):validate_minutes(minutes)
        with self.assertRaises(ValueError):validate_minutes(dict(new_minutes(),gossip=[]))
    def test_schema_and_prompt_ask_for_new_fields_with_meeting_date(self):
        schema=minutes_schema()
        self.assertIn('observations',schema['required']);self.assertIn('due_date',schema['properties']['tasks']['items']['required'])
        self.assertIn('2026-10-24',llm_prompt('[00:00:00] x',None,'2026-10-24'))
    def test_markdown_has_task_table_but_not_private_observations(self):
        with tempfile.TemporaryDirectory() as tmp:
            save_minutes(Path(tmp),new_minutes());text=(Path(tmp)/'minutes.md').read_text()
        self.assertIn('Следващи стъпки',text);self.assertIn('Въпроси, изискващи решение',text)
        self.assertIn('| Изпрати оферта | Иван | петък | 2026-10-30 | Отворена | 00:00:00 |',text)
        self.assertNotIn('нереалистичен',text)


class TaskTrackerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.service=MeetingService(Path(self.tmp.name),PROJECT,google=FakeGoogle())
    def tearDown(self):self.service.close();self.tmp.cleanup()
    def meeting(self,minutes):
        m=self.service.library.create('Среща','in_person',{});directory=self.service.library.directory(m['id'])
        atomic_json(directory/'transcript.json',[dict(start=0,end=5,text='Иван ще изпрати оферта до петък.',speaker=None)])
        atomic_json(directory/'minutes.json',minutes)
        return m['id']
    def test_tasks_from_all_meetings_and_overdue_summary(self):
        late=new_minutes();late['tasks'][0]['due_date']=(dt.date.today()-dt.timedelta(days=2)).isoformat()
        first=self.meeting(late);second=self.meeting(OLD)
        tasks=self.service.tasks()
        self.assertEqual({t['meeting_id'] for t in tasks},{first,second})
        self.assertEqual(self.service.task_summary()['open'],2);self.assertEqual(self.service.task_summary()['overdue'],1)
        self.assertEqual(self.service.detail(second)['minutes']['tasks'][0]['status'],'open')
    def test_update_task_status_and_due_date(self):
        mid=self.meeting(OLD)
        self.service.update_task(mid,0,'Изпрати оферта',{'status':'done','due_date':'2026-11-02'})
        saved=json.loads((self.service.library.directory(mid)/'minutes.json').read_text())['tasks'][0]
        self.assertEqual((saved['status'],saved['due_date']),('done','2026-11-02'))
        self.assertEqual(self.service.task_summary()['open'],0)
    def test_edit_task_text(self):
        mid=self.meeting(OLD)
        result=self.service.update_task(mid,0,'Изпрати оферта',{'task':'  Изпрати нова оферта '})
        self.assertEqual(result['task'],'Изпрати нова оферта');self.assertEqual(self.service.tasks()[0]['task'],'Изпрати нова оферта')
        self.assertIn('Изпрати нова оферта',(self.service.library.directory(mid)/'minutes.md').read_text())
    def test_delete_task(self):
        minutes=new_minutes();minutes['tasks'].append(dict(minutes['tasks'][0],task='Втора задача'))
        mid=self.meeting(minutes)
        with self.assertRaisesRegex(ValueError,'changed'):self.service.delete_task(mid,0,'Втора задача')
        self.service.delete_task(mid,0,'Изпрати оферта')
        self.assertEqual([t['task'] for t in self.service.tasks()],['Втора задача'])
        self.assertNotIn('Изпрати оферта',(self.service.library.directory(mid)/'minutes.md').read_text())
    def test_update_task_rejects_stale_index_and_other_fields(self):
        mid=self.meeting(OLD)
        with self.assertRaisesRegex(ValueError,'changed'):self.service.update_task(mid,0,'Друга задача',{'status':'done'})
        with self.assertRaisesRegex(ValueError,'changed'):self.service.update_task(mid,5,'Изпрати оферта',{'status':'done'})
        with self.assertRaises(ValueError):self.service.update_task(mid,0,'Изпрати оферта',{'meeting_id':'x'})
        with self.assertRaisesRegex(ValueError,'empty'):self.service.update_task(mid,0,'Изпрати оферта',{'task':'  '})
        with self.assertRaises(ValueError):self.service.update_task(mid,0,'Изпрати оферта',{'due_date':'tomorrow'})
        self.service.busy.add(mid)
        with self.assertRaisesRegex(ValueError,'Wait'):self.service.update_task(mid,0,'Изпрати оферта',{'status':'done'})


class TaskHTTPTests(unittest.TestCase):
    setUp,tearDown,request=HTTPTests.setUp,HTTPTests.tearDown,HTTPTests.request
    def test_task_routes(self):
        m=self.service.library.create('Route','in_person',{});directory=self.service.library.directory(m['id'])
        atomic_json(directory/'transcript.json',[dict(start=0,end=5,text='x',speaker=None)]);atomic_json(directory/'minutes.json',OLD)
        status,body,_=self.request('/api/tasks');self.assertEqual(status,200);self.assertEqual(json.loads(body)[0]['task'],'Изпрати оферта')
        status,body,_=self.request('/api/meetings/'+m['id']+'/task',{'index':0,'task':'Изпрати оферта','changes':{'status':'done'}})
        self.assertEqual(status,200);self.assertEqual(json.loads(body)['status'],'done')
        self.assertIn('task_summary',json.loads(self.request('/api/state')[1]))
        status,body,_=self.request('/api/meetings/'+m['id']+'/delete-task',{'index':0,'task':'Изпрати оферта'})
        self.assertEqual(status,200);self.assertEqual(json.loads(self.request('/api/tasks')[1]),[])


if __name__=='__main__':
    unittest.main()
