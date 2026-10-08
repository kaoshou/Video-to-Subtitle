import importlib
import importlib.util
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock
from types import SimpleNamespace


class DialogLogic(unittest.TestCase):
    def api(self):
        self.assertIsNotNone(importlib.util.find_spec('web_export_dialog'), 'dialog/controller missing')
        return importlib.import_module('web_export_dialog')

    def test_completion_requires_explicit_matching_source(self):
        m = self.api()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ['first.mp4', 'second.mp4', 'second.en.srt', 'out.txt', 'audio.mp3']:
                (root / name).write_bytes(b'x')
            mapping = {str(root / 'second.en.srt'): str(root / 'second.mp4')}
            self.assertEqual(m.completion_video(root / 'second.en.srt', mapping), root / 'second.mp4')
            self.assertIsNone(m.completion_video(root / 'out.txt', mapping))
            self.assertIsNone(m.completion_video(root / 'second.en.srt', {}))
            mapping[str(root / 'second.en.srt')] = str(root / 'audio.mp3')
            self.assertIsNone(m.completion_video(root / 'second.en.srt', mapping))

    def test_worker_only_delivers_data_to_main_thread(self):
        m = self.api()
        main = threading.get_ident()
        job = m.ExportJob(lambda progress, cancelled: threading.get_ident())
        job.thread.join(2)
        kind, result = job.events.get_nowait()
        self.assertEqual(kind, 'success')
        self.assertNotEqual(result, main)

    def test_cancel_and_error(self):
        m = self.api()
        gate = threading.Event()
        def work(progress, cancelled):
            gate.wait(2)
            if cancelled(): raise InterruptedError('cancelled')
        job = m.ExportJob(work)
        job.cancel(); gate.set(); job.thread.join(2)
        self.assertEqual(job.events.get_nowait()[0], 'cancelled')
        def fail(progress, cancelled): raise ValueError('invalid input')
        job = m.ExportJob(fail); job.thread.join(2)
        kind, result = job.events.get_nowait()
        self.assertEqual(kind, 'error')
        self.assertIn('invalid input', str(result))

    def test_late_cancel_does_not_convert_success_to_failure(self):
        m = self.api()
        gate = threading.Event()
        job = m.ExportJob(lambda progress, cancelled: gate.wait(2) or 'published')
        job.cancel(); gate.set(); job.thread.join(2)
        self.assertEqual(job.events.get_nowait()[0], 'success')

    def test_valid_export_does_not_ask_again(self):
        dialog = object.__new__(self.api().WebExportDialog)
        dialog.messagebox = Mock(); dialog.run_job = Mock()
        dialog.top = None; dialog.version = 'test'; dialog.show_issues = Mock()
        dialog.checked(Mock(), [])
        dialog.messagebox.askyesno.assert_not_called()
        dialog.run_job.assert_called_once()

    def test_errors_are_inline_and_warnings_can_be_declined(self):
        dialog = object.__new__(self.api().WebExportDialog)
        dialog.messagebox = Mock(); dialog.run_job = Mock()
        dialog.top = None; dialog.version = 'test'; dialog.show_issues = Mock()
        dialog.checked(Mock(), [SimpleNamespace(severity='error', message='字幕語言未設定')])
        dialog.show_issues.assert_called_once()
        dialog.messagebox.showerror.assert_not_called()
        dialog.run_job.assert_not_called()
        dialog.messagebox.askyesno.return_value = False
        dialog.checked(Mock(), [SimpleNamespace(severity='warning', message='影片編碼相容性')])
        dialog.messagebox.askyesno.assert_called_once()
        dialog.run_job.assert_not_called()

    def test_unknown_video_duration_is_displayable(self):
        from web_export_form import ExportFormState
        dialog = object.__new__(self.api().WebExportDialog)
        dialog.state = ExportFormState()
        dialog.media_info = Mock(); dialog.status = Mock()
        dialog.media_checked(Path('demo.mp4'), {'duration': None, 'size': 1048576})
        self.assertIn('長度未知', dialog.media_info.configure.call_args.kwargs['text'])

    def test_language_selection_commits_final_value_not_transient_deletion(self):
        from web_export_form import ExportFormState
        dialog = object.__new__(self.api().WebExportDialog)
        dialog.state = ExportFormState(); dialog.refresh_languages = Mock()
        dialog.state.add_track(Path('demo.en.srt'), 'en')
        dialog.state.default_choice = 'en'
        variable = Mock()
        dialog.track_inputs = [(dialog.state.tracks[0], variable)]
        # A ComboBox deletes its entry before inserting the selection.
        # Do not commit each write; read only after that atomic selection.
        variable.get.return_value = ''
        variable.get.return_value = '英文'
        dialog.commit_track_languages()
        self.assertEqual(dialog.state.default_choice, 'en')
        variable.get.return_value = '繁體中文'
        dialog.commit_track_languages()
        self.assertEqual(dialog.state.tracks[0].language, 'zh-TW')
        self.assertEqual(dialog.state.default_choice, '')

    def test_typed_default_selection_restores_export_readiness(self):
        from web_export_form import ExportFormState, export_action_state
        m = self.api()
        self.assertTrue(hasattr(m.WebExportDialog, 'commit_default'), 'typed default is not committed')
        dialog = object.__new__(m.WebExportDialog)
        dialog.state = ExportFormState()
        dialog.state.select_video(Path('/tmp/example.mp4'))
        dialog.state.add_track(Path('/tmp/example.en.srt'), 'en')
        dialog.state.default_choice = ''
        dialog.variables = {'default': SimpleNamespace(get=lambda: '英文')}
        # No Tk widgets are needed to check committed data and action readiness.
        dialog.commit_default()
        self.assertEqual(dialog.state.default_choice, 'en')
        self.assertTrue(export_action_state(dialog.state, 'idle', True).enabled)


if __name__ == '__main__': unittest.main()
