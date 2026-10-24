"""Windows handle validation, with unsupported tag queries at the WinAPI boundary.

The POSIX simulator supplies real descriptors/files to the unchanged Windows
SafeDirectory path. Native ABI and smoke coverage run separately on Windows.
"""
import ctypes
import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import evercam_integration as evercam
import safe_files


class WinFunction:
    def __init__(self, call):
        self.call = call

    def __call__(self, *args):
        return self.call(*args)


class FileAPI:
    def __init__(self):
        self.paths = {}
        self.closed = []
        self.attributes = None
        self.error = None
        self.error_at = None
        self.last_error = 87
        self.CreateFileW = WinFunction(self.create)
        self.GetFileInformationByHandleEx = WinFunction(lambda *args: 0)
        self.GetFileInformationByHandle = WinFunction(self.info)
        self.CloseHandle = WinFunction(self.close)

    def create(self, path, access, share, security, disposition, flags, template):
        # Fail if safety flags regress; actual descriptors back all reads.
        if not flags & 0x00200000 or share & 4 or disposition != 3:
            raise AssertionError('unsafe CreateFileW flags')
        fd = os.open(path, os.O_RDONLY)
        self.paths[fd] = path
        return fd

    def info(self, handle, pointer):
        if self.error and (self.error_at is None or self.paths[handle] == self.error_at):
            self.last_error = self.error
            return 0
        attributes = self.attributes
        if attributes is None:
            attributes = 0x10 if stat.S_ISDIR(os.fstat(handle).st_mode) else 0x80
        # BY_HANDLE_FILE_INFORMATION has thirteen 32-bit words, 52 bytes.
        info = pointer._obj
        if ctypes.sizeof(info) != 52:
            raise AssertionError('incorrect Windows structure size')
        ctypes.cast(pointer, ctypes.POINTER(ctypes.c_uint32))[0] = attributes
        return 1

    def close(self, handle):
        self.closed.append(handle)
        os.close(handle)
        return 1


def win_error(code):
    error = OSError(22, f'[WinError {code}] Windows file operation failed')
    error.winerror = code
    return error


