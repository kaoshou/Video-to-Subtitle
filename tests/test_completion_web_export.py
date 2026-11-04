"""One-click completion export uses real media and the safe package writer."""
import tempfile
import unittest
from pathlib import Path

from test_web_export_inputs import make_video


class CompletionExport(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.video = self.root / '示範課程.mp4'
        make_video(self.video)
        self.subtitle = self.root / '示範課程.srt'
        self.subtitle.write_text('1\n00:00:00,000 --> 00:00:00,900\n你好\n', encoding='utf-8')

    def export(self, **kwargs):
        import web_export_dialog as api
        self.assertTrue(hasattr(api, 'export_completed_video'), 'completion has no direct export path')
        return api.export_completed_video(self.video, self.subtitle, 'zh-TW',
            app_version='test', progress=lambda *args: None, cancelled=lambda: False, **kwargs)

    def test_creates_complete_package_beside_source_without_overwriting_existing(self):
        first = self.export()
        second = self.export()
        self.assertEqual(first.folder, self.root.resolve() / '示範課程-web')
        self.assertEqual(second.folder, self.root.resolve() / '示範課程-web-2')
        self.assertTrue(first.index_path.is_file())
        self.assertEqual((first.folder / 'media.mp4').read_bytes(), self.video.read_bytes())
        from web_export import load_package
        self.assertEqual(load_package(first.folder).request.default_subtitle, 'zh-TW')
        self.assertEqual(self.subtitle.read_text(encoding='utf-8').splitlines()[-1], '你好')

    def test_generated_subtitle_wins_and_other_languages_are_included(self):
        (self.root / '示範課程.en.srt').write_text('1\n00:00:00,000 --> 00:00:00,900\nHello\n', encoding='utf-8')
        (self.root / '示範課程.zh-TW.vtt').write_text('WEBVTT\n\n00:00.000 --> 00:00.900\n舊字幕\n', encoding='utf-8')
        result = self.export()
        from web_export import load_package
        request = load_package(result.folder).request
        self.assertEqual({t.language for t in request.subtitles}, {'zh-TW', 'en'})
        self.assertIn('你好', (result.folder / 'media.zh-TW.srt').read_text(encoding='utf-8'))

    def test_invalid_subtitle_still_blocks_export(self):
        self.subtitle.write_text('broken', encoding='utf-8')
        with self.assertRaises(ValueError):
            self.export()
        self.assertFalse((self.root / '示範課程-web').exists())

    def test_detected_language_survives_numbered_output_and_one_click_export(self):
        from web_export_dialog import export_completed_video
        from web_export import load_package
        tagged = self.subtitle.with_name('示範課程.ja_1.srt')
        self.subtitle.rename(tagged)
        result = export_completed_video(self.video, tagged, '', app_version='test',
            progress=lambda *args: None, cancelled=lambda: False)
        request = load_package(result.folder).request
        self.assertEqual(request.default_subtitle, 'ja')
        self.assertEqual([t.language for t in request.subtitles], ['ja'])
        self.assertTrue((result.folder / 'media.ja.srt').is_file())

    def test_compatibility_warning_preserves_the_full_subtitle_without_prompting(self):
        self.subtitle.write_text('1\n00:00:00,000 --> 00:00:05,000\n保留完整時間軸\n', encoding='utf-8')
        result = self.export()
        self.assertIn('00:00:05,000', (result.folder / 'media.zh-TW.srt').read_text(encoding='utf-8'))

    def test_cancelled_export_does_not_publish_a_folder(self):
        from web_export_dialog import export_completed_video
        with self.assertRaises(InterruptedError):
            export_completed_video(self.video, self.subtitle, 'zh-TW', app_version='test',
                progress=lambda *args: None, cancelled=lambda: True)
        self.assertFalse((self.root / '示範課程-web').exists())

    def test_existing_symlink_destination_is_not_followed_or_overwritten(self):
        destination = self.root / '別的資料'
        destination.mkdir()
        sentinel = destination / 'index.html'
        sentinel.write_text('不可覆寫', encoding='utf-8')
        try:
            (self.root / '示範課程-web').symlink_to(destination, target_is_directory=True)
        except OSError:
            self.skipTest('symlinks unavailable')
        result = self.export()
        self.assertEqual(result.folder.name, '示範課程-web-2')
        self.assertEqual(sentinel.read_text(encoding='utf-8'), '不可覆寫')
