"""Local MCP settings. Workers communicate with Tk exclusively through a queue."""
import json
from pathlib import Path
import queue
import threading
import time

from mcp_state import MCPError, State
from ui_theme import ui_font, wrap_to_width, secondary_button_style

_CLIENTS = (
    ('codex', 'Codex'), ('claude-code', 'Claude Code'), ('claude-desktop', 'Claude Desktop'),
    ('gemini-cli', 'Gemini CLI'), ('antigravity', 'Antigravity'), ('cursor', 'Cursor'),
    ('vscode', 'VS Code'), ('copilot', 'GitHub Copilot'), ('windsurf', 'Windsurf'),
    ('opencode', 'OpenCode'), ('generic', '其他 MCP 工具'))
_TERMINAL = frozenset(('succeeded', 'failed', 'cancelled', 'interrupted'))


class MCPSettingsDialog:
    def __init__(self, parent, *, state=None):
        import customtkinter as ctk
        import tkinter as tk
        from tkinter import filedialog, messagebox
        self.parent, self.ctk = parent, ctk
        self.filedialog, self.messagebox = filedialog, messagebox
        self.state = state if state is not None else State()  # pure path construction
        self.roots, self.workers, self.actions = [], [], []
        self.events = queue.Queue()
        self.busy = self.closed = False
        self._policy_ready = False
        self._jobs_due = None
        self.top = ctk.CTkToplevel(parent)
        self.top.title('AI 工具連接')
        self.top.geometry('780x720')
        self.top.minsize(640, 540)
        self.top.protocol('WM_DELETE_WINDOW', self.close)
        self.enabled = tk.BooleanVar(master=self.top, value=False)
        self.client = tk.StringVar(master=self.top, value='generic')
        self.stop_mode = tk.StringVar(master=self.top, value='取消已接受工作')
        header = ctk.CTkFrame(self.top, fg_color='transparent')
        header.pack(fill='x', padx=18, pady=(16, 8))
        ctk.CTkLabel(header, text='AI 工具連接', font=ui_font(size=22, weight='bold')).pack(side='left')
        self.button(header, '讀取設定', self.load_policy).pack(side='right')
        # Reserve bottom actions before packing expanding content, even on a
        # short desktop. Client details and long roots remain scrollable.
        footer = ctk.CTkFrame(self.top, fg_color='transparent')
        footer.pack(side='bottom', fill='x', padx=18, pady=(4, 12))
        self.notice = ctk.CTkLabel(footer, text='正在讀取已保存的權限…',
                                  justify='left', anchor='w', wraplength=700)
        self.notice.pack(fill='x', pady=(0, 8))
        wrap_to_width(self.notice)
        for titles in ((('套用權限', self.apply_policy), ('停用存取', self.disable_access), ('關閉', self.close)),
                       (('設定工具', self.configure_client), ('自我測試', self.test_connection),
                        ('手動設定', self.show_manual), ('移除設定', self.remove_client))):
            row = ctk.CTkFrame(footer, fg_color='transparent')
            row.pack(fill='x', pady=3)
            for title, command in titles:
                button = self.button(row, title, command)
                button.pack(side='left', expand=True, fill='x', padx=3)
                self.actions.append(button)
        self.form = ctk.CTkScrollableFrame(self.top)
        self.form.pack(fill='both', expand=True, padx=18, pady=4)
        self.master_switch = ctk.CTkSwitch(self.form, text='允許 AI 工具存取指定資料夾（套用後生效）',
                                          variable=self.enabled, state='disabled')
        self.master_switch.pack(anchor='w', padx=10, pady=10)
        self.privacy_notice = ctk.CTkLabel(self.form,
            text='轉錄在本機執行；AI 用戶端仍可能將回傳字幕傳送到雲端服務。\n私人儲存不是加密，也不保證整個流程離線。按「套用權限」表示同意此資料流與選定範圍。',
            justify='left', anchor='w', wraplength=660)
        self.privacy_notice.pack(fill='x', padx=10, pady=(0, 8))
        wrap_to_width(self.privacy_notice)
        ctk.CTkOptionMenu(self.form, variable=self.stop_mode,
                         values=['取消已接受工作', '完成已接受工作']).pack(anchor='w', padx=10)
        self.button(self.form, '新增允許的資料夾', self.choose_root).pack(anchor='w', padx=10, pady=8)
        self.roots_frame = ctk.CTkFrame(self.form, fg_color='transparent')
        self.roots_frame.pack(fill='x', padx=8)
        self.button(self.form, '偵測工具安裝與設定', self.detect_clients).pack(anchor='w', padx=10, pady=8)
        self.button(self.form, '選取其他設定檔', self.choose_config).pack(anchor='w', padx=10, pady=4)
        self.client_rows = {}
        for client_id, name in _CLIENTS:
            row = ctk.CTkFrame(self.form)
            row.pack(fill='x', padx=8, pady=3)
            ctk.CTkRadioButton(row, text=name, variable=self.client, value=client_id).pack(anchor='w', padx=10, pady=(8, 2))
            label = ctk.CTkLabel(row, text='尚未偵測；未驗證實際連線。', anchor='w', justify='left', wraplength=620)
            label.pack(fill='x', padx=10, pady=(0, 8))
            wrap_to_width(label)
            self.client_rows[client_id] = {'name': name, 'label': label, 'config_path': None}
        extra = ctk.CTkFrame(self.form, fg_color='transparent')
        extra.pack(fill='x', padx=8, pady=8)
        self.button(extra, '匯出 Claude MCPB', self.export_bundle).pack(side='left', padx=3)
        self.button(extra, '修復啟動檔', self.repair_launcher).pack(side='left', padx=3)
        self.output = ctk.CTkTextbox(self.form, height=140, wrap='word')
        self.output.pack(fill='x', padx=8, pady=8)
        location = ctk.CTkLabel(self.form, text=f'私人工作資料位置：{self.state.path}',
                               justify='left', anchor='w', wraplength=660)
        location.pack(fill='x', padx=10)
        wrap_to_width(location)
        self.button(self.form, '清理私人工作資料', self.cleanup_work).pack(anchor='w', padx=10, pady=8)
        self.button(self.form, '更新工作狀態', self.refresh_jobs).pack(anchor='w', padx=10, pady=8)
        self.jobs_frame = ctk.CTkFrame(self.form, fg_color='transparent')
        self.jobs_frame.pack(fill='x', padx=8, pady=8)
        self._timer = self.top.after(50, self._poll)
        # Opening this explicit settings UI authorizes an offline policy read.
        # App startup still does not construct the dialog or access MCP state.
        self.load_policy()

    def button(self, parent, text, command):
        button = self.ctk.CTkButton(parent, text=text, command=command, width=100, height=32,
                                   **secondary_button_style())
        button._canvas.configure(takefocus=1)
        button.bind('<Return>', lambda event: button.invoke())
        button.bind('<space>', lambda event: button.invoke())
        return button

    def _notice(self, text):
        self.notice.configure(text=text)

    def _guard_permissions(self, allow_busy=False):
        if not self._policy_ready:
            self._notice('請等待已保存的權限載入後再變更設定。')
            return False
        if not allow_busy and (getattr(self.parent, 'is_running', False) or getattr(self.parent, 'current_downloading_model', None)
                or getattr(self.parent, '_storage_current_target', None)):
            self._notice('請等待 GUI 轉錄或模型下載結束後再變更權限。')
            return False
        return True

    def _submit(self, operation, done):
        if self.closed or self.busy:
            if not self.closed:
                self._notice('正在處理上一個操作，請稍候。')
            return
        self.busy = True
        self._notice('正在處理…')
        def work():
            try:
                self.events.put((done, operation(), None))
            except Exception as error:
                self.events.put((done, None, error))
        worker = threading.Thread(target=work, daemon=True)
        self.workers.append(worker)
        worker.start()

    def _poll(self):
        if self.closed:
            return
        while True:
            try:
                done, result, error = self.events.get_nowait()
            except queue.Empty:
                break
            self.busy = False
            if error:
                self._notice(str(error))
            else:
                done(result)
        self.workers = [worker for worker in self.workers if worker.is_alive()]
        if not self.busy and self._jobs_due is not None and time.monotonic() >= self._jobs_due:
            self.refresh_jobs()
        self._timer = self.top.after(50, self._poll)

    def load_policy(self):
        def display(policy):
            self.enabled.set(policy['enabled'])
            self.roots = [Path(root['path']) for root in policy['roots']]
            self._render_roots()
            self._policy_ready = True
            self.master_switch.configure(state='normal')
            self._notice('目前已啟用。' if policy['enabled'] else '目前未啟用。')
        self._submit(self.state.policy, display)

    def choose_root(self):
        if self._guard_permissions():
            path = self.filedialog.askdirectory(parent=self.top, title='允許 AI 工具存取的資料夾')
            if path:
                self.add_root(Path(path))

    def add_root(self, path):
        if not self._guard_permissions():
            return
        path = Path(path)
        if path not in self.roots:
            self.roots.append(path)
        self._render_roots()

    def _render_roots(self):
        for child in self.roots_frame.winfo_children():
            child.destroy()
        for path in self.roots:
            row = self.ctk.CTkFrame(self.roots_frame, fg_color='transparent')
            row.pack(fill='x', pady=3)
            self.button(row, '移除', lambda p=path: self.remove_root(p)).pack(side='right', padx=4)
            label = self.ctk.CTkLabel(row, text=str(path), wraplength=480, justify='left', anchor='w')
            label.pack(side='left', fill='x', expand=True, padx=4)
            wrap_to_width(label)

    def remove_root(self, path):
        if self._guard_permissions(allow_busy=True):
            self.roots.remove(path)
            self._render_roots()

    def apply_policy(self):
        if not self._guard_permissions(allow_busy=True):
            return
        from mcp_runtime import enable
        roots, enabled = list(self.roots), self.enabled.get()
        # Capture all Tk values here. Workers never call a Tk variable getter.
        options = {}
        for key, attribute in (('device', 'device_var'), ('cache_dir', 'model_path_var')):
            variable = getattr(self.parent, attribute, None)
            if variable is not None:
                options[key] = variable.get()
        if hasattr(self.parent, 'get_clean_model_name'):
            options['model'] = self.parent.get_clean_model_name()
        def operation():
            if enabled:
                return enable(self.state, roots, owner=self.parent, **options)
            return self.state.disable(stop_mode='cancel')
        self._submit(operation, lambda policy: self._notice('權限已儲存；工具實際連線尚未驗證。'))

    def disable_access(self):
        from mcp_runtime import disable
        mode = 'finish' if self.stop_mode.get() == '完成已接受工作' else 'cancel'
        def done(policy):
            self.enabled.set(False)
            self._notice('已立即停用新存取；' + ('已接受工作將完成。' if mode == 'finish' else '已接受工作將安全取消。'))
        self._submit(lambda: disable(self.state, stop_mode=mode), done)

    def detect_clients(self):
        from mcp_clients import discover_clients
        def display(rows):
            for result in rows:
                row = self.client_rows[result['id']]
                row.update({key: value for key, value in result.items() if key not in ('label', 'name')})
                text = ('發現安裝位置' if result['installation_detected'] else '未發現已知安裝位置')
                text += '；' + ('已有設定檔' if result['configuration_detected'] else '未發現設定檔')
                text += '。未驗證發行者、版本或實際連線。'
                if result.get('manual_reason'):
                    text += '\n' + result['manual_reason']
                if result['config_path']:
                    text += '\n' + result['config_path']
                row['label'].configure(text=text)
            self._notice('偵測完成；安裝位置、設定檔與實際連線是不同狀態。')
        self._submit(discover_clients, display)

    def choose_config(self):
        self._target(choose=True)

    def _target(self, choose=False):
        client_id = self.client.get()
        row = self.client_rows[client_id]
        if client_id in ('generic', 'windsurf', 'claude-desktop'):
            self._notice('此工具請使用手動設定；Claude Desktop 請匯出 MCPB。')
            return None
        path = row.get('selected_config') or row['config_path']
        if choose or not path or (row.get('can_apply') is False and not row.get('selected_config')):
            if row.get('manual_reason'):
                self._notice(row['manual_reason'] + '；請明確選取此工具使用的設定檔。')
            path = self.filedialog.asksaveasfilename(parent=self.top, title='選取工具使用的設定檔',
                                                   confirmoverwrite=False)
            if path:
                row['selected_config'] = path
                row['label'].configure(text='已明確選取設定檔：\n' + path + '\n格式仍須預覽驗證；實際連線未驗證。')
        if not path:
            return None
        return client_id, path

    def configure_client(self):
        if not self._guard_permissions():
            return
        target = self._target()
        if target is None:
            return
        from mcp_clients import preview_connection, apply_connection
        from mcp_runtime import connection_command
        client_id, path = target
        draft_scope = '\n'.join(str(root) for root in self.roots) or '未指定'
        def preview():
            plan = preview_connection(client_id, path, connection_command(self.state), state_dir=self.state.path)
            return plan, self.state.policy()
        def confirm(result):
            plan, policy = result
            actual_scope = '\n'.join(root['path'] for root in policy['roots']) or '無'
            details = json.dumps({'before': plan['entry_before'], 'after': plan['entry_after']}, ensure_ascii=False, indent=2)
            self._output(details)
            text = (f"工具：{self.client_rows[client_id]['name']}\n設定檔：{path}\n"
                    f"目前有效資料夾（{'啟用' if policy['enabled'] else '停用'}）：\n{actual_scope}\n"
                    f"視窗待套用資料夾：\n{draft_scope}\n\n{details}\n\n"
                    f"備份：{plan['backup_plan']}\n完整設定備份可能包含其他伺服器的秘密；私人儲存不是加密。\n是否寫入此工具的設定？")
            if self.messagebox.askyesno('確認 AI 工具與資料夾範圍', text, parent=self.top):
                self._submit(lambda: apply_connection(plan, state_dir=self.state.path),
                             lambda value: self._notice('設定已儲存；請重新載入工具。實際連線未驗證。'))
            else:
                self._notice('已取消；工具設定未變更。')
        self._submit(preview, confirm)

    def remove_client(self):
        target = self._target()
        if target is None:
            return
        from mcp_clients import remove_connection
        client_id, path = target
        if self.messagebox.askyesno('移除本程式管理的設定', f'{self.client_rows[client_id]["name"]}\n{path}\n移除本程式的連接項目？', parent=self.top):
            self._submit(lambda: remove_connection(client_id, path, state_dir=self.state.path),
                         lambda value: self._notice('本程式管理的連接項目已移除。'))

    def _output(self, text):
        self.output.delete('1.0', 'end')
        self.output.insert('1.0', text)

    def show_manual(self):
        from mcp_clients import manual_configuration
        from mcp_runtime import connection_command
        client_id = self.client.get()
        def done(text):
            self._output(text)
            self._notice('可選取並複製手動設定；工具實際連線尚未驗證。')
        self._submit(lambda: manual_configuration(client_id, connection_command(self.state)), done)

    def test_connection(self):
        from mcp_runtime import connection_command
        from mcp_transport import probe_connection
        def done(result):
            self._output(json.dumps(result, ensure_ascii=False, indent=2))
            self._notice('本機 STDIO 自我測試通過；工具實際連線尚未驗證。' if result.get('connected')
                         else '本機 STDIO 自我測試失敗；請查看詳細資訊。')
        self._submit(lambda: probe_connection(self.state.path, command=connection_command(self.state)), done)

    def repair_launcher(self):
        from mcp_runtime import connection_command
        self._submit(lambda: connection_command(self.state, repair=True),
                     lambda value: self._notice('啟動檔已驗證；工具實際連線尚未驗證。'))

    def export_bundle(self):
        from mcp_clients import export_mcpb
        from mcp_runtime import connection_command
        path = self.filedialog.asksaveasfilename(parent=self.top, title='匯出新的 MCPB 檔案', defaultextension='.mcpb')
        if path:
            self._submit(lambda: export_mcpb(Path(path), connection_command(self.state)),
                         lambda value: self._notice('MCPB 已匯出；請在 Claude Desktop 審閱並安裝，尚未驗證實際連線。'))

    def refresh_jobs(self):
        self._jobs_due = time.monotonic() + 2
        def display(jobs):
            for child in self.jobs_frame.winfo_children():
                child.destroy()
            for job in jobs:
                row = self.ctk.CTkFrame(self.jobs_frame, fg_color='transparent')
                row.pack(fill='x', pady=3)
                if job['state'] not in _TERMINAL:
                    self.button(row, '取消工作', lambda key=job['id']: self.cancel_job(key)).pack(side='right')
                elif job['state'] == 'succeeded' and job.get('result', {}).get('index_path'):
                    self.button(row, '開啟結果', lambda key=job['id']: self.open_result(key)).pack(side='right')
                details = f"{job['id']}\n{job['state']}"
                if job.get('stage'):
                    details += ' · ' + job['stage']
                if job.get('error'):
                    details += '\n' + job['error'].get('code', '') + ': ' + job['error'].get('message', '')[:400]
                label = self.ctk.CTkLabel(row, text=details, justify='left', anchor='w')
                label.pack(fill='x', expand=True)
                wrap_to_width(label)
            self._notice(f'共有 {len(jobs)} 個工作。關閉設定視窗不會停止已接受的工作。')
        self._submit(lambda: self.state.records('jobs'), display)

    def open_result(self, job_id):
        from mcp_runtime import open_job_result
        self._submit(lambda: open_job_result(self.state, job_id),
                     lambda value: self._notice('已驗證授權與成果，並要求瀏覽器開啟。'))

    def cleanup_work(self):
        from mcp_cleanup import preview_cleanup, apply_cleanup
        def confirm(plan):
            text = (f"位置：{plan['location']}\n大小：{plan['bytes']} bytes\n"
                    '範圍：所有私人工作副本、原文逐字稿、未完成翻譯與完成翻譯、工作歷史、AI 重試 ID。\n'
                    '這些資料互相依賴，無法只保留部分草稿；請先完成或匯出要保留的資料。\n'
                    '原片、已發布播放器、模型、權限、連接設定及客戶端備份均保留。\n'
                    '需先停用 MCP 並等待工作及模型程序正常結束。刪除無法復原。\n'
                    + ('上次清理中斷；是否繼續？' if plan['resume'] else '是否清除上述全部私人工作資料？'))
            if self.messagebox.askyesno('確認清理私人工作資料', text, parent=self.top):
                self._submit(lambda: apply_cleanup(self.state, plan, consent=True),
                             lambda result: self._notice(f"已清理私人工作資料（{result['removed_bytes']} bytes）；保留原片、成果、模型與備份。"))
            else:
                self._notice('已取消清理；私人工作資料保留。')
        self._submit(lambda: preview_cleanup(self.state), confirm)

    def cancel_job(self, job_id):
        self._submit(lambda: self.state.cancel_job(job_id),
                     lambda value: self._notice('已請求安全取消；等待目前模型操作結束。'))

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.top.after_cancel(self._timer)
        self.top.destroy()
