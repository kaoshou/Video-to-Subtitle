"""Native widget geometry and file-drop integration; no speech models needed."""
import os
from pathlib import Path
import tempfile
import types
import unittest


@unittest.skipUnless(os.environ.get('VTS_RUN_GUI_TESTS') == '1', 'requires native GUI session')
class DesktopUI(unittest.TestCase):
    def setUp(self):
        import customtkinter as ctk
        from SubtitleTranscriber import EverCamConverterDialog
        self.ctk = ctk
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = ctk.CTk()
        self.errors = []
        self.root.report_callback_exception = lambda *error: self.errors.append(error)
        self.addCleanup(self.cleanup_root)
        self.dialog = EverCamConverterDialog(self.root)
        self.root.update()

    def cleanup_root(self):
        for timer in self.root.tk.call('after', 'info'):
            self.root.tk.call('after', 'cancel', timer)
        self.root.destroy()
        self.ctk.set_widget_scaling(1)
        self.ctk.set_window_scaling(1)

    def widgets(self, parent):
        for widget in parent.winfo_children():
            yield widget
            yield from self.widgets(widget)

    def assert_buttons_visible(self, top, texts):
        buttons = {w.cget('text'): w for w in self.widgets(top)
                   if isinstance(w, self.ctk.CTkButton)}
        for text in texts:
            widget = buttons[text]
            self.assertTrue(widget.winfo_ismapped(), text)
            self.assertGreaterEqual(widget.winfo_width(), widget.winfo_reqwidth() - 2, text)
            self.assertLessEqual(widget.winfo_rootx() + widget.winfo_width(),
                                 top.winfo_rootx() + top.winfo_width(), text)
            self.assertLessEqual(widget.winfo_rooty() + widget.winfo_height(),
                                 top.winfo_rooty() + top.winfo_height(), text)

    def course(self):
        course = Path(self.temp.name) / ('很長的中文課程路徑 ' * 6 + '{測試}')
        course.mkdir()
        (course / 'config.js').write_text('var config = {};', encoding='utf-8')
        (course / 'media.mp4').touch()
        return course

    def test_evercam_toolbar_and_card_actions_fit_constrained_high_dpi_window(self):
        dialog = self.dialog
        dialog.courses.append(str(self.course()))
        dialog.refresh_list()
        for scale in (1, 1.25, 1.5, 2):
            with self.subTest(scale=scale):
                self.ctk.set_widget_scaling(scale)
                self.ctk.set_window_scaling(scale)
                dialog.top.geometry('680x530')
                self.root.update()
                self.assertEqual(len(self.errors), 0, repr(self.errors[:1]))
                self.assert_buttons_visible(dialog.top, ['📁 選擇課程資料夾...', '🔍 批次掃描母目錄...',
                    '清空', '轉換網頁', '預覽', '目錄', '✕', '🚀 一鍵轉換全部的 EverCam 網頁', '關閉'])

    def test_evercam_drop_resolves_file_and_reports_unsupported_input(self):
        course = self.course()
        event = types.SimpleNamespace(data=self.root.tk.call('list', str(course / 'media.mp4')))
        self.dialog.on_drop(event)
        self.assertEqual(self.dialog.courses, [str(course)])
        ordinary = Path(self.temp.name) / '普通影片.mp4'
        ordinary.touch()
        self.dialog.on_drop(types.SimpleNamespace(data=self.root.tk.call('list', str(ordinary))))
        self.assertEqual(self.dialog.courses, [str(course)])
        self.assertIn('EverCam', self.dialog.drop_hint.cget('text'))
        self.assertIn('未', self.dialog.drop_hint.cget('text'))

    def test_drop_binding_reaches_nested_source_controls(self):
        from web_export_dialog import WebExportDialog
        dialog = WebExportDialog(self.root, app_version='test')
        self.root.update()
        # This sends a Tcl DnD event through the actual child label binding.
        # It verifies registration/dispatch, not an OS drag gesture.
        self.assertTrue(dialog.drop_available)
        target = dialog.media_info._label
        self.assertTrue(target.tk.call('bind', str(target), '<<Drop>>'))
        target.tk.call('event', 'generate', str(target), '<<Drop>>', '-data', '{missing.txt}')
        self.root.update()
        self.assertTrue(dialog.notice_error)
        self.assertIsNone(dialog.state.video)
        subtitle = Path(self.temp.name) / '課程.en.srt'
        subtitle.write_text('1\n00:00:00,000 --> 00:00:00,500\n字幕\n', encoding='utf-8')
        dialog.add_track(subtitle, 'en')
        dialog.refresh_languages()
        labels = [w for w in self.widgets(dialog.summary_tracks) if isinstance(w, self.ctk.CTkLabel)]
        self.assertTrue(labels)
        self.assertTrue(labels[-1]._label.tk.call('bind', str(labels[-1]._label), '<<Drop>>'))

    def test_standalone_drop_video_discovers_subtitles_and_rejects_multiple_videos(self):
        from web_export_dialog import WebExportDialog
        from test_web_export_inputs import make_video
        dialog = WebExportDialog(self.root, app_version='test')
        video = Path(self.temp.name) / '課程 {中文字幕}.mp4'
        make_video(video)
        video.with_suffix('.srt').write_text('1\n00:00:00,000 --> 00:00:00,500\n字幕\n', encoding='utf-8')
        dialog.on_drop(types.SimpleNamespace(data=self.root.tk.call('list', str(video))))
        self.assertEqual(dialog.state.video, video)
        self.assertEqual([t.path for t in dialog.state.tracks], [video.with_suffix('.srt')])
        dialog.on_drop(types.SimpleNamespace(data=self.root.tk.call('list', str(video))))
        self.assertIn('處理', dialog.notice)
        dialog.job.thread.join(timeout=10)
        dialog.poll()
        dialog.on_drop(types.SimpleNamespace(data=self.root.tk.call('list', str(video), str(video))))
        self.assertTrue(dialog.notice_error)
        self.assertIn('一個', dialog.notice)

    def test_readable_chinese_font_and_theme_follow_appearance(self):
        from ui_theme import install_theme
        install_theme()
        label = self.ctk.CTkLabel(self.root, text='繁體中文字幕')
        self.assertGreaterEqual(label.cget('font').cget('size'), 13)
        self.assertNotEqual(label.cget('font').cget('family'), 'Arial')
        self.ctk.set_appearance_mode('Dark')
        self.assertEqual(self.root.cget('fg_color')[1], '#171D28')
        self.ctk.set_appearance_mode('Light')

    def test_sharing_error_keeps_actions_visible_and_details_copyable(self):
        from web_export_dialog import WebExportDialog
        dialog = WebExportDialog(self.root, app_version='test')
        error = PermissionError('very long locked path ' + '中文路徑' * 400)
        error.winerror = 32
        error.staging_path = Path(self.temp.name) / ('暫存' * 60)
        def fail(progress, cancelled):
            raise error
        dialog.run_job(fail, lambda result: None)
        dialog.job.thread.join(timeout=5)
        dialog.poll()
        self.root.update()
        self.assertIn('占用', dialog.notice)
        self.assertLess(len(dialog.notice), 180)
        self.assertNotIn('very long', dialog.notice)
        self.assertFalse(dialog.error_details.winfo_manager())
        dialog.details_button.invoke()
        self.root.update()
        self.assertIn(str(error.staging_path), dialog.error_details.get('1.0', 'end'))
        self.assertEqual(dialog.error_details.cget('state'), 'disabled')
        self.assert_buttons_visible(dialog.top, [dialog.create_button.cget('text'), '關閉'])

    def test_standalone_actions_fit_with_long_paths_at_supported_scales(self):
        from web_export_dialog import WebExportDialog
        dialog = WebExportDialog(self.root, app_version='test')
        dialog.variables['parent'].set('/' + '中文路徑很長/' * 60)
        dialog.target_changed()
        for scale in (1, 1.25, 1.5, 2):
            with self.subTest(scale=scale):
                self.ctk.set_widget_scaling(scale)
                self.ctk.set_window_scaling(scale)
                dialog.top.geometry('720x640')
                self.root.update()
                self.assertEqual(len(self.errors), 0, repr(self.errors[:1]))
                self.assert_buttons_visible(dialog.top, [dialog.create_button.cget('text'), '關閉', '編輯既有網頁…'])

    def test_main_and_editor_keep_controls_and_chinese_table_readable(self):
        from unittest.mock import patch
        import SubtitleTranscriber as desktop
        # Suppress only persistent settings writes and network update checks.
        self.cleanup_root()
        with patch.object(desktop.App, 'load_settings'), patch.object(desktop.App, 'check_for_updates'), patch.object(desktop.App, 'save_settings'):
            self.root = desktop.App()
            self.root.report_callback_exception = lambda *error: self.errors.append(error)
            self.root.update()
            self.assertFalse(self.root.adv_settings_frame.winfo_manager())
            self.assertTrue(self.root.entry_prompt.winfo_ismapped())
            self.assertTrue(self.root.entry_hotwords.winfo_ismapped())
            self.assertTrue(self.root.btn_evercam_tool.winfo_ismapped())
            self.root.toggle_advanced_settings()
            for scale in (1, 1.25, 1.5, 2):
                self.ctk.set_widget_scaling(scale)
                self.ctk.set_window_scaling(scale)
                self.root.geometry('760x800')
                self.root.update()
                self.assert_buttons_visible(self.root, ['開始轉錄 (Start)', '取消 (Cancel)', '網頁播放器'])
                for widget in (self.root.chk_word_ts, self.root.chk_spacing, self.root.chk_case_corr, self.root.chk_vad, self.root.entry_max_chars):
                    self.assertGreaterEqual(widget.winfo_width(), widget.winfo_reqwidth() - 2)
                    self.assertLessEqual(widget.winfo_rootx() + widget.winfo_width(), self.root.winfo_rootx() + self.root.winfo_width())
            self.ctk.set_widget_scaling(1)
            self.ctk.set_window_scaling(1)
            subtitle = Path(self.temp.name) / '字幕.srt'
            subtitle.write_text('1\n00:00:00,000 --> 00:00:00,500\n中文字幕\n', encoding='utf-8')
            editor = desktop.SubtitleEditorWindow(self.root, str(subtitle))
            self.root.update()
            self.assertEqual(len(editor.tree.get_children()), 1)
            style = desktop.ttk.Style(self.root)
            self.assertIn('PingFang' if desktop.platform.system() == 'Darwin' else 'JhengHei' if desktop.platform.system() == 'Windows' else 'Noto', str(style.lookup('Treeview', 'font')))
            self.ctk.set_appearance_mode('Dark')
            self.root.update()
            self.assertEqual(style.lookup('Treeview', 'background'), '#222D3D')
            self.ctk.set_appearance_mode('Light')
            self.root.show_about()
            self.root.update()
            self.assert_buttons_visible(self.root.about_window, ['檢查更新', '關閉'])
            long_subtitle = Path(self.temp.name) / ('這是很長的中文字幕檔案名稱' * 3 + '.srt')
            long_subtitle.write_text(subtitle.read_text(encoding='utf-8'), encoding='utf-8')
            video = Path(self.temp.name) / '課程.mp4'
            video.touch()
            self.root.show_completion_dialog(1, [str(long_subtitle)], {str(long_subtitle): str(video)})
            self.root.update()
            completion = next(w for w in self.root.winfo_children() if isinstance(w, self.ctk.CTkToplevel) and w.title() == '轉錄任務完成')
            self.assert_buttons_visible(completion, ['開啟字幕', '開啟目錄', '字幕校對', '匯出字幕網頁', '關閉'])
            self.assertEqual(len(self.errors), 0, repr(self.errors[:1]))


if __name__ == '__main__':
    unittest.main()
