"""Local MCP settings. Workers communicate with Tk exclusively through a queue."""
import json
from pathlib import Path
import queue
import threading
import time

from mcp_state import MCPError, State
from ui_theme import ui_font, wrap_to_width, secondary_button_style, ACCENT, HOVER, MUTED, SURFACE, BACKGROUND, BORDER, CARD

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
        from ui_flow import AutoHideScrollableFrame
        from tkinter import filedialog, messagebox
        self.parent, self.ctk = parent, ctk
        self.filedialog, self.messagebox = filedialog, messagebox
        self.state = state if state is not None else State()  # pure path construction
        self.roots, self.workers, self.actions = [], [], []
        self.events = queue.Queue()
        self.busy = self.closed = False
        self._policy_ready = False
        self._jobs_due = None
        self._jobs_signature = None
        self._expanded_jobs = set()
        from ui_windows import DialogWindow, show_dialog
        self.top = DialogWindow(parent)
        self.top.title('AI 工具連接')
        self.top.geometry('860x820')
        self.top.minsize(680, 580)
        self.top.protocol('WM_DELETE_WINDOW', self.close)
        self.enabled = tk.BooleanVar(master=self.top, value=False)
        self.restricted = tk.BooleanVar(master=self.top, value=False)
        self.client = tk.StringVar(master=self.top, value='generic')
        self.stop_mode = tk.StringVar(master=self.top, value='取消已接受工作')
        header = ctk.CTkFrame(self.top, fg_color='transparent')
        header.pack(fill='x', padx=18, pady=(16, 8))
        ctk.CTkLabel(header, text='AI 工具連接', font=ui_font(size=22, weight='bold')).pack(side='left')
        self.connection_status = ctk.CTkLabel(header, text='讀取中', corner_radius=12,
                                              fg_color=SURFACE, width=110, height=30)
        self.connection_status.pack(side='right')
        ctk.CTkLabel(self.top, text='讓 AI 幫你轉字幕、翻譯多國語言，再產生網頁播放器。',
                     text_color=MUTED, anchor='w').pack(fill='x', padx=22, pady=(0, 6))
        # Reserve bottom actions before packing expanding content, even on a
        # short desktop. Client details and long roots remain scrollable.
        footer = ctk.CTkFrame(self.top, fg_color='transparent')
        footer.pack(side='bottom', fill='x', padx=18, pady=(4, 12))
        self.notice = ctk.CTkLabel(footer, text='正在讀取已保存的權限…',
                                  justify='left', anchor='w', wraplength=700)
        self.notice.pack(fill='x', pady=(0, 8))
        wrap_to_width(self.notice)
        self.button(footer, '關閉', self.close).pack(side='right')
        self.tabs = ctk.CTkTabview(self.top, corner_radius=14)
        self.tabs.configure(command=lambda: setattr(self, '_jobs_due', 0) if self.tabs.get() == '工作狀態' else None)
        self.tabs.pack(fill='both', expand=True, padx=18, pady=4)
        self.pages = {}
        for name in ('開始連接', '工作狀態', '進階管理'):
            tab = self.tabs.add(name)
            # The tabview owns page dimensions. Wrapped text in an inactive
            # page must not resize the tabview and feed back into its own wrap.
            tab.pack_propagate(False)
            page = AutoHideScrollableFrame(tab, fg_color=BACKGROUND)
            page.pack(fill='both', expand=True)
            self.pages[name] = page
        self.form = self.pages['開始連接']
        permissions = self.section(self.form, '1', '啟用 AI 連接', '啟用後，直接在 AI 對話指定影片或字幕路徑即可。')
        self.master_switch = ctk.CTkSwitch(permissions, text='啟用 AI 連接（套用後生效）',
                                          variable=self.enabled, state='disabled')
        self.master_switch.pack(anchor='w', padx=16, pady=(8, 4))
        scope = self.section(self.pages['進階管理'], '', '資料夾限制（選用）', '一般模式可處理目前使用者有權讀取的影音與字幕；需要縮小範圍時再開啟限制。')
        ctk.CTkSwitch(scope, text='僅允許指定資料夾', variable=self.restricted).pack(anchor='w', padx=16, pady=8)
        self.roots_frame = ctk.CTkFrame(scope, fg_color='transparent', height=1)
        self.roots_frame.pack(fill='x', padx=12, pady=4)
        self._render_roots()
        row = ctk.CTkFrame(permissions, fg_color='transparent', height=1)
        row.pack(fill='x', padx=16, pady=4)
        self.button(scope, '＋ 加入資料夾', self.choose_root).pack(anchor='w', padx=16, pady=4)
        self.button(scope, '套用資料夾限制', self.apply_policy).pack(anchor='e', padx=16, pady=8)
        self.primary_button(row, '套用權限', self.apply_policy).pack(side='right')
        self.privacy_notice = ctk.CTkLabel(permissions,
            text='一般模式可處理目前使用者有權讀取的影音與字幕，無須預先加入資料夾。\n轉錄在本機執行；AI 工具可能將字幕傳送至雲端，私人儲存不是加密。需要限制範圍可至「進階管理」設定。',
            text_color=MUTED, font=ui_font(size=12), height=1,
            justify='left', anchor='w', wraplength=660)
        self.privacy_notice.pack(fill='x', padx=16, pady=(6, 12))
        wrap_to_width(self.privacy_notice)
        tools = self.section(self.form, '2', '連接你的 AI 工具', '選擇工具、偵測設定位置，再確認寫入連接設定。')
        row = ctk.CTkFrame(tools, fg_color='transparent', height=1)
        row.pack(fill='x', padx=16, pady=(8, 4))
        self.client_picker = ctk.CTkOptionMenu(row, values=[name for _, name in _CLIENTS],
                                               command=self._select_client, width=230, height=34)
        self.client_picker.set(dict(_CLIENTS)[self.client.get()])
        self.client_picker.pack(side='left')
        self.button(row, '偵測工具', self.detect_clients).pack(side='right')
        self.client_details = ctk.CTkFrame(tools, fg_color='transparent', height=1)
        self.client_details.pack(fill='x', padx=16, pady=4)
        self.client_rows = {}
        for client_id, name in _CLIENTS:
            label = ctk.CTkLabel(self.client_details, text='尚未偵測。請按「偵測工具」尋找安裝與設定位置。',
                                  text_color=MUTED, anchor='w', justify='left', wraplength=620, height=1)
            wrap_to_width(label)
            self.client_rows[client_id] = {'name': name, 'label': label, 'config_path': None}
        self.client_action = self.primary_button(tools, '顯示手動設定', self.connect_selected)
        self.client_action.pack(anchor='e', padx=16, pady=(4, 12))
        self.client.trace_add('write', self._client_changed)
        self._client_changed()
        verify = self.section(self.form, '3', '確認連接，開始使用', '完成設定後，重新啟動或重新載入 AI 工具。')
        self.button(verify, '測試本機連接', self.test_connection).pack(anchor='w', padx=16, pady=8)
        self.description(verify, '通過測試後，回到 AI 對話提供影片完整路徑，並說：\n「請將這部影片轉成繁體中文字幕。」\n本機測試不代表 AI 工具已完成連接，仍需在 AI 工具中確認。')
        jobs = self.pages['工作狀態']
        self.description(jobs, '查看 AI 發起的工作、取消處理中的工作，或開啟已完成的網頁。')
        self.button(jobs, '更新工作狀態', self.refresh_jobs).pack(anchor='w', padx=16, pady=8)
        self.jobs_frame = ctk.CTkFrame(jobs, fg_color='transparent', height=1)
        self.jobs_frame.pack(fill='x', padx=12, pady=8)
        self.description(self.jobs_frame, '尚未載入工作。按「更新工作狀態」查看。')
        advanced = self.pages['進階管理']
        config = self.section(advanced, '', '工具設定與修復', '套用至「開始連接」目前選取的 AI 工具。')
        self.action_grid(config, (('選取其他設定檔', self.choose_config), ('手動設定', self.show_manual),
                                 ('匯出 Claude MCPB', self.export_bundle), ('修復啟動檔', self.repair_launcher),
                                 ('移除工具設定', self.remove_client), ('重新讀取權限', self.load_policy)))
        access = self.section(advanced, '', '停用連接', '停用後，AI 無法再開始新工作。請選擇如何處理已接受的工作。')
        ctk.CTkOptionMenu(access, variable=self.stop_mode,
                         values=['取消已接受工作', '完成已接受工作']).pack(anchor='w', padx=16, pady=8)
        self.button(access, '停用存取', self.disable_access).pack(anchor='w', padx=16, pady=(0, 12))
        storage = self.section(advanced, '', '私人工作資料', '清理僅移除 AI 工作副本與歷史；保留原始檔案、模型與已輸出的網頁。')
        location = ctk.CTkLabel(storage, text=f'儲存位置：{self.state.path}',
                               justify='left', anchor='w', wraplength=660)
        location.pack(fill='x', padx=16, pady=8)
        wrap_to_width(location)
        self.button(storage, '清理私人工作資料…', self.cleanup_work).pack(anchor='w', padx=16, pady=(0, 12))
        self.details_window = self.output = None
        self._timer = self.top.after(50, self._poll)
        # Opening this explicit settings UI authorizes an offline policy read.
        # App startup still does not construct the dialog or access MCP state.
        self.load_policy()
        show_dialog(self.top, parent, 860, 820)

    def description(self, parent, text):
        label = self.ctk.CTkLabel(parent, text=text, text_color=MUTED, justify='left', anchor='w', wraplength=620, height=1, font=ui_font(size=12))
        label.pack(fill='x', padx=16, pady=(2, 6))
        wrap_to_width(label)
        return label

    def section(self, parent, number, title, hint):
        card = self.ctk.CTkFrame(parent, corner_radius=12, height=1, border_width=1, border_color=BORDER)
        card.pack(fill='x', padx=2, pady=(0, 10))
        self.ctk.CTkLabel(card, text=(f'{number}  ' if number else '') + title,
                          font=ui_font(size=16, weight='bold'), anchor='w').pack(fill='x', padx=16, pady=(10, 0))
        self.description(card, hint)
        return card

    def primary_button(self, parent, text, command):
        button = self.button(parent, text, command)
        button.configure(fg_color=ACCENT, hover_color=HOVER, text_color='white', border_width=0)
        return button

    def action_grid(self, parent, actions):
        row = self.ctk.CTkFrame(parent, fg_color='transparent', height=1)
        row.pack(fill='x', padx=12, pady=(0, 12))
        row.grid_columnconfigure((0, 1), weight=1)
        for index, (text, command) in enumerate(actions):
            self.button(row, text, command).grid(row=index // 2, column=index % 2, sticky='ew', padx=4, pady=4)

    def _select_client(self, name):
        self.client.set(next(key for key, label in _CLIENTS if label == name))

    def _client_changed(self, *_):
        key = self.client.get()
        for row in self.client_rows.values():
            row['label'].pack_forget()
        self.client_rows[key]['label'].pack(fill='x')
        self.client_picker.set(self.client_rows[key]['name'])
        title = ('匯出 Claude 安裝檔…' if key == 'claude-desktop' else
                 '顯示手動設定' if key in ('generic', 'windsurf') else '設定此工具…')
        self.client_action.configure(text=title)

    def connect_selected(self):
        key = self.client.get()
        if key == 'claude-desktop':
            self.export_bundle()
        elif key in ('generic', 'windsurf'):
            self.show_manual()
        else:
            self.configure_client()

    def button(self, parent, text, command):
        button = self.ctk.CTkButton(parent, text=text, command=command, width=100, height=32,
                                   **secondary_button_style())
        button._canvas.configure(takefocus=1)
        button.bind('<Return>', lambda event: button.invoke())
        button.bind('<space>', lambda event: button.invoke())
        self.actions.append(button)
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

    def _submit(self, operation, done, *, quiet=False):
        if self.closed or self.busy:
            if not self.closed:
                self._notice('正在處理上一個操作，請稍候。')
            return
        self.busy = True
        if not quiet:
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
            self.restricted.set(policy.get('options', {}).get('access_mode', 'restricted' if policy['generation'] else 'general') == 'restricted')
            self.roots = [Path(root['path']) for root in policy['roots']]
            self._render_roots()
            self._policy_ready = True
            self.master_switch.configure(state='normal')
            self.connection_status.configure(text='已啟用' if policy['enabled'] else '尚未啟用')
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
        if not self.roots:
            self.description(self.roots_frame, '尚未加入資料夾。請選擇存放影片或字幕的資料夾。')
        for path in self.roots:
            row = self.ctk.CTkFrame(self.roots_frame, fg_color='transparent', height=1)
            row.pack(fill='x', pady=3)
            row.grid_columnconfigure(0, weight=1)
            self.button(row, '移除', lambda p=path: self.remove_root(p)).grid(row=0, column=1, padx=4)
            label = self.ctk.CTkLabel(row, text=str(path), width=1, wraplength=360, justify='left', anchor='w')
            label.grid(row=0, column=0, sticky='ew', padx=4)

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
        options = {'access_mode': 'restricted' if self.restricted.get() else 'general'}
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
        def done(policy):
            self.connection_status.configure(text='已啟用' if policy['enabled'] else '尚未啟用')
            self._notice('權限已儲存。下一步：選擇 AI 工具並設定連接。' if policy['enabled'] else '權限已儲存，目前未啟用。')
        self._submit(operation, done)

    def disable_access(self):
        from mcp_runtime import disable
        mode = 'finish' if self.stop_mode.get() == '完成已接受工作' else 'cancel'
        def done(policy):
            self.enabled.set(False)
            self.connection_status.configure(text='已停用')
            self._notice('已立即停用新存取；' + ('已接受工作將完成。' if mode == 'finish' else '已接受工作將安全取消。'))
        self._submit(lambda: disable(self.state, stop_mode=mode), done)

    def detect_clients(self):
        from mcp_clients import discover_clients
        def display(rows):
            for result in rows:
                row = self.client_rows[result['id']]
                row.update({key: value for key, value in result.items() if key not in ('label', 'name')})
                text = ('程式：找到安裝資訊' if result['installation_detected'] else '程式：未辨識安裝位置（不代表未安裝）')
                text += '\n設定檔：' + ('已找到，可繼續設定連接' if result['configuration_detected'] else '尚未建立或需自行指定')
                text += '\n連線：尚未驗證，設定後請執行步驟 3。'
                if result.get('manual_reason'):
                    text += '\n' + result['manual_reason']
                if result['config_path']:
                    text += '\n' + result['config_path']
                row['label'].configure(text=text)
            self._notice('偵測完成。已找到設定檔的工具可繼續設定，不必重新安裝。')
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
        draft_scope = ('\n'.join(str(root) for root in self.roots) or '未指定') if self.restricted.get() else '一般模式：直接指定影音或字幕路徑'
        def preview():
            plan = preview_connection(client_id, path, connection_command(self.state), state_dir=self.state.path)
            return plan, self.state.policy()
        def confirm(result):
            plan, policy = result
            actual_scope = '\n'.join(root['path'] for root in policy['roots']) or '無'
            if policy.get('options', {}).get('access_mode') == 'general':
                actual_scope = '一般模式：目前使用者有權讀取的影音與字幕'
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

    def _output(self, text, *, show=False):
        # A separate, non-modal window gives code/results their own scroll area.
        # Never nest a textbox scrollbar inside the setup page's scrollbar.
        if self.details_window is None or not self.details_window.winfo_exists():
            from ui_windows import DialogWindow
            self.details_window = DialogWindow(self.top)
            self.details_window.withdraw()
            self.details_window.title('連接設定與測試詳細資訊')
            self.details_window.geometry('700x480')
            self.details_window.minsize(520, 360)
            self.details_window.transient(self.top)
            self.details_window.protocol('WM_DELETE_WINDOW', self.details_window.withdraw)
            self.ctk.CTkLabel(self.details_window, text='連接設定與測試詳細資訊',
                              font=ui_font(size=20, weight='bold'), anchor='w').pack(fill='x', padx=20, pady=(16, 2))
            self.description(self.details_window, '手動連接時，複製下方設定至對應 AI 工具；測試結果也會顯示於此。')
            controls = self.ctk.CTkFrame(self.details_window, fg_color='transparent')
            controls.pack(side='bottom', fill='x', padx=16, pady=12)
            self.button(controls, '複製內容', self.copy_output).pack(side='left')
            self.button(controls, '關閉', self.details_window.withdraw).pack(side='right')
            self.output = self.ctk.CTkTextbox(self.details_window, wrap='word')
            self.output.pack(fill='both', expand=True, padx=16, pady=(16, 0))
        self.output.configure(state='normal')
        self.output.delete('1.0', 'end')
        self.output.insert('1.0', text)
        self.output.configure(state='disabled')
        if show:
            from ui_windows import show_dialog
            show_dialog(self.details_window, self.top, 700, 480)

    def copy_output(self):
        self.top.clipboard_clear()
        self.top.clipboard_append(self.output.get('1.0', 'end-1c'))
        self._notice('已複製設定內容。')

    def show_manual(self):
        from mcp_clients import manual_configuration
        from mcp_runtime import connection_command
        client_id = self.client.get()
        def done(text):
            self._output(text, show=True)
            self._notice('可選取並複製手動設定；工具實際連線尚未驗證。')
        self._submit(lambda: manual_configuration(client_id, connection_command(self.state)), done)

    def test_connection(self):
        from mcp_runtime import connection_command
        from mcp_transport import probe_connection
        def done(result):
            self._output(json.dumps(result, ensure_ascii=False, indent=2), show=True)
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
            from mcp_jobs import job_card
            signature = json.dumps(jobs, sort_keys=True, ensure_ascii=False)
            if signature == self._jobs_signature:
                return
            self._jobs_signature = signature
            for child in self.jobs_frame.winfo_children():
                child.destroy()
            if not jobs:
                self.description(self.jobs_frame, '目前沒有工作。\n回到 AI 對話提供影片路徑，即可開始產生字幕。')
            for job in jobs:
                card = job_card(job)
                row = self.ctk.CTkFrame(self.jobs_frame, fg_color=CARD, border_width=1, border_color=BORDER)
                row.pack(fill='x', pady=(0, 10))
                header = self.ctk.CTkFrame(row, fg_color='transparent')
                header.pack(fill='x', padx=14, pady=(12, 2))
                self.ctk.CTkLabel(header, text=card['status'], fg_color=SURFACE,
                    corner_radius=10, width=90, height=28).pack(side='right', padx=(8, 0))
                title = self.ctk.CTkLabel(header, text=card['title'], font=ui_font(size=15, weight='bold'), anchor='w', justify='left', width=1, height=1)
                title.pack(side='left', fill='x', expand=True)
                wrap_to_width(title)
                for text in (card['kind'], card['description'], *card['models'], *card['summary_lines'], card['progress_text'], card['timing_text']):
                    if not text:
                        continue
                    label = self.ctk.CTkLabel(row, text=text, anchor='w', justify='left', text_color=MUTED, height=1)
                    label.pack(fill='x', padx=14, pady=3)
                    wrap_to_width(label)
                if card['progress_fraction'] is not None:
                    bar = self.ctk.CTkProgressBar(row, height=5)
                    bar.pack(fill='x', padx=14, pady=(3, 5))
                    bar.set(card['progress_fraction'])
                actions = self.ctk.CTkFrame(row, fg_color='transparent')
                actions.pack(fill='x', padx=14, pady=(6, 10))
                if card['can_cancel']:
                    self.button(actions, '取消工作', lambda key=job['id']: self.cancel_job(key)).pack(side='right')
                if card['can_open']:
                    self.primary_button(actions, '開啟播放器', lambda key=job['id']: self.open_result(key)).pack(side='right')
                technical = self.ctk.CTkLabel(row, text=card['technical'], anchor='w', justify='left', text_color=MUTED, height=1)
                wrap_to_width(technical)
                def toggle(key=job['id'], label=technical):
                    if key in self._expanded_jobs:
                        self._expanded_jobs.remove(key)
                        label.pack_forget()
                    else:
                        self._expanded_jobs.add(key)
                        label.pack(fill='x', padx=14, pady=(0, 12))
                self.button(actions, '詳細資訊', toggle).pack(side='left')
                if job['id'] in self._expanded_jobs:
                    technical.pack(fill='x', padx=14, pady=(0, 12))
            active = sum(job['state'] not in _TERMINAL for job in jobs)
            completed = sum(job['state'] == 'succeeded' for job in jobs)
            self._notice(f'共 {len(jobs)} 個工作 · {active} 個處理中 · {completed} 個已完成。關閉此視窗不影響工作。')
        def load():
            jobs = self.state.records('jobs')
            for job in jobs:
                if job.get('asset_id'):
                    try:
                        asset = self.state.get('assets', job['asset_id'])
                    except MCPError:
                        continue
                    job['display_name'] = Path(asset['relative']).name
                    job['project_type'] = asset.get('project', {}).get('type')
            return jobs
        self._submit(load, display, quiet=True)

    def open_result(self, job_id):
        from mcp_runtime import open_job_result
        self._submit(lambda: open_job_result(self.state, job_id),
                     lambda value: self._notice('已開啟播放器網頁。'))

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
