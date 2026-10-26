import json
from pathlib import Path
import shutil
import subprocess
import unittest
from unittest.mock import Mock

from app.work_items import WorkItemConflict
from tests import test_gmail_ai


class EmailActionTests(unittest.TestCase):
    setUp = test_gmail_ai.AIJobTests.setUp
    preview = test_gmail_ai.AIJobTests.preview
    start = test_gmail_ai.AIJobTests.start
    finish = test_gmail_ai.AIJobTests.finish

    def test_automatic_qwen_reasoning_is_previewed_approved_and_sent_exactly(self):
        self.service.settings.update(local_ai_model='qwen3.5-9b', local_ai_reasoning='default')
        preview = self.preview()
        self.assertEqual(preview['reasoning'], 'none')
        self.assertEqual(preview['max_tokens'], self.service.settings['local_ai_max_tokens'])
        self.start(token=preview['preview_token']);result=self.finish()
        self.assertEqual(self.runner.calls[0]['local_ai_reasoning'], 'none')
        self.assertEqual(self.service.settings['local_ai_reasoning'], 'default')
        self.assertEqual((result['thread_id'],result['message_id']),('t1','mt1'))
        self.assertTrue(result['job_id'])

    def test_explicit_reasoning_remains_explicit_and_invalidates_old_consent(self):
        self.service.settings.update(local_ai_model='qwen3.5-9b',local_ai_reasoning='default')
        token=self.preview()['preview_token']
        for effort in ['server','low','medium','high']:
            self.service.settings['local_ai_reasoning']=effort
            self.assertEqual(self.preview()['reasoning'],effort)
            with self.assertRaises(WorkItemConflict):self.start(token=token)
        self.assertEqual(self.runner.calls,[])

    def test_zero_results_are_a_completed_analysis_with_message_identity(self):
        self.runner.result=dict(tasks=[])
        self.start();result=self.finish()
        self.assertEqual(result['status'],'complete')
        self.assertEqual(result['proposal_ids'],[])
        self.assertEqual(result['message_id'],'mt1')

    def test_worker_errors_are_actionable_without_echoing_message_content(self):
        for prefix, code in [('AI quote does not occur in the selected message','invalid_evidence'),
                             ('Local AI request failed.','endpoint_failed'),
                             ('The model output was truncated.','output_limit')]:
            with self.subTest(code=code):
                self.service.gmail_ai.runner=Mock()
                self.service.gmail_ai.runner.run.side_effect=RuntimeError(prefix+' PRIVATE_SYNTHETIC_TEXT')
                self.start();result=self.finish()
                self.assertEqual(result['status'],'error')
                self.assertEqual(result['error_code'],code)
                self.assertNotIn('PRIVATE_SYNTHETIC_TEXT',json.dumps(result))


