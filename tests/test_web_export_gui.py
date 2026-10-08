"""Real Tk integration tests, enabled on native Windows/macOS CI runners."""
import os
from pathlib import Path
import tempfile
import time
import unittest

from test_web_export_inputs import make_video
from web_export import load_package
from web_export_dialog import WebExportDialog


@unittest.skipUnless(os.environ.get('VTS_RUN_GUI_TESTS') == '1', 'requires native GUI session')
class NativeExportDialog(unittest.TestCase):
    def setUp(self):
        import customtkinter as ctk
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = ctk.CTk()
        self.addCleanup(self.close_root)
        self.errors = []
        self.root.report_callback_exception = lambda *error: self.errors.append(error)
        self.dialog = WebExportDialog(self.root, app_version='test')
        self.folder = Path(self.temp.name)
        self.video = self.folder / '課程.mp4'
        make_video(self.video)

    def close_root(self):
        # CTk registers interpreter-wide timers. Cancel them before destroying
        # this test's root so the next root cannot run orphaned Tcl callbacks.
        for timer in self.root.tk.call('after', 'info'):
            self.root.after_cancel(timer)
        self.root.destroy()

    def settle(self):
        deadline = time.monotonic() + 30
        while True:
            self.root.update()
            self.assertFalse(self.errors, repr(self.errors))
            if not self.dialog.job:
                break
            if time.monotonic() > deadline:
                self.dialog.job.cancel()
                self.dialog.job.thread.join(timeout=5)
                self.fail('GUI background job timed out')
            time.sleep(0.02)
        self.assertFalse(self.dialog.notice_error, self.dialog.notice)

    def add_subtitle(self, suffix):
        (self.folder / ('課程' + suffix)).write_text(
            '1\n00:00:00,000 --> 00:00:00,500\n字幕測試\n', encoding='utf-8')

    def test_select_auto_discover_export_and_reload(self):
        self.add_subtitle('.srt')
        self.add_subtitle('.en.srt')
        dialog = self.dialog
        self.assertEqual(dialog.create_button.cget('state'), 'disabled')
        self.assertFalse(dialog.more.winfo_manager())
        dialog.select_video(self.video)
        self.settle()
        self.assertEqual([t.language for t in dialog.state.tracks], ['und', 'en'])
        self.assertEqual(dialog.variables['title'].get(), '課程')
        self.assertEqual(dialog.create_button.cget('state'), 'normal')
        destination = dialog.state.output_parent / dialog.state.folder_name
        dialog.create_button.invoke()
        self.settle()
        self.assertEqual(dialog.phase, 'done')
        self.assertTrue((destination / 'index.html').is_file())
        loaded = load_package(destination)
        self.assertEqual(loaded.issues, [])
        self.assertEqual(loaded.request.default_subtitle, 'und')
        dialog.loaded(loaded)
        self.settle()
        self.assertEqual(dialog.package_id, loaded.request.package_id)
        self.assertEqual(dialog.create_button.cget('state'), 'normal')

    def test_missing_subtitle_recovers_and_advanced_settings_remain_editable(self):
        dialog = self.dialog
        dialog.select_video(self.video)
        self.settle()
        self.assertEqual(dialog.create_button.cget('state'), 'disabled')
        self.add_subtitle('.srt')
        dialog.select_video(self.video)
        self.settle()
        dialog.more_button.invoke()
        self.assertTrue(dialog.more.winfo_manager())
        dialog.variables['title'].set('自訂標題')
        dialog.variables['default'].set('不顯示字幕')
        dialog.commit_default()
        request = dialog.snapshot()
        self.assertEqual(request.metadata.title, '自訂標題')
        self.assertEqual(request.default_subtitle, 'off')
        self.assertEqual(dialog.create_button.cget('state'), 'normal')
