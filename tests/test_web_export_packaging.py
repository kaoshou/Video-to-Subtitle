import importlib.util
from pathlib import Path
import tempfile
import unittest


class PackagingSmoke(unittest.TestCase):
    def test_export_smoke_entrypoint(self):
        path = Path(__file__).resolve().parents[1] / 'scripts/smoke_web_export.py'
        self.assertTrue(path.is_file(), 'packaged export smoke harness missing')
        spec = importlib.util.spec_from_file_location('smoke_web_export', path)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as folder:
            result = module.run_smoke(Path(folder))
            self.assertTrue(result.index_path.is_file())
            self.assertTrue((result.folder / 'js/evercam-modern.js').is_file())