class SourcePollingTests(unittest.TestCase):
    def test_github_running_job_schedules_poll_in_visible_work_tab(self):
        if not shutil.which('node'):self.skipTest('Node is required for source UI behavior checks')
        source=(Path(__file__).resolve().parents[1]/'web/app.js').read_text()
        function=source[source.index('async function loadGitHub(){'):source.index('function renderGitHubKinds()')]
        setup=r'''
const assert=require('node:assert/strict');
let ghAccount='1',ghItem=0,ghTimer=null,ghWasRunning=false,ghFilter='all',ghItems=[],ghState={},lastTasks='';
const ghAutoSynced=new Set();const view='tasks',workTab='github',scheduled=[];
const nodes=new Map();function $(id){if(!nodes.has(id))nodes.set(id,{value:'',replaceChildren(){}});return nodes.get(id);}
const status={connection:{connected:true,account_id:'1',login:'synthetic'},job:{running:true,status:'syncing'},cached_accounts:[]};
async function api(path){return path==='/api/github'?status:{items:[],state:{last_sync:1}};}
function sourceState(){} function jobText(){return '';} function relTime(){return '';}
function cacheAccounts(){} function segmentedChoice(){} function renderGitHubKinds(){} function renderGitHubList(){} function emptyState(){}
function option(){return {};} function setTimeout(fn,delay){scheduled.push({fn,delay});return 1;} function clearTimeout(){}
'''
        check="\nloadGitHub().then(()=>{assert.equal(scheduled.length,1);assert.equal(scheduled[0].delay,1500);}).catch(e=>{console.error(e);process.exitCode=1;});"
        result=subprocess.run(['node','-e',setup+function+check],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        for payload in ["{items:[{issue_id:1,repository:'synthetic/repository'}],state:{count:1,complete:false}}", "{items:[],state:{}}"]:
            paused=setup.replace("running:true,status:'syncing'", "running:false,status:'paused for recording or processing'")
            paused=paused.replace("{items:[],state:{last_sync:1}}",payload)
            paused=paused.replace("async function api(path){return", "async function api(path){if(path.endsWith('/sync'))throw Error('Unexpected auto sync during processing');return")
            paused=paused.replace('function renderGitHubList(){}','function renderGitHubList(){rendered++;}')
            paused+="\nlet rendered=0;const state={active:null,meetings:[{status:'processing'}]};\n"
            verify="\nloadGitHub().then(()=>{assert.equal(rendered,1);assert.equal(scheduled.length,0);}).catch(e=>{console.error(e);process.exitCode=1;});"
            with self.subTest(payload=payload):
                result=subprocess.run(['node','-e',paused+function+verify],capture_output=True,text=True,timeout=10)
                self.assertEqual(result.returncode,0,result.stderr)


class GitHubOverviewResumeTests(unittest.TestCase):
    def setUp(self):
        from tests import test_github_source
        test_github_source.SyncTests.setUp(self)
        self.rows=[];self.issue_calls=0
        def handler(path,query):
            if path=='/user':return dict(data=dict(id=1,login='synthetic-user'))
            if path=='/issues':self.issue_calls+=1;return dict(data=self.rows,has_next=False)
            raise AssertionError(path)
        self.connection.handler=handler

    def rows_for(self,*numbers):
        from tests.test_github_source import issue,REPO
        return [dict(issue(n,n*100),repository=REPO) for n in numbers]

    def run_overview(self):
        self.sync.start_overview();self.sync.thread.join(5)
        self.assertFalse(self.sync.thread.is_alive())
        return self.sync.overview()

    def test_processing_pause_preserves_old_items_and_resumes_pending_rows(self):
        self.rows=self.rows_for(1,2);self.run_overview()
        self.rows=self.rows_for(3,4)
        def publish(account,record):
            self.changed.append(record['issue_id'])
            if record['number']==3:self.active=True
        self.sync.on_item=publish
        partial=self.run_overview()
        self.assertFalse(partial['state']['complete'])
        self.assertEqual({r['number'] for r in partial['items']},{1,2,3})
        self.assertNotIn('pending',partial['state'])
        self.assertNotIn('pending',self.sync.status()['states']['0:open:all'])
        self.active=False
        self.sync.on_item=lambda account,record:self.changed.append(record['issue_id'])
        completed=self.run_overview()
        self.assertEqual({r['number'] for r in completed['items']},{3,4})
        self.assertTrue(completed['state']['complete'])
        self.assertEqual(completed['state']['count'],2)
        self.assertEqual(self.issue_calls,2)  # Resume does not refetch/restart that page.
        self.assertEqual(self.changed.count(300),1)

    def test_callback_failure_retries_without_skipping_or_double_counting(self):
        self.rows=self.rows_for(1,2)
        def fail_second(account,record):
            if record['number']==2:raise RuntimeError('synthetic publication failure')
        self.sync.on_item=fail_second;self.run_overview()
        self.assertEqual(self.sync.status()['job']['status'],'error')
        self.sync.on_item=lambda *args:None
        result=self.run_overview()
        self.assertEqual(self.issue_calls,1)
        self.assertEqual(result['state']['count'],2)
        self.assertEqual({r['number'] for r in result['items']},{1,2})

    def test_overview_objects_keep_the_real_repository_for_access_loss_handling(self):
        from contextlib import closing
        self.rows=self.rows_for(1);self.run_overview()
        with closing(self.sync.db()) as db:
            self.assertEqual(db.execute('SELECT repo FROM objects').fetchone()[0],11)
