import importlib.util
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('desktop_packaging',Path(__file__).resolve().parents[1]/'scripts/build_desktop.py')
build=importlib.util.module_from_spec(spec);spec.loader.exec_module(build)


class MetalResourceTests(unittest.TestCase):
    def test_loader_alias_resolves_to_the_bundled_metal_kernels(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);kernels=root/'_internal/mlx/lib/mlx.metallib';kernels.parent.mkdir(parents=True);kernels.write_bytes(b'kernels')
            build.link_mlx_metallib(root);build.link_mlx_metallib(root)
            alias=root/'_internal/mlx.metallib'
            self.assertTrue(alias.samefile(kernels))
            self.assertEqual(alias.readlink(),Path('mlx/lib/mlx.metallib'))

    def test_missing_metal_resource_fails_before_shipping(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RuntimeError,'missing mlx.metallib'):build.link_mlx_metallib(tmp)
