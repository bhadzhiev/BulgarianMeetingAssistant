import base64
import copy
import datetime as dt
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from app import repo_reports as reports
from app.github_source import GitHubConnection,GitHubError
from app.local_ai import OutputTruncatedError
from app.service import MeetingService
from app.storage import atomic_json
from app.work_items import WorkItemConflict
from tests.test_calendar import FakeGoogle

PROJECT=Path(__file__).resolve().parents[1]
REPO='synthetic/repository'
A,B,C,D,E=[x*40 for x in 'abcde']
DATE='2026-10-21T10:00:00Z'
PATCH='@@ -1,2 +1,2 @@\n-def backup(): return False\n+def backup(): return True'
FILE=dict(filename='app/backup.py',status='modified',sha=D,patch=PATCH)


def finding(ev):return dict(kind='follow_up',text='Провери поведението на backup функцията.',certainty='inference',evidence=[dict(id=ev['id'],quote=ev['text'][-min(60,len(ev['text'])):])])


class FakeConnection:
    def __init__(self):self.account='1';self.calls=[];self.fail=False
    def status(self):return dict(connected=bool(self.account),account_id=self.account,login='synthetic-user')
    def get(self,path,query=None,expected_account=None):
        if expected_account!=self.account:raise GitHubError('Account changed')
        self.calls.append((path,copy.deepcopy(query)))
        prefix='/repos/'+REPO
        if path==prefix:data=dict(id=11,full_name=REPO,default_branch='main')
        elif path==prefix+'/commits':
            if query.get('per_page')==1:data=[dict(sha=B)]
            else:data=[dict(sha=sha,commit=dict(committer=dict(date=DATE))) for sha in [A,B]]
        elif path=='/search/issues':data=dict(items=[dict(number=7,repository_url='https://api.github.com'+prefix)],incomplete_results=False)
        elif path==prefix+'/pulls/7':data=dict(number=7,title='Correct backup',body='Changes the backup result.',merged_at=DATE,base=dict(ref='main',repo=dict(id=11)),head=dict(sha=C),merge_commit_sha=A,changed_files=1)
        elif path==prefix+'/compare/'+A+'...'+B:data=dict(status='ahead')
        elif path==prefix+'/pulls/7/files':data=[FILE]
        elif path.startswith(prefix+'/git/blobs/'):
            if self.fail:raise GitHubError('synthetic interruption')
            text='def backup():\n    return True\n'
            data=dict(sha=path.rsplit('/',1)[1],encoding='base64',size=len(text.encode()),content=base64.b64encode(text.encode()).decode())
        elif path==prefix+'/commits/'+A+'/pulls':data=[dict(merged_at=DATE,base=dict(ref='main'))]
        elif path==prefix+'/commits/'+B+'/pulls':data=[]
        elif path==prefix+'/commits/'+B:data=dict(sha=B,commit=dict(message='Update backup documentation',committer=dict(date=DATE)),files=[dict(FILE,filename='README.md',sha=E)])
        else:raise AssertionError(path)
        return dict(data=copy.deepcopy(data),has_next=False)


class FakeRunner:
    def __init__(self):self.calls=[];self.callback=None
    def run(self,action,directory,settings,progress,key='',**kwargs):
        assert action=='repo_report';self.calls.append(copy.deepcopy(settings))
        if self.callback:self.callback(kwargs['cancel'])
        return [dict(finding(settings['repo_evidence'][0]),id='ignored-worker-id')]


