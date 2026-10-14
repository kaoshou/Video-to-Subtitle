"""Local player launch contracts; OS/browser launches are the external boundary."""
import importlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


class LocalPageOpen(unittest.TestCase):
    def api(self):
        self.assertIsNotNone(importlib.util.find_spec('ui_open'), 'shared local-page opener missing')
        return importlib.import_module('ui_open')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name).resolve() / '中文 課程 #1 100% & {測試}'
        self.folder.mkdir()
        self.page = self.folder / 'index.html'
        self.page.write_text('<!doctype html><title>課程</title>', encoding='utf-8')

    def test_windows_launches_actual_absolute_filename_not_encoded_file_url(self):
        # Break caught: passing a percent-encoded file URI to Windows' URL
        # association instead of opening the actual exported HTML file.
        m = self.api()
        launched = []
        with patch.object(m.sys, 'platform', 'win32'), \
                patch.object(m.os, 'startfile', side_effect=launched.append, create=True), \
                patch.object(m.webbrowser, 'open_new_tab', side_effect=AssertionError('URL handler used')):
            self.assertTrue(m.open_local_page(self.page))
        self.assertEqual(launched, [str(self.page)])

    def test_non_windows_uses_escaped_uri_for_default_browser(self):
        # Break caught: manually concatenated URLs treat # as a fragment or
        # lose spaces/Unicode; no browser name should be forced.
        m = self.api()
        launched = []
        with patch.object(m.sys, 'platform', 'darwin'), \
                patch.object(m.webbrowser, 'open_new_tab', side_effect=lambda url: launched.append(url) or True):
            self.assertTrue(m.open_local_page(self.page))
        self.assertEqual(launched, [self.page.as_uri()])
        self.assertIn('%23', launched[0])
        self.assertIn('100%25', launched[0])

    def test_missing_page_reports_error_without_launching_browser(self):
        m = self.api()
        self.page.unlink()
        errors = []
        with patch.object(m.webbrowser, 'open_new_tab', side_effect=AssertionError('browser launched')), \
                patch('tkinter.messagebox.showerror', side_effect=lambda title, message, **kw: errors.append(message)):
            self.assertFalse(m.open_local_page(self.page))
        self.assertEqual(len(errors), 1)
        self.assertIn('index.html', errors[0])

    def test_windows_launch_failure_reports_original_reason(self):
        m = self.api()
        errors = []
        with patch.object(m.sys, 'platform', 'win32'), \
                patch.object(m.os, 'startfile', side_effect=OSError('file association unavailable'), create=True), \
                patch('tkinter.messagebox.showerror', side_effect=lambda title, message, **kw: errors.append(message)):
            self.assertFalse(m.open_local_page(self.page))
        self.assertIn('file association unavailable', errors[0])

    def test_browser_refusal_is_not_reported_as_success(self):
        m = self.api()
        errors = []
        with patch.object(m.sys, 'platform', 'linux'), \
                patch.object(m.webbrowser, 'open_new_tab', return_value=False), \
                patch('tkinter.messagebox.showerror', side_effect=lambda title, message, **kw: errors.append(message)):
            self.assertFalse(m.open_local_page(self.page))
        self.assertEqual(len(errors), 1)
        self.assertIn(str(self.page), errors[0])


if __name__ == '__main__': unittest.main()
