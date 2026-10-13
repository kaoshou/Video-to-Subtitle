"""Exercise real subtitle output; only the expensive recognizer is substituted."""
import contextlib
import io
import json
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import transcriber


SIMPLIFIED = '这是软件与数据库课程 我们学习多语言字幕转换与自动化测试'
TRADITIONAL = '這是軟體與資料庫課程 我們學習多語言字幕轉換與自動化測試'


class RecordedRecognizer:
    def __init__(self, text=SIMPLIFIED, words=False):
        self.text = text
        self.words = words

    def transcribe(self, path, **options):
        words = [SimpleNamespace(word=char, start=55.25 + index * .1, end=55.25 + (index + 1) * .1)
                 for index, char in enumerate(self.text)] if self.words else None
        segment = SimpleNamespace(text=self.text, start=55.25, end=63.15, words=words)
        return iter([segment]), SimpleNamespace(duration=120, language='zh', language_probability=1)


class TraditionalChineseOutput(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='vts-traditional-test-')
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.worker = transcriber.SubtitleTranscriber()
        self.worker.model = RecordedRecognizer()

    def output(self, **options):
        with contextlib.redirect_stdout(io.StringIO()):
            path = self.worker.run(str(self.folder / 'media.mp4'),
                                   clean_punctuation='none', spacing=False, **options)
        return Path(path).read_text(encoding='utf-8')

    def test_unavailable_converter_stops_instead_of_writing_simplified_subtitle(self):
        with patch.object(transcriber, 'converter', None):
            with self.assertRaisesRegex(RuntimeError, '繁體'):
                self.output(force_zh_tw=True)
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_unavailable_converter_does_not_load_a_model(self):
        self.worker.model = None
        def unexpected_load(*args, **kwargs):
            self.fail('A missing required converter must be detected before loading a model')
        self.worker.load_model = unexpected_load
        with patch.object(transcriber, 'converter', None):
            with self.assertRaisesRegex(RuntimeError, '繁體'):
                self.output(force_zh_tw=True)

    def test_unchecked_option_preserves_original_text_without_converter(self):
        with patch.object(transcriber, 'converter', None):
            self.assertIn(SIMPLIFIED, self.output(force_zh_tw=False, max_chars=100))

    def test_english_translation_is_not_blocked_by_missing_chinese_converter(self):
        self.worker.model = RecordedRecognizer('English translation.')
        with patch.object(transcriber, 'converter', None):
            self.assertIn('English translation.', self.output(force_zh_tw=True, task='translate'))

    def test_all_output_formats_convert_even_with_conflicting_prompt(self):
        self.assertIsNotNone(transcriber.converter, 'The test environment must include working OpenCC')
        for format in ('srt', 'vtt', 'txt', 'tsv', 'json'):
            with self.subTest(format=format):
                text = self.output(force_zh_tw=True, output_format=format, max_chars=100,
                                   initial_prompt='请用简体中文输出。', hotwords='Whisper,OpenAI')
                self.assertIn(TRADITIONAL, text)
                self.assertNotIn(SIMPLIFIED, text)
                if format == 'json':
                    self.assertEqual(json.loads(text)[0]['start'], 55.25)
                elif format == 'srt':
                    self.assertIn('00:00:55,250 --> 00:01:03,150', text)

    def test_long_segments_convert_with_or_without_word_timestamps(self):
        for words in (False, True):
            with self.subTest(words=words):
                self.worker.model = RecordedRecognizer(words=words)
                text = self.output(force_zh_tw=True, max_chars=25)
                self.assertIn('這是軟體與資料庫課程', text)
                for char in '这软与据课们学语换动测':
                    self.assertNotIn(char, text)

    def test_enabled_conversion_is_reported_in_task_log(self):
        logs = []
        self.output(force_zh_tw=True, log_callback=logs.append)
        self.assertTrue(any('繁體' in line and 'OpenCC' in line for line in logs), logs)

    def test_bad_opencc_initialization_keeps_non_chinese_transcription_available(self):
        def broken_converter(*args, **kwargs):
            raise RuntimeError('missing test dictionary')
        with patch.dict('sys.modules', {'opencc': SimpleNamespace(OpenCC=broken_converter)}), \
                self.assertLogs(level='WARNING'):
            try:
                module = runpy.run_path(str(Path(transcriber.__file__)))
            except RuntimeError as error:
                self.fail(f'Optional converter initialization must not crash application startup: {error}')
        self.assertIsNone(module['converter'])
        worker = module['SubtitleTranscriber']()
        worker.model = RecordedRecognizer('English recording.')
        with contextlib.redirect_stdout(io.StringIO()):
            path = worker.run(str(self.folder / 'english.mp4'), force_zh_tw=False)
        self.assertIn('English recording.', Path(path).read_text())
        with self.assertRaisesRegex(RuntimeError, 'missing test dictionary'), \
                contextlib.redirect_stdout(io.StringIO()):
            worker.run(str(self.folder / 'required.mp4'), force_zh_tw=True)

    def test_command_line_smoke_runs_traditional_conversion_not_only_web_export(self):
        # The known web-export flag keeps the old CLI headless, so this test
        # fails on its missing conversion check rather than launching a GUI.
        result = subprocess.run(
            [sys.executable, 'SubtitleTranscriber.py', '--test-traditional-chinese', '--test-web-export'],
            cwd=Path(transcriber.__file__).parent, capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Traditional Chinese subtitle smoke passed', result.stdout)

    def test_conversion_failure_is_identified_instead_of_continuing_the_batch(self):
        class BrokenDictionary:
            def convert(self, text):
                raise RuntimeError('dictionary unavailable during conversion')
        with patch.object(transcriber, 'converter', BrokenDictionary()):
            try:
                self.output(force_zh_tw=True)
            except RuntimeError as error:
                self.assertIsInstance(error, transcriber.TraditionalChineseConversionError)
                self.assertIn('繁體', str(error))
            else:
                self.fail('A failed conversion must not report a successful subtitle')

    def test_headless_smoke_writes_success_report(self):
        report = self.folder / 'smoke-report.json'
        result = subprocess.run(
            [sys.executable, 'SubtitleTranscriber.py', '--test-traditional-chinese',
             '--test-report', str(report)],
            cwd=Path(transcriber.__file__).parent, capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(report.is_file(), 'Windowed builds need a report when stdout is unavailable')
        self.assertTrue(json.loads(report.read_text())['success'])

    def test_headless_smoke_records_real_failure_even_without_stdio(self):
        report = self.folder / 'failure-report.json'
        command = (
            "import sys,runpy,transcriber; transcriber.converter=None; "
            "sys.stdout=None; sys.stderr=None; "
            "sys.argv=['SubtitleTranscriber.py','--test-traditional-chinese','--test-report',sys.argv[1]]; "
            "runpy.run_path('SubtitleTranscriber.py',run_name='__main__')"
        )
        result = subprocess.run([sys.executable, '-c', command, str(report)],
                                cwd=Path(transcriber.__file__).parent, timeout=120)
        self.assertEqual(result.returncode, 1)
        self.assertTrue(report.is_file(), 'A headless failure must leave actionable diagnostics')
        data = json.loads(report.read_text())
        self.assertFalse(data['success'])
        self.assertIn('繁體', data['error'])
        self.assertIn('TraditionalChineseConversionError', data['traceback'])


if __name__ == '__main__':
    unittest.main()
