"""Small subtitle-only editor for an existing OpenCam web player."""
from pathlib import Path
import queue
import webbrowser

import opencam_integration as opencam
from ui_drop import dropped_paths, register_file_drop
from ui_theme import BACKGROUND, CARD, BORDER, TEXT, MUTED, ACCENT, HOVER, ui_font, wrap_to_width
from web_export_dialog import ExportJob
from web_export_form import ExportFormState, language_code, language_label
from web_export_model import SubtitleSource, canonical_language


def offer_completed_projects(parent, projects, language='', *, ask=None, open_dialog=None):
    """Ask once per detected source project, never silently write a player."""
    if not projects:
        return
    if ask is None:
        from tkinter import messagebox
        ask = messagebox.askyesno
    open_dialog = open_dialog or OpenCamSubtitleDialog
    grouped = {}
    for folder, subtitle in projects:
        grouped.setdefault(folder, []).append(SubtitleSource(Path(subtitle), language))
    for folder, subtitles in grouped.items():
        if ask('OpenCam 字幕置入', f'偵測到 OpenCam 網頁播放器：{Path(folder).name}\n\n'
               '是否要將本次字幕置入原播放器？\n'
               '接著可確認語系，再按「備份並置入字幕」。\n'
               '同語系更新、其他語系保留；原檔會先備份，影片與章節不變。', parent=parent):
            open_dialog(parent, folder=folder, subtitles=tuple(subtitles))


class OpenCamFormState(ExportFormState):
    def __init__(self):
        super().__init__()
        self.project = None

    def select_project(self, folder, subtitles=()):
        project = opencam.load_project(folder)
        if self.project is None or self.project.folder != project.folder:
            self.tracks.clear()
        self.project = project
        self.video = project.video
        for source in subtitles:
            if source.language:
                self.add_track(source.path, source.language)
            else:
                self.add_subtitle(source.path)
        self.offer_candidates(opencam.subtitle_candidates(project.folder))

    def add_subtitle(self, path):
        path = Path(path)
        if path.suffix.lower() not in ('.srt', '.vtt'):
            raise ValueError('只接受 SRT／VTT 字幕')
        code = 'und'
        if self.video and path.stem.startswith(self.video.stem + '.'):
            code = language_code(path.stem[len(self.video.stem) + 1:]) or 'und'
        self.add_track(path, code)

    def request(self):
        if self.project is None or not self.tracks:
            raise ValueError('請選擇 OpenCam 專案並加入字幕')
        sources = tuple(SubtitleSource(t.path, canonical_language(t.language)) for t in self.tracks)
        if len({s.language for s in sources}) != len(sources):
            raise ValueError('字幕語系不可重複；同語系請只保留一個檔案')
        return self.project.folder, sources


