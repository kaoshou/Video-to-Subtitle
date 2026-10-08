"""Regression: an external reader briefly holds newly written HTML on Windows."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

import safe_files


def sharing_error(code=32):
    error = PermissionError('file temporarily in use')
    error.winerror = code
    return error


class SharingRegression(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def publication(self, exclusive):
        if os.name == 'nt':
            return 'safe_files.os.rename' if exclusive else 'safe_files.os.replace'
        return 'safe_files._publish_exclusive' if exclusive else 'safe_files.os.replace'

    def test_temporary_sharing_violation_preserves_atomic_write(self):
        # Break caught: failing immediately instead of retrying a transient lock.
        for exclusive in (False, True):
            with self.subTest(exclusive=exclusive):
                name = 'index-exclusive.html' if exclusive else 'index.html'
                if not exclusive:
                    (self.root / name).write_bytes(b'old page')
                target = self.publication(exclusive)
                original = (safe_files._publish_exclusive if target.endswith('_publish_exclusive')
                            else os.rename if target.endswith('rename') else os.replace)
                failures = iter([32, 33, None])
                def temporarily_busy(*args, **kwargs):
                    code = next(failures, None)
                    if code:
                        if not exclusive:
                            self.assertEqual((self.root / name).read_bytes(), b'old page')
                        raise sharing_error(code)
                    return original(*args, **kwargs)
                try:
                    with patch(target, side_effect=temporarily_busy):
                        with safe_files.SafeDirectory(self.root) as directory:
                            directory.write_bytes(name, b'new page', exclusive=exclusive)
                except OSError as error:
                    self.fail(f'transient Windows lock prevented publication: {error}')
                self.assertEqual((self.root / name).read_bytes(), b'new page')
                self.assertFalse(list(self.root.glob('.vts-*')))

    def test_destination_created_during_retry_is_never_overwritten(self):
        # Break caught: retry downgrades an exclusive publication to replacement.
        path = self.root / 'index.html'
        target = self.publication(True)
        original = safe_files._publish_exclusive if os.name != 'nt' else os.rename
        first = True
        def competitor(*args, **kwargs):
            nonlocal first
            if first:
                first = False
                path.write_bytes(b'other writer')
                raise sharing_error()
            return original(*args, **kwargs)
        with patch(target, side_effect=competitor), safe_files.SafeDirectory(self.root) as directory:
            with self.assertRaises(FileExistsError):
                directory.write_bytes('index.html', b'our page', exclusive=True)
        self.assertEqual(path.read_bytes(), b'other writer')

    def test_non_sharing_errors_are_not_retried(self):
        attempts = []
        error = sharing_error(5)
        def access_denied(*args, **kwargs):
            attempts.append(1)
            raise error
        with patch('safe_files.os.replace', side_effect=access_denied):
            with safe_files.SafeDirectory(self.root) as directory:
                with self.assertRaises(OSError) as caught:
                    directory.write_bytes('index.html', b'page')
        self.assertIs(caught.exception, error)
        self.assertEqual(len(attempts), 1)
        self.assertFalse((self.root / 'index.html').exists())

    def test_persistent_lock_is_bounded_and_keeps_original_page(self):
        # Break caught: infinite retries, swallowing failure, or replacing old data.
        path = self.root / 'index.html'
        path.write_bytes(b'old page')
        attempts = []
        error = sharing_error()
        def locked(*args, **kwargs):
            attempts.append(1)
            raise error
        with patch('safe_files.os.replace', side_effect=locked), patch('time.sleep'):
            with safe_files.SafeDirectory(self.root) as directory:
                with self.assertRaises(OSError) as caught:
                    directory.write_bytes('index.html', b'new page')
        self.assertIs(caught.exception, error)
        self.assertGreater(len(attempts), 1)
        self.assertLessEqual(len(attempts), 10)
        self.assertEqual(path.read_bytes(), b'old page')

    def test_cleanup_failure_does_not_hide_original_sharing_error(self):
        # Break caught: rmdir failure replaces the useful WinError32 diagnosis.
        error = sharing_error()
        cleanup_error = OSError('temporary directory still in use')
        cleanup_error.winerror = 145
        with patch('safe_files.os.replace', side_effect=error), patch('time.sleep'):
            with safe_files.SafeDirectory(self.root) as directory:
                with patch('safe_files.os.rmdir', side_effect=cleanup_error):
                    with self.assertRaises(OSError) as caught:
                        directory.write_bytes('index.html', b'new page')
        self.assertIs(caught.exception, error)
        self.assertTrue(caught.exception.staging_path.is_dir())
        self.assertFalse((self.root / 'index.html').exists())

    @unittest.skipUnless(os.name == 'nt', 'requires real Windows file sharing')
    def test_real_external_reader_releases_source_before_retry_deadline(self):
        # Break caught: fresh HTML locked by a reader cannot be renamed.
        original = os.rename
        child = None
        timer = None
        observed = []
        reader = '''import ctypes, sys
from ctypes import wintypes
k = ctypes.WinDLL('kernel32', use_last_error=True)
k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                         wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
k.CreateFileW.restype = wintypes.HANDLE
k.CloseHandle.argtypes = [wintypes.HANDLE]
h = k.CreateFileW(sys.argv[1], 0x80000000, 3, None, 3, 0, None)
if h == wintypes.HANDLE(-1).value: raise ctypes.WinError(ctypes.get_last_error())
print('locked', flush=True)
sys.stdin.readline()
k.CloseHandle(h)
'''
        def lock_before_rename(source, destination, *args, **kwargs):
            nonlocal child, timer
            if child is None:
                child = subprocess.Popen([sys.executable, '-c', reader, str(source)],
                                         stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE, text=True)
                self.assertEqual(child.stdout.readline().strip(), 'locked')
                def release():
                    child.stdin.write('release\n'); child.stdin.flush()
                timer = threading.Timer(0.3, release)
                timer.start()
            try:
                return original(source, destination, *args, **kwargs)
            except OSError as error:
                observed.append(error.winerror)
                raise
        failure = None
        try:
            with patch('safe_files.os.rename', side_effect=lock_before_rename):
                with safe_files.SafeDirectory(self.root) as directory:
                    directory.write_bytes('index.html', b'complete HTML', exclusive=True)
        except OSError as error:
            failure = error
        finally:
            if timer: timer.join(3)
            if child:
                child.communicate(timeout=5)
        self.assertIn(32, observed, 'fixture did not cause the reported native sharing violation')
        self.assertIsNone(failure, f'external reader interrupted safe publication: {failure}')
        self.assertEqual((self.root / 'index.html').read_bytes(), b'complete HTML')
        self.assertFalse(list(self.root.glob('.vts-*')))
