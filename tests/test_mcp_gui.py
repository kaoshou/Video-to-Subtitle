import gc
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from mcp_state import ProcessLock, State


class GUIEngine:
    def __init__(self, *args, **kwargs):
        self.loaded = False

    def load_model(self, **kwargs):
        self.loaded = True
        kwargs['log_callback']('fake model loaded')

    def run(self, path, **kwargs):
        if not self.loaded:
            raise RuntimeError('model not loaded')
        kwargs['log_callback']('child-pid:' + str(os.getpid()))
        kwargs['progress_callback'](.5)
        kwargs['stage_callback']('transcribe', 'fake progress')
        return str(Path(path).with_suffix('.srt'))


@unittest.skipUnless(os.environ.get('VTS_RUN_GUI_TESTS') == '1', 'requires native GUI session')
class MCPGuiTests(unittest.TestCase):
    def setUp(self):
        import customtkinter as ctk
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.state = State(self.path / 'state')
        self.default = patch('mcp_state.default_state_dir', return_value=self.state.path)
        self.default.start()
        self.addCleanup(self.default.stop)
        self.root = ctk.CTk()
        self.root.is_running = False
        self.root.transcriber = None
        self.dialog = None
        self.errors = []
        self.root.report_callback_exception = lambda *args: self.errors.append(args)
        self.addCleanup(self.cleanup)
        # Native Tk must finish mapping its first root before a test replaces
        # it with the TkDND-backed application interpreter.
        self.root.update()

    def cleanup(self):
        if self.dialog:
            for worker in self.dialog.workers:
                worker.join(timeout=3)
            self.dialog.close()
        if self.root is None:
            gc.collect()
            return
        for timer in self.root.tk.call('after', 'info'):
            self.root.tk.call('after', 'cancel', timer)
        if getattr(self.root, '_mcp_direct_lock', None):
            self.root._mcp_direct_lock.release()
        if getattr(self.root, '_mcp_direct_residency', None):
            self.root._mcp_direct_residency.release()
        self.root.destroy()
        self.dialog = self.root = None
        gc.collect()

    def main_app(self):
        import SubtitleTranscriber as desktop
        for timer in self.root.tk.call('after', 'info'):
            self.root.tk.call('after', 'cancel', timer)
        self.root.destroy()
        self.root = None
        gc.collect()
        with patch.object(desktop.App, 'load_settings'), patch.object(desktop.App, 'save_settings'), \
                patch.object(desktop.App, 'check_for_updates'):
            self.root = desktop.App()
        self.root.report_callback_exception = lambda *args: self.errors.append(args)
        return self.root

    def open(self, default=False):
        from mcp_dialog import MCPSettingsDialog
        self.dialog = MCPSettingsDialog(self.root, **({} if default else {'state': self.state}))
        self.root.update()
        self.settle()
        return self.dialog

    def settle(self):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            self.root.update()
            if not self.dialog.busy:
                break
            time.sleep(.01)
        self.assertFalse(self.dialog.busy)
        self.assertFalse(self.errors, repr(self.errors))

    def test_open_default_does_not_touch_state_or_discover_clients(self):
        with patch('mcp_clients.discover_clients', side_effect=AssertionError('unexpected discovery')):
            dialog = self.open(default=True)
            self.root.update()
        self.assertFalse(self.state.path.exists())
        self.assertIsNone(dialog.top.grab_current())
        self.assertEqual(len(dialog.client_rows), 11)

    def test_ambiguous_discovery_requires_explicit_target_and_allows_alternate(self):
        from mcp_clients import discover_clients
        dialog = self.open()
        row = next(r for r in discover_clients(home=self.path, environ={'CODEX_HOME': 'relative'}) if r['id'] == 'codex')
        dialog.client_rows['codex'].update(row)
        dialog.client.set('codex')
        selected = str(self.path / 'selected.toml')
        with patch.object(dialog.filedialog, 'asksaveasfilename', return_value=''):
            self.assertIsNone(dialog._target())
        with patch.object(dialog.filedialog, 'asksaveasfilename', return_value=selected):
            self.assertEqual(dialog._target(), ('codex', selected))
        alternate = str(self.path / 'alternate.toml')
        with patch.object(dialog.filedialog, 'asksaveasfilename', return_value=alternate):
            dialog.choose_config()
        self.assertEqual(dialog._target(), ('codex', alternate))

    def test_activation_disclosure_and_job_monitor_show_actionable_details(self):
        self.state.put('jobs', 'failed', {'id': 'failed', 'state': 'failed', 'stage': 'subtitle',
            'error': {'code': 'INVALID_SUBTITLE', 'message': 'Invalid subtitle; reimport.'}})
        self.state.put('jobs', 'done', {'id': 'done', 'state': 'succeeded', 'stage': 'complete',
            'result': {'index_path': '/unvalidated/index.html'}})
        dialog = self.open()
        self.assertIn('雲端', dialog.privacy_notice.cget('text'))
        self.assertIn('不是加密', dialog.privacy_notice.cget('text'))
        dialog.refresh_jobs()
        self.settle()
        texts = [str(child.cget('text')) for row in dialog.jobs_frame.winfo_children()
                 for child in row.winfo_children() if isinstance(child, (dialog.ctk.CTkLabel, dialog.ctk.CTkButton))]
        self.assertTrue(any('INVALID_SUBTITLE' in text and 'subtitle' in text for text in texts), texts)
        self.assertIn('開啟結果', texts)

    def test_cleanup_confirmation_names_unfinished_translations_and_requires_consent(self):
        self.state.put('drafts', 'pending', {'id': 'pending', 'text': 'unfinished'})
        dialog = self.open()
        confirmations = []
        def no(title, message, **kwargs):
            confirmations.append(message)
            return False
        with patch.object(dialog.messagebox, 'askyesno', side_effect=no):
            dialog.cleanup_work()
            self.settle()
        self.assertIn(str(self.state.path), confirmations[0])
        self.assertIn('未完成翻譯', confirmations[0])
        self.assertIn('bytes', confirmations[0])
        self.assertTrue(self.state.get('drafts', 'pending'))

    def test_explicit_settings_open_loads_saved_policy_without_writing(self):
        saved = self.state.configure(True, [self.path])
        original = (self.state.path / 'policy.json').read_bytes()
        with patch('mcp_clients.discover_clients', side_effect=AssertionError('automatic discovery')):
            dialog = self.open()
        self.assertTrue(dialog.enabled.get())
        self.assertEqual(dialog.roots, [Path(saved['roots'][0]['path'])])
        self.assertEqual((self.state.path / 'policy.json').read_bytes(), original)

    def test_roots_and_toggle_only_persist_after_explicit_apply(self):
        dialog = self.open()
        dialog.add_root(self.path)
        dialog.enabled.set(True)
        self.root.update()
        self.assertFalse(self.state.path.exists())
        dialog.apply_policy()
        self.settle()
        policy = self.state.policy()
        self.assertTrue(policy['enabled'])
        self.assertEqual(policy['roots'][0]['path'], str(self.path.resolve()))
        self.root.is_running = True
        dialog.roots = []
        dialog.apply_policy()
        self.settle()
        self.assertTrue(self.state.policy()['enabled'])
        self.assertEqual(len(self.state.policy()['roots']), 0)

    def test_first_activation_needs_no_folders_and_restriction_is_optional(self):
        dialog = self.open()
        self.assertFalse(dialog.restricted.get())
        dialog.enabled.set(True)
        dialog.apply_policy()
        self.settle()
        self.assertTrue(self.state.policy()['enabled'])
        self.assertEqual(self.state.policy()['roots'], [])
        self.assertEqual(self.state.policy()['options']['access_mode'], 'general')
        dialog.restricted.set(True)
        dialog.add_root(self.path)
        dialog.apply_policy()
        self.settle()
        self.assertEqual(self.state.policy()['options']['access_mode'], 'restricted')
        self.assertEqual(len(self.state.policy()['roots']), 1)

    def test_manual_generic_and_owned_configuration_require_consent(self):
        dialog = self.open()
        dialog.client.set('generic')
        dialog.show_manual()
        self.settle()
        self.assertIn('--mcp', dialog.output.get('1.0', 'end'))
        config = self.path / 'settings.json'
        config.write_text('{"other": 4}')
        dialog.client.set('claude-code')
        dialog.client_rows['claude-code']['config_path'] = str(config)
        dialog.add_root(self.path)
        with patch.object(dialog.messagebox, 'askyesno', return_value=False) as consent:
            dialog.configure_client()
            self.settle()
            self.assertIn(str(self.path), consent.call_args.args[1])
            self.assertIn('Claude Code', consent.call_args.args[1])
        self.assertEqual(config.read_text(), '{"other": 4}')
        with patch.object(dialog.messagebox, 'askyesno', return_value=True):
            dialog.configure_client()
            self.settle()
        self.assertIn('video-to-subtitle', config.read_text())
        self.assertIn('"other": 4', config.read_text())
        self.assertIn('未驗證', dialog.notice.cget('text'))

    def test_discovery_worker_does_not_block_tk_or_claim_live_connection(self):
        dialog = self.open()
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        from mcp_clients import discover_clients
        rows = discover_clients(home=self.path, environ={}, system='Linux', application_roots=(), executable_roots=())
        def slow():
            entered.set()
            release.wait(3)
            return rows
        with patch('mcp_clients.discover_clients', side_effect=slow):
            dialog.detect_clients()
            self.assertTrue(entered.wait(1))
            ticks = []
            self.root.after(0, lambda: ticks.append(True))
            self.root.update()
            self.assertEqual(ticks, [True])
            release.set()
            self.settle()
        self.assertIn('未驗證', dialog.client_rows['codex']['label'].cget('text'))

    def test_disable_finish_then_cancel_revokes_existing_session_admission(self):
        original = self.state.configure(True, [self.path])
        dialog = self.open()
        dialog.stop_mode.set('完成已接受工作')
        dialog.disable_access()
        self.settle()
        self.assertEqual(self.state.policy()['drain_generation'], original['generation'])
        dialog.stop_mode.set('取消已接受工作')
        dialog.disable_access()
        self.settle()
        self.assertNotIn('drain_generation', self.state.policy())

    def test_lock_conflict_visible_before_gui_model_load(self):
        import SubtitleTranscriber as desktop
        self.main_app()
        self.root.file_list = [str(self.path / 'unused.mp4')]
        lock = ProcessLock(self.state.path / 'locks', 'inference')
        self.assertTrue(lock.acquire())
        try:
            with patch.object(desktop, 'SubtitleTranscriber', side_effect=AssertionError('model constructed before lock')), \
                    patch.object(desktop.messagebox, 'showerror') as error:
                self.root.process_batch()
            self.assertIsNone(self.root.transcriber)
            self.assertIn('模型', error.call_args.args[1])
        finally:
            lock.release()

    def test_long_paths_wrap_and_actions_remain_reachable_in_both_themes(self):
        import customtkinter as ctk
        dialog = self.open()
        dialog.add_root(self.path / ('很長的中文課程資料夾' * 12))
        for mode in ('Light', 'Dark'):
            ctk.set_appearance_mode(mode)
            self.root.update()
            for tab in dialog.pages:
                dialog.tabs.set(tab)
                self.root.update()
                visible = [button for button in dialog.actions if button.winfo_ismapped()]
                self.assertTrue(visible)
                for button in visible:
                    self.assertGreaterEqual(button.winfo_rootx(), dialog.top.winfo_rootx())
                    self.assertLessEqual(button.winfo_rootx() + button.winfo_width(),
                                         dialog.top.winfo_rootx() + dialog.top.winfo_width())
            self.assertIsNone(dialog.top.grab_current())
        ctk.set_appearance_mode('Light')

    def test_actions_are_keyboard_reachable_and_return_invokes_manual(self):
        dialog = self.open()
        dialog.tabs.set('進階管理')
        self.root.update()
        button = next(button for button in dialog.actions if button.cget('text') == '手動設定')
        self.assertTrue(int(button._canvas.cget('takefocus')))
        button._canvas.focus_force()
        self.root.update()
        button._canvas.event_generate('<Return>')
        self.settle()
        self.assertIn('--mcp', dialog.output.get('1.0', 'end'))

    def test_setup_has_one_scroll_level_and_code_uses_separate_window(self):
        dialog = self.open()
        self.assertIsNone(dialog.output)
        for page in dialog.pages.values():
            def inspect(widget):
                for child in widget.winfo_children():
                    self.assertNotIsInstance(child, (dialog.ctk.CTkScrollableFrame, dialog.ctk.CTkTextbox))
                    inspect(child)
            inspect(page)
        dialog._output('controlled setting', show=True)
        self.root.update()
        self.assertEqual(dialog.output.winfo_toplevel(), dialog.details_window)
        self.assertIsNone(dialog.top.grab_current())
        with patch.object(dialog.top, 'clipboard_clear'), patch.object(dialog.top, 'clipboard_append') as copy:
            dialog.copy_output()
            copy.assert_called_once_with('controlled setting')

    def test_selected_tool_exposes_only_its_details_and_correct_action(self):
        dialog = self.open()
        for key, label in (('codex', '設定此工具…'), ('claude-desktop', '匯出 Claude 安裝檔…'),
                           ('windsurf', '顯示手動設定'), ('generic', '顯示手動設定')):
            dialog.client.set(key)
            self.root.update()
            self.assertEqual(dialog.client_action.cget('text'), label)
            self.assertEqual([client for client, row in dialog.client_rows.items() if row['label'].winfo_ismapped()], [key])
        with patch.object(dialog, 'show_manual') as manual:
            dialog.connect_selected()
            manual.assert_called_once()

    def test_interrupted_jobs_cannot_be_returned_to_cancelling(self):
        self.state.put('jobs', 'interrupted-job', {'id': 'interrupted-job', 'state': 'interrupted'})
        dialog = self.open()
        dialog.cancel_job('interrupted-job')
        self.settle()
        self.assertEqual(self.state.get('jobs', 'interrupted-job')['state'], 'interrupted')

    def test_probe_pass_is_not_reported_as_external_client_connected(self):
        dialog = self.open()
        with patch('mcp_transport.probe_connection', return_value={'connected': True, 'enabled': False}) as probe:
            dialog.test_connection()
            self.settle()
        self.assertEqual(probe.call_args.kwargs['command'][-3:], ['--mcp', '--state-dir', str(self.state.path)])
        self.assertIn('自我測試通過', dialog.notice.cget('text'))
        self.assertIn('尚未驗證', dialog.notice.cget('text'))

    def test_closing_main_gui_does_not_cancel_an_accepted_service_job(self):
        from mcp_service import Service
        from test_web_export_inputs import make_video
        media = self.path / 'lesson.mp4'
        make_video(media)
        root_id = self.state.configure(True, [self.path])['roots'][0]['id']
        entered, release = threading.Event(), threading.Event()
        class Fake:
            def __init__(self, **kwargs): pass
            def load_model(self, **kwargs): pass
            def run(self, path, **kwargs):
                entered.set()
                release.wait(5)
                return None
        service = Service(self.state, transcribe_factory=Fake)
        self.addCleanup(service.close)
        self.addCleanup(release.set)
        asset = service.call('list_media', {'root_id': root_id})['items'][0]['asset_id']
        accepted = service.call('start_transcription', {'asset_id': asset, 'request_id': 'close-dialog'})
        self.assertTrue(entered.wait(3))
        self.main_app()
        self.root.on_app_closing()
        self.root = None
        gc.collect()
        self.assertEqual(service.call('get_job', accepted)['state'], 'running')
        self.assertFalse(self.state.get('jobs', accepted['job_id']).get('cancel_requested', False))
        release.set()

    def test_main_batch_uses_one_child_and_releases_lock_after_batch(self):
        import mcp_inference
        class FixtureProxy(mcp_inference.ProcessTranscriber):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs, engine_factory=GUIEngine)
        self.state.configure(True, [self.path])
        app = self.main_app()
        app.file_list = [str(self.path / 'one.mp4'), str(self.path / 'two.mp4')]
        logs, results = [], []
        with patch.object(mcp_inference, 'ProcessTranscriber', FixtureProxy), \
                patch.object(app, 'log', side_effect=logs.append), \
                patch.object(app, 'show_completion_dialog', side_effect=lambda *args: results.append(args)), \
                patch.object(app, 'refresh_model_menu'), patch.object(app, 'update_download_button_state'):
            app.process_batch()
            self.root.update()
        self.assertIsNone(app.transcriber)
        pids = [line for line in logs if line.startswith('child-pid:')]
        self.assertEqual(len(pids), 2)
        self.assertEqual(pids[0], pids[1])
        self.assertNotEqual(pids[0], 'child-pid:' + str(os.getpid()))
        self.assertEqual(results[0][0], 2)
        self.assertEqual(results[0][1], [str(self.path / 'one.srt'), str(self.path / 'two.srt')])
        contender = ProcessLock(self.state.path / 'locks', 'inference')
        self.assertTrue(contender.acquire())
        contender.release()

    def test_main_app_and_settings_open_without_any_mcp_storage(self):
        app = self.main_app()
        with patch('mcp_clients.discover_clients', side_effect=AssertionError('automatic discovery')):
            app.open_mcp_settings()
            self.dialog = app._mcp_settings_dialog
            self.root.update()
        self.assertFalse(self.state.path.exists())

    def test_job_monitor_refreshes_after_explicit_start(self):
        self.state.put('jobs', 'watched-job', {'id': 'watched-job', 'state': 'running'})
        dialog = self.open()
        dialog.refresh_jobs()
        self.settle()
        self.state.put('jobs', 'watched-job', {'id': 'watched-job', 'state': 'succeeded'})
        dialog._jobs_due = 0
        deadline = time.monotonic() + 2
        texts = []
        while time.monotonic() < deadline:
            self.root.update()
            texts = [widget.cget('text') for row in dialog.jobs_frame.winfo_children()
                     for widget in row.winfo_children() if isinstance(widget, dialog.ctk.CTkLabel)]
            if any('succeeded' in text for text in texts):
                break
            time.sleep(.01)
        self.assertTrue(any('succeeded' in text for text in texts), texts)

    def test_main_close_waits_for_owned_batch_to_finish_cooperatively(self):
        import SubtitleTranscriber as desktop
        app = self.main_app()
        app.is_running = True
        with patch.object(desktop.messagebox, 'askyesno', return_value=True), patch.object(app, 'destroy') as destroy:
            app.on_app_closing()
            deadline = time.monotonic() + .3
            while time.monotonic() < deadline:
                app.update()
                time.sleep(.01)
            self.assertTrue(app.cancel_flag)
            self.assertFalse(destroy.called, 'Tk must survive while the owned inference batch is draining')
            app.is_running = False
            deadline = time.monotonic() + .3
            while time.monotonic() < deadline and not destroy.called:
                app.update()
                time.sleep(.01)
            self.assertTrue(destroy.called)


if __name__ == '__main__':
    unittest.main()
