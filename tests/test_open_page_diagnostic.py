"""Frozen/no-console page-open diagnostics must leave actionable reports."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class OpenPageDiagnosticTests(unittest.TestCase):
    def probe(self, folder, launch, path):
        report = folder / 'report.json'
        command = (
            "import sys,runpy,webbrowser; "
            f"webbrowser.open_new_tab=lambda url: {launch}; "
            "sys.stdout=None;sys.stderr=None; "
            "sys.argv=['SubtitleTranscriber.py','--test-open-page',sys.argv[1],"
            "'--test-report',sys.argv[2],'--test-web-export']; "
            "runpy.run_path('SubtitleTranscriber.py',run_name='__main__')"
        )
        result = subprocess.run([sys.executable, '-c', command, str(path), str(report)],
                                cwd=Path(__file__).resolve().parents[1], timeout=120)
        self.assertTrue(report.is_file(), 'A windowed diagnostic must write its report')
        return result, json.loads(report.read_text(encoding='utf-8'))

    @unittest.skipIf(sys.platform == 'win32', 'The real Windows boundary is tested by the CI browser smoke')
    def test_success_without_standard_streams(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            page = folder / '測試 # %.html'
            page.write_text('<html>fixture</html>', encoding='utf-8')
            result, report = self.probe(folder, 'True', page)
            self.assertEqual(result.returncode, 0)
            self.assertTrue(report['success'])

    @unittest.skipIf(sys.platform == 'win32', 'The real Windows boundary is tested by the CI browser smoke')
    def test_browser_refusal_is_nonblocking_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            page = folder / 'index.html'
            page.write_text('<html>fixture</html>', encoding='utf-8')
            result, report = self.probe(folder, 'False', page)
            self.assertEqual(result.returncode, 1)
            self.assertFalse(report['success'])
            self.assertIn('預設瀏覽器', report['error'])

    def test_missing_page_is_nonblocking_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            result, report = self.probe(folder, 'True', folder / 'missing.html')
            self.assertEqual(result.returncode, 1)
            self.assertFalse(report['success'])
            self.assertIn('找不到網頁', report['error'])
