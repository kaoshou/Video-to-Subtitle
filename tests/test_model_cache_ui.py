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