class PeriodTests(unittest.TestCase):
    def test_sofia_dst_and_today_boundaries_are_explicit(self):
        now=dt.datetime(2026,10,27,12,30,tzinfo=reports.TZ)
        p=reports.period('2026-10-25','2026-10-25',now)
        self.assertEqual((reports.stamp(p['until'])-reports.stamp(p['since'])).total_seconds(),25*3600)
        self.assertEqual(reports.period('2026-10-26','2026-10-27',now)['until'],'2026-10-27T10:30:00Z')
        self.assertEqual(reports.defaults(now)['start'],'2026-10-26')
        for first,last in [('2026-10-28','2026-10-28'),('2026-10-27','2026-10-26'),('2026-01-01','2026-10-27')]:
            with self.assertRaises(ValueError):reports.period(first,last,now)

    def test_patch_parts_keep_hunk_line_anchors(self):
        patch='@@ -20,1 +30,1 @@\n-old\n+new\n'+' x\n'*2200+'@@ -4000,1 +5000,1 @@\n-a\n+b\n'
        parts=reports.patch_parts(patch)
        self.assertEqual(''.join(p[0] for p in parts),patch)
        self.assertTrue(all(len(p[0])<=reports.PART_SIZE for p in parts))
        self.assertEqual(parts[0][1],30)
        self.assertTrue(all(type(p[1]) is int and p[1]>0 for p in parts))

    def test_unknown_sources_and_fabricated_quotes_are_rejected(self):
        ev=dict(id='known',text='Actual source code')
        for ref in [dict(id='missing',quote='Actual'),dict(id='known',quote='fabricated')]:
            with self.assertRaises(ValueError):reports.validate_findings(dict(findings=[dict(finding(ev),evidence=[ref])]),[ev])

    def test_truncated_output_splits_bounded_input_and_keeps_quotes(self):
        ev=dict(id='e',text='before code\n'*300+'after code\n'*300)
        def complete(settings,messages,*args,**kwargs):
            payload=json.loads(messages[1]['content'])['untrusted_repository_evidence']
            if len(payload[0]['text'])>4000:raise OutputTruncatedError('synthetic truncation')
            return dict(findings=[finding(payload[0])])
        with patch('app.repo_reports.complete_json',side_effect=complete) as call:
            result=reports.analyze([ev],{})
        self.assertGreater(call.call_count,1);self.assertTrue(result)
        for f in result:self.assertIn(f['evidence'][0]['quote'],ev['text'])


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.s=MeetingService(self.root/'library',PROJECT,google=FakeGoogle(),backup_dir=self.root/'archives');self.addCleanup(self.s.close)
        self.s.settings.update(summarizer='local',local_ai_model='qwen3.5-9b',local_ai_reasoning='default')
        self.connection=FakeConnection();self.s.github.connection=self.connection
        self.runner=FakeRunner();self.r=self.s.repo_reports;self.r.runner=self.runner

    def finish(self):
        if self.r.thread:self.r.thread.join(5)
        self.assertFalse(self.r.job['running']);return self.r.detail(self.key)

    def collect(self):
        self.key=self.r.collect(REPO,'','2026-10-21','2026-10-21')['report_id'];return self.finish()

    def analyze(self):
        preview=self.r.preview(self.key);self.r.start_analysis(self.key,preview['preview_token'],True);return self.finish()

    def test_pins_head_and_deduplicates_pr_commits_without_ai_export(self):
        row=self.collect();self.assertTrue(row['collection_complete']);self.assertEqual(row['head'],B)
        changes=[c for c in row['changes'].values() if not c.get('skipped')]
        self.assertEqual({c['kind'] for c in changes},{'pull_request','commit'})
        self.assertEqual(len(changes),2);self.assertEqual(self.runner.calls,[])
        dated=[q for p,q in self.connection.calls if p.endswith('/commits') and q.get('since')]
        self.assertEqual(dated[0]['sha'],B)
        self.assertTrue(any('File context' in e['text'] for e in row['evidence']))

    def test_collection_failure_rolls_back_partial_change_then_resumes(self):
        self.connection.fail=True;row=self.collect();self.assertEqual(row['status'],'error')
        self.assertEqual(row['evidence'],[]);self.assertEqual(row['coverage']['files'],0)
        self.connection.fail=False;self.r.collect(report_id=self.key);row=self.finish()
        self.assertTrue(row['collection_complete']);self.assertEqual(len(row['evidence']),4)
        self.assertEqual(len({e['id'] for e in row['evidence']}),4)

    def test_ai_requires_current_explicit_approval_and_preserves_completed_parts(self):
        self.collect();preview=self.r.preview(self.key)
        self.assertEqual(preview['target']['local_ai_reasoning'],'none')
        with self.assertRaises(ValueError):self.r.start_analysis(self.key,preview['preview_token'],False)
        self.s.settings['local_ai_max_tokens']=8192
        with self.assertRaises(WorkItemConflict):self.r.start_analysis(self.key,preview['preview_token'],True)
        row=self.analyze();self.assertTrue(row['analysis']['complete']);calls=len(self.runner.calls)
        result=self.r.start_analysis(self.key,self.r.preview(self.key)['preview_token'],True)
        self.assertEqual(result['status'],'reused');self.assertEqual(len(self.runner.calls),calls)
        self.assertEqual(self.s.tasks(),[])
        first=next(iter(row['analysis']['parts'].values()))[0]
        result=self.r.propose(self.key,first['id']);self.assertTrue(result['proposals'])
        self.assertEqual(self.s.tasks(),[])
        proposal=self.s.item_list()['graph']['proposals'][0]
        self.assertEqual(proposal['state'],'pending');self.assertEqual(proposal['origin'],'repo_ai')

    def test_recording_cancels_export_before_publication(self):
        self.collect()
        def interrupt(flag):self.s.active='synthetic';self.assertTrue(flag.is_set())
        self.runner.callback=interrupt
        row=self.analyze();self.s.active=None
        self.assertEqual(row['status'],'interrupted');self.assertEqual(row['analysis']['parts'],{})
        self.assertEqual(self.s.tasks(),[])

    def test_accounts_and_restart_revoke_old_preview_without_erasing_reports(self):
        self.collect();preview=self.r.preview(self.key)
        self.connection.account='other'
        self.assertEqual(self.r.listing()['reports'],[])
        with self.assertRaises(ValueError):self.r.detail(self.key)
        self.connection.account='1';reopened=reports.RepoReports(self.s,runner=self.runner)
        with self.assertRaises(WorkItemConflict):reopened.start_analysis(self.key,preview['preview_token'],True)
        self.assertEqual(reopened.detail(self.key)['head'],B)

    def test_backup_and_restore_keep_reports_without_replacing_existing(self):
        self.collect();name=self.s.create_backup()['created']['name']
        self.r.delete(self.key);self.assertEqual(self.r.listing()['reports'],[])
        self.s.restore_backup(name);self.assertEqual(self.r.detail(self.key)['head'],B)
        self.assertEqual(self.s.tasks(),[])

    def test_clear_reports_works_after_disconnect_but_requires_confirmation(self):
        self.collect();self.connection.account=''
        with self.assertRaises(ValueError):self.r.clear_all(False)
        self.r.clear_all(True);self.assertEqual(reports.read_store(self.r.path)['reports'],{})

    def test_cloud_target_is_fixed_and_key_is_not_persisted(self):
        self.collect();self.s.settings.update(summarizer='openai',local_ai_base_url='https://unrelated.invalid/v1');self.s.api_key='synthetic-private-key'
        preview=self.r.preview(self.key)
        self.assertEqual(preview['target']['local_ai_base_url'],'https://api.openai.com/v1')
        self.r.start_analysis(self.key,preview['preview_token'],True);self.finish()
        self.assertNotIn('synthetic-private-key',self.r.path.read_text())

    def test_branch_search_injection_is_rejected(self):
        with self.assertRaises(ValueError):self.r.collect(REPO,'main repo:other/private','2026-10-21','2026-10-21')

    def test_corrupt_report_store_does_not_disable_meeting_library(self):
        atomic_json(self.r.path,dict(version=0))
        reopened=reports.RepoReports(self.s)
        self.assertTrue(reopened.listing()['error'])
        self.assertIsInstance(self.s.library.list(),list)
        with self.assertRaises(ValueError):reopened.collect(REPO,'main','2026-10-21','2026-10-21')


class EndpointTests(unittest.TestCase):
    def test_commit_reads_are_allowed_but_other_services_and_paths_are_not(self):
        connection=GitHubConnection(Path('/unused'));connection.loaded=True;connection.bundle=dict(id=1,token='synthetic-token')
        connection.request=lambda path,query,token:dict(data={})
        for path in ['/repos/a/b/commits','/repos/a/b/commits/'+A,'/repos/a/b/commits/'+A+'/pulls','/repos/a/b/pulls/7/files','/repos/a/b/git/blobs/'+D,'/repos/a/b/compare/'+A+'...'+B]:
            connection.get(path,expected_account='1')
        for path in ['https://other.test/commits','/repos/a/b/actions/runs','/repos/a/b/commits/../../user','/repos/a/b/git/blobs/not-a-sha']:
            with self.assertRaises(ValueError):connection.get(path,expected_account='1')
