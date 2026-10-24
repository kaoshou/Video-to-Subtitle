"""Model status presentation without a native Tk window or network."""
from types import SimpleNamespace
import os
import gc
import unittest
from unittest.mock import Mock, patch

import SubtitleTranscriber as desktop


class Value:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class ModelCacheUI(unittest.TestCase):
    def app(self):
        app = Mock(
            model_var=Value('medium'), model_path_var=Value('/cache'),
            device_var=Value('cpu'), available_models=['medium'],
            combo_model=Mock(), btn_download_model=Mock(), is_running=False,
            _storage_current_target=None,
        )
        app.get_clean_model_name = lambda: desktop.App.get_clean_model_name(app)
        app.update_download_button_state = lambda: desktop.App.update_download_button_state(app)
        return app

    def test_partial_model_is_not_presented_as_never_downloaded(self):
        app = self.app()
        status = SimpleNamespace(state='incomplete', path='/cache/snapshot', message='缺少 tokenizer.json')
        with patch.object(desktop, 'inspect_model_cache', return_value=status, create=True):
            desktop.App.refresh_model_menu(app)
        self.assertEqual(app.model_var.get(), 'medium [下載未完成]')
        self.assertEqual(app.btn_download_model.configure.call_args.kwargs['text'], '繼續下載')

    def test_unreadable_model_is_not_presented_as_missing(self):
        app = self.app()
        status = SimpleNamespace(state='unavailable', path=None, message='無法讀取')
        with patch.object(desktop, 'inspect_model_cache', return_value=status, create=True):
            desktop.App.refresh_model_menu(app)
        self.assertEqual(app.model_var.get(), 'medium [無法讀取]')
        self.assertEqual(app.btn_download_model.configure.call_args.kwargs['text'], '檢查存取')

    def test_ready_model_refreshes_immediately_without_restart(self):
        app = self.app()
        status = SimpleNamespace(state='ready', path='/cache/snapshot', message='')
        with patch.object(desktop, 'inspect_model_cache', return_value=status, create=True):
            desktop.App.refresh_model_menu(app)
        self.assertEqual(app.model_var.get(), 'medium [已下載]')
        self.assertEqual(app.btn_download_model.configure.call_args.kwargs['text'], '已就緒')

    def test_storage_download_blocks_second_main_download(self):
        app = self.app()
        app._storage_current_target = 'medium'
        with patch.object(desktop.messagebox, 'showwarning') as warning, patch.object(desktop.threading, 'Thread'):
            desktop.App.manual_download_model(app)
        self.assertTrue(warning.called)

    def test_storage_download_blocks_transcription_start(self):
        app = self.app()
        app._storage_current_target = 'medium'
        app.file_list = ['movie.mp4']
        with patch.object(desktop.messagebox, 'showwarning') as warning, patch.object(desktop.threading, 'Thread'):
            desktop.App.start_thread(app)
        self.assertTrue(warning.called)


@unittest.skipUnless(os.environ.get('VTS_RUN_GUI_TESTS') == '1', 'requires native GUI session')
class ModelStorageConcurrency(unittest.TestCase):
    def test_all_download_entrypoints_report_access_error_without_cleanup_prompt(self):
        from test_model_cache import ModelCacheTests
        fixture = ModelCacheTests()
        fixture.setUp()
        try:
            fixture.files()
            config = str(fixture.snapshot / 'config.json')
            original = os.stat
            def blocked(path, *args, **kwargs):
                if os.fspath(path) == config:
                    error = PermissionError(13, 'untrusted mount point', config)
                    error.winerror = 448
                    raise error
                return original(path, *args, **kwargs)
            class InlineThread:
                def __init__(self, target, **kwargs):
                    self.target = target
                def start(self):
                    self.target()
            for entrypoint in ('manual', 'manager', 'batch'):
                with self.subTest(entrypoint=entrypoint), \
                        patch.object(desktop.App, 'load_settings'), \
                        patch.object(desktop.App, 'save_settings'), \
                        patch.object(desktop.App, 'check_for_updates'):
                    app = desktop.App()
                    try:
                        app.model_var.set('medium')
                        app.device_var.set('cpu')
                        app.model_path_var.set(str(fixture.cache))
                        app.zh_tw_var.set(False)
                        app.file_list = ['fixture.mp4']
                        app.after = lambda delay, callback, *args: callback(*args)
                        errors = []
                        with patch('os.stat', side_effect=blocked), \
                                patch.object(desktop.threading, 'Thread', InlineThread), \
                                patch.object(desktop.messagebox, 'showerror',
                                             side_effect=lambda title, message, **kw: errors.append((title, message))), \
                                patch.object(desktop.messagebox, 'askyesno',
                                             side_effect=AssertionError('Access errors must not offer cache deletion')), \
                                patch.object(desktop, 'clear_model_cache',
                                             side_effect=AssertionError('Existing cache must not be deleted')):
                            if entrypoint == 'manual':
                                app.manual_download_model()
                            elif entrypoint == 'manager':
                                app.show_storage_settings()
                                def descendants(parent):
                                    for widget in parent.winfo_children():
                                        yield widget
                                        yield from descendants(widget)
                                buttons = [widget for widget in descendants(app.storage_window)
                                           if isinstance(widget, desktop.ctk.CTkButton)
                                           and widget.cget('text') == '檢查存取']
                                # The medium row has an unreadable cache; the
                                # other catalog entries are ordinary downloads.
                                medium = next(button for button in buttons
                                              if any(isinstance(sibling, desktop.ctk.CTkLabel)
                                                     and str(sibling.cget('text')).strip() == 'medium'
                                                     for sibling in button.master.winfo_children()))
                                medium.invoke()
                            else:
                                app.process_batch()
                        self.assertEqual(len(errors), 1)
                        self.assertEqual(errors[0][0], '模型快取無法存取')
                        self.assertIn('快取已保留', errors[0][1])
                        self.assertTrue((fixture.snapshot / 'model.bin').is_file())
                    finally:
                        for timer in app.tk.call('after', 'info'):
                            app.tk.call('after', 'cancel', timer)
                        app.destroy()
                        app = None
                        gc.collect()
        finally:
            fixture.doCleanups()

    def test_reopened_manager_cannot_start_second_download(self):
        # The old dialog can be closed while its worker is still running.
        # The new dialog's local is_downloading flag then starts out False.
        status = SimpleNamespace(state='ready', path='/cache/model', message='')
        with patch.object(desktop.App, 'load_settings'), patch.object(desktop.App, 'save_settings'), \
                patch.object(desktop.App, 'check_for_updates'), \
                patch.object(desktop, 'inspect_model_cache', return_value=status):
            app = desktop.App()
            try:
                app._storage_current_target = 'medium'
                app.show_storage_settings()
                app.update()
                def descendants(parent):
                    for widget in parent.winfo_children():
                        yield widget
                        yield from descendants(widget)
                button = next(widget for widget in descendants(app.storage_window)
                              if isinstance(widget, desktop.ctk.CTkButton)
                              and widget.cget('text') == '重新下載')
                with patch.object(desktop.messagebox, 'showwarning') as warning, \
                        patch.object(desktop.threading, 'Thread') as thread:
                    button.invoke()
                self.assertTrue(warning.called)
                thread.assert_not_called()
                self.assertEqual(app._storage_current_target, 'medium')
            finally:
                for timer in app.tk.call('after', 'info'):
                    app.tk.call('after', 'cancel', timer)
                app.destroy()
                app = None
                gc.collect()
