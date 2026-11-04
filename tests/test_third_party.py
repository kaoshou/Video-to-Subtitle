from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


class Notices(unittest.TestCase):
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
                self.assertTrue(destination.startswith('licenses/sample/1.0/'))
                self.assertNotIn('..', Path(destination).parts)
