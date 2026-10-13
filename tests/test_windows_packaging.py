"""Execute the spec with lightweight build-boundary doubles, not source greps."""
import os
from pathlib import Path
import runpy
import types
import unittest
from unittest.mock import patch


class WindowsPackaging(unittest.TestCase):
    def spec(self, mode):
        records = {}
        hooks = types.ModuleType('PyInstaller.utils.hooks')
        hooks.collect_all = lambda name: ([(name + '-data', name)],
                                         [(name + '-dll', name)], [name])
        def analysis(scripts, **kwargs):
            return types.SimpleNamespace(pure=[], scripts=scripts,
                                         binaries=kwargs['binaries'], datas=kwargs['datas'])
        def build(kind):
            def run(*args, **kwargs):
                records[kind] = (args, kwargs)
                return kind
            return run
        with patch.dict('sys.modules', {'PyInstaller': types.ModuleType('PyInstaller'),
                        'PyInstaller.utils': types.ModuleType('PyInstaller.utils'),
                        'PyInstaller.utils.hooks': hooks}), patch('sys.platform', 'win32'), \
                patch.dict(os.environ, {'VTS_WINDOWS_BUNDLE': mode}):
            runpy.run_path(str(Path(__file__).resolve().parents[1] / 'VideoToSubtitle.spec'),
                           init_globals={'Analysis': analysis, 'PYZ': build('PYZ'),
                                         'EXE': build('EXE'), 'COLLECT': build('COLLECT')})
        return records

    def test_portable_remains_a_self_contained_single_executable(self):
        records = self.spec('onefile')
        args, kwargs = records['EXE']
        self.assertIn(('av-dll', 'av'), args[2])
        self.assertIn(('assets', 'assets'), args[3])
        self.assertNotIn('COLLECT', records)
        self.assertFalse(kwargs.get('exclude_binaries', False))

    def test_installer_payload_keeps_dependencies_outside_executable(self):
        records = self.spec('onedir')
        args, kwargs = records['EXE']
        self.assertTrue(kwargs.get('exclude_binaries', False),
                        'installer must not wrap the slow-extracting onefile executable')
        self.assertEqual(args[2], [])
        collected, options = records['COLLECT']
        self.assertIn(('av-dll', 'av'), collected[1])
        self.assertIn(('assets', 'assets'), collected[2])
        self.assertIn(('app_icon.ico', '.'), collected[2])
        self.assertEqual(options['name'], 'VideoToSubtitle')

    def test_unknown_bundle_mode_fails_instead_of_silently_building_portable(self):
        with self.assertRaises(ValueError):
            self.spec('onerdir')
