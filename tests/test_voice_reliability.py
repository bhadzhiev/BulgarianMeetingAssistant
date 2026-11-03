"""Adversarial voice/review regressions; no real audio, model downloads or connector writes."""
import subprocess
from pathlib import Path
import shutil
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app import voices, reprocess
from app.jobs import JobCancelled
from app.review_queue import build
from app.service import MeetingService
from app.storage import atomic_json
from tests import test_voices as fixtures, test_review_queue as queue_fixtures, test_reprocess as rerun_fixtures
from tests.test_app import wait_for


class VoiceLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ServiceVoiceTests(); self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.s, self.mid = self.fixture.s, self.fixture.new
        self.directory = self.s.library.directory(self.mid)
        (self.directory / 'recording.wav').write_bytes(b'synthetic')

    def test_edit_and_delete_are_blocked_until_learning_releases_the_meeting(self):
        (self.directory/voices.FILE).unlink()
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        def run(*args, **kwargs):
            entered.set()
            if not release.wait(4): raise RuntimeError('Test barrier timed out')
        revision = self.s.detail(self.mid)['transcript_revision']
        with patch('app.diarization.availability', return_value=dict(available=True)), patch.object(self.s, '_execute', side_effect=run):
            self.s.learn_voices(); self.assertTrue(entered.wait(2))
            self.assertIn(self.mid, self.s.busy)
            with self.assertRaises(ValueError): self.s.delete(self.mid)
            with self.assertRaises(ValueError):
                self.s.edit(self.mid, dict(speaker_name=dict(speaker='SPEAKER_00',name='Alex',revision=revision)))
            release.set(); self.s.voice_thread.join(4)
        self.assertFalse(self.s.voice_thread.is_alive()); self.assertNotIn(self.mid, self.s.busy)
        self.assertNotIn(self.mid, self.s.cancel_events); self.assertEqual(self.s.voice_job['failed'],0)
        self.s.delete(self.mid); self.assertFalse(self.directory.exists())

    def test_deleted_queued_meeting_is_not_recreated(self):
        (self.directory/voices.FILE).unlink()
        self.s.processing_slot.acquire()
        with patch('app.diarization.availability', return_value=dict(available=True)), patch.object(self.s,'_execute') as run:
            try:
                self.s.learn_voices(); self.s.delete(self.mid)
            finally: self.s.processing_slot.release()
            self.s.voice_thread.join(4)
        run.assert_not_called(); self.assertFalse(self.directory.exists()); self.assertFalse(self.s.voice_job['running'])

    def test_shutdown_cancels_owned_worker_and_joins_voice_thread(self):
        (self.directory/voices.FILE).unlink()
        entered = threading.Event(); cancelled = threading.Event()
        def run(action,directory,settings,progress,key,speakers,trackers,cancel=None):
            entered.set()
            if cancel is not None and cancel.wait(4):
                cancelled.set(); raise JobCancelled()
            raise RuntimeError('Missing worker cancellation')
        self.s.step_runner = SimpleNamespace(run=run)
        with patch('app.diarization.availability', return_value=dict(available=True)):
            self.s.learn_voices(); self.assertTrue(entered.wait(2)); self.s.close()
        self.assertTrue(cancelled.is_set()); self.assertFalse(self.s.voice_thread.is_alive())
        self.assertFalse(self.s.busy); self.assertFalse(self.s.voice_job['running'])

    def test_partial_real_name_correction_invalidates_bank_profile(self):
        mid = self.fixture.known; directory = self.s.library.directory(mid)
        revision = self.s.detail(mid)['transcript_revision']
        self.s.edit(mid, dict(speaker_assignment=dict(indices=[0],name='Ivan',revision=revision,defer_analysis=True)))
        self.assertFalse(voices.current(directory)); self.assertEqual(self.s.detail(self.mid)['voice_suggestions'],{})

    def test_stale_target_profile_is_not_used(self):
        atomic_json(self.directory/'speaker-turns.json',[dict(start=0,end=10,speaker='SPEAKER_00')])
        self.assertFalse(voices.current(self.directory)); self.assertEqual(self.s.detail(self.mid)['voice_suggestions'],{})

    def test_rename_does_not_bless_an_already_stale_profile(self):
        atomic_json(self.directory/'speaker-turns.json',[dict(start=0,end=10,speaker='SPEAKER_00')])
        revision=self.s.detail(self.mid)['transcript_revision']
        self.s.edit(self.mid,dict(speaker_name=dict(speaker='SPEAKER_00',name='Alex',revision=revision)))
        self.assertFalse(voices.current(self.directory))

    def test_distinct_people_with_close_voices_still_require_the_margin(self):
        unit=fixtures.unit
        groups={('person','one'):dict(fixtures.group('Alex',unit(1,0)),person=True),
                ('person','two'):dict(fixtures.group('Blair',unit(.8,.6)),person=True)}
        self.assertEqual(voices.suggest(fixtures.prints(SPEAKER_00=unit(1,.3)),groups,set()),{})

    def test_confirmed_aliases_group_without_inventing_an_extra_rival(self):
        self.s.save_person(dict(name='Maria Example',aliases=['Мария','M. Example']))
        self.fixture.meeting('Earlier','M. Example',fixtures.unit(1,.1))
        self.assertEqual(self.s.detail(self.mid)['voice_suggestions']['SPEAKER_00']['name'],'Maria Example')

    def test_watcher_reports_progress_finish_and_global_bank_invalidation(self):
        stream=self.s.watcher.events();self.addCleanup(stream.close)
        self.assertEqual(next(stream),('hello',{}))
        for job in [dict(running=True,done=0,total=2,failed=0),dict(running=True,done=1,total=2,failed=0),dict(running=False,done=2,total=2,failed=0)]:
            before=self.s.watcher.fingerprint()[0]
            with self.s.lock:self.s.voice_job=job
            self.assertNotEqual(self.s.watcher.fingerprint()[0],before)
            self.s.watcher.check();self.assertEqual(next(stream)[0],'state')
        path=self.directory/voices.FILE;atomic_json(path,dict(voices.read(self.directory),test_revision=1))
        self.s.watcher.check();self.assertEqual(next(stream),('state',{'changed':None}))
        atomic_json(self.directory/'speaker-turns.json',[dict(start=0,end=10,speaker='Changed')])
        self.s.watcher.check();self.assertEqual(next(stream),('state',{'changed':None}))


class VoicePublishTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.ComputeTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)

    def test_compute_does_not_recreate_a_directory_deleted_during_inference(self):
        deleted=False
        def embed(samples):
            nonlocal deleted
            if not deleted:shutil.rmtree(self.fixture.dir);deleted=True
            return self.fixture.embed(samples)
        with self.assertRaises((OSError,ValueError)):
            voices.compute(self.fixture.dir,embed,fixtures.MODEL)
        self.assertFalse(self.fixture.dir.exists())

    def test_changed_turns_preserve_previous_profile_instead_of_publishing(self):
        voices.compute(self.fixture.dir,self.fixture.embed,fixtures.MODEL)
        previous=(self.fixture.dir/voices.FILE).read_bytes()
        def embed(samples):
            atomic_json(self.fixture.dir/'speaker-turns.json',[dict(start=0,end=20,speaker='Different')])
            return self.fixture.embed(samples)
        with self.assertRaisesRegex(ValueError,'changed'):
            voices.compute(self.fixture.dir,embed,fixtures.MODEL)
        self.assertEqual((self.fixture.dir/voices.FILE).read_bytes(),previous)
        self.assertFalse(voices.current(self.fixture.dir))


class ReviewIsolationTests(unittest.TestCase):
    def test_one_broken_source_keeps_other_meetings_visible_and_original_bytes(self):
        fixture=queue_fixtures.ReviewQueueTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        s=fixture.s;bad=fixture.meeting('Damaged',fixtures_rows())
        directory=s.library.directory(bad)
        for name,payload in [('minutes.json',b'{broken'),('minutes.json',b'{"tasks":true}'),('transcript.json',b'{broken'),('transcript.json',b'{}')]:
            with self.subTest(name=name,payload=payload):
                path=directory/name;path.write_bytes(payload)
                data=build(s);rows={row['id']:row for row in data['meetings']}
                self.assertEqual(rows[fixture.mid]['items'],1);self.assertIn(name,rows[bad]['repair'])
                self.assertEqual(path.read_bytes(),payload)


def fixtures_rows():
    return [dict(start=0,end=10,speaker='SPEAKER_00',text='Synthetic content')]


class TextAnalyticsTests(unittest.TestCase):
    def test_preview_matches_execution_with_audio_but_no_speaker_timeline(self):
        fixture=rerun_fixtures.ReprocessTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        s=fixture.s;s.settings['diarization_enabled']=True;s.library.update(fixture.mid,mode='audio')
        (fixture.directory/'recording.wav').write_bytes(b'Audio must not be opened')
        atomic_json(fixture.directory/'transcript.json',fixtures_rows());before=(fixture.directory/'transcript.json').read_bytes()
        calls=[]
        def run(action,*args,**kwargs):calls.append(action);return {}
        with patch.object(s,'_execute',side_effect=run),patch.object(s,'_run_analytics',side_effect=lambda *a,**k:MeetingService._run_analytics(s,*a,**k)),patch('wave.open',side_effect=AssertionError('Text analytics opened audio')):
            preview=fixture.preview('analytics');self.assertFalse(preview['uses_audio'])
            self.assertEqual([p['operation'] for p in preview['providers']],['Analytics'])
            reprocess.start(s,dict(token=preview['token'],approved=True));wait_for(lambda:fixture.mid not in s.busy)
        self.assertEqual(calls,['analytics']);self.assertEqual((fixture.directory/'transcript.json').read_bytes(),before)
        self.assertEqual(s.library.get(fixture.mid)['status'],'ready')


class VoiceUIStatusTests(unittest.TestCase):
    def test_unchanged_names_do_not_prevent_progress_and_completion_rendering(self):
        root=Path(__file__).resolve().parents[1]
        result=subprocess.run(['node','tests/web_voice_status_regressions.cjs'],cwd=root,capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
