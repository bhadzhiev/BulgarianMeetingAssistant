import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

PROJECT=Path(__file__).resolve().parents[1]
APP='Atlanta.app'
LEGACY='Bulgarian Meeting Assistant.app'


class DesktopInstallerTests(unittest.TestCase):
    def run_install(self, failure='', options=(), legacy=False, lock_pid=None):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name);project=root/'project';(project/'scripts').mkdir(parents=True)
        shutil.copy2(PROJECT/'scripts/install_desktop.sh',project/'scripts/install_desktop.sh')
        (project/'desktop/node_modules').mkdir(parents=True)
        (project/'desktop/package-lock.json').write_text('{}')
        (project/'desktop/node_modules/.package-lock.json').write_text('{}')
        tools=root/'tools';tools.mkdir();venv=root/'venv/bin';venv.mkdir(parents=True)
        def executable(path,text):path.write_text('#!/bin/sh\nset -eu\n'+text);path.chmod(0o755)
        executable(venv/'python', '''printf '%s\\n' "$*" >> "$INSTALL_TEST_LOG"
case "$1" in
  */build_desktop.py) mkdir -p "$INSTALL_TEST_BUILT"; echo new > "$INSTALL_TEST_BUILT/payload" ;;
esac
''')
        for name in ['cargo','npm','xcrun','ffmpeg']:executable(tools/name,'exit 0\n')
        executable(tools/'uname','echo Darwin arm64\n')
        executable(tools/'osascript','echo false\n')
        executable(tools/'ditto','cp -R "$1" "$2"\n')
        executable(tools/'codesign','[ "$INSTALL_TEST_FAILURE" != verify ]\n')
        executable(tools/'mv','''case "$1" in
 */.bma-install.*/*) [ "$INSTALL_TEST_FAILURE" != publish ] || exit 1 ;;
esac
exec /bin/mv "$@"
''')
        if lock_pid is not None:
            (project/'build/install.lock').mkdir(parents=True);(project/'build/install.lock/pid').write_text(f'{lock_pid}\n')
        self.project=project
        install=root/'installed';(install/APP).mkdir(parents=True);(install/APP/'payload').write_text('old\n')
        if legacy:(install/LEGACY).mkdir();(install/LEGACY/'payload').write_text('legacy\n')
        env=dict(os.environ,PATH=str(tools)+os.pathsep+os.environ['PATH'],BMA_BUILD_VENV=str(venv.parent),BMA_INSTALL_DIR=str(install),
                 INSTALL_TEST_LOG=str(root/'commands'),INSTALL_TEST_BUILT=str(project/'desktop/src-tauri/target/release/bundle/macos'/APP),INSTALL_TEST_FAILURE=failure)
        result=subprocess.run(['sh',str(project/'scripts/install_desktop.sh'),*options],env=env,capture_output=True,text=True,timeout=10)
        commands=root/'commands'
        return result,install,commands.read_text() if commands.exists() else ''

    def test_a_second_install_stops_while_one_runs(self):
        # This test process is alive, so its PID stands for a running install.
        result,install,commands=self.run_install(lock_pid=os.getpid())
        self.assertNotEqual(result.returncode,0)
        self.assertIn(f'Another install is running (process {os.getpid()})',result.stderr)
        self.assertEqual(commands,'')
        self.assertEqual((install/APP/'payload').read_text(),'old\n')
        self.assertTrue((self.project/'build/install.lock').is_dir())  # the lock of the running install stays

    def test_a_lock_left_by_a_stopped_install_is_taken_and_released(self):
        dead=subprocess.Popen(['true']);dead.wait()
        result,install,_=self.run_install(lock_pid=dead.pid)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual((install/APP/'payload').read_text(),'new\n')
        self.assertFalse((self.project/'build/install.lock').exists())

    def test_a_failed_install_releases_its_lock(self):
        result,_,_=self.run_install('verify')
        self.assertNotEqual(result.returncode,0)
        self.assertFalse((self.project/'build/install.lock').exists())

    def test_installs_speaker_dependencies_and_keeps_previous_app(self):
        result,install,commands=self.run_install()
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('requirements-diarization.txt',commands)
        self.assertEqual(commands.count('--with-diarization'),1)
        self.assertEqual(commands.count('requirements-diarization.txt'),1)
        self.assertEqual((install/APP/'payload').read_text(),'new\n')
        backups=list(install.glob('.bma-previous.*/'+APP+'/payload'))
        self.assertEqual(len(backups),1)
        self.assertEqual(backups[0].read_text(),'old\n')
        self.assertEqual(list(install.glob('.bma-install.*')),[])

    def test_the_old_name_is_replaced_and_kept_as_previous(self):
        self.tmp_legacy=True
        result,install,_=self.run_install(legacy=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertFalse((install/LEGACY).exists())
        self.assertEqual((install/APP/'payload').read_text(),'new\n')
        self.assertEqual([p.read_text() for p in install.glob('.bma-previous.*/'+LEGACY+'/payload')],['legacy\n'])
        self.assertIn('The app is now named Atlanta.',result.stdout)

    def test_explicit_small_build_omits_speaker_dependencies(self):
        result,install,commands=self.run_install(options=('--without-diarization',))
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertNotIn('requirements-diarization.txt',commands)
        self.assertNotIn('--with-diarization',commands)
        self.assertNotIn('--without-diarization',commands)

    def test_signature_failure_keeps_installed_app(self):
        result,install,_=self.run_install('verify')
        self.assertNotEqual(result.returncode,0)
        self.assertEqual((install/APP/'payload').read_text(),'old\n')
        self.assertEqual(list(install.glob('.bma-install.*')),[])

    def test_failed_publish_restores_previous_bundle(self):
        result,install,_=self.run_install('publish')
        self.assertNotEqual(result.returncode,0)
        self.assertEqual((install/APP/'payload').read_text(),'old\n')
        self.assertEqual(list(install.glob('.bma-install.*')),[])

    def test_apple_silicon_installs_parakeet_once_by_default(self):
        result,_,commands=self.run_install(options=('--with-parakeet',))
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('requirements-parakeet.txt',commands)
        self.assertEqual(commands.split().count('--with-parakeet'),1)

    def test_without_parakeet_does_not_install_or_forward_the_option(self):
        result,_,commands=self.run_install(options=('--without-parakeet',))
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertNotIn('requirements-parakeet.txt',commands)
        self.assertNotIn('--with-parakeet',commands.split())
        self.assertNotIn('--without-parakeet',commands.split())

    def test_vocabulary_backend_is_included_once_and_can_be_omitted_independently(self):
        result,_,commands=self.run_install(options=('--with-parakeet-sherpa',))
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(commands.split().count('--with-parakeet-sherpa'),1)
        self.assertEqual(commands.count('requirements-parakeet-sherpa.txt'),1)
        result,_,commands=self.run_install(options=('--without-parakeet-sherpa',))
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertNotIn('requirements-parakeet-sherpa.txt',commands)
        self.assertNotIn('--with-parakeet-sherpa',commands.split())
        self.assertIn('--with-parakeet',commands.split())
