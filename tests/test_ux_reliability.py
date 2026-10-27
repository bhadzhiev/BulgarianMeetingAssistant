from pathlib import Path
import json
import subprocess
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app import task_draft,repo_reports
from app.desktop import editor_state
from tests import test_task_draft,test_repo_reports,test_prepare

PROJECT=Path(__file__).resolve().parents[1]

class FrontendTests(unittest.TestCase):
 def test_actual_reader_functions_and_shared_helpers(self):
  subprocess.run(['node','tests/web_ux_regressions.cjs'],cwd=PROJECT,check=True,capture_output=True)
 def test_editor_private_pipe_does_not_include_content(self):
  import io
  output=io.StringIO();editor_state(True,output)
  self.assertEqual(json.loads(output.getvalue()),dict(event='ui',dirty=True))

class TaskDraftReliabilityTests(test_task_draft.DraftTests):
 def test_operation_retry_with_different_text_does_not_create_twice(self):
  project=self.s.create_project('Synthetic project')['id']
  body=dict(self.approved(),title='Original confirmed text',operation_id='a'*32,project_ids=[project])
  first=task_draft.create(self.s,body);second=task_draft.create(self.s,dict(body,title='Changed after a lost response'))
  self.assertEqual(first,second);self.assertEqual(len(self.s.tasks()),1)
  self.assertEqual(self.s.tasks()[0]['text'],'Original confirmed text');self.assertEqual(self.s.tasks()[0]['project_ids'],[project])
  prepared=self.s.prepare(project);self.assertIn(first['item_id'],[task['item_id'] for task in prepared['tasks']])
 def test_cancelled_job_does_not_publish_a_late_result(self):
  entered=threading.Event()
  def work(*args,**kwargs):
   entered.set()
   while not kwargs['cancel'].is_set():time.sleep(.01)
   from app.jobs import JobCancelled
   raise JobCancelled()
  jobs=task_draft.DraftJobs(self.s,SimpleNamespace(run=work));self.addCleanup(jobs.close)
  job=jobs.start(self.approved());self.assertTrue(entered.wait(3));jobs.stop(job['id']);jobs.thread.join(3)
  result=jobs.status(job['id']);self.assertFalse(result['running']);self.assertNotIn('text',result);self.assertEqual(self.s.tasks(),[])

class ReportBatchTests(test_repo_reports.ReportTests):
 def test_batches_reduce_steps_and_keep_cross_source_quotes_after_restart(self):
  self.collect();self.analyze();row=self.r.detail(self.key)
  self.assertIn('summary',row['analysis']);self.assertLess(row['analysis']['metrics']['worker_steps'],len(row['evidence'])+1)
  self.assertEqual(repo_reports.read_store(self.r.path)['reports'][self.key]['analysis']['summary'],row['analysis']['summary'])
  for f in row['analysis']['summary']:
   for ref in f['evidence']:
    ev=next(e for e in row['evidence'] if e['id']==ref['id']);self.assertIn(ref['quote'],ev['text'])
 def test_batch_boundaries_and_synthesis_are_bounded(self):
  evidence=[dict(id=str(i),change_id='pr:'+str(i//3),text='x'*3000) for i in range(12)]
  batches=repo_reports.analysis_batches(evidence);self.assertEqual(len(batches),4)
  self.assertEqual([e for b in batches for e in b],evidence)
  self.assertTrue(all(len(json.dumps(b))<16000 for b in batches))

class PrepareRevisionTests(test_prepare.PrepareTests):
 def test_prepare_includes_the_current_item_revision(self):
  _,_,project,_=self.scenario();result=self.service.prepare(project)
  for task in result['tasks']:
   self.assertIsInstance(task['revision'],int)


class MetadataCacheTests(unittest.TestCase):
 def test_cache_does_not_share_mutable_values_and_observes_external_replacement(self):
  import tempfile
  from app.storage import Library,atomic_json
  with tempfile.TemporaryDirectory() as tmp:
   library=Library(Path(tmp));meeting=library.create('Original','in_person',{})
   first=library.get(meeting['id']);first['title']='Not saved'
   self.assertEqual(library.get(meeting['id'])['title'],'Original')
   path=library.directory(meeting['id'])/'meeting.json';updated=dict(meeting,title='Externally replaced')
   atomic_json(path,updated)
   self.assertEqual(library.get(meeting['id'])['title'],'Externally replaced')
   library.delete(meeting['id']);self.assertNotIn(meeting['id'],library.metadata_cache)
