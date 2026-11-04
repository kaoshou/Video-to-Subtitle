from pathlib import Path
import importlib.util
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


class Notices(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec('PyInstaller'), 'PyInstaller build environment required')
    def test_specs_import_local_license_collector_without_cwd_on_python_path(self):
        root = Path(__file__).resolve().parents[1]
        # The PyInstaller console command executes specs without adding the
        # checkout to sys.path; reproduce that bootstrap in an isolated Python.
        for name, boundary in [('MCPLauncher.spec', 'excluded ='),
                               ('VideoToSubtitle.spec', 'windows_bundle =')]:
            with self.subTest(spec=name), tempfile.TemporaryDirectory() as temporary:
                code = ('from pathlib import Path; import sys; '
                        'p = Path(sys.argv[1]); '
                        'scope = {"SPECPATH": str(p.parent)}; '
                        'exec(compile(p.read_text(encoding="utf-8").split(sys.argv[2])[0], str(p), "exec"), scope); '
                        'assert callable(scope["collect_license_datas"])')
                result = subprocess.run([sys.executable, '-I', '-c', code, str(root / name), boundary],
                                        cwd=temporary, capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_packaging_preserves_original_dependency_and_native_notices(self):
        from third_party import collect_license_datas
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            entries = [Path('sample.dist-info/licenses/LICENSE'), Path('sample/native/ThirdPartyNotices.txt')]
            for index, entry in enumerate(entries):
                (root / entry).parent.mkdir(parents=True, exist_ok=True)
                (root / entry).write_text(f'Original copyright and terms {index}')
            dist = SimpleNamespace(metadata={'Name':'sample'}, version='1.0',
                files=entries + [Path('../outside/LICENSE')], locate_file=lambda p: root / p)
            with patch('importlib.metadata.distributions', return_value=[dist]):
                resources = collect_license_datas()
            self.assertEqual(len(resources), 2)
            for index, (source, destination) in enumerate(resources):
                self.assertEqual(Path(source).read_text(), f'Original copyright and terms {index}')
                self.assertEqual(Path(destination).parts[:3], ('licenses', 'sample', '1.0'))
                self.assertNotIn('..', Path(destination).parts)
