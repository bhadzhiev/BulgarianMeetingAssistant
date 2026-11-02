import unittest
from types import SimpleNamespace
from app.followup import build

class FollowupTests(unittest.TestCase):
    def setUp(self):
        self.meeting=dict(id='m',title='Review',created='2026-01-10T12:00:00',meeting_type='daily')
        self.item=dict(id='t',kind='task',status='open',text='Runbook',created='2026-01-01',owner='Maria',history=[],links=[dict(meeting_id='m',evidence_timestamp='00:00:03')],effective_project_ids=['p'])
        self.links=[dict(repository='org/repo',number=123,state='closed',verification='cached',cached_at=1,url='https://github.com/org/repo/issues/123')]
        self.service=SimpleNamespace(github_links=SimpleNamespace(for_resource=lambda *a:self.links),people=SimpleNamespace(match=lambda name:dict(id='person')),detail=lambda key:dict(transcript=[dict(start=0,end=10,text='Maria will update the runbook')]))
        self.brief=dict(meeting_type='daily',project_id='p',series_id=None,tasks=[dict(item_id='t',source=None)],decisions=[],proposed=[],done=[],done_unknown=[])
    def test_closed_cached_issue_does_not_complete_local_work(self):
        result=build(self.service,self.brief,[self.item],[self.meeting],{})
        row=result['commitments'][0]
        self.assertEqual(row['status'],'open');self.assertTrue(row['external'][0]['completion_suggested'])
        self.assertIn('unknown',row['external'][0]['verification_label'])
        self.assertEqual(row['quote'],'Maria will update the runbook')
        self.assertEqual(row['person_id'],'person');self.assertEqual(len(result['unchanged']),1)
    def test_inactivity_does_not_invent_blocker(self):
        result=build(self.service,self.brief,[self.item],[self.meeting],{})
        self.assertEqual(result['blocked'],[])
    def test_ai_blocker_and_confirmed_blocker_are_separate(self):
        notes={'m':{'blockers':[dict(text='Waiting on access',review='ai'),dict(text='Confirmed dependency',review='verified')]}}
        result=build(self.service,self.brief,[self.item],[self.meeting],notes)
        self.assertEqual([r['text'] for r in result['blocked']],['Confirmed dependency'])
        self.assertEqual([r['text'] for r in result['blockers_to_review']],['Waiting on access'])
    def test_other_series_is_not_included_through_project(self):
        self.item['links'][0]['meeting_id']='other';self.brief['series_id']='series'
        result=build(self.service,self.brief,[self.item],[self.meeting],{})
        self.assertEqual(result['commitments'],[])
    def test_first_meeting_does_not_invent_unchanged_period(self):
        self.brief['meeting_type']='sprint_review'
        result=build(self.service,self.brief,[self.item],[self.meeting],{})
        self.assertIsNone(result['anchor']);self.assertEqual(result['unchanged'],[])
