import copy
import json
from pathlib import Path
import tempfile
import unittest
from app.service import MeetingService,DEFAULTS
from app.storage import atomic_json
from app.work_items import WorkItemConflict
from tests.test_calendar import FakeGoogle
from tests.test_notes import minutes
from meeting_assistant import save_minutes

PROJECT=Path(__file__).resolve().parents[1]

class TurnSpeakerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.s=MeetingService(Path(self.tmp.name),PROJECT,google=FakeGoogle());self.addCleanup(self.s.close)
        self.s._run_analytics=lambda *a,**k:None
        self.m=self.s.library.create('Synthetic dialogue','in_person',dict(DEFAULTS,auto_title=False));self.mid=self.m['id'];self.directory=self.s.library.directory(self.mid)
        self.s.library.update(self.mid,status='ready',duration=4)
        self.rows=[dict(start=i,end=i+1,text='Words '+str(i),speaker=speaker) for i,speaker in enumerate(['SPEAKER_00','SPEAKER_00','Ivan',None])]
        atomic_json(self.directory/'transcript.json',self.rows);atomic_json(self.directory/'speaker-timeline.json',[dict(start=r['start'],end=r['end'],speaker=r['speaker']) for r in self.rows])
    def body(self,indices,name):return dict(speaker_assignment=dict(indices=indices,name=name,revision=self.s.detail(self.mid)['transcript_revision']))
    def test_generic_label_changes_only_selected_turn_and_timeline(self):
        result=self.s.edit(self.mid,self.body([0],'Maria'))
        self.assertEqual([s['speaker'] for s in result['transcript']],['Maria','SPEAKER_00','Ivan',None])
        self.assertEqual([s['text'] for s in result['transcript']],[s['text'] for s in self.rows])
        timeline=json.loads((self.directory/'speaker-timeline.json').read_text());self.assertEqual(timeline[0]['speaker'],'Maria');self.assertEqual(timeline[1]['speaker'],'SPEAKER_00')
    def test_unidentified_can_be_assigned_and_cleared(self):
        self.assertEqual(self.s.edit(self.mid,self.body([3],'Ivan'))['transcript'][3]['speaker'],'Ivan')
        self.assertIsNone(self.s.edit(self.mid,self.body([3],None))['transcript'][3]['speaker'])
    def test_stale_change_does_not_overwrite_saved_assignment(self):
        stale=self.body([0],'Maria');self.s.edit(self.mid,self.body([0],'Ivan'))
        with self.assertRaises(WorkItemConflict):self.s.edit(self.mid,stale)
        self.assertEqual(self.s.detail(self.mid)['transcript'][0]['speaker'],'Ivan')
    def test_turn_with_multiple_segments_can_be_assigned_together(self):
        result=self.s.edit(self.mid,self.body([0,1],'Maria'))
        self.assertEqual([s['speaker'] for s in result['transcript']],['Maria','Maria','Ivan',None])
    def test_notes_are_preserved_and_marked_for_review(self):
        save_minutes(self.directory,minutes());before=(self.directory/'minutes.json').read_bytes()
        result=self.s.edit(self.mid,self.body([0],'Maria'))
        self.assertTrue(result['notes_need_refresh']);self.assertEqual((self.directory/'minutes.json').read_bytes(),before)
    def test_invalid_indices_and_names_preserve_transcript(self):
        before=(self.directory/'transcript.json').read_bytes()
        for indices,name in [([],None),([True],'Ivan'),([9],'Ivan'),([0,0],'Ivan'),([0],''),([0],'bad\nname')]:
            with self.subTest(indices=indices,name=name),self.assertRaises(ValueError):self.s.edit(self.mid,self.body(indices,name))
            self.assertEqual((self.directory/'transcript.json').read_bytes(),before)
