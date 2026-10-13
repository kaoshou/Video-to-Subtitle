"""Settings must outlive an installed application, without following links."""
import json
import os
from pathlib import Path
import tempfile
import unittest


class AppSettings(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bundle = self.root / 'installed' / '_internal'
        self.bundle.mkdir(parents=True)
        self.local = self.root / 'user data'
        self.local.mkdir()

    def resolve(self, **options):
        from app_settings import resolve_settings_path
        return resolve_settings_path(self.bundle, system='win32', frozen=True,
                                     environ={'LOCALAPPDATA': str(self.local)}, **options)

    def test_windows_frozen_settings_survive_bundle_replacement(self):
        from app_settings import read_settings, write_settings
        path = self.resolve()
        self.assertEqual(path, self.local / 'VideoToSubtitle' / 'config.json')
        write_settings(path, {'model': 'small', 'hotwords': '老師, 教學'})
        self.bundle.rmdir()
        self.bundle.mkdir()
        self.assertEqual(read_settings(self.resolve()),
                         {'model': 'small', 'hotwords': '老師, 教學'})
        self.assertFalse((self.bundle / 'config.json').exists())

    def test_source_and_mac_keep_legacy_settings_location(self):
        from app_settings import resolve_settings_path
        for system, frozen in [('win32', False), ('darwin', True), ('linux', False)]:
            self.assertEqual(resolve_settings_path(self.bundle, system=system, frozen=frozen),
                             self.bundle / 'config.json')

    def test_existing_user_settings_are_not_overwritten_by_legacy(self):
        from app_settings import read_settings, write_settings
        (self.bundle / 'config.json').write_text('{"model": "tiny"}', encoding='utf-8')
        path = self.resolve()
        self.assertEqual(read_settings(path), {'model': 'tiny'})
        write_settings(path, {'model': 'medium'})
        self.assertEqual(read_settings(self.resolve()), {'model': 'medium'})
        self.assertEqual(json.loads((self.bundle / 'config.json').read_text()), {'model': 'tiny'})

    def test_invalid_legacy_settings_do_not_prevent_first_launch(self):
        from app_settings import write_settings, read_settings
        for content in ('not json', '[]'):
            (self.bundle / 'config.json').write_text(content, encoding='utf-8')
            path = self.resolve()
            self.assertFalse(path.exists())
        write_settings(path, {'format': 'vtt'})
        self.assertEqual(read_settings(path), {'format': 'vtt'})

    def test_relative_localappdata_cannot_write_into_working_directory(self):
        from app_settings import resolve_settings_path
        home = self.root / 'home'
        (home / 'AppData' / 'Local').mkdir(parents=True)
        path = resolve_settings_path(self.bundle, system='win32', frozen=True,
                                     environ={'LOCALAPPDATA': 'relative'}, home=home)
        self.assertEqual(path, home / 'AppData' / 'Local' / 'VideoToSubtitle' / 'config.json')

    def test_read_and_write_reject_symlink_without_changing_target(self):
        from app_settings import read_settings, write_settings
        from safe_files import UnsafePathError
        path = self.resolve()
        victim = self.root / 'victim.json'
        victim.write_text('{"model": "small"}', encoding='utf-8')
        try:
            path.symlink_to(victim)
        except OSError:
            self.skipTest('creating symlinks is not permitted')
        for operation in (lambda: read_settings(path), lambda: write_settings(path, {'model': 'tiny'})):
            with self.assertRaises(UnsafePathError):
                operation()
        self.assertEqual(victim.read_text(), '{"model": "small"}')

    def test_rejects_non_object_and_oversized_settings(self):
        from app_settings import read_settings
        path = self.resolve()
        for data in ('[]', '{"prompt": "' + 'x' * (1024 * 1024) + '"}'):
            path.write_text(data, encoding='utf-8')
            with self.assertRaises(ValueError):
                read_settings(path)


if __name__ == '__main__':
    unittest.main()
