"""Unpublished resources must not depend on renaming each newly written file."""
import errno
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from safe_files import SafeDirectory, StagedDirectory


class StagedResources(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_resource_export_survives_per_file_rename_sharing_conflict(self):
        # Model the reported content -> index.html conflict while keeping real
        # file writes and whole-package publication. No retry can cure this lock.
        error = PermissionError('new resource is held without delete sharing')
        error.winerror = 32
        with patch('safe_files._publish_exclusive', side_effect=error), \
                patch('safe_files.os.rename', side_effect=error), patch('safe_files.time.sleep'):
            with SafeDirectory(self.root) as parent, StagedDirectory(parent) as stage:
                stage.write_bytes('index.html', b'complete HTML')
                stage.write_bytes('css/site.css', b'body { color: blue; }')
                self.assertFalse((self.root / 'result').exists())
                result = stage.publish('result')
        self.assertEqual((result / 'index.html').read_bytes(), b'complete HTML')
        self.assertEqual((result / 'css/site.css').read_bytes(), b'body { color: blue; }')
        self.assertFalse(list(self.root.rglob('.vts-*')))

    def test_existing_resource_and_hardlink_are_never_truncated(self):
        victim = self.root / 'outside'
        victim.write_bytes(b'keep outside')
        with SafeDirectory(self.root) as parent, StagedDirectory(parent) as stage:
            path = Path(stage.directory.path)
            (path / 'index.html').write_bytes(b'other writer')
            os.link(victim, path / 'linked.html')
            for name in ('index.html', 'linked.html'):
                with self.assertRaises(FileExistsError):
                    stage.write_bytes(name, b'our content')
            result = stage.publish('result')
        self.assertEqual((result / 'index.html').read_bytes(), b'other writer')
        self.assertEqual(victim.read_bytes(), b'keep outside')

    def test_resource_symlink_is_rejected_without_following_target(self):
        victim = self.root / 'outside'
        victim.write_bytes(b'keep outside')
        with SafeDirectory(self.root) as parent, StagedDirectory(parent) as stage:
            path = Path(stage.directory.path) / 'index.html'
            try:
                path.symlink_to(victim)
            except OSError as error:
                self.skipTest(f'symlink fixture unavailable: {error}')
            with self.assertRaises(OSError):
                stage.write_bytes('index.html', b'bad')
            self.assertEqual(victim.read_bytes(), b'keep outside')
            # Remove only this test-created link so normal empty-stage cleanup runs.
            path.unlink()

    def test_resource_flush_failure_preserves_error_and_unpublished_package(self):
        error = OSError(errno.ENOSPC, 'disk full')
        with SafeDirectory(self.root) as parent:
            with self.assertRaises(OSError) as caught:
                with StagedDirectory(parent) as stage:
                    with patch('safe_files.os.fsync', side_effect=error):
                        stage.write_bytes('index.html', b'incomplete resource')
                    stage.publish('result')
        self.assertIs(caught.exception, error)
        self.assertFalse((self.root / 'result').exists())
        self.assertTrue(error.staging_path.is_dir())
        self.assertEqual(error.export_stage, '寫入網頁資源')
        self.assertEqual(error.export_resource, 'index.html')

    @unittest.skipUnless(os.name == 'nt', 'requires real Windows sharing semantics')
    def test_native_reader_can_hold_new_resource_until_write_returns(self):
        # Real SAME-PROCESS reader: Windows sharing conflicts do not imply the
        # user launched another application. It remains open beyond all retries.
        import ctypes
        import msvcrt
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.GetFinalPathNameByHandleW.argtypes = [wintypes.HANDLE, wintypes.LPWSTR,
                                                   wintypes.DWORD, wintypes.DWORD]
        kernel.GetFinalPathNameByHandleW.restype = wintypes.DWORD
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                      wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        held = []
        real_fsync = os.fsync

        def flush_then_hold(fd):
            real_fsync(fd)
            buffer = ctypes.create_unicode_buffer(32768)
            length = kernel.GetFinalPathNameByHandleW(msvcrt.get_osfhandle(fd), buffer, len(buffer), 0)
            if not 0 < length < len(buffer):
                raise ctypes.WinError(ctypes.get_last_error())
            handle = kernel.CreateFileW(buffer.value, 0x80000000, 3, None, 3, 0, None)
            if handle == wintypes.HANDLE(-1).value:
                raise ctypes.WinError(ctypes.get_last_error())
            held.append(handle)

        with SafeDirectory(self.root) as parent, StagedDirectory(parent) as stage:
            try:
                with patch('safe_files.os.fsync', side_effect=flush_then_hold):
                    stage.write_bytes('index.html', b'complete native HTML')
                self.assertEqual(len(held), 1)
                self.assertEqual((Path(stage.directory.path) / 'index.html').read_bytes(),
                                 b'complete native HTML')
            finally:
                for handle in held:
                    kernel.CloseHandle(handle)
            result = stage.publish('result')
        self.assertEqual((result / 'index.html').read_bytes(), b'complete native HTML')
        self.assertFalse(list(self.root.glob('.vts-*')))
