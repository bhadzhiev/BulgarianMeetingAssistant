import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('build_desktop', PROJECT / 'scripts' / 'build_desktop.py')
build_desktop = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_desktop)
REAL_RUN = subprocess.run


class BackendLinkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.backend = root / 'build' / 'meeting-backend'
        (self.backend / '_internal' / 'mlx' / 'lib').mkdir(parents=True)
        (self.backend / '_internal' / 'mlx' / 'lib' / 'libmlx.dylib').write_bytes(b'library')
        (self.backend / '_internal' / 'mlx' / 'lib' / 'mlx.metallib').write_bytes(b'kernels')
        os.symlink('mlx/lib/libmlx.dylib', self.backend / '_internal' / 'libmlx.dylib')
        self.app = root / 'Atlanta.app'
        # Tauri's copy: the link became a second file without the kernels next to it.
        copied = self.app / 'Contents' / 'Resources' / 'backend' / 'meeting-backend' / '_internal'
        copied.mkdir(parents=True)
        (copied / 'libmlx.dylib').write_bytes(b'library')
        self.entitlements = root / 'Entitlements.plist'
        self.calls = []

    def run_tool(self, command, check):
        self.calls.append(command)
        if command[0] == 'ditto':
            REAL_RUN(command, check=check)

    def test_the_app_gets_the_links_and_a_new_signature(self):
        with patch.object(build_desktop.subprocess, 'run', side_effect=self.run_tool):
            build_desktop.keep_backend_links(self.app, self.backend, self.entitlements)
        link = self.app / 'Contents' / 'Resources' / 'backend' / 'meeting-backend' / '_internal' / 'libmlx.dylib'
        self.assertTrue(link.is_symlink())
        self.assertEqual(os.readlink(link), 'mlx/lib/libmlx.dylib')
        self.assertEqual((link.parent / 'mlx' / 'lib' / 'mlx.metallib').read_bytes(), b'kernels')
        sign, verify = self.calls[1], self.calls[2]
        self.assertEqual(sign[:7], ['codesign', '--force', '--sign', '-', '--options', 'runtime', '--entitlements'])
        self.assertEqual((sign[-1], verify), (str(self.app), ['codesign', '--verify', '--deep', '--strict', str(self.app)]))

    def test_a_local_certificate_signs_the_backend_and_the_app(self):
        identity = 'A' * 40
        with patch.object(build_desktop.subprocess, 'run', side_effect=self.run_tool):
            build_desktop.keep_backend_links(self.app, self.backend, self.entitlements, identity)
        backend = self.app / 'Contents' / 'Resources' / 'backend' / 'meeting-backend' / 'meeting-backend'
        self.assertEqual(self.calls[1], ['codesign', '--force', '--sign', identity, str(backend)])
        self.assertEqual(self.calls[2][:4], ['codesign', '--force', '--sign', identity])
        self.assertEqual(self.calls[2][-1], str(self.app))

    def test_the_identity_is_the_local_certificate_or_ad_hoc(self):
        listed = '  1) ' + 'B' * 40 + ' "Atlanta Local Code Signing" (CSSMERR_TP_NOT_TRUSTED)\n     1 identities found\n'
        found = subprocess.CompletedProcess([], 0, stdout=listed)
        with patch.dict(os.environ, {}, clear=False), patch.object(build_desktop.subprocess, 'run', return_value=found):
            os.environ.pop('BMA_SIGN_IDENTITY', None)
            self.assertEqual(build_desktop.signing_identity(), 'B' * 40)
            found.stdout = '     0 identities found\n'
            self.assertEqual(build_desktop.signing_identity(), '-')
            os.environ['BMA_SIGN_IDENTITY'] = 'Other'
            self.assertEqual(build_desktop.signing_identity(), 'Other')

    def test_an_app_without_a_backend_stops_the_build(self):
        with patch.object(build_desktop.subprocess, 'run', side_effect=self.run_tool), self.assertRaises(SystemExit):
            build_desktop.keep_backend_links(Path(self.tmp.name) / 'Other.app', self.backend, self.entitlements)
        self.assertEqual(self.calls, [])