class OpenCamSubtitleDialog:
    def __init__(self, parent, *, folder=None, subtitles=()):
        import tkinter as tk
        from tkinter import filedialog, messagebox
        import customtkinter as ctk
        self.ctk, self.tk = ctk, tk
        self.filedialog, self.messagebox = filedialog, messagebox
        self.state = OpenCamFormState()
        self.job = None
        self.result = None
        self.action_issue = ''
        self.inputs = []
        self.controls = []
        self.top = ctk.CTkToplevel(parent)
        self.top.withdraw()
        self.top.title('OpenCam 字幕置入')
        self.top.geometry('760x650')
        self.top.minsize(640, 520)
        self.top.configure(fg_color=BACKGROUND)
        self.top.protocol('WM_DELETE_WINDOW', self.close)
        header = ctk.CTkFrame(self.top, fg_color='transparent')
        header.pack(fill='x', padx=28, pady=(24, 12))
        ctk.CTkLabel(header, text='OpenCam 字幕置入', font=ui_font(size=25, weight='bold'),
                     text_color=TEXT).pack(anchor='w')
        ctk.CTkLabel(header, text='保留原播放器，讓字幕與逐字稿直接就位。', text_color=MUTED).pack(anchor='w', pady=(4, 0))
        footer = ctk.CTkFrame(self.top, fg_color=CARD)
        footer.pack(side='bottom', fill='x')
        self.notice = ctk.CTkLabel(footer, text='選擇或拖入 OpenCam 資料夾／media.mp4。',
                                 justify='left', anchor='w', text_color=MUTED)
        self.notice.pack(fill='x', padx=24, pady=(14, 8))
        wrap_to_width(self.notice)
        bar = ctk.CTkFrame(footer, fg_color='transparent')
        bar.pack(fill='x', padx=24, pady=(0, 18))
        self.preview_button = ctk.CTkButton(bar, text='預覽播放器', height=38, command=self.preview, state='disabled')
        self.preview_button.pack(side='left')
        self.submit_button = ctk.CTkButton(bar, text='備份並置入字幕', height=40,
                                         fg_color=ACCENT, hover_color=HOVER, command=self.submit, state='disabled')
        self.submit_button.pack(side='right')
        ctk.CTkButton(bar, text='關閉', width=76, height=38, command=self.close,
                     fg_color='transparent', text_color=TEXT).pack(side='right', padx=12)
        form = ctk.CTkScrollableFrame(self.top, fg_color='transparent')
        form.pack(fill='both', expand=True, padx=20, pady=(0, 12))
        source = ctk.CTkFrame(form, fg_color=CARD, corner_radius=14, border_width=1, border_color=BORDER)
        source.pack(fill='x', pady=(0, 12))
        ctk.CTkLabel(source, text='01   OpenCam 專案', font=ui_font(size=16, weight='bold')).pack(anchor='w', padx=18, pady=(16, 6))
        select = ctk.CTkButton(source, text='選擇資料夾…', height=40, command=self.choose_project)
        select.pack(fill='x', padx=18, pady=(0, 10))
        self.controls.append(select)
        self.project_info = ctk.CTkLabel(source, text='需包含 index.html、media.mp4 與 opencam-player.js',
                                       anchor='w', justify='left', text_color=MUTED)
        self.project_info.pack(fill='x', padx=18, pady=(0, 16))
        wrap_to_width(self.project_info)
        card = ctk.CTkFrame(form, fg_color=CARD, corner_radius=14, border_width=1, border_color=BORDER)
        card.pack(fill='x')
        ctk.CTkLabel(card, text='02   要置入的字幕', font=ui_font(size=16, weight='bold')).pack(anchor='w', padx=18, pady=(16, 6))
        hint = ctk.CTkLabel(card, text='自動讀取 media.srt／media.zh-TW.srt 等同名字幕，也可手動加入多個語系。\n'
                            '同語系更新、其他語系保留；原預設字幕不變。未標示語系的檔案可在下方修改。',
                            anchor='w', justify='left', text_color=MUTED)
        hint.pack(fill='x', padx=18, pady=(0, 10))
        wrap_to_width(hint)
        self.tracks_frame = ctk.CTkFrame(card, fg_color='transparent')
        self.tracks_frame.pack(fill='x', padx=18)
        add = ctk.CTkButton(card, text='加入 SRT／VTT 字幕…', height=36, command=self.choose_subtitles)
        add.pack(anchor='w', padx=18, pady=(10, 18))
        self.controls.append(add)
        if folder:
            self.select_project(folder, subtitles)
        else:
            self.render()
        register_file_drop(self.top, self.on_drop)
        self.top.deiconify()

    def select_project(self, folder, subtitles=()):
        if self.job: return
        try:
            self.commit_languages()
            self.state.select_project(folder, subtitles)
            self.result = None
            self.notice.configure(text='已就緒；只更新字幕資料，影片與章節不會變更。', text_color=MUTED)
            self.render()
        except (OSError, ValueError, UnicodeError, RecursionError) as error:
            self.notice.configure(text=str(error), text_color=('#B3261E', '#FF9C95'))

    def choose_project(self):
        path = self.filedialog.askdirectory(parent=self.top, title='選擇 OpenCam 網頁播放器資料夾')
        if path: self.select_project(path)

    def choose_subtitles(self):
        paths = self.filedialog.askopenfilenames(parent=self.top, title='加入字幕',
                                                filetypes=[('字幕檔', '*.srt *.vtt')])
        self.add_subtitles(paths)

    def add_subtitles(self, paths):
        if self.job: return
        try:
            self.commit_languages()
            for path in paths: self.state.add_subtitle(path)
            self.notice.configure(text='確認語系後，按「備份並置入字幕」。', text_color=MUTED)
        except ValueError as error:
            self.notice.configure(text=str(error), text_color=('#B3261E', '#FF9C95'))
        self.render()

    def on_drop(self, event):
        if self.job: return 'break'
        paths = dropped_paths(self.top, event.data)
        subtitles = []
        for path in paths:
            if Path(path).suffix.lower() in ('.srt', '.vtt'):
                subtitles.append(path)
            else:
                detected, folder = opencam.detect_opencam_project(path)
                if detected: self.select_project(folder)
                else: self.notice.configure(text='不是支援的 OpenCam 專案，請拖入資料夾或 media.mp4。')
        if subtitles: self.add_subtitles(subtitles)
        return 'break'

    def commit_languages(self):
        for track, variable in self.inputs:
            track.language = language_code(variable.get())
            track.automatic = False

    def refresh_action(self, *_):
        self.commit_languages()
        try:
            self.state.request()
            enabled = not self.job
        except ValueError as error:
            enabled = False
            self.action_issue = str(error)
            self.notice.configure(text=self.action_issue,
                                  text_color=('#B3261E', '#FF9C95') if self.state.tracks else MUTED)
        else:
            if self.action_issue:
                self.action_issue = ''
                self.notice.configure(text='已就緒，按「備份並置入字幕」即可。', text_color=MUTED)
        self.submit_button.configure(state='normal' if enabled else 'disabled')

    def render(self):
        project = self.state.project
        if project:
            existing = (project.data.get('subtitles') or {}).get('tracks', [])
            langs = '、'.join(t['language'] for t in existing) or '尚未夾帶字幕'
            self.project_info.configure(text=f"{project.data['title']}\n{project.folder}\n"
                                       f"{len(project.data['chapters'])} 個章節 · 原字幕：{langs}")
        self.preview_button.configure(state='normal' if project and not self.job else 'disabled')
        for child in self.tracks_frame.winfo_children(): child.destroy()
        self.inputs = []
        codes = ['und', 'zh-TW', 'zh-CN', 'en', 'ja', 'ko', 'vi', 'id', 'th', 'my', 'es', 'pt', 'ru', 'fr', 'de']
        for track in self.state.tracks:
            row = self.ctk.CTkFrame(self.tracks_frame, fg_color='transparent')
            row.pack(fill='x', pady=4)
            remove = self.ctk.CTkButton(row, text='移除', width=54, height=32,
                                      command=lambda t=track: self.remove(t))
            remove.pack(side='right')
            variable = self.tk.StringVar(master=self.top, value=language_label(track.language))
            combo = self.ctk.CTkComboBox(row, width=132, height=32, variable=variable,
                                        values=[language_label(c) for c in codes], command=self.refresh_action)
            combo.pack(side='right', padx=8)
            combo.bind('<FocusOut>', self.refresh_action)
            combo.bind('<Return>', self.refresh_action)
            label = self.ctk.CTkLabel(row, text=track.path.name, anchor='w', justify='left')
            label.pack(side='left', fill='x', expand=True)
            wrap_to_width(label)
            self.inputs.append((track, variable))
        if not self.state.tracks:
            self.ctk.CTkLabel(self.tracks_frame, text='尚未找到外部字幕；可轉錄 media.mp4，或手動加入字幕。',
                              text_color=MUTED).pack(anchor='w', pady=8)
        self.refresh_action()
        register_file_drop(self.tracks_frame, self.on_drop)

    def remove(self, track):
        if self.job: return
        self.commit_languages()
        self.state.remove_track(track)
        self.render()

    def submit(self):
        if self.job: return
        self.commit_languages()
        try:
            folder, sources = self.state.request()
        except ValueError as error:
            self.notice.configure(text=str(error), text_color=('#B3261E', '#FF9C95'))
            return
        self.job = ExportJob(lambda progress, cancelled: opencam.insert_subtitles(folder, sources))
        self.set_busy(True)
        self.notice.configure(text='正在驗證字幕、備份原檔並置入…', text_color=MUTED)
        self.top.after(50, self.poll)

    def set_busy(self, busy):
        for control in self.controls: control.configure(state='disabled' if busy else 'normal')
        def freeze(widget):
            for child in widget.winfo_children():
                if isinstance(child, (self.ctk.CTkButton, self.ctk.CTkComboBox)):
                    child.configure(state='disabled' if busy else 'normal')
                else: freeze(child)
        freeze(self.tracks_frame)
        self.submit_button.configure(state='disabled' if busy else 'normal')
        self.preview_button.configure(state='disabled' if busy else ('normal' if self.state.project else 'disabled'))

    def poll(self):
        try:
            kind, result = self.job.events.get_nowait()
        except queue.Empty:
            self.top.after(50, self.poll)
            return
        self.job = None
        self.set_busy(False)
        if kind == 'success':
            self.result = result
            self.state.project = opencam.load_project(result.index_path.parent)
            self.render()
            self.notice.configure(text=f"已置入 {len(result.languages)} 軌字幕（{'、'.join(result.languages)}）。\n"
                                  f'原檔備份：{result.backup_path.name}', text_color=ACCENT)
        else:
            self.notice.configure(text=f'置入失敗：{result}\n原播放器未被截斷；請確認權限或檔案占用後重試。',
                                  text_color=('#B3261E', '#FF9C95'))

    def preview(self):
        if self.state.project and not self.job:
            webbrowser.open((self.state.project.folder / 'index.html').as_uri())

    def close(self):
        if self.job:
            self.notice.configure(text='正在安全寫入，完成後即可關閉。')
            return
        self.top.destroy()
