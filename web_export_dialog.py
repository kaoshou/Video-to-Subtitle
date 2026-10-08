"""Standalone export UI. Workers never call Tk; all results cross a queue."""
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import webbrowser
from ui_theme import install_theme, ui_font, wrap_to_width
from ui_drop import dropped_paths, register_file_drop

from web_export_model import ExportRequest, Metadata, SubtitleSource, canonical_language
from web_export import export_package, inspect_inputs, load_package, probe_video
from web_export_form import ExportFormState, LANGUAGES, language_label, language_code, find_subtitle_candidates, suggested_folder, export_action_state


def completion_video(subtitle, sources):
    subtitle = Path(subtitle)
    source = sources.get(str(subtitle))
    if not source or subtitle.suffix.lower() not in ('.srt', '.vtt'):
        return None
    video = Path(source)
    return video if video.suffix.lower() == '.mp4' and video.is_file() and subtitle.is_file() else None


class ExportJob:
    def __init__(self, operation):
        self.events = queue.Queue()
        self._cancel = threading.Event()
        self.progress = (0, 1)
        def run():
            try:
                result = operation(self._progress, self._cancel.is_set)
                self.events.put(('success', result))
            except InterruptedError as error:
                self.events.put(('cancelled', error))
            except Exception as error:
                self.events.put(('error', error))
        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()

    def _progress(self, done, total):
        self.progress = (done, max(1, total))

    def cancel(self):
        self._cancel.set()


