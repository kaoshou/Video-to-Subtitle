import tempfile
import unittest
from pathlib import Path
from subtitle_languages import output_language, subtitle_language, matching_media


class LanguageTests(unittest.TestCase):
    def test_output_precedence_and_unknown(self):
        self.assertEqual(output_language('ja', task='translate', force_zh_tw=True), 'en')
        self.assertEqual(output_language('zh', force_zh_tw=True), 'zh-TW')
        self.assertEqual(output_language('zh'), 'zh')
        self.assertEqual(output_language('unknown'), 'und')
        self.assertEqual(output_language(None), 'und')

    def test_collision_and_video_title_are_not_languages(self):
        self.assertEqual(subtitle_language('movie.zh-TW_2.srt', 'movie.mp4'), 'zh-TW')
        self.assertEqual(subtitle_language('movie.en.srt', 'movie.en.mp4'), 'und')
        self.assertEqual(subtitle_language('movie_1.ja.srt', 'movie.mp4'), 'und')

    def test_editor_finds_tagged_media_without_confusing_exact_name(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            video = root / 'lesson.mp4'
            video.touch()
            self.assertEqual(matching_media(root / 'lesson.zh-TW_1.srt'), video)
            exact = root / 'lesson.zh-TW_1.mp4'
            exact.touch()
            self.assertEqual(matching_media(root / 'lesson.zh-TW_1.srt'), exact)
