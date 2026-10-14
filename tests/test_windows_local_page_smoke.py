import importlib
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
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

    def test_browser_inherits_runner_profile_with_python_removed(self):
        smoke = self.module()
        self.assertTrue(hasattr(smoke, '_local_page_environment'),
                        'Local-page runtime environment must preserve the browser profile')
        source = {'SystemRoot': r'C:\Windows', 'PATH': r'C:\Python;C:\ffmpeg',
                  'PYTHONHOME': r'C:\Python', 'PYTHONPATH': r'C:\site-packages',
                  'LOCALAPPDATA': r'C:\Users\runneradmin\AppData\Local'}
        environment = smoke._local_page_environment(source)
        self.assertEqual(environment['LOCALAPPDATA'], r'C:\Users\runneradmin\AppData\Local')
        self.assertEqual(environment['PATH'], str(Path(r'C:\Windows') / 'System32'))
        self.assertNotIn('PYTHONHOME', environment)
        self.assertNotIn('PYTHONPATH', environment)
        self.assertEqual(source['PATH'], r'C:\Python;C:\ffmpeg')

    def test_closes_sentinel_before_removing_its_html_directory(self):
        smoke = self.module()
        temporary_directory = tempfile.TemporaryDirectory
        state = {'closed': False}
        test = self

        class HtmlTemporaryDirectory:
            def __init__(self, **kwargs):
                self.directory = temporary_directory(**kwargs)

            def __enter__(self):
                return self.directory.__enter__()

            def __exit__(self, *args):
                try:
                    test.assertTrue(state['closed'], 'HTML cleanup preceded browser WM_CLOSE')
                finally:
                    self.directory.__exit__(*args)

        class Desktop:
            def windows(self):
                return [] if state['closed'] else [
                    {'hwnd': 42, 'pid': 4242, 'process_name': 'msedge.exe', 'title': state['title']}]

            def responsive(self, hwnd):
                return True

            def screenshot(self, hwnd, path):
                pass

            def close_sentinel(self, window, sentinel):
                test.assertTrue(state['page'].is_file(), 'Browser closed after HTML removal')
                test.assertIn(sentinel, window['title'])
                state['closed'] = True
                return True

        def open_page(command, **kwargs):
            page = Path(command[command.index('--test-open-page') + 1])
            state['page'] = page
            state['title'] = page.read_text(encoding='utf-8').split('<title>')[1].split('</title>')[0]
            report = Path(command[command.index('--test-report') + 1])
            report.write_text('{"success": true}', encoding='utf-8')
            return SimpleNamespace(returncode=0)

        with temporary_directory() as temporary:
            executable = Path(temporary) / 'fixture.exe'
            executable.touch()
            report_dir = Path(temporary) / 'reports'
            with patch.object(smoke.sys, 'platform', 'win32'), patch.dict(
                    smoke.os.environ, {'GITHUB_ACTIONS': 'true'}), patch.object(
                    smoke, '_WindowsDesktop', Desktop), patch.object(
                    smoke, '_warm_edge', return_value=({'available': False}, None)), patch.object(
                    smoke.subprocess, 'run', side_effect=open_page), patch.object(
                    smoke.tempfile, 'TemporaryDirectory', HtmlTemporaryDirectory):
                result = smoke.smoke_local_page(executable, report_dir)
            self.assertTrue(result['success'])
            self.assertFalse(state['page'].exists())
            self.assertTrue(json.loads((report_dir / 'local-page-smoke.json').read_text())['success'])


if __name__ == '__main__':
    unittest.main()
