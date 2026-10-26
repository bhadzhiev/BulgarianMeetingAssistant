import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

PROJECT=Path(__file__).resolve().parents[1]
APP='Bulgarian Meeting Assistant.app'


class DesktopInstallerTests(unittest.TestCase):
    def run_install(self, failure='', options=()):
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
        executable(tools/'osascript','echo false\n')
        executable(tools/'ditto','cp -R "$1" "$2"\n')
        executable(tools/'codesign','[ "$INSTALL_TEST_FAILURE" != verify ]\n')
        executable(tools/'mv','''case "$1" in
 */.bma-install.*/*) [ "$INSTALL_TEST_FAILURE" != publish ] || exit 1 ;;
esac
exec /bin/mv "$@"
''')
        install=root/'installed';(install/APP).mkdir(parents=True);(install/APP/'payload').write_text('old\n')
        env=dict(os.environ,PATH=str(tools)+os.pathsep+os.environ['PATH'],BMA_BUILD_VENV=str(venv.parent),BMA_INSTALL_DIR=str(install),
                 INSTALL_TEST_LOG=str(root/'commands'),INSTALL_TEST_BUILT=str(project/'desktop/src-tauri/target/release/bundle/macos'/APP),INSTALL_TEST_FAILURE=failure)
        result=subprocess.run(['sh',str(project/'scripts/install_desktop.sh'),*options],env=env,capture_output=True,text=True,timeout=10)
        return result,install,(root/'commands').read_text()

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