class WebExportDialog:
    def __init__(self, parent, *, app_version, video=None, subtitles=()):
        import tkinter as tk
        import customtkinter as ctk
        from tkinter import filedialog, messagebox
        install_theme()
        self.ctk, self.tk, self.filedialog, self.messagebox = ctk, tk, filedialog, messagebox
        self.version = app_version
        self.top = ctk.CTkToplevel(parent)
        self.top.title('建立字幕網頁')
        self.top.geometry('800x740')
        self.top.minsize(720, 640)
        self.top.protocol('WM_DELETE_WINDOW', self.close)
        self.state = ExportFormState()
        self.title_state = self.state.title
        self._syncing = False
        self.package_id = None
        self.job = None
        self.phase = 'idle'
        self.media_ready = False
        self.notice = ''
        self.notice_error = False
        self.closing = False
        self.rows = []
        self.track_inputs = []
        self.editable = []
        self.variables = {key: tk.StringVar(master=self.top) for key in
                          ('video', 'title', 'parent', 'folder', 'author', 'organization', 'poster', 'default')}
        self.top.configure(fg_color=('#F4F7FB', '#171D28'))
        header = ctk.CTkFrame(self.top, fg_color='transparent')
        header.pack(fill='x', padx=32, pady=(26, 10))
        self.state_badge = ctk.CTkLabel(header, text='等待選擇影片', corner_radius=12, fg_color=('#E6EDF7','#28354B'),
                                      text_color=('#365575','#B9D2ED'), padx=14, height=28, font=ui_font(size=12))
        self.state_badge.pack(side='right',anchor='n',pady=4)
        ctk.CTkLabel(header, text='建立字幕網頁', font=ui_font(size=27, weight='bold'), text_color=('#172C46','#E6EDF7')).pack(anchor='w')
        ctk.CTkLabel(header, text='影片選好，字幕就位。', font=ui_font(size=14), text_color=('#65748A','#A5B2C5')).pack(anchor='w', pady=(4,0))
        self.form = ctk.CTkScrollableFrame(self.top, fg_color='transparent')
        self.form.pack(fill='both', expand=True, padx=24, pady=8)
        self.form.grid_columnconfigure(1, weight=1)

        def entry(label, key, row, command=None, button='選擇…', host=None):
            host = host or self.more
            ctk.CTkLabel(host, text=label, text_color=('#52637B','#BDCADC')).grid(row=row, column=0, sticky='w', padx=14, pady=8)
            widget = ctk.CTkEntry(host, textvariable=self.variables[key], height=34, corner_radius=8)
            widget.grid(row=row, column=1, sticky='ew', padx=6, pady=8)
            self.editable.append(widget)
            if command:
                self.button(host, button, command).grid(row=row, column=2, padx=6)
            return widget

        def card(row, title, hint):
            host = ctk.CTkFrame(self.form, corner_radius=16, fg_color=('#FFFFFF','#222D3D'), border_width=1, border_color=('#E4EAF2','#344257'))
            host.grid(row=row, column=0, columnspan=3, sticky='ew', pady=(0,12))
            ctk.CTkLabel(host, text=title, font=ui_font(size=16,weight='bold'), text_color=('#243C59','#DFE9F7')).pack(anchor='w', padx=22, pady=(18,2))
            ctk.CTkLabel(host, text=hint, text_color=('#718096','#A5B2C5'), wraplength=620, justify='left').pack(anchor='w', padx=22, pady=(0,12))
            return host

        video_card = card(0, '01   影片來源', '選擇 MP4，自動尋找同資料夾內的同檔名與語系字幕。')
        self.video_button = self.button(video_card, '選擇或拖入 MP4 影片…', self.choose_video)
        self.video_button.configure(height=44, font=ui_font(size=15, weight='bold'), fg_color=('#EAF2FD','#293F5C'), hover_color=('#DCEAFF','#344E70'), text_color=('#2363AD','#C5DEFF'))
        self.video_button.pack(fill='x', padx=22, pady=(0,10))
        self.media_info = ctk.CTkLabel(video_card, text='支援 .mp4  ·  不修改原始檔案', wraplength=620, anchor='w', justify='left', text_color=('#65748A','#A5B2C5'))
        self.media_info.pack(fill='x', padx=22, pady=(0,18))
        wrap_to_width(self.media_info)

        subtitle_card = card(1, '02   字幕', '自動配對、多語一起加入；同語系優先使用 VTT。')
        self.candidate_info = ctk.CTkLabel(subtitle_card, text='選好影片後，字幕會自動顯示於此。', wraplength=610, anchor='w', justify='left', text_color=('#65748A','#A5B2C5'))
        self.candidate_info.pack(fill='x', padx=22, pady=(0,6))
        self.summary_tracks = ctk.CTkFrame(subtitle_card, fg_color='transparent')
        self.summary_tracks.pack(fill='x', padx=22, pady=(0,16))
        self._updating_title = False
        self.variables['title'].trace_add('write', self.title_changed)
        self.more_button = self.button(self.form, '▸ 進階設定（選填）', self.toggle_more)
        self.more_button.configure(fg_color='transparent')
        self.more_button.grid(row=3, column=0, columnspan=3, sticky='w', pady=(0,8))
        self.more = ctk.CTkFrame(self.form, corner_radius=14, fg_color=('#FFFFFF','#222D3D'))
        self.more.grid_columnconfigure(1, weight=1)
        entry('網頁標題', 'title', 0, self.reset_title, '恢復影片檔名')
        entry('講者／作者', 'author', 1, host=self.more)
        entry('單位／課程', 'organization', 2, host=self.more)
        entry('封面（選填）', 'poster', 3, self.choose_poster, host=self.more)
        ctk.CTkLabel(self.more, text='簡介（純文字）').grid(row=4, column=0, padx=6, sticky='nw')
        self.description = ctk.CTkTextbox(self.more, height=100)
        self.description.grid(row=4, column=1, columnspan=2, sticky='ew', padx=6, pady=6)
        self.editable.append(self.description)
        ctk.CTkLabel(self.more, text='開啟時顯示字幕').grid(row=5, column=0, padx=6, sticky='w')
        self.default_menu = ctk.CTkComboBox(self.more, variable=self.variables['default'], values=['自動（第一個字幕）','不顯示字幕'], command=self.default_changed)
        self.default_menu.grid(row=5, column=1, sticky='ew', padx=6, pady=6)
        self.default_menu.bind('<FocusOut>', self.commit_default)
        self.default_menu.bind('<Return>', self.commit_default)
        self.editable.append(self.default_menu)
        self.variables['default'].set('自動（第一個字幕）')
        entry('新資料夾名稱', 'folder', 6, self.reset_folder, '自動命名')
        self.variables['folder'].trace_add('write', self.folder_changed)
        self.button(self.more, '變更儲存位置…', self.choose_parent).grid(row=7,column=1,sticky='w',padx=6,pady=8)
        ctk.CTkLabel(self.more, text='字幕可移除後更換檔案。無語系使用「預設字幕」，亦可改語言或輸入 pt-BR 等代碼。', wraplength=590, text_color=('gray40','gray70')).grid(row=8,column=0,columnspan=3,padx=12,pady=(0,10))
        self.button(self.more, '＋ 加入／更換字幕檔…', self.choose_subtitles).grid(row=9,column=0,columnspan=3,sticky='w',padx=12,pady=(0,6))
        self.tracks_frame = ctk.CTkFrame(self.more, fg_color='transparent')
        self.tracks_frame.grid(row=10,column=0,columnspan=3,sticky='ew',padx=6,pady=(0,10))
        self.error_details = ctk.CTkTextbox(self.form, height=140, wrap='word')
        self.error_details.configure(state='disabled')
        self.footer = ctk.CTkFrame(self.top, fg_color=('#FFFFFF','#202B3B'), corner_radius=0)
        self.footer.pack(fill='x')
        self.target = ctk.CTkLabel(self.footer, text='儲存位置會自動設在影片旁的新資料夾', wraplength=690, anchor='w', justify='left', text_color=('#6B7A90','#ADBCD0'), font=ui_font(size=12))
        self.target.pack(fill='x', padx=30, pady=(14,0))
        wrap_to_width(self.target)
        self.status = ctk.CTkLabel(self.footer, text='', wraplength=690, anchor='w', justify='left', font=ui_font(size=13))
        self.status.pack(fill='x', padx=30, pady=(2,4))
        wrap_to_width(self.status)
        self.details_button = ctk.CTkButton(self.footer, text='查看錯誤詳細資訊',
            command=self.toggle_details, height=26, width=150, fg_color='transparent',
            text_color=('#405570','#CBDAED'))
        self.progressbar = ctk.CTkProgressBar(self.footer, height=3, corner_radius=0, progress_color=('#2873C6','#5CA3EE'), fg_color=('#EAF0F7','#354256'))
        self.progressbar.set(0); self.progressbar.pack(fill='x', padx=30, pady=(0,12))
        actions = ctk.CTkFrame(self.footer, fg_color='transparent'); actions.pack(fill='x', padx=26, pady=(0,18))
        self.button(actions, '編輯既有網頁…', self.choose_package).pack(side='left', padx=4)
        self.create_button = self.button(actions, '建立網頁 →', self.start)
        self.create_button.configure(height=42, width=154, font=ui_font(size=15,weight='bold'),
                                     fg_color=('#2468B4','#367FCB'), hover_color=('#1C5697','#438DD9'), text_color='white', text_color_disabled=('#A5B5C8','#8195AD'))
        self.create_button.pack(side='right', padx=4)
        self.close_button = ctk.CTkButton(actions, text='關閉', width=86, height=36, command=self.close,
                                        fg_color='transparent', hover_color=('#EDF2F8','#314055'), text_color=('#64748B','#B9C8DB'))
        self.close_button.pack(side='right', padx=4)
        self.preview = ctk.CTkFrame(self.footer, fg_color='transparent')
        for track in subtitles: self.add_track(track.path, track.language)
        if video: self.select_video(Path(video))
        self.update_flow()
        self.drop_available = register_file_drop(self.top, self.on_drop)
        if not self.drop_available:
            self.video_button.configure(text='選擇 MP4 影片…（此環境未啟用拖放）')
        self.top.after(100, self.top.lift)

    def on_drop(self, event):
        if self.job:
            self.notice = '正在處理，請完成或取消目前作業後再拖入檔案。'
            self.notice_error = True
            self.update_flow()
            return 'break'
        paths = [Path(p) for p in dropped_paths(self.top, event.data)]
        videos = [p for p in paths if p.suffix.lower() == '.mp4']
        if len(videos) > 1:
            message = '一次只能拖入一個 MP4 影片；可一起加入 SRT／VTT 字幕。'
        elif not paths or any(not p.is_file() or p.suffix.lower() not in ('.mp4', '.srt', '.vtt') for p in paths):
            message = '請拖入可讀取的 MP4 影片或 SRT／VTT 字幕檔，不支援資料夾或其他格式。'
        elif not videos and not self.state.video:
            message = '請先選擇或拖入一個 MP4 影片，再加入字幕。'
        else:
            if videos:
                self.select_video(videos[0])
            for path in paths:
                if path.suffix.lower() in ('.srt', '.vtt'):
                    language = ''
                    parts = path.stem.rsplit('.', 1)
                    if len(parts) == 2:
                        try: language = canonical_language(parts[-1])
                        except ValueError: pass
                    self.add_track(path, language)
            # New subtitle controls must retain the in-progress lock too.
            if self.job:
                for widget in self.editable:
                    if widget.winfo_exists(): widget.configure(state='disabled')
            return 'break'
        self.notice, self.notice_error = message, True
        self.update_flow()
        return 'break'

    def button(self, host, text, command):
        widget = self.ctk.CTkButton(host, text=text, command=command, width=120, height=34, corner_radius=8,
                                   fg_color=('#EDF2F8','#304159'), hover_color=('#E0E8F3','#3B5070'), text_color=('#405570','#CBDAED'))
        self.editable.append(widget)
        return widget

    def title_changed(self, *args):
        if not self._updating_title: self.title_state.edit(self.variables['title'].get())
        self.update_flow(clear_notice=True)

    def sync_title(self):
        self._updating_title = True
        self.variables['title'].set(self.title_state.value)
        self._updating_title = False

    def reset_title(self):
        self.title_state.use_filename(); self.sync_title()

    def select_video(self, path, *, discover=True):
        self.media_ready = False
        self.notice = ''
        self.phase = 'idle'
        self.commit_track_languages()
        self.variables['video'].set(str(path))
        self.state.select_video(path)
        self.sync_title(); self.sync_output()
        self.video_button.configure(text='更換影片…')
        try:
            size = path.stat().st_size / (1024 * 1024)
            self.media_info.configure(text=f'{path.name}  ·  {size:.1f} MiB\n{path.parent}')
        except OSError: self.media_info.configure(text='請選擇可讀取的 MP4 影片。')
        if discover:
            candidates = find_subtitle_candidates(path)
            self.state.offer_candidates(candidates)
        self.render_tracks()
        if discover:
            self.run_job(lambda progress,cancelled: probe_video(path), lambda info: self.media_checked(path,info), phase='reading')

    def media_checked(self, path, info):
        duration = max(0, int(info['duration'] or 0))
        label = f'{duration // 60}:{duration % 60:02d}' if info['duration'] is not None else '長度未知'
        self.media_info.configure(text=f'{path.name}  ·  {label}  ·  {info["size"] / 1048576:.1f} MiB\n{path.parent}')
        self.media_ready = True
        self.update_flow()

    def sync_output(self):
        self._syncing = True
        self.variables['parent'].set(str(self.state.output_parent or ''))
        self.variables['folder'].set(self.state.folder_name)
        self._syncing = False
        self.target_changed()

    def folder_changed(self, *args):
        if not self._syncing: self.state.set_folder_name(self.variables['folder'].get())
        self.target_changed()

    def reset_folder(self):
        self.state.folder_manual = False; self.state.refresh_output_name(); self.sync_output()

    def target_changed(self, *args):
        if hasattr(self, 'target'):
            path = str(Path(self.variables['parent'].get()) / self.variables['folder'].get())
            display = path if len(path) <= 150 else path[:45] + '…' + path[-100:]
            self.target.configure(text='儲存位置  ' + display)
        self.update_flow(clear_notice=True)

    def choose_video(self):
        path = self.filedialog.askopenfilename(parent=self.top, filetypes=[('MP4 影片','*.mp4')])
        if path: self.select_video(Path(path))

    def choose_parent(self):
        path = self.filedialog.askdirectory(parent=self.top)
        if path: self.state.set_output_parent(path); self.sync_output()

    def choose_poster(self):
        path = self.filedialog.askopenfilename(parent=self.top, filetypes=[('PNG／JPEG','*.png *.jpg *.jpeg')])
        if path: self.variables['poster'].set(path)

    def choose_subtitles(self):
        paths = self.filedialog.askopenfilenames(parent=self.top, initialdir=str(Path(self.variables['video'].get()).parent),
                                               filetypes=[('SRT／VTT 字幕','*.srt *.vtt')])
        for path in paths:
            suffix = Path(path).stem.rsplit('.',1)
            language = ''
            if len(suffix) == 2:
                try: language = canonical_language(suffix[-1])
                except ValueError: pass
            self.add_track(Path(path), language)

    def add_track(self, path, language=''):
        self.commit_track_languages()
        self.state.add_track(path, language)
        self.render_tracks()

    def render_tracks(self):
        for child in self.tracks_frame.winfo_children(): child.destroy()
        self.rows = []
        self.track_inputs = []
        self.editable = [w for w in self.editable if w.winfo_exists()]
        for track in self.state.tracks:
            row = self.ctk.CTkFrame(self.tracks_frame); row.pack(fill='x', pady=3)
            var = self.tk.StringVar(master=self.top, value=language_label(track.language) or '請選擇語言')
            self.rows.append((track.path, var, row))
            self.track_inputs.append((track, var))
            self.ctk.CTkLabel(row, text=track.path.name, anchor='w', wraplength=330, justify='left').pack(side='left', fill='x', expand=True, padx=10, pady=8)
            combo = self.ctk.CTkComboBox(row, variable=var, width=145, values=list(LANGUAGES.values()),
                                      command=lambda value,t=track: self.track_language_changed(t,value))
            combo.pack(side='left', padx=4); self.editable.append(combo)
            remove = self.button(row, '移除', lambda t=track: self.remove_track(t))
            remove.configure(width=55); remove.pack(side='right', padx=6)
            combo.bind('<FocusOut>', lambda event: self.commit_track_languages())
        self.refresh_languages()

    def track_language_changed(self, track, value):
        self.state.set_track_language(track,value)
        self.refresh_languages()

    def commit_track_languages(self):
        # CTkComboBox selection deletes then inserts its text. Commit only
        # complete selections / typed edits, never those intermediate writes.
        for track, variable in self.track_inputs:
            value = variable.get()
            if language_code(value) != track.language:
                self.state.set_track_language(track, value)
        self.refresh_languages()

    def remove_track(self, track):
        self.commit_track_languages()
        self.state.remove_track(track); self.render_tracks()

    def default_changed(self, value):
        self.state.default_choice = {'自動（第一個字幕）':'auto','不顯示字幕':'off'}.get(value,language_code(value))
        self.update_flow(clear_notice=True)

    def commit_default(self, event=None):
        self.default_changed(self.variables['default'].get())

    def refresh_languages(self):
        if not hasattr(self, 'default_menu'): return
        languages = list(dict.fromkeys(language_label(t.language) for t in self.state.tracks if t.language))
        self.default_menu.configure(values=['自動（第一個字幕）','不顯示字幕'] + languages)
        value = self.state.default_choice
        self.variables['default'].set({'auto':'自動（第一個字幕）','off':'不顯示字幕','':'請重新選擇'}.get(value,language_label(value)))
        if self.state.tracks:
            summary = f'已找到 {len(self.state.tracks)} 軌字幕，不需額外設定'
        else:
            summary = ('未找到同名字幕。請放入同資料夾後重新選擇影片，或展開進階設定加入。'
                       if self.state.video else '選擇影片後，會在這裡顯示找到的字幕。')
        self.candidate_info.configure(text=summary)
        for child in self.summary_tracks.winfo_children(): child.destroy()
        for track in self.state.tracks:
            row = self.ctk.CTkFrame(self.summary_tracks, fg_color='transparent')
            row.pack(fill='x',pady=4)
            self.ctk.CTkLabel(row, text=language_label(track.language) or '待修正', width=94, height=28, corner_radius=7,
                             fg_color=('#EAF2FD','#2B4260'),text_color=('#2E659D','#C2DFFF'),font=ui_font(size=12)).pack(side='left')
            self.ctk.CTkLabel(row,text=track.path.name,anchor='w',wraplength=420,justify='left',text_color=('#3C506B','#CFDBEB')).pack(side='left',fill='x',expand=True,padx=(12,0))
        self.update_flow(clear_notice=True)

        register_file_drop(self.top, self.on_drop)

    def update_flow(self, *, clear_notice=False):
        if not hasattr(self, 'create_button'): return
        if clear_notice and not self.job:
            self.notice = ''
            self.notice_error = False
            self.phase = 'idle'
        action = export_action_state(self.state, self.phase, self.media_ready)
        self.create_button.configure(state='normal' if action.enabled else 'disabled', text=action.label)
        labels = {'reading':'讀取中', 'checking':'檢查中', 'exporting':'建立中', 'cancelling':'正在取消', 'done':'建立完成'}
        badge = labels.get(self.phase, '可以建立網頁' if action.enabled else '等待選擇影片' if not self.state.video else '需要確認')
        color = ('#B14536','#FFB9A8') if self.notice_error else ('#536881','#B6C7DD')
        self.state_badge.configure(text=badge)
        self.status.configure(text=self.notice or action.hint, text_color=color)

    def toggle_more(self):
        if self.more.winfo_manager():
            self.more.grid_remove(); self.more_button.configure(text='▸ 進階設定（選填）')
        else:
            self.more.grid(row=4, column=0, columnspan=3, sticky='ew', pady=(0,8))
            self.more_button.configure(text='▾ 收合進階設定')

    def choose_package(self):
        path = self.filedialog.askdirectory(parent=self.top, title='選擇已匯出的網頁資料夾')
        if path: self.run_job(lambda progress, cancelled: load_package(Path(path)), self.loaded, phase='reading')

    def loaded(self, loaded):
        request = loaded.request
        self.package_id = request.package_id
        self.title_state.edit(request.metadata.title)
        self.track_inputs = []
        self.state.tracks.clear()
        self.state.parent_manual = self.state.folder_manual = False
        self.select_video(request.video, discover=False); self.sync_title()
        for key in ('author','organization'): self.variables[key].set(getattr(request.metadata, key))
        self.description.delete('1.0','end'); self.description.insert('1.0', request.metadata.description)
        self.variables['poster'].set(str(request.poster or ''))
        self.state.set_output_parent(request.output_parent)
        self.state.set_folder_name(suggested_folder(request.output_parent, request.folder_name))
        self.sync_output()
        self.state.default_choice = request.default_subtitle
        for track in request.subtitles: self.add_track(track.path, track.language)
        self.refresh_languages()
        self.run_job(lambda progress,cancelled: probe_video(request.video),
                     lambda info: self.media_checked(request.video,info), phase='reading')
        self.notice = '已載入，修改後另存新資料夾。\n' + '\n'.join(i.message for i in loaded.issues)

    def snapshot(self):
        self.state.refresh_output_name(); self.sync_output()
        self.default_changed(self.variables['default'].get())
        self.commit_track_languages()
        v = {k: value.get().strip() for k,value in self.variables.items()}
        if not v['parent'] or not v['video']: raise ValueError('請選擇影片與輸出父資料夾')
        return ExportRequest(Path(v['video']), tuple(SubtitleSource(t.path, t.language) for t in self.state.tracks),
                             Metadata(v['title'],v['author'],v['organization'],self.description.get('1.0','end-1c')),
                             Path(v['parent']),v['folder'],self.state.default_language(),Path(v['poster']) if v['poster'] else None,self.package_id)

    def start(self):
        try: request = self.snapshot()
        except ValueError as error:
            self.show_issues([str(error)]); return
        self.preview.pack_forget()
        self.run_job(lambda progress,cancelled: inspect_inputs(request), lambda issues: self.checked(request,issues))

    def checked(self, request, issues):
        errors = [i.message for i in issues if i.severity == 'error']
        if errors:
            self.show_issues(errors); return
        warnings = '\n'.join(i.message for i in issues)
        if warnings and not self.messagebox.askyesno('請確認相容性提醒', warnings + '\n\n仍要建立網頁嗎？', parent=self.top):
            self.show_issues(['已暫停，尚未建立網頁。']); return
        self.run_job(lambda progress,cancelled: export_package(request,app_version=self.version,
                     progress=progress,cancelled=cancelled,accept_warnings=True), self.exported, phase='exporting')

    def show_issues(self, messages):
        self.notice = '請確認以下設定：\n' + '\n'.join(messages)
        self.notice_error = True
        self.update_flow()
        if not self.more.winfo_manager(): self.toggle_more()

    def run_job(self, operation, success, *, phase='checking'):
        if self.job: return
        self._success = success
        self.phase = phase
        self.notice = ''
        self.notice_error = False
        self.details_button.pack_forget()
        self.error_details.grid_remove()
        for widget in self.editable:
            if widget.winfo_exists(): widget.configure(state='disabled')
        self.close_button.configure(text='取消並關閉')
        self.progressbar.stop()
        self.progressbar.configure(mode='determinate' if phase == 'exporting' else 'indeterminate')
        self.progressbar.set(0)
        if phase != 'exporting': self.progressbar.start()
        self.job = ExportJob(operation)
        self.update_flow()
        self.top.after(80, self.poll)

    def poll(self):
        if not self.top.winfo_exists():
            if self.job: self.job.cancel()
            return
        if self.phase == 'exporting':
            done,total = self.job.progress; self.progressbar.set(done/total)
        try: kind,result = self.job.events.get_nowait()
        except queue.Empty:
            self.top.after(80,self.poll); return
        self.job = None
        self.phase = 'idle'
        self.progressbar.stop()
        self.progressbar.configure(mode='determinate')
        self.progressbar.set(0)
        for widget in self.editable:
            if widget.winfo_exists(): widget.configure(state='normal')
        self.close_button.configure(text='關閉')
        if self.closing:
            if kind == 'success' and hasattr(result, 'index_path'):
                self.messagebox.showinfo('匯出已完成', str(result.folder), parent=self.top)
            elif hasattr(result, 'staging_path'):
                self.messagebox.showwarning('暫存保留', str(result.staging_path), parent=self.top)
            self.top.destroy(); return
        if kind == 'success': self._success(result)
        else:
            message = f'程式版本：{self.version}\n' + str(result)
            if hasattr(result, 'export_stage'):
                message += '\n失敗階段：' + result.export_stage
            if hasattr(result, 'export_resource'):
                message += '\n相關資源：' + result.export_resource
            if hasattr(result,'staging_path'): message += '\n未能安全清理的暫存：' + str(result.staging_path)
            self.error_details.configure(state='normal')
            self.error_details.delete('1.0', 'end')
            self.error_details.insert('1.0', message)
            self.error_details.configure(state='disabled')
            self.details_button.pack(anchor='w', padx=30, pady=(0, 6), before=self.progressbar)
            if getattr(result, 'winerror', None) in (32, 33):
                self.notice = '檔案發生占用或共享衝突；尚無法判定來源。請稍候重試，或改選其他輸出資料夾。'
            else:
                self.notice = str(result)[:150] + ('…' if len(str(result)) > 150 else '')
            if hasattr(result, 'staging_path'):
                self.notice += '\n已保留暫存檔案，位置請見詳細資訊。'
            self.notice_error = kind == 'error'
        self.update_flow()

    def toggle_details(self):
        if self.error_details.winfo_manager():
            self.error_details.grid_remove()
            self.details_button.configure(text='查看錯誤詳細資訊')
        else:
            self.error_details.grid(row=5, column=0, columnspan=3, sticky='ew', pady=8)
            self.details_button.configure(text='收合錯誤詳細資訊')
            self.form._parent_canvas.yview_moveto(1)

    def exported(self,result):
        self.phase = 'done'
        self.notice = '網頁已建立完成，可以開啟預覽或查看輸出資料夾。'
        self.progressbar.set(1)
        for child in self.preview.winfo_children(): child.destroy()
        self.ctk.CTkButton(self.preview,text='開啟網頁',command=lambda:webbrowser.open(result.index_path.as_uri())).pack(side='left',padx=4)
        self.ctk.CTkButton(self.preview,text='開啟輸出資料夾',command=lambda:self.open_folder(result.folder)).pack(side='left',padx=4)
        self.preview.pack(pady=(0,12))
        self.update_flow()

    def open_folder(self,path):
        if sys.platform == 'win32': os.startfile(str(path))
        else: subprocess.Popen(['open' if sys.platform == 'darwin' else 'xdg-open',str(path)])

    def close(self):
        if self.job:
            self.closing = True; self.job.cancel()
            self.phase = 'cancelling'
            self.notice = '正在取消…若已產生部分檔案，將保留暫存並告知位置。'
            self.update_flow()
        else: self.top.destroy()
