import importlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


class WindowsLocalPageSmokeTests(unittest.TestCase):
    def module(self):
        name = 'scripts.smoke_windows_local_page'
        self.assertIsNotNone(importlib.util.find_spec(name), 'Local page smoke harness is missing')
        return importlib.import_module(name)

    def test_refuses_other_platforms_and_non_ci_without_creating_reports(self):
        smoke = self.module()
        with tempfile.TemporaryDirectory() as temporary:
            report_dir = Path(temporary) / 'reports'
            for platform, github in (('darwin', 'true'), ('win32', 'false'), ('win32', 'TRUE')):
                with self.subTest(platform=platform, github=github):
                    with patch.object(smoke.sys, 'platform', platform), patch.dict(
                            smoke.os.environ, {'GITHUB_ACTIONS': github}):
                        with self.assertRaisesRegex(RuntimeError, 'disposable Windows GitHub CI'):
                            smoke.smoke_local_page(Path(temporary) / 'app.exe', report_dir)
                    self.assertFalse(report_dir.exists())

    def test_application_report_requires_true_boolean_and_successful_exit(self):
        smoke = self.module()
        with tempfile.TemporaryDirectory() as temporary:
            report = Path(temporary) / 'app.json'
            report.write_text('{"success": true}', encoding='utf-8')
            self.assertEqual(smoke._read_open_report(report, 0), {'success': True})
            for payload, exit_code in (({'success': False}, 0), ({'success': 'true'}, 0),
                                       ({'success': 1}, 0), ({}, 0), ({'success': True}, 1),
                                       ([], 0)):
                with self.subTest(payload=payload, exit_code=exit_code):
                    report.write_text(json.dumps(payload), encoding='utf-8')
                    with self.assertRaises(RuntimeError):
                        smoke._read_open_report(report, exit_code)

    def test_missing_and_malformed_reports_cannot_pass(self):
        smoke = self.module()
        with tempfile.TemporaryDirectory() as temporary:
            report = Path(temporary) / 'app.json'
            with self.assertRaises(RuntimeError):
                smoke._read_open_report(report, 0)
            report.write_text('{not json', encoding='utf-8')
            with self.assertRaises(RuntimeError):
                smoke._read_open_report(report, 0)

    def test_title_requires_unique_sentinel_and_real_browser_process(self):
        smoke = self.module()
        sentinel = 'VTS_LOCAL_PAGE_1234'
        self.assertTrue(smoke._is_browser_page(sentinel + ' - Microsoft Edge', 'msedge.exe', sentinel))
        self.assertTrue(smoke._is_browser_page(sentinel + ' - Mozilla Firefox', 'FIREFOX.EXE', sentinel))
        self.assertFalse(smoke._is_browser_page('Welcome to Microsoft Edge', 'msedge.exe', sentinel))
        self.assertFalse(smoke._is_browser_page(sentinel, 'notepad.exe', sentinel))
        self.assertFalse(smoke._is_browser_page('VTS_LOCAL_PAGE_other', 'chrome.exe', sentinel))


if __name__ == '__main__':
    unittest.main()
