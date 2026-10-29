"""Native widget geometry and file-drop integration; no speech models needed."""
import os
import gc
from pathlib import Path
import tempfile
import types
import time
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
        self.exports = []
        self.errors = []
        self.root.report_callback_exception = lambda *error: self.errors.append(error)
        self.addCleanup(self.cleanup_root)
        self.dialog = EverCamConverterDialog(self.root)
        self.root.update()

    def cleanup_root(self):
        # Native Tk owns interpreter resources on its creating thread. Join
        # workers and collect destroyed interpreter cycles here, before a
        # later test's worker can trigger collection on a background thread.
        for dialog in self.exports:
            if dialog.job:
                dialog.job.cancel()
                dialog.job.thread.join(timeout=5)
                self.assertFalse(dialog.job.thread.is_alive())
        for timer in self.root.tk.call('after', 'info'):
            self.root.tk.call('after', 'cancel', timer)
        self.root.destroy()
        self.dialog = None
        self.root = None
        self.exports.clear()
        dialog = None
        gc.collect()
        self.ctk.set_widget_scaling(1)
        self.ctk.set_window_scaling(1)

    def export_dialog(self):
        from web_export_dialog import WebExportDialog
        dialog = WebExportDialog(self.root, app_version='test')
        self.exports.append(dialog)
        return dialog

    def main_app(self):
        from unittest.mock import patch
        import SubtitleTranscriber as desktop
        self.cleanup_root()
        # Leave controls and layout real; suppress only user settings/network.
        for name in ('load_settings', 'save_settings', 'check_for_updates'):
            guard = patch.object(desktop.App, name)
            guard.start()
            self.addCleanup(guard.stop)
        self.root = desktop.App()
        self.root.report_callback_exception = lambda *error: self.errors.append(error)
        self.root.update()
        return self.root

    def settle_scaling(self):
        # CTk restores native window-size constraints after one second.
        deadline = time.monotonic() + 1.2
        while time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)

    def test_missing_traditional_converter_stops_batch_before_model_initialization(self):
        from unittest.mock import patch
        import SubtitleTranscriber as desktop
        import transcriber
        app = self.main_app()
        app.file_list = [str(Path(self.temp.name) / 'media.mp4')]
        app.zh_tw_var.set(True)
        app.translate_en_var.set(False)
        errors = []
        with patch.object(transcriber, 'converter', None), \
                patch.object(desktop.messagebox, 'showerror', side_effect=lambda title, text: errors.append(text)), \
                patch.object(desktop.SubtitleTranscriber, 'load_model', side_effect=RuntimeError('unexpected model loading')):
            app.process_batch()
        self.root.update()
        self.assertIsNone(app.transcriber, 'Missing converter must stop before model initialization')
        self.assertTrue(any('繁體' in text and 'OpenCC' in text for text in errors), errors)
        self.assertFalse(list(Path(self.temp.name).glob('*.srt')))

    def test_batch_size_requires_enable_and_supported_backend(self):
        app = self.main_app()
        self.assertEqual(app.combo_batch_size.cget('state'), 'disabled')

        app.batch_acceleration_var.set(True)
        app.update_batch_controls()
        self.assertEqual(app.combo_batch_size.cget('state'), 'normal')
        app.device_var.set('mlx')
        self.root.update()
        self.assertEqual(app.combo_batch_size.cget('state'), 'disabled')
        self.assertIn('MLX', app.batch_hint.cget('text'))
        app.device_var.set('cpu')
        app.vad_filter_var.set(False)
        self.root.update()
        self.assertEqual(app.combo_batch_size.cget('state'), 'disabled')
        app.vad_filter_var.set(True)
        self.root.update()
        self.assertEqual(app.combo_batch_size.cget('state'), 'normal')
        app.batch_acceleration_var.set(False)
        app.update_batch_controls()
        self.assertEqual(app.combo_batch_size.cget('state'), 'disabled')

    def test_selected_cpu_threads_reach_model_initialization(self):
        from unittest.mock import patch
        import SubtitleTranscriber as desktop
        app = self.main_app()
        app.file_list = [str(Path(self.temp.name) / 'media.mp4')]
        with patch.object(desktop.SubtitleTranscriber, 'load_model', side_effect=RuntimeError('stop before inference')), \
                patch.object(desktop.messagebox, 'showerror'):
            app.cpu_threads_var.set('8')
            app.process_batch()
            self.root.update()
            previous = app.transcriber
            self.assertEqual(previous.cpu_threads, 8)
            app.cpu_threads_var.set('16')
            app.process_batch()
            self.root.update()
            self.assertEqual(app.transcriber.cpu_threads, 16)
            self.assertIsNot(app.transcriber, previous)

    def test_main_content_surfaces_remain_distinct_in_both_themes(self):
        # Break caught: the file list or settings inputs disappear into a
        # same-colored parent surface after a palette/layout change.
        app = self.main_app()
        for mode in ('Light', 'Dark'):
            self.ctk.set_appearance_mode(mode)
            self.root.update()
            color = app._apply_appearance_mode
            self.assertNotEqual(color(app.file_rows.cget('fg_color')),
                                color(app.file_frame.cget('fg_color')))
            self.assertGreaterEqual(app.file_rows.cget('border_width'), 1)
            for entry in (app.entry_prompt, app.entry_hotwords):
                self.assertNotEqual(color(entry.cget('fg_color')),
                                    color(app.settings_frame.cget('fg_color')))
        self.ctk.set_appearance_mode('Light')

    def test_installed_settings_save_and_reload_without_writing_app_directory(self):
        # Break caught: App ignores its per-user path, drops Chinese settings,
        # or cannot read settings after an installer replaces its files.
        from unittest.mock import patch
        import SubtitleTranscriber as desktop
        from app_settings import resolve_settings_path
        self.cleanup_root()
        source = Path(self.temp.name) / 'bundle'
        local = Path(self.temp.name) / 'user'
        source.mkdir(); local.mkdir()
        def user_path(_source):
            return resolve_settings_path(source, system='win32', frozen=True,
                                         environ={'LOCALAPPDATA': str(local)})
        with patch.object(desktop, 'resolve_settings_path', side_effect=user_path), \
                patch.object(desktop.App, 'check_for_updates'):
            self.root = desktop.App()
            self.root.update()
            self.root.model_var.set('small')
            self.root.hotwords_var.set('字幕, 研習')
            self.root.batch_acceleration_var.set(True)
            self.root.batch_size_var.set('8')
            self.root.cpu_threads_var.set('8')
            self.root.save_settings()
            self.assertTrue(Path(self.root.config_file).is_file())
            self.assertFalse((source / 'config.json').exists())
            self.cleanup_root()
            source.rmdir(); source.mkdir()
            self.root = desktop.App()
            self.root.update()
            self.assertEqual(self.root.get_clean_model_name(), 'small')
            self.assertEqual(self.root.hotwords_var.get(), '字幕, 研習')
            self.assertTrue(self.root.batch_acceleration_var.get())
            self.assertEqual(self.root.batch_size_var.get(), '8')
            self.assertEqual(self.root.cpu_threads_var.get(), '8')

    def test_opencam_opened_from_homepage_stays_above_home_without_global_topmost(self):
        # Break caught: closing the source picker restores the homepage over
        # an unowned OpenCam window, hiding the tool the user just opened.
        app = self.main_app()
        app.open_web_player()
        self.root.update()
        picker = next(widget for widget in app.winfo_children()
                      if isinstance(widget, self.ctk.CTkToplevel) and widget.title() == '網頁播放器')
        button = next(widget for widget in picker.winfo_children()
                      if isinstance(widget, self.ctk.CTkButton) and widget.cget('text') == 'OpenCam 置入字幕')
        button.invoke()
        self.root.update()
        top = next(widget for widget in app.winfo_children()
                   if isinstance(widget, self.ctk.CTkToplevel) and widget.title() == 'OpenCam 字幕置入')
        self.assertEqual(str(top.transient()), str(app))
        self.assertTrue(top.winfo_viewable())
        self.assertFalse(top.attributes('-topmost'))
        # Simulate the native focus restoration after the picker closes.
        app.lift()
        # Window-server ordering and CTk titlebar focus restoration are async.
        # Observe after their queued events, not before the first native paint.
        deadline = time.monotonic() + 0.3
        while time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.assertTrue(app.tk.call('wm', 'stackorder', top._w, 'isabove', app._w),
                        f"stack={app.tk.call('wm', 'stackorder', app._w)}, focus={app.focus_get()}")

    def test_opencam_null_subtitles_selection_multitrack_and_real_publication(self):
        # Break caught: null subtitles crash rendering or UI commits wrong
        # languages, disables publication or changes the original player.
        import test_opencam_integration as fixtures
        from opencam_dialog import OpenCamSubtitleDialog
        f = fixtures.OpenCamIntegration(); f.setUp()
        self.addCleanup(f.doCleanups)
        original = (f.folder / 'opencam-player.js').read_bytes()
        dialog = OpenCamSubtitleDialog(self.root, folder=f.folder)
        self.addCleanup(lambda: dialog.top.destroy() if dialog.top.winfo_exists() else None)
        self.assertEqual(dialog.submit_button.cget('state'), 'disabled')
        dialog.add_subtitles([f.srt])
        self.root.update()
        self.assertEqual(dialog.submit_button.cget('state'), 'normal')
        dialog.inputs[0][1].set('英文')
        dialog.refresh_action()
        dialog.submit_button.invoke()
        deadline = time.monotonic() + 15
        while dialog.job and time.monotonic() < deadline:
            self.root.update(); time.sleep(0.01)
        self.assertIsNone(dialog.job)
        self.assertIsNotNone(dialog.result, dialog.notice.cget('text'))
        import opencam_integration
        data = opencam_integration.load_project(f.folder).data
        self.assertEqual(data['subtitles']['tracks'][0]['language'], 'en')
        self.assertEqual(dialog.result.backup_path.read_bytes(), original)
        self.assertEqual((f.folder / 'index.html').read_bytes(), b'original player')
        self.assertFalse(self.errors, repr(self.errors))

    def test_opencam_completion_has_no_extra_question_or_automatic_write(self):
        # Break caught: completion queues another modal question, or writes
        # the player before the user presses the explicit insertion button.
        import test_opencam_integration as fixtures
        from unittest.mock import patch
        import SubtitleTranscriber as desktop
        f = fixtures.OpenCamIntegration(); f.setUp()
        self.addCleanup(f.doCleanups)
        app = self.main_app()
        original = (f.folder / 'opencam-player.js').read_bytes()
        app.add_files_from_paths([str(f.folder)])
        self.assertIn(str(f.folder / 'media.mp4'), app.file_list)
        with patch.object(desktop.messagebox, 'askyesno', return_value=False) as question:
            app.show_completion_dialog(1, [str(f.srt)], {str(f.srt): str(f.folder / 'media.mp4')})
            deadline = time.monotonic() + .6
            while time.monotonic() < deadline:
                app.update(); time.sleep(.01)
            self.assertEqual(question.call_count, 0)
        self.assertFalse(any(isinstance(w, self.ctk.CTkToplevel) and w.title() == 'OpenCam 字幕置入'
                             for w in app.winfo_children()))
        self.assertEqual((f.folder / 'opencam-player.js').read_bytes(), original)
        self.assertEqual(list(f.folder.glob('*.backup-*.js')), [])
        self.assertFalse(self.errors, repr(self.errors))

    def test_opencam_preview_opens_actual_html_on_windows(self):
        import test_opencam_integration as fixtures
        from unittest.mock import patch
        from opencam_dialog import OpenCamSubtitleDialog
        f = fixtures.OpenCamIntegration(); f.setUp()
        self.addCleanup(f.doCleanups)
        dialog = OpenCamSubtitleDialog(self.root, folder=f.folder)
        self.root.update()
        launched = []
        with patch('sys.platform', 'win32'), \
                patch('os.startfile', side_effect=launched.append, create=True), \
                patch('webbrowser.open', return_value=True):
            dialog.preview_button.invoke()
        self.assertEqual(launched, [str(f.folder / 'index.html')])
        self.assertFalse(self.errors, repr(self.errors))

    def test_evercam_preview_opens_actual_html_on_windows(self):
        from unittest.mock import patch
        import evercam_integration
        course = self.course()
        ok, message, _ = evercam_integration.deploy_evercam_player(course)
        self.assertTrue(ok, message)
        page = course / 'index.html'
        self.dialog.courses.append(str(course))
        self.dialog.refresh_list(); self.root.update()
        preview = next(w for w in self.widgets(self.dialog.top) if isinstance(w, self.ctk.CTkButton)
                       and w.cget('text') == '預覽')
        self.assertEqual(preview.cget('state'), 'normal')
        launched = []
        with patch('sys.platform', 'win32'), \
                patch('os.startfile', side_effect=launched.append, create=True), \
                patch('webbrowser.open', return_value=True):
            preview.invoke()
        self.assertEqual(launched, [str(page)])
        self.assertFalse(self.errors, repr(self.errors))

    def test_opencam_homepage_and_completion_button_open_prefilled_ui(self):
        import test_opencam_integration as fixtures
        from unittest.mock import patch
        import SubtitleTranscriber as desktop
        f = fixtures.OpenCamIntegration(); f.setUp()
        self.addCleanup(f.doCleanups)
        app = self.main_app()
        app.open_web_player(); app.update()
        button = next(w for w in self.widgets(app) if isinstance(w, self.ctk.CTkButton)
                      and w.cget('text') == 'OpenCam 置入字幕')
        button.invoke(); app.update()
        top = next(w for w in app.winfo_children() if isinstance(w, self.ctk.CTkToplevel)
                   and w.title() == 'OpenCam 字幕置入')
        self.assert_buttons_visible(top, ['選擇資料夾…', '加入 SRT／VTT 字幕…', '備份並置入字幕'])
        top.destroy()
        with patch.object(desktop.messagebox, 'askyesno', return_value=False):
            app.show_completion_dialog(1, [str(f.srt)], {str(f.srt): str(f.folder / 'media.mp4')}, 'en')
            deadline = time.monotonic() + .6
            while time.monotonic() < deadline:
                app.update(); time.sleep(.01)
        completion = next(w for w in app.winfo_children() if isinstance(w, self.ctk.CTkToplevel)
                          and w.title() == '轉錄任務完成')
        insert = next(w for w in self.widgets(completion) if isinstance(w, self.ctk.CTkButton)
                      and w.cget('text') == 'OpenCam 置入字幕')
        insert.invoke(); app.update()
        top = next(w for w in app.winfo_children() if isinstance(w, self.ctk.CTkToplevel)
                   and w.title() == 'OpenCam 字幕置入')
        labels = [w.cget('text') for w in self.widgets(top) if isinstance(w, self.ctk.CTkLabel)]
        self.assertIn(f.srt.name, labels)
        combos = [w for w in self.widgets(top) if isinstance(w, self.ctk.CTkComboBox)]
        self.assertEqual([w.get() for w in combos], ['英文'])
        self.assertIsNone(app.grab_current())
        self.assertEqual(list(f.folder.glob('*.backup-*.js')), [])
        self.assertFalse(self.errors, repr(self.errors))

    def test_opencam_completion_badge_is_after_filename_and_actions_fit(self):
        # Break caught: missing/misplaced badge, or a long filename squeezes
        # either the badge or right-hand operations out of the result card.
        import test_opencam_integration as fixtures
        from unittest.mock import patch
        import SubtitleTranscriber as desktop
        f = fixtures.OpenCamIntegration(); f.setUp()
        self.addCleanup(f.doCleanups)
        long_subtitle = f.root / ('很長的錄影課程名稱' * 5 + '.zh-TW.srt')
        long_subtitle.write_bytes(f.srt.read_bytes())
        app = self.main_app()
        with patch.object(desktop.messagebox, 'askyesno', return_value=False):
            app.show_completion_dialog(1, [str(long_subtitle)],
                                       {str(long_subtitle): str(f.folder / 'media.mp4')})
            app.update()
        top = next(w for w in app.winfo_children() if isinstance(w, self.ctk.CTkToplevel)
                   and w.title() == '轉錄任務完成')
        badges = [w for w in self.widgets(top) if isinstance(w, self.ctk.CTkLabel)
                  and w.cget('text') == 'OpenCam 播放器']
        self.assertEqual(len(badges), 1, 'OpenCam source needs a badge next to its result filename')
        badge = badges[0]
        filename = next(w for w in badge.master.winfo_children()
                        if isinstance(w, self.ctk.CTkLabel) and '.srt' in w.cget('text'))
        for scale in (1, 1.25, 1.5, 2):
            self.ctk.set_widget_scaling(scale)
            self.ctk.set_window_scaling(scale)
            self.settle_scaling()
            self.assert_buttons_visible(top, ['開啟字幕', '開啟目錄', '字幕校對', 'OpenCam 置入字幕', '關閉'])
            self.assertTrue(badge.winfo_ismapped())
            self.assertGreaterEqual(badge.winfo_width(), badge.winfo_reqwidth() - 2)
            self.assertGreaterEqual(badge.winfo_rootx(), filename.winfo_rootx() + filename.winfo_width())
            row = badge.master.master
            self.assertLessEqual(badge.winfo_rootx() + badge.winfo_width(),
                                 row.winfo_rootx() + row.winfo_width())
            first_action = next(w for w in self.widgets(row) if isinstance(w, self.ctk.CTkButton)
                                and w.cget('text') == '開啟字幕')
            self.assertLessEqual(badge.winfo_rootx() + badge.winfo_width(), first_action.winfo_rootx())
        self.assertFalse(self.errors, repr(self.errors))

    def test_completion_badge_uses_source_mapping_not_neighboring_opencam(self):
        import test_opencam_integration as fixtures
        from unittest.mock import patch
        import SubtitleTranscriber as desktop
        f = fixtures.OpenCamIntegration(); f.setUp()
        self.addCleanup(f.doCleanups)
        ordinary = f.folder / 'unrelated.mp4'; ordinary.touch()
        text_output = f.root / 'media.txt'; text_output.write_text('字幕', encoding='utf-8')
        app = self.main_app()
        with patch.object(desktop.messagebox, 'askyesno', return_value=False):
            app.show_completion_dialog(2, [str(f.srt), str(text_output)],
                                       {str(f.srt): str(ordinary), str(text_output): str(f.folder / 'media.mp4')})
            app.update()
        top = next(w for w in app.winfo_children() if isinstance(w, self.ctk.CTkToplevel)
                   and w.title() == '轉錄任務完成')
        badges = [w for w in self.widgets(top) if isinstance(w, self.ctk.CTkLabel)
                  and w.cget('text') == 'OpenCam 播放器']
        self.assertEqual(len(badges), 1)
        sibling_labels = [w.cget('text') for w in badges[0].master.winfo_children()
                          if isinstance(w, self.ctk.CTkLabel)]
        self.assertIn('media.txt', sibling_labels)
        self.assertFalse(any(isinstance(w, self.ctk.CTkButton) and w.cget('text') == 'OpenCam 置入字幕'
                             for w in self.widgets(top)), 'only timed outputs may be inserted')

    def test_mixed_completion_keeps_each_badge_and_matches_insertion_to_its_row(self):
        # Break caught: reusing the last loop value attaches the wrong
        # OpenCam project/subtitle, or the existing EverCam badge disappears.
        import test_opencam_integration as fixtures
        from unittest.mock import patch
        import SubtitleTranscriber as desktop
        f = fixtures.OpenCamIntegration(); f.setUp()
        self.addCleanup(f.doCleanups)
        from web_export_model import SubtitleSource
        course = self.course()
        ec_subtitle = course / 'media.srt'; ec_subtitle.write_bytes(f.srt.read_bytes())
        other_subtitle = f.root / 'media.en.srt'; other_subtitle.write_bytes(f.srt.read_bytes())
        app = self.main_app()
        opened = []
        with patch.object(desktop.messagebox, 'askyesno', return_value=False):
            app.show_completion_dialog(3, [str(f.srt), str(ec_subtitle), str(other_subtitle)],
                                       {str(f.srt): str(f.folder / 'media.mp4'),
                                        str(other_subtitle): str(f.folder / 'media.mp4')}, 'en')
            app.update()
        top = next(w for w in app.winfo_children() if isinstance(w, self.ctk.CTkToplevel)
                   and w.title() == '轉錄任務完成')
        labels = [w.cget('text') for w in self.widgets(top) if isinstance(w, self.ctk.CTkLabel)]
        self.assertEqual(labels.count('OpenCam 播放器'), 2)
        self.assertEqual(labels.count('EverCam 課程'), 1)
        self.assert_buttons_visible(top, ['開啟字幕', '開啟目錄', '字幕校對',
                                         'OpenCam 置入字幕', 'EverCam網頁轉換', '關閉'])
        with patch.object(app, 'open_opencam_tool', side_effect=lambda *args: opened.append(args)):
            for button in self.widgets(top):
                if isinstance(button, self.ctk.CTkButton) and button.cget('text') == 'OpenCam 置入字幕':
                    button.invoke()
        self.assertEqual(opened, [(str(f.folder), (SubtitleSource(f.srt, 'en'),)),
                                  (str(f.folder), (SubtitleSource(other_subtitle, 'en'),))])
        self.assertFalse(self.errors, repr(self.errors))

    def test_opencam_adding_another_subtitle_keeps_pending_language_edit(self):
        import test_opencam_integration as fixtures
        from opencam_dialog import OpenCamSubtitleDialog
        f = fixtures.OpenCamIntegration(); f.setUp()
        self.addCleanup(f.doCleanups)
        dialog = OpenCamSubtitleDialog(self.root, folder=f.folder)
        self.addCleanup(lambda: dialog.top.destroy() if dialog.top.winfo_exists() else None)
        dialog.add_subtitles([f.srt]); self.root.update()
        # A file drop can arrive before the entry receives FocusOut.
        dialog.inputs[0][1].set('英文')
        another = f.root / 'media.ja.vtt'; another.touch()
        dialog.add_subtitles([another]); self.root.update()
        self.assertEqual([t.language for t in dialog.state.tracks], ['en', 'ja'])
        self.assertEqual([v.get() for t, v in dialog.inputs], ['英文', '日文'])
        dialog.inputs[1][1].set('英文')
        dialog.refresh_action()
        self.assertEqual(dialog.submit_button.cget('state'), 'disabled')
        self.assertIn('語系不可重複', dialog.notice.cget('text'))
        self.assertFalse(self.errors, repr(self.errors))

    def test_about_and_update_check_use_the_launched_version(self):
        # Break caught: late dialogs/reporting read updated metadata, while
        # the title and main header still describe the original running app.
        import io
        from unittest.mock import patch
        import SubtitleTranscriber as desktop
        check_updates = desktop.App.check_for_updates
        metadata = Path(self.temp.name) / 'pyproject.toml'
        metadata.write_text('[project]\nversion = "9.8.0"\n', encoding='utf-8')
        reset = getattr(desktop.get_version, 'cache_clear', lambda: None)
        reset()
        self.addCleanup(reset)
        with patch.object(desktop, '__file__', str(metadata.with_name('SubtitleTranscriber.py'))):
            app = self.main_app()
            self.assertIn('v9.8.0', app.title())
            self.assertIn('v9.8.0', app.version_label.cget('text'))
            metadata.write_text('[project]\nversion = "9.8.1"\n', encoding='utf-8')
            app.show_about()
            self.root.update()
            labels = [w.cget('text') for w in self.widgets(app.about_window)
                      if isinstance(w, self.ctk.CTkLabel)]
            self.assertIn('Version 9.8.0', labels)
            shown = []
            with patch.object(desktop, 'safe_urlopen',
                              return_value=io.BytesIO(b'{"tag_name":"v9.8.0"}')), \
                 patch.object(desktop.messagebox, 'showinfo',
                              side_effect=lambda title, message, **kwargs: shown.append(message)):
                check_updates(app, manual=True)
            self.assertEqual(len(shown), 1)
            self.assertIn('v9.8.0', shown[0])
            with patch.object(desktop.messagebox, 'askyesno',
                              side_effect=lambda title, message, **kwargs: shown.append(message) or False):
                app.show_update_dialog('9.8.1', 'https://example.invalid', '更新說明')
            self.assertIn('目前版本：v9.8.0', shown[-1])
            self.assertIn('v9.8.0', app.title())
        self.assertFalse(self.errors, repr(self.errors))

    def test_main_list_and_settings_keep_values_and_actions_at_small_size(self):
        app = self.main_app()
        video = Path(self.temp.name) / '課程.mp4'
        video.touch()
        app.add_files_from_paths([str(video)])
        app.prompt_var.set('資料庫課程')
        app.hotwords_var.set('索引, B-tree')
        for scale in (1, 1.25, 1.5, 2):
            with self.subTest(scale=scale):
                self.ctk.set_widget_scaling(scale)
                self.ctk.set_window_scaling(scale)
                self.settle_scaling()
                app.geometry('760x500')
                self.root.update()
                self.assertEqual(app.file_name_labels[str(video)].cget('text'), video.name)
                self.assertEqual(app.file_path_labels[str(video)].cget('text'), str(video.parent))
                self.assert_buttons_visible(app, ['加入檔案...', '清除清單',
                    '網頁播放器', '開始產生字幕', '取消 (Cancel)'])
                app.settings_frame._parent_canvas.yview_moveto(1)
                self.root.update()
                app.btn_toggle_adv.invoke()
                self.root.update()
                self.assertTrue(app.is_adv_settings_visible)
                app.btn_toggle_adv.invoke()
                self.root.update()
                self.assertEqual(app.prompt_var.get(), '資料庫課程')
                self.assertEqual(app.hotwords_var.get(), '索引, B-tree')
        app.btn_clear.invoke()
        self.assertEqual(app.file_list, [])
        self.assertEqual(app.file_remove_buttons, {})
        self.assertFalse(self.errors, repr(self.errors))

    def test_video_selection_does_not_show_or_register_hidden_dropdown_menus(self):
        # Break caught: recursive DnD registration maps macOS Menu windows.
        import tkinter as tk
        from test_web_export_inputs import make_video
        dialog = self.export_dialog()
        video = Path(self.temp.name) / '影片.mp4'
        make_video(video)
        video.with_suffix('.srt').write_text('1\n00:00:00,000 --> 00:00:00,500\n字幕\n', encoding='utf-8')
        dialog.select_video(video)
        deadline = time.monotonic() + 15
        while dialog.job and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.assertIsNone(dialog.job)
        self.assertFalse(dialog.notice_error, dialog.notice)
        menus = [w for w in self.widgets(dialog.top) if isinstance(w, tk.Menu)]
        self.assertGreaterEqual(len(menus), 2)
        for menu in menus:
            self.assertFalse(menu.winfo_ismapped(), str(menu))
            self.assertFalse(menu.tk.call('bind', str(menu), '<<DropTargetTypes>>'), str(menu))
        combo = next(w for w in self.widgets(dialog.tracks_frame) if isinstance(w, self.ctk.CTkComboBox))
        # Language selection still executes the real menu command.
        menu = combo._dropdown_menu
        index = next(i for i in range(menu.index('end') + 1)
                     if menu.type(i) == 'command' and menu.entrycget(i, 'label').strip() == '英文')
        menu.invoke(index)
        self.root.update()
        self.assertEqual(dialog.state.tracks[0].language, 'en')
        self.assertFalse(menu.winfo_ismapped())
        self.assertFalse(self.errors, repr(self.errors))

    def test_advanced_expansion_reveals_settings_and_collapse_restores_scroll(self):
        # Break caught: grid() adds controls below the viewport without reveal.
        app = self.main_app()
        app.max_chars_var.set('47')
        for scale in (1, 1.25, 1.5, 2):
            with self.subTest(scale=scale):
                self.ctk.set_widget_scaling(scale)
                self.ctk.set_window_scaling(scale)
                self.settle_scaling()
                app.geometry('800x700')
                self.root.update()
                if app.is_adv_settings_visible:
                    app.btn_toggle_adv.invoke()
                    self.root.update()
                canvas = app.settings_frame._parent_canvas
                canvas.yview_moveto(0)
                app.btn_toggle_adv.invoke()
                self.root.update()
                first = app.chk_word_ts
                self.assertGreaterEqual(first.winfo_rooty(), canvas.winfo_rooty())
                self.assertLessEqual(first.winfo_rooty() + first.winfo_height(),
                                     canvas.winfo_rooty() + canvas.winfo_height())
                app.btn_toggle_adv.invoke()
                self.root.update()
                self.assertFalse(app.adv_settings_frame.winfo_manager())
                self.assertAlmostEqual(canvas.yview()[0], 0, delta=0.02)
                self.assertEqual(app.max_chars_var.get(), '47')
                self.assert_buttons_visible(app, ['開始產生字幕', '取消 (Cancel)'])
        self.assertFalse(self.errors, repr(self.errors))

    def test_advanced_first_option_is_visible_at_minimum_window_height(self):
        # Break caught: a fixed settings header consumes the short viewport,
        # leaving the first revealed option below its bottom edge.
        app = self.main_app()
        app.geometry('800x500')
        self.settle_scaling()
        app.btn_toggle_adv.invoke()
        self.root.update()
        canvas = app.settings_frame._parent_canvas
        first = app.chk_word_ts
        self.assertGreaterEqual(first.winfo_rooty(), canvas.winfo_rooty())
        self.assertLessEqual(first.winfo_rooty() + first.winfo_height(),
                             canvas.winfo_rooty() + canvas.winfo_height())
        self.assert_buttons_visible(app, ['開始產生字幕', '取消 (Cancel)'])
        self.assertFalse(self.errors, repr(self.errors))

    def test_model_manager_done_button_is_full_height_at_supported_scales(self):
        # Break caught: list/progress consume the fixed window before Close.
        app = self.main_app()
        app.show_storage_settings()
        window = app.storage_window
        done = next(w for w in self.widgets(window)
                    if isinstance(w, self.ctk.CTkButton) and w.cget('text') == '完成 (Close)')
        cancel = next(w for w in self.widgets(window)
                      if isinstance(w, self.ctk.CTkButton) and w.cget('text') == '取消下載')
        progress = next(w for w in self.widgets(cancel.master)
                        if isinstance(w, self.ctk.CTkProgressBar))
        for scale in (1, 1.25, 1.5, 2):
            with self.subTest(scale=scale):
                self.ctk.set_widget_scaling(scale)
                self.ctk.set_window_scaling(scale)
                self.settle_scaling()
                self.assert_buttons_visible(window, ['完成 (Close)', '取消下載'])
                self.assertGreaterEqual(done.winfo_height(), round(40 * done._get_widget_scaling()) - 2)
                for control in (cancel, progress):
                    self.assertTrue(control.winfo_ismapped())
                    self.assertGreaterEqual(control.winfo_height(), control.winfo_reqheight() - 2)
                    self.assertLessEqual(control.winfo_rooty() + control.winfo_height(),
                                         window.winfo_rooty() + window.winfo_height())
        done.invoke()
        self.root.update()
        self.assertFalse(window.winfo_exists())
        self.assertFalse(self.errors, repr(self.errors))

    def widgets(self, parent):
        for widget in parent.winfo_children():
            yield widget
            yield from self.widgets(widget)

    def test_model_manager_controls_remain_reachable_in_short_window(self):
        # A window manager may cap height at high DPI; fixed header/path
        # content must not consume the download actions or hide the list.
        app = self.main_app()
        app.show_storage_settings()
        window = app.storage_window
        window.geometry('660x360')
        self.root.update()
        self.assert_buttons_visible(window, ['完成 (Close)', '取消下載'])
        for button in self.widgets(window):
            if isinstance(button, self.ctk.CTkButton) and button.cget('text') in ('完成 (Close)', '取消下載'):
                self.assertGreaterEqual(button.winfo_height(), button.winfo_reqheight() - 2)
        scrolls = [w for w in self.widgets(window) if isinstance(w, self.ctk.CTkScrollableFrame)]
        self.assertTrue(scrolls)
        for scroll in scrolls:
            scroll._parent_canvas.yview_moveto(1)
        self.root.update()
        last_model_button = next(w for w in reversed(list(self.widgets(scrolls[-1])))
                                 if isinstance(w, self.ctk.CTkButton))
        self.assertTrue(last_model_button.winfo_ismapped())
        self.assertGreaterEqual(last_model_button.winfo_rooty(), window.winfo_rooty())
        self.assertLessEqual(last_model_button.winfo_rooty() + last_model_button.winfo_height(),
                             window.winfo_rooty() + window.winfo_height())
        for scroll in scrolls:
            canvas = scroll._parent_canvas
            self.assertGreaterEqual(last_model_button.winfo_rooty(), canvas.winfo_rooty())
            self.assertLessEqual(last_model_button.winfo_rooty() + last_model_button.winfo_height(),
                                 canvas.winfo_rooty() + canvas.winfo_height())
            self.assertGreaterEqual(last_model_button.winfo_rootx(), canvas.winfo_rootx())
            self.assertLessEqual(last_model_button.winfo_rootx() + last_model_button.winfo_width(),
                                 canvas.winfo_rootx() + canvas.winfo_width())
        self.assertGreaterEqual(last_model_button.winfo_height(), last_model_button.winfo_reqheight() - 2)
        self.assertGreaterEqual(last_model_button.winfo_width(), last_model_button.winfo_reqwidth() - 2)
        self.assertFalse(self.errors, repr(self.errors))

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
        dialog = self.export_dialog()
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
        dialog = self.export_dialog()
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
        dialog = self.export_dialog()
        error = PermissionError('very long locked path ' + '中文路徑' * 400)
        error.winerror = 32
        error.export_stage = '寫入網頁資源'
        error.export_resource = 'index.html'
        error.staging_path = Path(self.temp.name) / ('暫存' * 60)
        def fail(progress, cancelled):
            raise error
        dialog.run_job(fail, lambda result: None)
        dialog.job.thread.join(timeout=5)
        dialog.poll()
        self.root.update()
        self.assertIn('占用', dialog.notice)
        self.assertNotIn('被其他程式', dialog.notice)
        self.assertLess(len(dialog.notice), 180)
        self.assertNotIn('very long', dialog.notice)
        self.assertFalse(dialog.error_details.winfo_manager())
        dialog.details_button.invoke()
        self.root.update()
        self.assertIn(str(error.staging_path), dialog.error_details.get('1.0', 'end'))
        self.assertIn('寫入網頁資源', dialog.error_details.get('1.0', 'end'))
        self.assertIn('index.html', dialog.error_details.get('1.0', 'end'))
        self.assertIn('程式版本：test', dialog.error_details.get('1.0', 'end'))
        self.assertEqual(dialog.error_details.cget('state'), 'disabled')
        self.assert_buttons_visible(dialog.top, [dialog.create_button.cget('text'), '關閉'])

    def test_standalone_actions_fit_with_long_paths_at_supported_scales(self):
        from web_export_dialog import WebExportDialog
        dialog = self.export_dialog()
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
                self.assert_buttons_visible(self.root, ['開始產生字幕', '取消 (Cancel)', '網頁播放器'])
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
            self.ctk.set_widget_scaling(1.25)
            self.ctk.set_window_scaling(1.25)
            # CTk restores native min/max constraints one second after a
            # scaling change. Wait for that real window-manager transition.
            deadline = time.monotonic() + 1.2
            while time.monotonic() < deadline:
                self.root.update()
                time.sleep(0.01)
            editor.geometry('920x560')
            self.root.update()
            self.assert_buttons_visible(editor, ['儲存並關閉', '關閉', '儲存'])
            self.ctk.set_widget_scaling(1)
            self.ctk.set_window_scaling(1)
            style = desktop.ttk.Style(self.root)
            self.assertIn('PingFang' if desktop.platform.system() == 'Darwin' else 'JhengHei' if desktop.platform.system() == 'Windows' else 'Noto', str(style.lookup('Treeview', 'font')))
            from tkinter import font as tkfont
            normal_linespace = tkfont.Font(root=self.root, font=style.lookup('Treeview', 'font')).metrics('linespace')
            self.ctk.set_widget_scaling(2)
            self.root.update()
            large_linespace = tkfont.Font(root=self.root, font=style.lookup('Treeview', 'font')).metrics('linespace')
            self.assertGreaterEqual(large_linespace, normal_linespace * 1.7)
            self.ctk.set_widget_scaling(1)
            previous_scaling = self.root.tk.call('tk', 'scaling')
            for tk_scaling in (1.333, 1.667, 2, 2.667):
                self.root.tk.call('tk', 'scaling', tk_scaling)
                editor._apply_treeview_theme()
                line_height = tkfont.Font(root=self.root, font=style.lookup('Treeview', 'font')).metrics('linespace')
                self.assertGreaterEqual(int(style.lookup('Treeview', 'rowheight')), line_height + 4)
            self.root.tk.call('tk', 'scaling', previous_scaling)
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
