import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from threading import RLock
from app.items import Registry
from app.meeting_review import snapshot, act
from app.work_items import WorkItemConflict

class MeetingReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        registry=Registry(Path(self.tmp.name)/'items.json')
        self.mid='a'*32
        self.key=registry.create('task',dict(task='Check rollout',status='open'),self.mid);registry.save()
        self.source='first'
        self.service=SimpleNamespace(items=registry,lock=RLock())
        self.service.detail=lambda key:dict(transcript_revision=self.source,minutes_revision='notes',items=registry.items,minutes={'summary':'Summary'})
    def body(self,action='confirm'):
        view=snapshot(self.service,self.mid);row=view['items'][0]
        return dict(meeting_id=self.mid,item_id=self.key,action=action,source=view['source'],content=row['content'])
    def test_confirm_is_local_and_retry_is_idempotent(self):
        body=self.body();before=len(self.service.items.items[self.key]['history'])
        self.assertEqual(act(self.service,body)['items'][0]['state'],'confirmed')
        act(self.service,body)
        self.assertEqual(len(self.service.items.items[self.key]['history']),before+1)
        self.assertEqual(len(self.service.items.items),1)
        self.assertEqual(self.service.items.items[self.key]['status'],'open')
    def test_changed_source_invalidates_confirmation_and_old_request(self):
        body=self.body();act(self.service,body);self.source='changed'
        self.assertEqual(snapshot(self.service,self.mid)['items'][0]['state'],'needs_review')
        with self.assertRaises(WorkItemConflict):act(self.service,body)
    def test_confirmed_commitment_cannot_be_dismissed(self):
        act(self.service,self.body())
        with self.assertRaises(ValueError):act(self.service,self.body('dismiss'))
    def test_edited_text_requires_review_without_changing_id(self):
        act(self.service,self.body());self.service.items.items[self.key]['text']='Edited task';self.service.items.save()
        row=snapshot(self.service,self.mid)['items'][0]
        self.assertEqual(row['state'],'needs_review');self.assertEqual(row['id'],self.key)

    def test_inline_edit_keeps_id_and_requires_explicit_confirmation(self):
        def update(key, text, changes, revision):
            registry=self.service.items
            self.assertEqual(registry.items[key]['text'],text)
            registry.update(key,changes);registry.save()
        self.service.update_item=update
        body=self.body('edit');body['changes']={'text':'Review rollout evidence','owner':'Maria'}
        result=act(self.service,body)
        self.assertEqual(result['items'][0]['state'],'edited')
        self.assertEqual(result['items'][0]['id'],self.key)
        self.assertEqual(result['items'][0]['owner'],'Maria')
        self.assertEqual(act(self.service,self.body())['items'][0]['state'],'confirmed')

    def test_candidate_without_actual_meeting_link_is_not_reviewable(self):
        self.service.items.items[self.key]['links'][0]['meeting_id']='b'*32
        self.service.items.save()
        self.assertEqual(snapshot(self.service,self.mid)['items'],[])
