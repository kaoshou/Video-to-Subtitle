"""Exercise the production version reader without importing Tk or speech engines."""
import ast
from functools import lru_cache
import os
from pathlib import Path
import tempfile
import unittest


class AppVersion(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.toml = Path(self.temp.name) / 'pyproject.toml'
        source = Path(__file__).resolve().parents[1] / 'SubtitleTranscriber.py'
        tree = ast.parse(source.read_text(encoding='utf-8'))
        self.reader = next(node for node in tree.body
                           if isinstance(node, ast.FunctionDef) and node.name == 'get_version')

    def new_process_reader(self):
        # Compile the real function, including decorators, in fresh module
        # globals. Only __file__ changes to an isolated package fixture.
        scope = {'os': os, 'lru_cache': lru_cache,
                 '__file__': str(self.toml.with_name('SubtitleTranscriber.py'))}
        exec(compile(ast.Module(body=[self.reader], type_ignores=[]),
                     'production_version_reader', 'exec'), scope)
        return scope['get_version']

    def write_version(self, version):
        self.toml.write_text(f'[project]\nversion = "{version}"\n', encoding='utf-8')

    def test_running_version_does_not_follow_an_updated_version_file(self):
        # Break caught: a later About/update-check call rereads new metadata
        # even though the running Python code still belongs to the old launch.
        self.write_version('9.8.0')
        read = self.new_process_reader()
        self.assertEqual(read(), '9.8.0')
        self.write_version('9.8.1')
        self.assertEqual(read(), '9.8.0')
        self.assertEqual(self.new_process_reader()(), '9.8.1')

    def test_running_version_survives_missing_metadata(self):
        self.write_version('9.8.0')
        read = self.new_process_reader()
        self.assertEqual(read(), '9.8.0')
        self.toml.unlink()
        self.assertEqual(read(), '9.8.0')

    def test_running_version_survives_corrupt_metadata(self):
        self.write_version('9.8.0')
        read = self.new_process_reader()
        self.assertEqual(read(), '9.8.0')
        self.toml.write_text('[project', encoding='utf-8')
        self.assertEqual(read(), '9.8.0')


if __name__ == '__main__':
    unittest.main()
