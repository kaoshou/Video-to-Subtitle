"""Exercise real packaging and archive bytes without invoking a compiler."""
import importlib
from pathlib import Path
import tempfile
import unittest
import zipfile


class ReleasePackages(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dist = Path(self.temp.name)
        (self.dist / 'installer').mkdir()
        (self.dist / 'VideoToSubtitle.exe').write_bytes(b'portable payload')
        (self.dist / 'installer/VideoToSubtitle-Setup-v2.9.1.exe').write_bytes(b'installer payload')
        (self.dist / 'VideoToSubtitle.dmg').write_bytes(b'dmg payload')

    def package(self, system, machine, version='2.9.1'):
        module = importlib.import_module('scripts.package_release')
        return module.package_release(self.dist, version, system, machine)

    def test_windows_has_one_installer_and_one_zip_containing_runnable_portable(self):
        paths = self.package('Windows', 'AMD64')
        self.assertEqual({path.name for path in paths}, {
            'VideoToSubtitle_v2.9.1_Windows_x64_Portable.zip',
            'VideoToSubtitle_v2.9.1_Windows_x64_Setup.exe'})
        self.assertEqual(len(list((self.dist / 'release').iterdir())), 2)
        with zipfile.ZipFile(self.dist / 'release/VideoToSubtitle_v2.9.1_Windows_x64_Portable.zip') as archive:
            self.assertEqual(archive.namelist(), ['VideoToSubtitle.exe'])
            self.assertEqual(archive.read('VideoToSubtitle.exe'), b'portable payload')
            self.assertIsNone(archive.testzip())
        self.assertEqual((self.dist / 'release/VideoToSubtitle_v2.9.1_Windows_x64_Setup.exe').read_bytes(), b'installer payload')
        self.assertEqual((self.dist / 'VideoToSubtitle.exe').read_bytes(), b'portable payload')

    def test_mac_has_exact_arm64_dmg_and_keeps_original_bytes(self):
        paths = self.package('Darwin', 'arm64')
        self.assertEqual([path.name for path in paths], ['VideoToSubtitle_v2.9.1_macOS_arm64.dmg'])
        self.assertEqual(paths[0].read_bytes(), b'dmg payload')

    def test_missing_or_empty_sources_do_not_create_partial_release(self):
        for content in (None, b''):
            with self.subTest(content=content):
                source = self.dist / 'installer/VideoToSubtitle-Setup-v2.9.1.exe'
                if content is None:
                    source.unlink(missing_ok=True)
                else:
                    source.write_bytes(content)
                with self.assertRaises(ValueError):
                    self.package('Windows', 'AMD64')
                self.assertFalse((self.dist / 'release').exists())

    def test_wrong_architecture_or_version_cannot_be_mislabeled(self):
        for system, machine, version in [('Darwin','x86_64','2.9.1'), ('Windows','arm64','2.9.1'),
                                         ('Linux','x86_64','2.9.1'), ('Windows','AMD64','../../bad')]:
            with self.subTest(system=system, machine=machine, version=version):
                with self.assertRaises(ValueError):
                    self.package(system, machine, version)
                self.assertFalse((self.dist / 'release').exists())

    def test_existing_packages_are_not_overwritten(self):
        paths = self.package('Windows', 'x86_64')
        before = {path: path.read_bytes() for path in paths}
        with self.assertRaises(FileExistsError):
            self.package('Windows', 'x86_64')
        self.assertEqual({path: path.read_bytes() for path in paths}, before)