@unittest.skipIf(os.name == 'nt', 'POSIX-backed WinAPI simulation')
class UnsupportedTagInformation(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.api = FileAPI()
        proxy = SimpleNamespace(**{name: getattr(os, name) for name in dir(os)})
        proxy.name = 'nt'
        proxy.O_BINARY = 0
        self.addCleanup(patch.stopall)
        patch.object(safe_files, 'os', proxy).start()
        patch.object(ctypes, 'WinDLL', return_value=self.api, create=True).start()
        patch.object(ctypes, 'get_last_error', side_effect=lambda: self.api.last_error, create=True).start()
        patch.object(ctypes, 'WinError', side_effect=win_error, create=True).start()
        patch.dict('sys.modules', {'msvcrt': SimpleNamespace(open_osfhandle=lambda handle, flags: handle)}).start()

    def test_safe_directory_write_and_read_when_tag_query_is_unsupported(self):
        # Break caught: requiring FileAttributeTagInfo on FAT/exFAT.
        with safe_files.SafeDirectory(self.root) as directory:
            directory.write_bytes('字幕.txt', b'first')
            directory.write_bytes('字幕.txt', b'replaced')
            self.assertEqual(directory.read_bytes('字幕.txt'), b'replaced')
        self.assertEqual(list(self.root.iterdir()), [self.root / '字幕.txt'])

    def test_real_deploy_and_redeploy_when_tag_query_is_unsupported(self):
        for name, content in {'config.js': 'var config = {};', 'media.mp4': 'video',
                              'index.html': 'original', 'media.srt':
                              '1\n00:00:01,000 --> 00:00:02,000\n字幕\n'}.items():
            (self.root / name).write_text(content, encoding='utf-8')
        for _ in range(2):
            ok, message, output = evercam.deploy_evercam_player(str(self.root))
            self.assertTrue(ok, message)
            self.assertEqual(output, str(self.root / 'index.html'))
        self.assertEqual((self.root / 'index.evercam-original.html').read_text(), 'original')
        self.assertEqual((self.root / 'media.mp4').read_text(), 'video')
        self.assertIn('字幕', (self.root / 'subtitles-data.js').read_text(encoding='utf-8'))
        self.assertFalse(list(self.root.rglob('.vts-*')))

    def test_every_reparse_bit_and_type_mismatch_is_rejected_and_closed(self):
        file = self.root / 'file'
        file.write_bytes(b'keep')
        for path, directory, attributes in ((file, False, 0x400), (self.root, True, 0x410),
                                             (file, False, 0x10), (self.root, True, 0x80)):
            with self.subTest(attributes=attributes, directory=directory):
                self.api.attributes = attributes
                before = len(self.api.closed)
                with self.assertRaises(safe_files.UnsafePathError):
                    safe_files._win_open(str(path), directory=directory)
                self.assertEqual(len(self.api.closed), before + 1)
        self.assertEqual(file.read_bytes(), b'keep')

    def test_basic_information_errors_include_path_and_close_handle(self):
        for code in (5, 87):
            with self.subTest(code=code):
                self.api.error = code
                before = len(self.api.closed)
                with self.assertRaises(OSError) as caught:
                    safe_files._win_open(str(self.root), directory=True)
                self.assertEqual(caught.exception.winerror, code)
                self.assertIn(str(self.root), str(caught.exception))
                self.assertEqual(len(self.api.closed), before + 1)

    def test_partial_ancestor_open_failure_closes_all_acquired_handles(self):
        self.api.error = 87
        self.api.error_at = os.path.realpath(self.root)
        directory = safe_files.SafeDirectory(self.root)
        with self.assertRaises(OSError):
            with directory:
                self.fail('failed validation must not enter the directory')
        self.assertFalse(directory.handles)
        self.assertEqual(set(self.api.closed), set(self.api.paths))
        for handle in self.api.paths:
            with self.assertRaises(OSError):
                os.fstat(handle)

    def test_unexpected_query_exception_closes_handle(self):
        def abort(*args):
            raise RuntimeError('query aborted')

        self.api.GetFileInformationByHandle = WinFunction(abort)
        with self.assertRaisesRegex(RuntimeError, 'query aborted'):
            safe_files._win_open(str(self.root), directory=True)
        self.assertEqual(len(self.api.closed), 1)

    def test_deploy_failure_reports_course_and_error_without_permissions_diagnosis(self):
        (self.root / 'config.js').write_text('var config = {};')
        (self.root / 'media.mp4').write_text('video')
        self.api.error = 87
        ok, message, output = evercam.deploy_evercam_player(str(self.root))
        self.assertFalse(ok)
        self.assertEqual(output, '')
        self.assertIn(str(self.root), message)
        self.assertIn('87', message)
        self.assertNotIn('請檢查檔案權限', message)


@unittest.skipUnless(os.name == 'nt', 'requires native Windows API')
class NativeWindowsInformation(unittest.TestCase):
    def test_native_information_buffer_has_windows_abi_layout(self):
        original_byref = ctypes.byref
        captured = []

        def capture(info):
            captured.append(info)
            return original_byref(info)

        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(ctypes, 'byref', side_effect=capture):
                handle, close = safe_files._win_open(temporary, directory=True)
            close(handle)
        self.assertEqual(len(captured), 1)
        info = captured[0]
        self.assertEqual(ctypes.sizeof(info), 52)
        for field, offset in (('attributes', 0), ('creation_time', 4),
                              ('access_time', 12), ('write_time', 20),
                              ('volume_serial', 28), ('size_high', 32),
                              ('size_low', 36), ('links', 40),
                              ('index_high', 44), ('index_low', 48)):
            self.assertEqual(getattr(type(info), field).offset, offset)

    def test_native_handle_write_read_and_deploy(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with safe_files.SafeDirectory(root) as directory:
                directory.write_bytes('config.js', b'var config = {};')
                directory.write_bytes('media.mp4', b'video')
                directory.write_bytes('index.html', b'original')
                self.assertEqual(directory.read_bytes('index.html'), b'original')
            ok, message, _ = evercam.deploy_evercam_player(str(root))
            self.assertTrue(ok, message)
            self.assertEqual((root / 'index.evercam-original.html').read_bytes(), b'original')
