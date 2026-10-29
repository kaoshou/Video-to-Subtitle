import gc
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch


@unittest.skipUnless(os.environ.get('VTS_RUN_GUI_TESTS') == '1', 'requires native GUI')
class ReviewProgressGUI(unittest.TestCase):
    def setUp(self):
        import SubtitleTranscriber as desktop
        self.desktop = desktop
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        with patch.object(desktop.App, 'load_settings'), patch.object(desktop.App, 'check_for_updates'):
            self.root = desktop.App()
        self.errors = []
        self.root.report_callback_exception = lambda *error: self.errors.append(error)
        self.addCleanup(self.close)
        self.path = Path(self.temp.name) / '課程.srt'
        self.path.write_text('1\n00:00:00,000 --> 00:00:02,000\n老師好歡迎\n\n'
                             '2\n00:00:03,000 --> 00:00:04,000\n下課\n', encoding='utf-8')

    def close(self):
        for timer in self.root.tk.call('after', 'info'):
            self.root.tk.call('after', 'cancel', timer)
        self.root.destroy()
        self.root = None
        gc.collect()

    def editor(self):
        evidence = [dict(start=0., end=2., text='老師好歡迎', reasons=['辨識信心偏低'])]
        editor = self.desktop.SubtitleEditorWindow(self.root, str(self.path), review_evidence=evidence)
        self.root.update()
        editor._select_tree_row(0)
        return editor

    def settle_review(self):
        deadline = time.monotonic() + .35
        while time.monotonic() < deadline:
            self.root.update()
            time.sleep(.01)

    def test_editor_controls_wrap_inside_narrow_pane_at_scaled_sizes(self):
        editor = self.editor()
        ctk = self.desktop.ctk
        self.addCleanup(lambda: ctk.set_widget_scaling(1))
        def descendants(widget):
            for child in widget.winfo_children():
                yield child
                yield from descendants(child)
        for scale in (1, 1.25, 1.5, 2):
            with self.subTest(scale=scale):
                ctk.set_widget_scaling(scale)
                editor.geometry('1200x1000')
                self.root.update()
                editor.paned_window.sashpos(0, round(360 * scale))
                self.root.update()
                controls = [editor.entry_start, editor.entry_end] + [
                    w for w in descendants(editor.editor_dock) if isinstance(w, ctk.CTkButton)]
                captions = [w.cget('text') for w in controls if isinstance(w, ctk.CTkButton)]
                self.assertTrue(any('下一條' in caption for caption in captions))
                left = editor.sub_frame.winfo_rootx()
                right = left + editor.sub_frame.winfo_width()
                for widget in controls:
                    self.assertTrue(widget.winfo_ismapped(),
                                    f'{widget}: pane={editor.sub_frame.winfo_geometry()}, '
                                    f'dock={editor.editor_dock.winfo_geometry()}, widget={widget.winfo_geometry()}')
                    self.assertGreaterEqual(widget.winfo_rootx(), left)
                    self.assertLessEqual(widget.winfo_rootx() + widget.winfo_width(), right + 1)
                    self.assertGreaterEqual(widget.winfo_width(), widget.winfo_reqwidth() - 2)
                self.assertNotEqual(editor.entry_start.winfo_rooty(),
                                    next(w for w in controls if isinstance(w, ctk.CTkButton)
                                         and '下一條' in w.cget('text')).winfo_rooty())
        self.assertFalse(self.errors)

    def test_review_tools_are_compact_and_reason_follows_selection_in_dock(self):
        editor = self.editor()
        self.assertIs(editor.search_entry.master, editor.review_summary.master)
        self.assertIs(editor.review_only.master, editor.review_summary.master)
        self.assertTrue(str(editor.review_detail).startswith(str(editor.editor_dock) + '.'))
        self.assertLess(editor.top_frame.winfo_height(), 130)
        editor.review_only.select()
        editor._on_search_change()
        self.assertEqual(editor.tree.get_children(), ('0',))
        editor._toggle_raw_mode()
        self.assertFalse(editor.search_bar_frame.winfo_manager())
        editor._toggle_raw_mode()
        self.assertTrue(editor.search_bar_frame.winfo_manager())
        self.assertIn('辨識信心偏低', editor.review_detail.cget('text'))

    def test_small_default_window_keeps_table_and_text_editor_usable_when_scaled(self):
        editor = self.editor()
        ctk = self.desktop.ctk
        self.addCleanup(lambda: ctk.set_widget_scaling(1))
        for scale, geometry in ((1, '750x480'), (2, '1240x740')):
            with self.subTest(scale=scale):
                ctk.set_widget_scaling(scale)
                editor.geometry(geometry)
                self.root.update()
                editor.paned_window.sashpos(0, round(360 * scale))
                self.root.update()
                for widget in (editor.tree, editor.txt_item_editor):
                    self.assertTrue(widget.winfo_ismapped())
                    self.assertGreater(widget.winfo_height(), 30 * scale)
                    self.assertLessEqual(widget.winfo_rooty() + widget.winfo_height(),
                                         editor.winfo_rooty() + editor.winfo_height())

    def test_summary_filter_reason_and_edits_do_not_change_subtitle_file(self):
        original = self.path.read_bytes()
        editor = self.editor()
        self.assertIn('1', editor.review_summary.cget('text'))
        self.assertIn('辨識信心偏低', editor.review_detail.cget('text'))
        editor.review_only.select()
        editor._on_search_change()
        self.assertEqual(editor.tree.get_children(), ('0',))
        editor.search_var.set('下課')
        self.assertEqual(editor.tree.get_children(), ())
        editor.search_var.set('')
        editor.txt_item_editor.delete('0.0', 'end')
        editor.txt_item_editor.insert('0.0', '同學好')
        editor._on_text_edit()
        self.settle_review()
        self.assertEqual(editor.review_flags, {})
        self.assertEqual(editor.tree.get_children(), ())
        self.assertEqual(self.path.read_bytes(), original)
        self.assertFalse(self.errors)

    def test_split_merge_and_raw_reload_keep_review_on_correct_content(self):
        editor = self.editor()
        editor.txt_item_editor.mark_set('insert', '1.3')
        editor._split_current_subtitle()
        self.assertEqual(set(editor.review_flags), {0, 1})
        editor._select_tree_row(0)
        editor._merge_with_next_subtitle()
        self.assertEqual(set(editor.review_flags), {0})
        editor._toggle_raw_mode()
        editor.raw_editor.delete('0.0', 'end')
        editor.raw_editor.insert('0.0', '1\n00:00:00,000 --> 00:00:02,000\n更正內容\n')
        editor._toggle_raw_mode()
        self.assertEqual(editor.review_flags, {})
        editor.entry_start.delete(0, 'end')
        editor.entry_start.insert(0, '00:00:05,000')
        editor._on_time_edit()
        self.settle_review()
        self.assertIn('時間軸異常', editor.review_detail.cget('text'))
        editor.entry_start.delete(0, 'end')
        editor.entry_start.insert(0, 'invalid')
        editor._on_time_edit()
        self.settle_review()
        self.assertIn('時間軸異常', editor.review_detail.cget('text'))

    def test_old_subtitles_and_txt_still_open_without_model_metadata(self):
        editor = self.desktop.SubtitleEditorWindow(self.root, str(self.path))
        self.assertEqual(editor.review_flags, {})
        text = Path(self.temp.name) / '課程.txt'
        text.write_text('純文字內容', encoding='utf-8')
        txt = self.desktop.SubtitleEditorWindow(self.root, str(text))
        self.assertIn('純文字內容', txt.txt_editor.get('0.0', 'end'))

    def test_stage_timer_worker_queue_terminal_and_stale_job(self):
        app = self.root
        with patch.object(self.desktop.time, 'monotonic', return_value=100.):
            token = app._begin_stage_tracking()
        worker = threading.Thread(target=lambda: app.queue_stage(token, 'recognition', 'MLX'))
        worker.start(); worker.join(timeout=2)
        self.assertFalse(worker.is_alive())
        with patch.object(self.desktop.time, 'monotonic', return_value=103.):
            app._poll_stage_tracking(token)
        with patch.object(self.desktop.time, 'monotonic', return_value=108.):
            app._poll_stage_tracking(token)
        self.assertIn('00:05', app.stage_label.cget('text'))
        self.assertIn('00:08', app.stage_label.cget('text'))
        app.log('字幕內容不應取代階段')
        self.root.update()
        self.assertNotEqual(app.status_label.cget('text'), '字幕內容不應取代階段')
        app.queue_stage(token, 'terminal', 'cancelled')
        app._poll_stage_tracking(token)
        self.assertFalse(app._stage_active)
        self.assertIn('已取消', app.stage_label.cget('text'))
        newer = app._begin_stage_tracking()
        app.queue_stage(token, 'failed', '過期事件')
        app._poll_stage_tracking(newer)
        self.assertNotIn('過期事件', app.stage_label.cget('text'))
        self.assertFalse(self.errors)

    def test_close_stops_stage_timer_and_completion_keeps_diagnostics(self):
        app = self.root
        token = app._begin_stage_tracking()
        evidence = [dict(start=0, end=2, text='老師好歡迎', reasons=['辨識信心偏低'])]
        app.queue_stage(token, 'review', (str(self.path), evidence))
        app._poll_stage_tracking(token)
        self.assertEqual(app._review_by_path[str(self.path)], evidence)
        with patch.object(app, 'destroy'):
            app.on_app_closing()
        self.assertFalse(app._stage_active)
        self.assertIsNone(app._stage_tick)

    def test_batch_completion_has_review_ready_before_dialog_and_keeps_100_percent(self):
        from types import SimpleNamespace
        app = self.root
        media = str(Path(self.temp.name) / '測試.mp4')
        app.file_list = [media]
        app.transcriber = self.desktop.SubtitleTranscriber('medium', 'cpu', 'int8')
        item = SimpleNamespace(start=0, end=2, text='老師好', words=None, avg_logprob=-1.2)
        app.transcriber.model = SimpleNamespace(transcribe=lambda *a, **k:
            (iter([item]), SimpleNamespace(duration=5, language='zh', language_probability=1)))
        token = app._begin_stage_tracking()
        notices = []
        def completed(count, files, *args):
            notices.append(app._review_by_path.get(os.path.abspath(files[0])))
        with patch.object(app.transcriber, 'load_model'), patch.object(app, 'refresh_model_menu'), \
                patch.object(app, 'show_completion_dialog', side_effect=completed):
            app.process_batch(token)
            self.root.update()
        self.assertEqual(notices[0][0]['reasons'], ['辨識信心偏低'])
        self.assertEqual(app.progress_label.cget('text'), '100.0%')

    def test_cancel_during_model_preparation_is_not_reported_as_failure(self):
        app = self.root
        app.file_list = [str(Path(self.temp.name) / 'media.mp4')]
        token = app._begin_stage_tracking()
        def cancel(*args, **kwargs):
            app.cancel_flag = True
            raise InterruptedError('cancelled')
        with patch.object(self.desktop.SubtitleTranscriber, 'load_model', side_effect=cancel), \
                patch.object(self.desktop.messagebox, 'showinfo'):
            app.process_batch(token)
            self.root.update()
        app._poll_stage_tracking(token)
        self.assertIn('已取消', app.stage_label.cget('text'))

    def test_filtered_ctrl_j_keyrelease_cannot_overwrite_merged_text(self):
        self.path.write_text('1\n00:00:00,000 --> 00:00:02,000\n相同內容\n\n'
                             '2\n00:00:02,000 --> 00:00:04,000\n相同內容\n', encoding='utf-8')
        editor = self.desktop.SubtitleEditorWindow(self.root, str(self.path))
        self.root.update()
        editor.review_only.select()
        editor._on_search_change()
        editor.txt_item_editor.focus_force()
        self.root.update()
        editor.txt_item_editor._textbox.event_generate('<Control-KeyPress-j>')
        self.root.update()
        self.assertEqual(len(editor.items), 1, '實際 Ctrl+J 必須先執行合併')
        editor.txt_item_editor._textbox.event_generate('<Control-KeyRelease-j>')
        self.root.update()
        self.assertEqual(editor.items[0]['text'], '相同內容 相同內容')
        self.assertEqual(editor.tree.get_children(), ())
        self.assertIsNone(editor.current_selected_idx)
        self.assertEqual(editor.txt_item_editor.cget('state'), 'disabled')

    def test_playback_selection_updates_reason_both_directions(self):
        editor = self.editor()
        editor.tree.selection_set('1')
        editor._load_item_to_editor_silent(1)
        editor._on_tree_select()
        self.assertNotIn('辨識信心偏低', editor.review_detail.cget('text'))
        editor.tree.selection_set('0')
        editor._load_item_to_editor_silent(0)
        self.assertIn('辨識信心偏低', editor.review_detail.cget('text'))


if __name__ == '__main__':
    unittest.main()
