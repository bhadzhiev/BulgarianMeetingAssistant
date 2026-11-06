import datetime as dt
import tempfile
import unittest
from pathlib import Path
from app import task_draft
from app.service import MeetingService
from app.storage import atomic_json
from tests.test_calendar import FakeGoogle

PROJECT=Path(__file__).resolve().parents[1]
# A recording from an earlier day: its file date is the meeting date.
RECORDED='2026-10-01T09:30:00+03:00'


class TaskDateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.s=MeetingService(Path(self.tmp.name)/'library',PROJECT,google=FakeGoogle(),backup_dir=Path(self.tmp.name)/'backups');self.addCleanup(self.s.close)
        self.s.settings.update(summarizer='local',local_ai_model='synthetic')
        self.mid=self.s.library.create('Daily','audio',self.s.settings)['id']
        self.s.library.update(self.mid,status='ready',created=RECORDED,started_at=RECORDED)
        atomic_json(self.s.library.directory(self.mid)/'transcript.json',[dict(start=0,end=8,speaker='Maria',text='Please test backup recovery.')])

    def same_moment(self,value,expected=RECORDED):
        self.assertEqual(dt.datetime.fromisoformat(value),dt.datetime.fromisoformat(expected))

    def test_task_from_notes_uses_the_recording_date(self):
        self.s.edit(self.mid,dict(minutes=dict(summary=[],tasks=[dict(task='Check alert routing',owner=None,deadline=None,evidence_timestamp='00:00:00')],decisions=[],open_questions=[])))
        task=next(i for i in self.s.items.items.values() if i['text']=='Check alert routing')
        self.same_moment(task['created'])
        created=next(e for e in task['history'] if e['event']=='created')
        self.same_moment(created['at']);self.assertIn('recorded_at',created)

    def test_manual_task_for_a_meeting_uses_the_meeting_date(self):
        task=self.s.create_task(dict(request_id='a'*32,text='Write the runbook',meeting_id=self.mid))
        self.same_moment(task['created']);self.same_moment(task['history'][-1]['at'])

    def test_task_from_transcript_selection_uses_the_meeting_date(self):
        body=dict(provider='meeting',id=self.mid,revision=self.s.detail(self.mid)['transcript_revision'],first=0,last=0)
        body['preview_token']=task_draft.preview(self.s,body)['preview_token']
        key=task_draft.create(self.s,dict(body,title='Verify recovery',operation_id='b'*32))['item_id']
        self.same_moment(self.s.items.items[key]['created'])

    def test_live_recording_uses_its_start_time(self):
        started=dt.datetime.now().astimezone().replace(microsecond=0)-dt.timedelta(hours=2)
        live=self.s.library.create('Live','in_person',self.s.settings)['id']
        self.s.library.update(live,status='ready',started_at=started.isoformat())
        task=self.s.create_task(dict(request_id='c'*32,text='Send the summary',meeting_id=live))
        self.same_moment(task['created'],started.isoformat())

    def test_task_without_a_meeting_uses_the_current_time(self):
        before=dt.datetime.now().astimezone().replace(microsecond=0)
        task=self.s.create_task(dict(request_id='d'*32,text='Plan the week'))
        self.assertGreaterEqual(dt.datetime.fromisoformat(task['created']),before)
        self.assertNotIn('recorded_at',task['history'][-1])


if __name__=='__main__':
    unittest.main()
