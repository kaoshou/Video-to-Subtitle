
import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
import customtkinter as ctk
import webbrowser
import platform
import time
import json

# Import core logic from transcriber.py
from transcriber import SubtitleTranscriber, check_model_downloaded

# --- 嘗試匯入拖曳功能庫 (tkinterdnd2) ---
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    DND_AVAILABLE = True
except ImportError:
    DND_AVAILABLE = False
    print("提示: 若要啟用檔案拖曳功能，請執行 pip install tkinterdnd2")

# --- 版本資訊讀取 ---
def get_version():
    """從 pyproject.toml 讀取版本號"""
    try:
        # 優先嘗試 Python 3.11+ 內建的 tomllib
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib
        
        # 獲取 pyproject.toml 的絕對路徑 (考慮打包後的環境)
        script_dir = os.path.dirname(os.path.abspath(__file__))
        toml_path = os.path.join(script_dir, "pyproject.toml")
        
        if os.path.exists(toml_path):
            with open(toml_path, "rb") as f:
                data = tomllib.load(f)
                return data.get("project", {}).get("version", "Unknown")
    except Exception as e:
        print(f"DEBUG: Failed to load version from pyproject.toml: {e}")
    
    return "2.5.1" # Fallback

# --- 設定外觀 ---
ctk.set_appearance_mode("System")  # Modes: "System" (standard), "Dark", "Light"
ctk.set_default_color_theme("blue")  # Themes: "blue" (standard), "green", "dark-blue"

# 支援的檔案格式
SUPPORTED_EXTENSIONS = {".mp4", ".mp3", ".mkv", ".wav", ".mov", ".avi", ".m4a", ".flac", ".ogg", ".webm"}

# --- 圖形介面區 (CustomTkinter UI) ---

# 如果環境支援 TkinterDnD，則繼承它，否則只繼承 ctk.CTk
# 注意: ctk.CTk 已經繼承了 tk.Tk
BaseClass = ctk.CTk
if DND_AVAILABLE:
    class CTkDnD(ctk.CTk, TkinterDnD.DnDWrapper):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.TkdndVersion = TkinterDnD._require(self)
    BaseClass = CTkDnD

class SubtitleEditorWindow(ctk.CTkToplevel):
    def __init__(self, parent, file_path):
        super().__init__(parent)
        self.title(f"快速校對編輯 - {os.path.basename(file_path)}")
        self.geometry("780x600")
        
        if platform.system() != "Darwin":
            self.transient(parent)
            self.grab_set()
            
        # 套用 APP 圖標
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app_icon.ico")
        if os.path.exists(icon_path):
            try:
                self.after(200, lambda: self.iconbitmap(icon_path))
            except Exception as e:
                print(f"Failed to set editor window icon: {e}")
        
        self.file_path = file_path
        self.is_txt = file_path.lower().endswith(".txt")
        
        if self.is_txt:
            self.items = []
            self.txt_content = self.load_txt_file(file_path)
        else:
            self.items = self.parse_subtitle(file_path)
            
        self.entries = []
        self.items_per_page = 100
        self.current_page = 0
        
        # 頂部提示與標題
        self.header_frame = ctk.CTkFrame(self)
        self.header_frame.pack(fill="x", padx=15, pady=(15, 10))
        
        self.title_label = ctk.CTkLabel(self.header_frame, text=f"正在編輯: {os.path.basename(file_path)}", 
                                        font=ctk.CTkFont(size=14, weight="bold"))
        self.title_label.pack(anchor="w", padx=10, pady=(10, 2))
        
        self.tip_label = ctk.CTkLabel(self.header_frame, text="提示：直接在下方編輯文字，完成後點選「儲存並關閉」即可自動更新檔案。", 
                                      font=ctk.CTkFont(size=12), text_color="gray")
        self.tip_label.pack(anchor="w", padx=10, pady=(2, 10))
        
        # 中間區域：根據格式決定
        if self.is_txt:
            self.txt_editor = ctk.CTkTextbox(self, font=ctk.CTkFont(size=13))
            self.txt_editor.pack(fill="both", expand=True, padx=15, pady=5)
            self.txt_editor.insert("0.0", self.txt_content)
        else:
            self.scroll_frame = ctk.CTkScrollableFrame(self)
            self.scroll_frame.pack(fill="both", expand=True, padx=15, pady=5)
            self.render_items()
        
        # 底部操作列
        self.footer_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.footer_frame.pack(fill="x", padx=15, pady=15)
        
        if not self.is_txt and len(self.items) > self.items_per_page:
            self.pagination_frame = ctk.CTkFrame(self.footer_frame, fg_color="transparent")
            self.pagination_frame.pack(side="left")
            
            self.btn_prev = ctk.CTkButton(self.pagination_frame, text="< 上一頁", width=70, command=self.prev_page, state="disabled")
            self.btn_prev.pack(side="left", padx=(0, 5))
            
            self.lbl_page = ctk.CTkLabel(self.pagination_frame, text="第 1 頁 / 共 1 頁")
            self.lbl_page.pack(side="left", padx=5)
            
            self.btn_next = ctk.CTkButton(self.pagination_frame, text="下一頁 >", width=70, command=self.next_page)
            self.btn_next.pack(side="left", padx=(5, 0))
            
            self.update_pagination_ui()
            
        self.btn_save = ctk.CTkButton(self.footer_frame, text="儲存並關閉 (Save & Close)", 
                                       fg_color="#1f538d", hover_color="#14375e",
                                       command=self.save_and_close)
        self.btn_save.pack(side="right", padx=(10, 0))
        
        self.btn_cancel = ctk.CTkButton(self.footer_frame, text="取消 (Cancel)", 
                                         fg_color="gray", hover_color="#555555",
                                         command=self.destroy)
        self.btn_cancel.pack(side="right")
        
    def load_txt_file(self, file_path):
        if not os.path.exists(file_path):
            return ""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            print(f"Error reading txt file: {e}")
            return ""

    def parse_subtitle(self, file_path):
        items = []
        if not os.path.exists(file_path):
            return items
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except Exception as e:
            print(f"Error reading file: {e}")
            return items
            
        i = 0
        n = len(lines)
        while i < n:
            line = lines[i].strip()
            if "-->" in line:
                time_str = line
                index = ""
                if i > 0 and lines[i-1].strip().isdigit():
                    index = lines[i-1].strip()
                
                text_lines = []
                i += 1
                while i < n:
                    next_line = lines[i].rstrip('\n')
                    if next_line.strip() == "":
                        break
                    if "-->" in next_line:
                        i -= 1
                        break
                    text_lines.append(next_line)
                    i += 1
                    
                text = "\n".join(text_lines).strip()
                items.append({
                    "index": index,
                    "time": time_str,
                    "text": text
                })
            i += 1
        return items

    def save_subtitle(self, file_path, items):
        is_vtt = file_path.lower().endswith(".vtt")
        with open(file_path, "w", encoding="utf-8") as f:
            if is_vtt:
                f.write("WEBVTT\n\n")
            for idx, item in enumerate(items):
                if is_vtt:
                    f.write(f"{item['time']}\n")
                    f.write(f"{item['text']}\n\n")
                else:
                    srt_idx = item['index'] if item['index'] else str(idx + 1)
                    f.write(f"{srt_idx}\n")
                    f.write(f"{item['time']}\n")
                    f.write(f"{item['text']}\n\n")

    def render_items(self):
        # 先清除舊的 widgets
        for widget in self.scroll_frame.winfo_children():
            widget.destroy()
        self.entries = []

        if not self.file_path.lower().endswith((".srt", ".vtt")):
            lbl = ctk.CTkLabel(self.scroll_frame, text="目前格式只支援校對 .srt 和 .vtt 字幕檔案。")
            lbl.pack(pady=20)
            return
            
        start_idx = self.current_page * self.items_per_page
        end_idx = min(start_idx + self.items_per_page, len(self.items))
            
        for i in range(start_idx, end_idx):
            item = self.items[i]
            row_frame = ctk.CTkFrame(self.scroll_frame, fg_color="transparent")
            row_frame.pack(fill="x", pady=2, padx=5)
            
            idx_str = f"[{i+1:03d}]"
            lbl_idx = ctk.CTkLabel(row_frame, text=idx_str, width=40, font=ctk.CTkFont(family="Consolas", size=11))
            lbl_idx.pack(side="left", padx=(0, 5))
            
            time_clean = item['time'].replace(" --> ", " -> ")
            lbl_time = ctk.CTkLabel(row_frame, text=time_clean, width=170, 
                                    font=ctk.CTkFont(family="Consolas", size=10), text_color="gray")
            lbl_time.pack(side="left", padx=5)
            
            entry = ctk.CTkEntry(row_frame, font=ctk.CTkFont(size=12))
            entry.insert(0, item['text'])
            entry.pack(side="left", fill="x", expand=True, padx=(5, 0))
            
            self.entries.append(entry)

    def save_current_page(self):
        if not self.is_txt and hasattr(self, 'entries'):
            start_idx = self.current_page * self.items_per_page
            for i, entry in enumerate(self.entries):
                if start_idx + i < len(self.items):
                    self.items[start_idx + i]['text'] = entry.get().strip()

    def update_pagination_ui(self):
        max_page = max(0, (len(self.items) - 1) // self.items_per_page)
        if hasattr(self, 'lbl_page'):
            self.lbl_page.configure(text=f"第 {self.current_page + 1} 頁 / 共 {max_page + 1} 頁")
            self.btn_prev.configure(state="normal" if self.current_page > 0 else "disabled")
            self.btn_next.configure(state="normal" if self.current_page < max_page else "disabled")

    def prev_page(self):
        if self.current_page > 0:
            self.save_current_page()
            self.current_page -= 1
            self.render_items()
            self.update_pagination_ui()

    def next_page(self):
        max_page = (len(self.items) - 1) // self.items_per_page
        if self.current_page < max_page:
            self.save_current_page()
            self.current_page += 1
            self.render_items()
            self.update_pagination_ui()
            
    def save_and_close(self):
        if self.is_txt:
            new_text = self.txt_editor.get("0.0", "end")
            try:
                with open(self.file_path, "w", encoding="utf-8") as f:
                    f.write(new_text.strip() + "\n")
                messagebox.showinfo("成功", f"文字講義已成功儲存！\n檔名: {os.path.basename(self.file_path)}", parent=self)
                self.destroy()
            except Exception as e:
                messagebox.showerror("錯誤", f"儲存檔案時發生錯誤:\n{e}", parent=self)
            return

        if not self.file_path.lower().endswith((".srt", ".vtt")):
            self.destroy()
            return
            
        self.save_current_page()
            
        try:
            self.save_subtitle(self.file_path, self.items)
            messagebox.showinfo("成功", f"修改已儲存！\n檔名: {os.path.basename(self.file_path)}", parent=self)
            self.destroy()
        except Exception as e:
            messagebox.showerror("錯誤", f"儲存檔案時發生錯誤:\n{e}", parent=self)

class DynamicProgressBar(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, height=12, fg_color="transparent", **kwargs)
        
        self.filled = ctk.CTkProgressBar(self, mode="determinate", height=12)
        self.filled.set(1.0)
        self.filled.place(relx=0, rely=0, relwidth=0.0, relheight=1.0)
        
        self.unfilled = ctk.CTkProgressBar(self, mode="indeterminate", height=12)
        self.unfilled.place(relx=0.0, rely=0, relwidth=1.0, relheight=1.0)
        
    def start(self):
        self.unfilled.start()
        
    def stop(self):
        self.unfilled.stop()
        
    def configure(self, **kwargs):
        if "mode" in kwargs:
            kwargs.pop("mode") # Ignore mode changes, we handle it natively
        super().configure(**kwargs)
        
    def set(self, value):
        if value < 0: value = 0.0
        if value > 1: value = 1.0
        
        if value == 0:
            self.filled.place_forget()
            self.unfilled.place(relx=0.0, rely=0, relwidth=1.0, relheight=1.0)
        elif value >= 1.0:
            self.unfilled.place_forget()
            self.filled.place(relx=0, rely=0, relwidth=1.0, relheight=1.0)
        else:
            self.filled.place(relx=0, rely=0, relwidth=value, relheight=1.0)
            self.unfilled.place(relx=value, rely=0, relwidth=1.0-value, relheight=1.0)

class App(BaseClass):
    def __init__(self):
        super().__init__()
        
        self.title("Video to Subtitle - 本地語音轉字幕工具")
        self.geometry("780x720")
        
        # Windows 工作列圖示與進程組 ID 宣告，防止 Windows 使用 Python 預設火箭圖示
        if platform.system() == "Windows":
            try:
                import ctypes
                myappid = 'kaoshou.subtitletranscriber.v2'
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
            except Exception as e:
                print(f"Failed to set AppUserModelID: {e}")
                
        # 設定主視窗圖示
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app_icon.ico")
        if os.path.exists(icon_path):
            try:
                self.iconbitmap(icon_path)
            except Exception as e:
                print(f"Failed to set main window icon: {e}")
        
        # 初始化變數
        self.transcriber = None
        self.is_running = False
        self.cancel_flag = False
        self.file_list = [] # 儲存多個檔案路徑
        self.available_models = ["tiny", "base", "small", "medium", "large-v3", "large-v3-turbo"]
        self.model_var = ctk.StringVar(value="medium")
        self.device_var = ctk.StringVar(value="cpu")
        self.format_var = ctk.StringVar(value="srt")
        self.zh_tw_var = ctk.BooleanVar(value=False) 
        self.translate_en_var = ctk.BooleanVar(value=False) 
        self.max_chars_var = ctk.StringVar(value="35") 
        self.hotwords_var = ctk.StringVar(value="") 
        self.model_path_var = ctk.StringVar(value="") 
        
        # 進階設定變數
        self.clean_punc_var = ctk.StringVar(value="標點轉空格 (space)")
        self.word_timestamps_var = ctk.BooleanVar(value=True)
        self.spacing_var = ctk.BooleanVar(value=True)
        self.case_correction_var = ctk.BooleanVar(value=True)
        self.cpu_threads_var = ctk.StringVar(value="4")
        self.vad_filter_var = ctk.BooleanVar(value=True)
        
        self.clean_punc_mapping = {
            "none": "保留標點 (none)",
            "remove": "移除標點 (remove)",
            "space": "標點轉空格 (space)"
        }
        self.clean_punc_mapping_rev = {v: k for k, v in self.clean_punc_mapping.items()}

        # 讀取設定檔 (持久化)
        self.config_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
        self.load_settings()

        # Grid configuration
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1) # Main content expands

        # 建構 UI
        self.create_widgets()
        self.setup_dnd()
        
        # 啟動後檢查更新 (非同步)
        threading.Thread(target=self.check_for_updates, daemon=True).start()

    def setup_dnd(self):
        if DND_AVAILABLE:
            try:
                # 綁定拖曳功能到主視窗
                self.drop_target_register(DND_FILES)
                self.dnd_bind('<<Drop>>', self.on_drop)
            except Exception as e:
                print(f"拖曳功能初始化失敗: {e}")

    def on_drop(self, event):
        files_data = event.data
        # 處理 tkinterdnd2 的路徑格式 (大括號包覆含空白的路徑)
        new_files = self.parse_dnd_files(files_data)
        
        valid_files_added = 0
        invalid_files = []

        for f in new_files:
            # 去除可能的引號與多餘空白
            f = f.strip().strip('"').strip("'")
            
            if not os.path.exists(f): 
                continue

            # 驗證副檔名
            _, ext = os.path.splitext(f)
            if ext.lower() in SUPPORTED_EXTENSIONS:
                if f not in self.file_list:
                    self.file_list.append(f)
                    valid_files_added += 1
            else:
                invalid_files.append(os.path.basename(f))
        
        self.update_file_list_ui()
        
        status_msg = f"已加入 {valid_files_added} 個檔案 (總計: {len(self.file_list)})"
        if invalid_files:
            # 顯示警告，但不要太打擾，用 status bar 提醒或彈窗
            msg = f"已忽略不支援的檔案:\n{', '.join(invalid_files[:3])}"
            if len(invalid_files) > 3: msg += "..."
            self.log(f"⚠️ {msg}")
            messagebox.showwarning("格式不支援", f"以下檔案非影片或音訊格式，已忽略：\n\n{msg}")
        
        if valid_files_added > 0:
            self.status_label.configure(text=status_msg)
            self.btn_run.focus_set()

    def parse_dnd_files(self, data):
        # 簡單且強健的 Windows 路徑解析
        if not data: return []
        
        # 如果是單一檔案且被 {} 包圍 (tkinterdnd2 常見格式)
        if data.startswith('{') and data.endswith('}') and data.count('{') == 1:
            return [data[1:-1]]
            
        # 嘗試利用 tk 的 splitlist (處理多個檔案與帶空白路徑)
        try:
             # self.tk 是主視窗底層的 Tk 物件
             return self.tk.splitlist(data)
        except:
             # Fallback: 簡單空白分割 (失敗率較高)
             return data.split()

    def update_file_list_ui(self):
        self.textbox_files.configure(state="normal")
        self.textbox_files.delete("0.0", "end")
        for f in self.file_list:
            self.textbox_files.insert("end", f"{f}\n")
        self.textbox_files.configure(state="disabled")

    def create_widgets(self):
        # --- 1. Header Frame (Top) ---
        self.header_frame = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.header_frame.grid(row=0, column=0, sticky="ew", padx=20, pady=(15, 0))
        
        self.logo_label = ctk.CTkLabel(self.header_frame, text="Video to Subtitle", font=ctk.CTkFont(size=24, weight="bold"))
        self.logo_label.pack(side="left")
        
        self.subtitle_label = ctk.CTkLabel(self.header_frame, text="本地語音轉字幕工具", font=ctk.CTkFont(size=14), text_color="gray")
        self.subtitle_label.pack(side="left", padx=(10, 0), pady=(5, 0))

        # --- 2. Main Content Area (Middle) ---
        self.main_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.main_frame.grid(row=1, column=0, sticky="nsew", padx=20, pady=10)
        self.main_frame.grid_columnconfigure(0, weight=1)
        self.main_frame.grid_rowconfigure(4, weight=1) # Log area expands

        # File Selection Frame (Batch Processing)
        self.file_frame = ctk.CTkFrame(self.main_frame)
        self.file_frame.grid(row=0, column=0, sticky="ew", pady=(0, 15))
        self.file_frame.grid_columnconfigure(0, weight=1) # Textbox expands
        
        self.label_file = ctk.CTkLabel(self.file_frame, text="1. 待處理清單 (支援拖曳多個檔案)", font=ctk.CTkFont(size=14, weight="bold"))
        self.label_file.grid(row=0, column=0, columnspan=2, padx=15, pady=(10, 0), sticky="w")

        # File List Textbox
        self.textbox_files = ctk.CTkTextbox(self.file_frame, height=100)
        self.textbox_files.grid(row=1, column=0, padx=15, pady=10, sticky="ew")
        self.textbox_files.configure(state="disabled") # Read-only
        
        # Buttons Frame within File Frame (Right side)
        self.btns_file_frame = ctk.CTkFrame(self.file_frame, fg_color="transparent")
        self.btns_file_frame.grid(row=1, column=1, padx=15, pady=10, sticky="n")
        
        self.btn_add = ctk.CTkButton(self.btns_file_frame, text="加入檔案...", command=self.browse_file, width=120)
        self.btn_add.pack(fill="x", pady=(0, 5))
        
        self.btn_clear = ctk.CTkButton(self.btns_file_frame, text="清除清單", command=self.clear_files, width=120, fg_color="gray")
        self.btn_clear.pack(fill="x")
        
        self.btn_edit_manual = ctk.CTkButton(self.btns_file_frame, text="編輯現有字幕檔", command=self.open_manual_edit, width=120,
                                             fg_color="transparent", border_width=1, text_color=("gray10", "#DCE4EE"))
        self.btn_edit_manual.pack(fill="x", pady=(5, 0))

        # Settings Frame
        self.settings_frame = ctk.CTkFrame(self.main_frame)
        self.settings_frame.grid(row=1, column=0, sticky="ew", pady=(0, 15))
        self.settings_frame.grid_columnconfigure(1, weight=1)
        self.settings_frame.grid_columnconfigure(3, weight=1)
        
        self.label_settings = ctk.CTkLabel(self.settings_frame, text="2. 轉換設定", font=ctk.CTkFont(size=14, weight="bold"))
        self.label_settings.grid(row=0, column=0, columnspan=4, padx=15, pady=(10, 5), sticky="w")

        # Row 1: Comboboxes
        self.label_model = ctk.CTkLabel(self.settings_frame, text="準確度 (Model):")
        self.label_model.grid(row=1, column=0, padx=15, pady=5, sticky="e")
        self.combo_model = ctk.CTkOptionMenu(self.settings_frame, variable=self.model_var, 
                                             values=self.available_models)
        self.combo_model.grid(row=1, column=1, padx=15, pady=5, sticky="ew")
        
        self.label_device = ctk.CTkLabel(self.settings_frame, text="運算單元:")
        self.label_device.grid(row=1, column=2, padx=15, pady=5, sticky="e")
        
        device_values = ["cpu", "mlx"] if platform.system() == "Darwin" else ["cpu", "cuda"]
        self.combo_device = ctk.CTkOptionMenu(self.settings_frame, variable=self.device_var, values=device_values,
                                             command=lambda _: self.refresh_model_menu())
        self.combo_device.grid(row=1, column=3, padx=15, pady=5, sticky="ew")

        # Row 2: Format & Checkboxes
        self.label_fmt = ctk.CTkLabel(self.settings_frame, text="輸出格式:")
        self.label_fmt.grid(row=2, column=0, padx=15, pady=5, sticky="e")
        self.combo_fmt = ctk.CTkOptionMenu(self.settings_frame, variable=self.format_var, 
                                           values=["srt", "vtt", "txt", "tsv", "json"], width=100)
        self.combo_fmt.grid(row=2, column=1, padx=15, pady=5, sticky="w")
        
        # Checkboxes 
        self.chk_frame = ctk.CTkFrame(self.settings_frame, fg_color="transparent")
        self.chk_frame.grid(row=2, column=2, columnspan=2, sticky="w")
        
        self.chk_zhtw = ctk.CTkCheckBox(self.chk_frame, text="強制繁體中文", variable=self.zh_tw_var, command=self.on_check_zhtw)
        self.chk_zhtw.pack(side="left", padx=(15, 10), pady=5)

        self.chk_trans = ctk.CTkCheckBox(self.chk_frame, text="翻譯為英文", variable=self.translate_en_var, command=self.on_check_trans)
        self.chk_trans.pack(side="left", padx=10, pady=5)

        # Row 3: Subtitle Segmentation Strategy (Natural speech & pause driven)
        self.label_max_chars = ctk.CTkLabel(self.settings_frame, text="字幕斷句策略:")
        self.label_max_chars.grid(row=3, column=0, padx=15, pady=(5, 10), sticky="e")
        
        self.chars_frame = ctk.CTkFrame(self.settings_frame, fg_color="transparent")
        self.chars_frame.grid(row=3, column=1, columnspan=3, sticky="w")
        
        self.label_strategy_desc = ctk.CTkLabel(self.chars_frame, text="自然語意與停頓 (預設)", font=ctk.CTkFont(weight="bold"))
        self.label_strategy_desc.pack(side="left", padx=(15, 5), pady=(5, 10))
        
        self.label_limit = ctk.CTkLabel(self.chars_frame, text="防溢出上限:")
        self.label_limit.pack(side="left", padx=(15, 5), pady=(5, 10))
        
        self.entry_max_chars = ctk.CTkEntry(self.chars_frame, textvariable=self.max_chars_var, width=50)
        self.entry_max_chars.pack(side="left", padx=5, pady=(5, 10))
        
        self.label_chars_hint = ctk.CTkLabel(self.chars_frame, text="字 (避免破碎斷句，依語意與聲音停頓自然斷句)", font=ctk.CTkFont(size=11), text_color="gray")
        self.label_chars_hint.pack(side="left", padx=5, pady=(5, 10))

        # Row 4: Hotwords
        self.label_hotwords = ctk.CTkLabel(self.settings_frame, text="熱詞補強 (Hotwords):")
        self.label_hotwords.grid(row=4, column=0, padx=15, pady=(5, 15), sticky="e")
        
        self.hotwords_container = ctk.CTkFrame(self.settings_frame, fg_color="transparent")
        self.hotwords_container.grid(row=4, column=1, columnspan=3, padx=15, pady=(5, 15), sticky="ew")
        
        self.entry_hotwords = ctk.CTkEntry(self.hotwords_container, textvariable=self.hotwords_var, 
                                           placeholder_text="例如: Python, Unity, 鄭郁翰, 崑山科技大學 (以逗號分隔)")
        self.entry_hotwords.pack(side="left", fill="x", expand=True)
        
        # New: Import Button for Hotwords
        self.btn_import_hotwords = ctk.CTkButton(self.hotwords_container, text="載入", width=45, height=28,
                                                fg_color="gray", hover_color="#555555",
                                                command=self.load_hotwords_from_file)
        self.btn_import_hotwords.pack(side="left", padx=(5, 0))
        
        self.btn_help_hotwords = ctk.CTkButton(self.hotwords_container, text="?", width=28, height=28, 
                                                fg_color="gray", hover_color="#555555", corner_radius=14,
                                                command=self.show_hotwords_help)
        self.btn_help_hotwords.pack(side="left", padx=(5, 0))
        
        self.entry_hotwords.bind("<FocusIn>", lambda e: self.show_temp_status("提示: 使用逗號分隔關鍵字，可大幅減少專有名詞的拼寫錯誤。"))

        # 進階設定折疊按鈕 (移除 Emoji)
        self.btn_toggle_adv = ctk.CTkButton(self.settings_frame, text="顯示進階設定", 
                                           fg_color="transparent", border_width=1, text_color=("gray10", "#DCE4EE"),
                                           command=self.toggle_advanced_settings, height=28)
        self.btn_toggle_adv.grid(row=5, column=0, columnspan=4, sticky="w", padx=15, pady=(5, 10))

        # 進階設定面板 (Nested inside settings_frame)
        self.adv_settings_frame = ctk.CTkFrame(self.settings_frame, fg_color=("gray92", "gray18"), corner_radius=6)
        self.adv_settings_frame.grid_remove() # 預設隱藏
        self.adv_settings_frame.grid_columnconfigure((1, 3), weight=1)
        
        # Row 0: Word Timestamps & Spacing Checkbox
        self.chk_word_ts = ctk.CTkCheckBox(self.adv_settings_frame, text="精準時間軸 (Word Timestamps)", variable=self.word_timestamps_var)
        self.chk_word_ts.grid(row=0, column=0, columnspan=2, padx=15, pady=10, sticky="w")
        
        self.chk_spacing = ctk.CTkCheckBox(self.adv_settings_frame, text="中英文自動加空格", variable=self.spacing_var)
        self.chk_spacing.grid(row=0, column=2, columnspan=2, padx=15, pady=10, sticky="w")
        
        # Row 1: Case Checkbox & VAD Filter Checkbox
        self.chk_case_corr = ctk.CTkCheckBox(self.adv_settings_frame, text="熱詞大小寫自動校正", variable=self.case_correction_var)
        self.chk_case_corr.grid(row=1, column=0, columnspan=2, padx=15, pady=(5, 10), sticky="w")
        
        self.chk_vad = ctk.CTkCheckBox(self.adv_settings_frame, text="VAD 靜音過濾 (消除靜音幻覺)", variable=self.vad_filter_var)
        self.chk_vad.grid(row=1, column=2, columnspan=2, padx=15, pady=(5, 10), sticky="w")
        
        # Row 2: CPU Threads & Punctuation Clean
        self.label_threads = ctk.CTkLabel(self.adv_settings_frame, text="CPU 執行緒數:")
        self.label_threads.grid(row=2, column=0, padx=15, pady=(5, 15), sticky="e")
        
        self.combo_threads = ctk.CTkOptionMenu(self.adv_settings_frame, variable=self.cpu_threads_var,
                                               values=["1", "2", "4", "8", "16"], width=80)
        self.combo_threads.grid(row=2, column=1, padx=15, pady=(5, 15), sticky="w")

        self.label_clean_punc = ctk.CTkLabel(self.adv_settings_frame, text="標點符號處理:")
        self.label_clean_punc.grid(row=2, column=2, padx=15, pady=(5, 15), sticky="e")
        
        clean_punc_values = list(self.clean_punc_mapping.values())
        self.combo_clean_punc = ctk.CTkOptionMenu(self.adv_settings_frame, variable=self.clean_punc_var,
                                                  values=clean_punc_values)
        self.combo_clean_punc.grid(row=2, column=3, padx=15, pady=(5, 15), sticky="w")

        # Action Buttons
        self.action_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.action_frame.grid(row=2, column=0, sticky="ew", pady=(0, 10))

        self.btn_run = ctk.CTkButton(self.action_frame, text="開始轉錄 (Start)", command=self.start_thread, 
                                     font=ctk.CTkFont(size=15, weight="bold"), height=45)
        self.btn_run.pack(side="left", fill="x", expand=True, padx=(0, 10))

        self.btn_cancel = ctk.CTkButton(self.action_frame, text="取消 (Cancel)", command=self.cancel_task, 
                                        fg_color="transparent", border_width=2, text_color=("gray10", "#DCE4EE"),
                                        font=ctk.CTkFont(size=15, weight="bold"), height=45, state="disabled")
        self.btn_cancel.pack(side="right", fill="x", expand=True, padx=(0, 0))

        # Progress Bar Frame (兼顧特效與進度顯示)
        self.progress_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.progress_frame.grid(row=3, column=0, sticky="ew", pady=(0, 10))
        self.progress_frame.grid_columnconfigure(0, weight=1)

        self.progressbar = DynamicProgressBar(self.progress_frame)
        self.progressbar.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self.progressbar.set(0) # 0%
        
        self.progress_label = ctk.CTkLabel(self.progress_frame, text="0.0%", width=45, font=ctk.CTkFont(size=12, weight="bold"))
        self.progress_label.grid(row=0, column=1, sticky="e")
        
        # 動畫狀態變數
        self._target_progress = 0.0
        self._current_progress = 0.0
        self._progress_animating = False

        # Log Area
        self.log_textbox = ctk.CTkTextbox(self.main_frame, font=ctk.CTkFont(family="Consolas", size=12))
        self.log_textbox.grid(row=4, column=0, sticky="nsew", pady=(0, 5))
        self.log_textbox.configure(state="disabled")

        # --- 3. Footer Controls (Row 2) ---
        self.controls_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.controls_frame.grid(row=2, column=0, sticky="ew", padx=20, pady=(0, 10))
        self.controls_frame.grid_columnconfigure(0, weight=1) # Spacer spans

        # Left: Appearance Mode
        self.label_mode = ctk.CTkLabel(self.controls_frame, text="外觀 (Theme):", text_color="gray")
        self.label_mode.pack(side="left", padx=(0, 5))
        
        self.appearance_mode_optionemenu = ctk.CTkOptionMenu(self.controls_frame, values=["System", "Light", "Dark"],
                                                               command=self.change_appearance_mode_event, width=100)
        self.appearance_mode_optionemenu.pack(side="left")

        # Right: Storage & About Buttons
        self.btn_about = ctk.CTkButton(self.controls_frame, text="關於本程式 (About)", command=self.show_about, 
                                       width=120, fg_color="transparent", border_width=1, text_color=("gray10", "#DCE4EE"))
        self.btn_about.pack(side="right")

        self.btn_storage = ctk.CTkButton(self.controls_frame, text="模型儲存管理", command=self.show_storage_settings,
                                        width=120, fg_color="transparent", border_width=1, text_color=("gray10", "#DCE4EE"))
        self.btn_storage.pack(side="right", padx=(0, 10))

        # --- 4. Status Bar (Row 3 - Bottom) ---
        self.status_frame = ctk.CTkFrame(self, height=24, corner_radius=0, fg_color=("gray95", "gray10"))
        self.status_frame.grid(row=3, column=0, sticky="ew")
        self.status_frame.grid_columnconfigure(0, weight=1) # Status label expands

        # Left: Status
        self.status_label = ctk.CTkLabel(self.status_frame, text="就緒 - 請加入檔案", anchor="w", font=ctk.CTkFont(size=12))
        self.status_label.grid(row=0, column=0, sticky="ew", padx=10)

        # Right: Credits
        self.credit_label = ctk.CTkLabel(self.status_frame, text="Developed by Yu-Han Cheng 鄭郁翰", 
                                         font=ctk.CTkFont(size=10), text_color="gray")
        self.credit_label.grid(row=0, column=1, sticky="e", padx=10)

        # 初始化模型下拉選單標籤
        self.refresh_model_menu()

    def get_clean_model_name(self, raw_val=None):
        """從選單文字中取得乾淨的模型名稱 (例如從 'large-v3-turbo [已下載]' 取出 'large-v3-turbo')"""
        val = raw_val if raw_val is not None else self.model_var.get()
        if not val:
            return "medium"
        return val.split()[0].strip()

    def refresh_model_menu(self, preferred_model=None):
        """根據本地快取狀態，刷新模型下拉選單標籤 (已下載 / 未下載)"""
        if preferred_model is None:
            current_clean = self.get_clean_model_name()
        else:
            current_clean = preferred_model.split()[0].strip()
        
        current_download_root = self.model_path_var.get().strip()
        if not current_download_root:
            current_download_root = None
        
        device = self.device_var.get().strip()
        
        new_values = []
        matched_item = None
        
        for m in self.available_models:
            is_downloaded = check_model_downloaded(m, download_root=current_download_root, device=device)
            tag = " [已下載]" if is_downloaded else " [未下載]"
            item_label = f"{m}{tag}"
            new_values.append(item_label)
            if m == current_clean:
                matched_item = item_label
                
        if hasattr(self, 'combo_model'):
            self.combo_model.configure(values=new_values)
            if matched_item:
                self.model_var.set(matched_item)
            elif new_values:
                self.model_var.set(new_values[0])

    def change_appearance_mode_event(self, new_appearance_mode: str):
        ctk.set_appearance_mode(new_appearance_mode)
        self.save_settings()

    def show_storage_settings(self):
        """顯示模型儲存路徑管理視窗"""
        # 避免重複開啟
        if hasattr(self, "storage_window") and self.storage_window is not None and self.storage_window.winfo_exists():
            self.storage_window.lift()
            self.storage_window.focus_force()
            return

        self.storage_window = ctk.CTkToplevel(self)
        self.storage_window.title("模型儲存管理")
        self.storage_window.geometry("500x380")
        self.storage_window.resizable(False, False)
        
        # 套用 APP 圖標
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app_icon.ico")
        if os.path.exists(icon_path):
            try:
                self.storage_window.after(200, lambda: self.storage_window.iconbitmap(icon_path))
            except Exception as e:
                print(f"Failed to set storage window icon: {e}")
        
        if platform.system() != "Darwin":
            self.storage_window.transient(self)
            self.storage_window.grab_set()
        
        # 標題與說明
        ctk.CTkLabel(self.storage_window, text="模型快取與儲存管理", font=ctk.CTkFont(size=18, weight="bold")).pack(pady=(20, 10))
        
        desc_text = (
            "Whisper 模型檔案通常較大 (約 500MB 至 2GB)，預設會儲存在系統磁碟中。\n\n"
            "若您的系統槽 (通常是 C 槽) 空間不足，建議將路徑更改至其他磁碟。\n"
            "更改後，程式會自動從新路徑讀取，若新路徑無檔案則會重新下載。"
        )
        ctk.CTkLabel(self.storage_window, text=desc_text, justify="left", wraplength=440).pack(padx=20, pady=10)

        # 路徑顯示區
        path_frame = ctk.CTkFrame(self.storage_window)
        path_frame.pack(fill="x", padx=30, pady=15)
        
        ctk.CTkLabel(path_frame, text="目前儲存路徑:", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=15, pady=(10, 0))
        
        # 使用 Textbox 顯示長路徑以便複製或查看
        path_display = ctk.CTkTextbox(path_frame, height=60, font=ctk.CTkFont(size=11))
        path_display.pack(fill="x", padx=15, pady=10)
        
        def update_display():
            current_path = self.model_path_var.get().strip()
            if not current_path:
                current_path = os.path.expanduser("~/.cache/huggingface/hub (系統預設)")
            path_display.configure(state="normal")
            path_display.delete("0.0", "end")
            path_display.insert("end", current_path)
            path_display.configure(state="disabled")

        update_display()

        # 按鈕區
        btn_frame = ctk.CTkFrame(self.storage_window, fg_color="transparent")
        btn_frame.pack(pady=10)
        
        def on_change():
            self.browse_model_path()
            update_display()

        ctk.CTkButton(btn_frame, text="更改路徑...", command=on_change, width=120).pack(side="left", padx=10)
        ctk.CTkButton(btn_frame, text="開啟資料夾", command=self.open_model_path, width=120, fg_color="gray").pack(side="left", padx=10)

        # 底部關閉按鈕
        ctk.CTkButton(self.storage_window, text="完成 (Close)", command=self.storage_window.destroy, width=100).pack(pady=(10, 20))

    def browse_model_path(self):
        directory = filedialog.askdirectory(title="選擇模型儲存路徑")
        if directory:
            self.model_path_var.set(directory)
            self.save_settings()
            self.refresh_model_menu()

    def open_model_path(self):
        path = self.model_path_var.get().strip()
        if not path:
            # 預設路徑 (faster-whisper 預設)
            path = os.path.expanduser("~/.cache/huggingface/hub")
            
        if not os.path.exists(path):
            try:
                os.makedirs(path, exist_ok=True)
            except:
                messagebox.showerror("錯誤", f"路徑不存在且無法建立:\n{path}")
                return
        
        # 根據平台開啟資料夾
        if platform.system() == "Windows":
            os.startfile(path)
        elif platform.system() == "Darwin":
            import subprocess
            subprocess.Popen(["open", path])
        else:
            import subprocess
            subprocess.Popen(["xdg-open", path])

    def load_settings(self):
        """從 config.json 載入設定"""
        if not os.path.exists(self.config_file):
            return
            
        try:
            with open(self.config_file, "r", encoding="utf-8") as f:
                config = json.load(f)
                
            if "model" in config:
                clean_m = config["model"].split()[0].strip()
                self.model_var.set(clean_m)
            if "device" in config: self.device_var.set(config["device"])
            if "format" in config: self.format_var.set(config["format"])
            if "zh_tw" in config: self.zh_tw_var.set(config["zh_tw"])
            if "translate_en" in config: self.translate_en_var.set(config["translate_en"])
            if "max_chars" in config:
                val = str(config["max_chars"])
                try:
                    if int(val) < 25: val = "35"
                except:
                    val = "35"
                self.max_chars_var.set(val)
            if "hotwords" in config: self.hotwords_var.set(config["hotwords"])
            if "model_path" in config: self.model_path_var.set(config["model_path"])
            if "appearance_mode" in config: 
                ctk.set_appearance_mode(config["appearance_mode"])
                # 更新下拉選單顯示 (如果有)
                if hasattr(self, 'appearance_mode_optionemenu'):
                    self.appearance_mode_optionemenu.set(config["appearance_mode"])
        except Exception as e:
            print(f"DEBUG: Failed to load config: {e}")

    def save_settings(self):
        """將目前設定儲存至 config.json"""
        config = {
            "model": self.get_clean_model_name(),
            "device": self.device_var.get(),
            "format": self.format_var.get(),
            "zh_tw": self.zh_tw_var.get(),
            "translate_en": self.translate_en_var.get(),
            "max_chars": self.max_chars_var.get(),
            "hotwords": self.hotwords_var.get(),
            "model_path": self.model_path_var.get(),
            "appearance_mode": ctk.get_appearance_mode()
        }
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"DEBUG: Failed to save config: {e}")

    def show_hotwords_help(self):
        help_msg = (
            "【熱詞補強 (Hotwords) 使用說明】\n\n"
            "這個功能可以幫助模型更精準地辨識專用術語、人名或品牌名。\n\n"
            "1. 如何輸入：在欄位中輸入詞彙，並使用「半型逗號 (,)」或「全型逗號 (，)」隔開。\n"
            "   例如：Python, TensorFlow, 鄭郁翰\n\n"
            "2. 適用場景：教學影片中的程式名、公司名稱、或是錄音品質較差時的關鍵字。\n\n"
            "3. 注意事項：請勿輸入過長的整段句子，這會導致模型產生幻覺輸出。"
        )
        # 修正：優先使用關於視窗做為父視窗，若無則使用主視窗
        parent = self.about_window if (hasattr(self, 'about_window') and self.about_window is not None and self.about_window.winfo_exists()) else self
        self.after(100, lambda: messagebox.showinfo("功能說明: 熱詞補強", help_msg, parent=parent))

    def load_hotwords_from_file(self):
        """從文字檔匯入熱詞"""
        file_path = filedialog.askopenfilename(
            filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")],
            title="選擇熱詞清單檔 (每行一個詞或以逗號分隔)"
        )
        if not file_path:
            return
            
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
                
            # 分割邏輯：支援換行或逗號
            import re
            words = [w.strip() for w in re.split(r'[,\n，]', content) if w.strip()]
            
            if not words:
                messagebox.showwarning("匯入提示", "選取的檔案中沒有偵測到有效的詞彙。")
                return
                
            # 與現有的熱詞合併
            existing_words = [w.strip() for w in re.split(r'[,\n，]', self.hotwords_var.get()) if w.strip()]
            
            # 使用 set 去重但保持基本順序的邏輯
            new_list = existing_words.copy()
            for w in words:
                if w not in new_list:
                    new_list.append(w)
            
            result_str = ", ".join(new_list)
            self.hotwords_var.set(result_str)
            self.log(f"成功從檔案匯入 {len(words)} 個熱詞。")
            self.show_temp_status(f"已匯入 {len(words)} 個熱詞")
            
        except Exception as e:
            messagebox.showerror("匯入失敗", f"讀取熱詞檔案時發生錯誤：\n{e}")

    def check_for_updates(self, manual=False):
        """檢查 GitHub 上是否有新版本
        manual: 若為 True，則在無更新時也會提示「已是最新版本」
        """
        if manual and hasattr(self, 'btn_manual_update'):
            self.btn_manual_update.configure(state="disabled", text="檢查中...")

        current_version = get_version()
        repo = "kaoshou/Video-to-Subtitle"
        url = f"https://api.github.com/repos/{repo}/releases/latest"
        
        try:
            import urllib.request
            import json
            import re
            
            # 建立請求，增加 User-Agent 避免被 GitHub 拒絕
            req = urllib.request.Request(url, headers={'User-Agent': 'SubtitleTranscriber-Updater'})
            with urllib.request.urlopen(req, timeout=5) as response:
                data = json.loads(response.read().decode())
                
                latest_version = (data.get("tag_name") or "").replace("v", "")
                if not latest_version:
                    latest_version = (data.get("name") or "").replace("v", "")
                
                if not latest_version:
                    if manual: messagebox.showinfo("檢查結果", "暫時無法取得版本資訊，請稍後再試。", parent=getattr(self, 'about_window', self))
                    return

                # 版本比較
                def version_to_tuple(v):
                    try:
                        return tuple(map(int, (re.sub(r'[^0-9.]', '', v).split('.'))))
                    except:
                        return (0, 0, 0)

                if version_to_tuple(latest_version) > version_to_tuple(current_version):
                    release_url = data.get("html_url") or f"https://github.com/{repo}/releases"
                    body = data.get("body") or "無更新說明"
                    
                    # 彈出提示
                    target_parent = getattr(self, 'about_window', self)
                    self.after(500 if manual else 2000, lambda: self.show_update_dialog(latest_version, release_url, body, parent=target_parent))
                elif manual:
                    messagebox.showinfo("檢查結果", f"目前已是最新版本 (v{current_version})", parent=getattr(self, 'about_window', self))
                    
        except Exception as e:
            msg = f"更新檢查失敗: {e}"
            if "404" in str(e):
                msg = "尚未在 GitHub 建立 Release (404)"
            
            if manual:
                messagebox.showerror("檢查失敗", f"無法連線至 GitHub 檢查更新：\n{msg}", parent=getattr(self, 'about_window', self))
            else:
                self.after(3000, lambda: self.status_label.configure(text=msg))
        finally:
            if manual and hasattr(self, 'btn_manual_update'):
                self.btn_manual_update.configure(state="normal", text="檢查更新")

    def show_update_dialog(self, latest_version, url, body, parent=None):
        """顯示更新提示視窗"""
        parent = parent if parent else self
        # 確保 body 為字串，避免 NoneType 錯誤 (例如 GitHub Release 無內文時)
        safe_body = body if body else "無更新說明"
        msg = f"發現新版本：v{latest_version}\n目前版本：v{get_version()}\n\n是否要前往下載新版本？\n\n更新說明：\n{safe_body[:200]}{'...' if len(safe_body) > 200 else ''}"
        if messagebox.askyesno("軟體更新提示", msg, parent=parent):
            webbrowser.open_new(url)

    def on_check_zhtw(self):
        if self.zh_tw_var.get() and self.translate_en_var.get():
            self.show_temp_status("注意: 若勾選「翻譯成英文」，則「強制繁體中文」將無效。")
        else:
            self.show_temp_status("提示: 勾選「強制繁體中文」可避免出現簡體字。")

    def show_temp_status(self, msg, duration=3000):
        current_status = self.status_label.cget("text")
        self.status_label.configure(text=msg)
        self.after(duration, lambda: self.status_label.configure(text=current_status))

    def on_check_trans(self):
        self.on_check_zhtw()

    def show_about(self):
        # 避免重複開啟關於視窗
        if hasattr(self, "about_window") and self.about_window is not None and self.about_window.winfo_exists():
            self.about_window.lift()
            self.about_window.focus_force()
            return

        # Create a new Toplevel window
        self.about_window = ctk.CTkToplevel(self)
        self.about_window.title("關於本程式")
        self.about_window.geometry("500x600")
        self.about_window.resizable(False, False)
        
        # 套用 APP 圖標
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app_icon.ico")
        if os.path.exists(icon_path):
            try:
                self.about_window.after(200, lambda: self.about_window.iconbitmap(icon_path))
            except Exception as e:
                print(f"Failed to set about window icon: {e}")
        
        # Ensure it stays on top and grabs focus (針對 macOS 特殊處理避免崩潰)
        if platform.system() == "Darwin":
            # macOS 下直接呼叫 transient 或 grab_set 極易導致 Tcl/Tk 崩潰
            self.about_window.after(200, self.about_window.lift)
        else:
            self.about_window.transient(self)
            self.about_window.grab_set()
            
        # Bind local variable for compatibility with the rest of the layout logic
        about_window = self.about_window
        
        # Helper for clickable links
        def create_link(parent, text, url):
            link = ctk.CTkLabel(parent, text=text, text_color=("#0078d7", "#4da3ff"), cursor="hand2")
            link.bind("<Button-1>", lambda e: webbrowser.open_new(url))
            return link

        # Main Scrollable Frame
        scroll_frame = ctk.CTkScrollableFrame(about_window, fg_color="transparent")
        scroll_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # Title
        ctk.CTkLabel(scroll_frame, text="Video to Subtitle (本地語音轉字幕工具)", font=ctk.CTkFont(size=20, weight="bold")).pack(pady=(10, 5))
        
        version_frame = ctk.CTkFrame(scroll_frame, fg_color="transparent")
        version_frame.pack(pady=(0, 20))
        
        ctk.CTkLabel(version_frame, text=f"Version {get_version()}").pack(side="left", padx=5)
        
        self.btn_manual_update = ctk.CTkButton(version_frame, text="檢查更新", width=80, height=24, 
                                              font=ctk.CTkFont(size=11),
                                              command=lambda: self.check_for_updates(manual=True))
        self.btn_manual_update.pack(side="left", padx=5)

        # --- Developer Info Section ---
        dev_frame = ctk.CTkFrame(scroll_frame)
        dev_frame.pack(fill="x", pady=10)
        
        ctk.CTkLabel(dev_frame, text="開發人員資訊 (Developer)", font=ctk.CTkFont(weight="bold")).pack(pady=5)
        ctk.CTkLabel(dev_frame, text="鄭郁翰 (Yu-Han Cheng)").pack()
        ctk.CTkLabel(dev_frame, text="E-mail: kaoshou@gmail.com").pack()
        
        # GitHub Link
        create_link(dev_frame, "GitHub: https://github.com/kaoshou/Video-to-Subtitle/", "https://github.com/kaoshou/Video-to-Subtitle/").pack(pady=5)

        # --- Open Source Section ---
        os_frame = ctk.CTkFrame(scroll_frame)
        os_frame.pack(fill="x", pady=10)
        
        ctk.CTkLabel(os_frame, text="開源專案宣告 (Open Source Acknowledgements)", font=ctk.CTkFont(weight="bold")).pack(pady=(10, 5))
        ctk.CTkLabel(os_frame, text="本軟體使用以下開源專案：", font=ctk.CTkFont(size=12)).pack(pady=(0, 10))

        # List of libraries
        libs = [
            ("faster-whisper", "MIT License", "https://github.com/SYSTRAN/faster-whisper"),
            ("CTranslate2", "MIT License", "https://github.com/OpenNMT/CTranslate2"),
            ("mlx-whisper", "MIT License", "https://github.com/ml-explore/mlx-examples/tree/main/whisper"),
            ("CustomTkinter", "MIT License", "https://github.com/TomSchimansky/CustomTkinter"),
            ("tkinterdnd2", "MIT License", "https://github.com/pmgagne/tkinterdnd2"),
            ("OpenCC", "Apache-2.0 License", "https://github.com/BYVoid/OpenCC"),
            ("tomli", "MIT License", "https://github.com/hukkin/tomli"),
            ("huggingface-hub", "Apache-2.0 License", "https://github.com/huggingface/huggingface_hub")
        ]

        for name, license_, url in libs:
            item_frame = ctk.CTkFrame(os_frame, fg_color="transparent")
            item_frame.pack(fill="x", pady=2)
            ctk.CTkLabel(item_frame, text=f"• {name} ({license_})", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=20)
            create_link(item_frame, url, url).pack(anchor="w", padx=40)

        # Close Button
        ctk.CTkButton(about_window, text="關閉 (Close)", command=about_window.destroy, width=100).pack(pady=10)

    def log(self, msg):
        def _update():
            self.log_textbox.configure(state="normal")
            self.log_textbox.insert("end", msg + "\n")
            self.log_textbox.see("end")
            self.log_textbox.configure(state="disabled")
            self.status_label.configure(text=msg) # Status bar shows last log
        self.after(0, _update)

    def update_progress(self, value):
        # Value is float between 0.0 and 1.0
        def _update():
            self._target_progress = value
            if not getattr(self, '_progress_animating', False):
                self._animate_progress_loop()
        self.after(0, _update)

    def _animate_progress_loop(self):
        self._progress_animating = True
        diff = self._target_progress - self._current_progress
        
        if abs(diff) < 0.001:
            self._current_progress = self._target_progress
            self.progressbar.set(self._current_progress)
            self.progress_label.configure(text=f"{self._current_progress * 100:.1f}%")
            self._progress_animating = False
            return
            
        # 每次移動剩餘差距的 15%，實現平滑過渡特效
        step = diff * 0.15
        if abs(step) < 0.001:
            step = 0.001 if diff > 0 else -0.001
            
        if abs(step) > abs(diff):
            step = diff
            
        self._current_progress += step
        self.progressbar.set(self._current_progress)
        self.progress_label.configure(text=f"{self._current_progress * 100:.1f}%")
        
        self.after(20, self._animate_progress_loop)

    def browse_file(self):
        filenames = filedialog.askopenfilenames(
            filetypes=[("Media Files", "*.mp4 *.mp3 *.mkv *.wav *.mov *.avi *.m4a"), ("All Files", "*.*")]
        )
        if filenames:
            for f in filenames:
                if f not in self.file_list:
                    self.file_list.append(f)
            self.update_file_list_ui()
            self.status_label.configure(text=f"目前共有 {len(self.file_list)} 個檔案")
            self.btn_run.focus_set()

    def clear_files(self):
        self.file_list = []
        self.update_file_list_ui()
        self.status_label.configure(text="清單已清除")

    def cancel_task(self):
        if self.is_running:
            if messagebox.askyesno("取消確認", "確定要停止目前的轉錄任務嗎？"):
                self.cancel_flag = True
                self.btn_cancel.configure(text="正在停止...", state="disabled")

    def start_thread(self):
        if self.is_running: return
        if not self.file_list:
            messagebox.showerror("錯誤", "請先加入至少一個影片檔案！")
            return

        self.is_running = True
        self.cancel_flag = False
        self.btn_run.configure(state="disabled")
        self.btn_add.configure(state="disabled") # 執行中不給加檔案
        self.btn_clear.configure(state="disabled")
        self.btn_cancel.configure(state="normal", text="取消 (Cancel)")
        
        self.save_settings() # 開始轉錄前先儲存設定
        
        self.log_textbox.configure(state="normal")
        self.log_textbox.delete("0.0", "end")
        self.log_textbox.configure(state="disabled")
        
        self._target_progress = 0.0
        self._current_progress = 0.0
        if hasattr(self, 'progress_label'):
            self.progress_label.configure(text="0.0%")
        self.progressbar.start()

        thread = threading.Thread(target=self.process_batch)
        thread.daemon = True
        thread.start()

    def process_batch(self):
        try:
            model_size = self.get_clean_model_name()
            device = self.device_var.get()
            output_fmt = self.format_var.get()
            compute_type = "int8" if device == "cpu" else "float16"
            
            use_zh_tw = self.zh_tw_var.get()
            translate_to_en = self.translate_en_var.get()
            
            task = "translate" if translate_to_en else "transcribe"
            initial_prompt = "以下是使用台灣繁體中文撰寫的字幕。" if (use_zh_tw and not translate_to_en) else None
            
            try:
                user_max_chars = int(self.max_chars_var.get())
                if user_max_chars < 25: user_max_chars = 35
            except:
                user_max_chars = 35
                
            hotwords = self.hotwords_var.get().strip()

            self.log(f"--- 批次任務開始: 共 {len(self.file_list)} 個檔案 (斷句策略: 自然語意與停頓, 防溢出上限: {user_max_chars} 字) ---")
            
            # --- 初始化轉錄核心與模型載入 (含錯誤處理) ---
            # 先嘗試用預設路徑 (系統緩存)
            # 若發生權限錯誤，詢問使用者是否改用本地 ./models 目錄
            
            current_download_root = self.model_path_var.get().strip()
            if not current_download_root: current_download_root = None
            
            # 建立或更新實例
            if not self.transcriber:
                self.transcriber = SubtitleTranscriber(model_size, device, compute_type, download_root=current_download_root)
            else:
                 # 若參數變更，重新建立
                if (self.transcriber.model_size != model_size or 
                    self.transcriber.device != device or 
                    getattr(self.transcriber, 'download_root', None) != current_download_root):
                     self.transcriber = SubtitleTranscriber(model_size, device, compute_type, download_root=current_download_root)

            # 嘗試載入模型
            try:
                self.transcriber.load_model(self.log)
                self.after(0, self.refresh_model_menu)
            except Exception as e:
                error_str = str(e).lower()
                # 檢查是否為權限或存取相關錯誤 (排除網路/模型下載失敗的相關錯誤)
                is_permission = (
                    ("permission denied" in error_str or "access is denied" in error_str or "read-only file system" in error_str)
                    and not ("模型下載" in str(e) or "網路" in str(e) or "connection" in error_str or "huggingface" in error_str)
                )
                if is_permission:
                    self.log(f"⚠️ 預設路徑存取失敗: {e}")
                    
                    # 詢問使用者
                    if messagebox.askyesno("權限錯誤 (Permission Error)", 
                                           "系統無法寫入預設模型快取目錄 (通常發生在權限受限的環境，如 MacOS 或公司電腦)。\n\n"
                                           "是否要改為下載模型到本程式下的 'models' 資料夾？\n(Download models to local './models' folder?)"):
                        
                        # 定義本地路徑
                        local_models_dir = os.path.join(os.getcwd(), "models")
                        try:
                            os.makedirs(local_models_dir, exist_ok=True)
                            self.log(f"正在切換模型儲存路徑至: {local_models_dir}")
                            
                            # 使用新的 download_root 重新初始化
                            self.transcriber = SubtitleTranscriber(model_size, device, compute_type, download_root=local_models_dir)
                            
                            # 再次嘗試載入
                            self.transcriber.load_model(self.log)
                            
                        except Exception as retry_e:
                            self.log(f"❌ 切換至本地目錄仍失敗: {retry_e}")
                            messagebox.showerror("錯誤", f"無法建立或寫入本地目錄:\n{retry_e}")
                            return
                    else:
                        self.log("❌ 使用者拒絕切換目錄，任務中止。")
                        return
                else:
                    # 其他錯誤（包含網路連線、GPU 等）直接拋出交由外層統一安全處理
                    raise e

            check_cancel = lambda: self.cancel_flag

            completed_count = 0
            produced_files = []
            
            # 取得執行緒數
            try:
                threads_count = int(self.cpu_threads_var.get())
            except:
                threads_count = 4

            # 傳入 cpu_threads 以便在需要時重新初始化核心
            if self.transcriber:
                self.transcriber.cpu_threads = threads_count

            for idx, file_path in enumerate(self.file_list):
                if self.cancel_flag:
                    break
                
                self.log(f"\n>> 正在處理 ({idx+1}/{len(self.file_list)}): {os.path.basename(file_path)}")
                def _start_progress():
                    self._target_progress = 0.0
                    self._current_progress = 0.0
                    if hasattr(self, 'progress_label'):
                        self.progress_label.configure(text="0.0%")
                    self.progressbar.start()
                self.after(0, _start_progress)
                
                try:
                    clean_punc = self.clean_punc_mapping_rev.get(self.clean_punc_var.get(), "space")
                    word_ts = self.word_timestamps_var.get()
                    spacing = self.spacing_var.get()
                    case_corr = self.case_correction_var.get()
                    vad_filter = self.vad_filter_var.get()
                    
                    result = self.transcriber.run(
                        file_path, 
                        log_callback=self.log,
                        progress_callback=self.update_progress,
                        cancel_check_callback=check_cancel,
                        output_format=output_fmt,
                        initial_prompt=initial_prompt,
                        task=task,
                        force_zh_tw=use_zh_tw,
                        max_chars=user_max_chars,
                        hotwords=hotwords if hotwords else None,
                        clean_punctuation=clean_punc,
                        word_timestamps=word_ts,
                        spacing=spacing,
                        case_correction=case_corr,
                        vad_filter=vad_filter
                    )
                    
                    if result:
                        completed_count += 1
                        produced_files.append(result)
                    else:
                        self.log(f"檔案 {idx+1} 已中止。")
                        
                except Exception as e:
                    error_str = str(e)
                    # 若為模型下載失敗、網路連線中斷或重大核心問題，應直接中止後續檔案，避免無效重複報錯
                    if "模型下載" in error_str or "網路連線失敗" in error_str or "無法取得模型" in error_str or "缺少 GPU 函式庫" in error_str:
                        raise e
                    self.log(f"檔案 {os.path.basename(file_path)} 發生錯誤: {e}")
                    continue

            if self.cancel_flag:
                self.log("\n--- 批次任務已手動取消 ---")
                messagebox.showwarning("已取消", "批次轉錄已中止。")
            else:
                self.log(f"\n--- 批次任務完成: 成功 {completed_count} / {len(self.file_list)} ---")
                self.after(0, lambda: self.show_completion_dialog(completed_count, produced_files))
            
        except Exception as e:
            error_msg = str(e)
            self.log(f"\n❌ 任務中止: {error_msg}")
            title = "網路連線錯誤" if ("網路" in error_msg or "下載" in error_msg) else "發生錯誤"
            messagebox.showerror(title, f"{error_msg}")
        
        finally:
            self.is_running = False
            def _reset_progress():
                self.progressbar.stop()
                self.progressbar.set(0)
                self._target_progress = 0.0
                self._current_progress = 0.0
                if hasattr(self, 'progress_label'):
                    self.progress_label.configure(text="0.0%")
            self.after(0, _reset_progress)
            self.status_label.configure(text="就緒 - 等待下一個任務")
            self.after(0, lambda: self.btn_run.configure(state="normal"))
            self.after(0, lambda: self.btn_add.configure(state="normal"))
            self.after(0, lambda: self.btn_clear.configure(state="normal"))
            self.after(0, lambda: self.btn_cancel.configure(state="disabled", text="取消 (Cancel)"))

    def toggle_advanced_settings(self):
        if self.adv_settings_frame.winfo_viewable():
            self.adv_settings_frame.grid_remove()
            self.btn_toggle_adv.configure(text="顯示進階設定")
        else:
            self.adv_settings_frame.grid(row=6, column=0, columnspan=4, sticky="ew", pady=(0, 15), padx=15)
            self.btn_toggle_adv.configure(text="隱藏進階設定")

    def open_manual_edit(self):
        file_types = [("字幕與文字檔案", "*.srt *.vtt *.txt"), ("SRT 字幕檔", "*.srt"), ("VTT 字幕檔", "*.vtt"), ("TXT 純文字檔", "*.txt"), ("所有檔案", "*.*")]
        selected_file = filedialog.askopenfilename(
            title="選擇要校對編輯的檔案",
            filetypes=file_types
        )
        if selected_file:
            SubtitleEditorWindow(self, selected_file)

    def show_completion_dialog(self, count, files):
        if not files:
            messagebox.showinfo("任務完成", f"批次處理結束！\n共成功轉錄 0 個檔案。")
            return
            
        dialog = ctk.CTkToplevel(self)
        dialog.title("轉錄任務完成")
        dialog.geometry("680x420")
        
        if platform.system() != "Darwin":
            dialog.transient(self)
            dialog.grab_set()
            
        # 套用 APP 圖標
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app_icon.ico")
        if os.path.exists(icon_path):
            try:
                dialog.after(200, lambda: dialog.iconbitmap(icon_path))
            except Exception as e:
                print(f"Failed to set dialog icon: {e}")
            
        label_title = ctk.CTkLabel(dialog, text="轉錄任務已完成", font=ctk.CTkFont(size=18, weight="bold"), text_color=("#1f538d", "#DCE4EE"))
        label_title.pack(pady=(15, 5))
        
        msg = f"已成功轉錄 {count} 個影音檔案。您可以直接在下方對個別檔案進行操作："
        label_msg = ctk.CTkLabel(dialog, text=msg, font=ctk.CTkFont(size=13))
        label_msg.pack(pady=(0, 10))
        
        # 轉換檔案列表滾動區域
        scroll = ctk.CTkScrollableFrame(dialog, height=220)
        scroll.pack(fill="both", expand=True, padx=20, pady=5)
        
        def open_file(f_path):
            if os.path.exists(f_path):
                if platform.system() == "Windows":
                    os.startfile(f_path)
                elif platform.system() == "Darwin":
                    import subprocess
                    subprocess.Popen(["open", f_path])
                else:
                    import subprocess
                    subprocess.Popen(["xdg-open", f_path])
                    
        def open_folder(f_path):
            output_dir = os.path.dirname(f_path)
            if os.path.exists(output_dir):
                if platform.system() == "Windows":
                    os.startfile(output_dir)
                elif platform.system() == "Darwin":
                    import subprocess
                    subprocess.Popen(["open", output_dir])
                else:
                    import subprocess
                    subprocess.Popen(["xdg-open", output_dir])
                    
        def edit_file(f_path):
            SubtitleEditorWindow(self, f_path)
            
        # 逐一填入檔案
        for i, f_path in enumerate(files):
            row_frame = ctk.CTkFrame(scroll, fg_color="transparent")
            row_frame.pack(fill="x", pady=4, padx=5)
            
            idx_str = f"[{i+1:02d}] "
            short_name = os.path.basename(f_path)
            
            # 限制長度
            if len(short_name) > 35:
                display_name = short_name[:17] + "..." + short_name[-15:]
            else:
                display_name = short_name
                
            lbl_name = ctk.CTkLabel(row_frame, text=idx_str + display_name, anchor="w", font=ctk.CTkFont(size=12))
            lbl_name.pack(side="left", fill="x", expand=True, padx=(5, 10))
            
            can_edit = f_path.lower().endswith((".srt", ".vtt", ".txt"))
            
            # 按鈕 1：開啟
            btn_open = ctk.CTkButton(row_frame, text="開啟", width=65, height=26, font=ctk.CTkFont(size=11),
                                     command=lambda p=f_path: open_file(p))
            btn_open.pack(side="left", padx=3)
            
            # 按鈕 2：校對
            if can_edit:
                btn_edit = ctk.CTkButton(row_frame, text="校對", width=65, height=26, font=ctk.CTkFont(size=11),
                                         fg_color="#1f538d", hover_color="#14375e", text_color="white",
                                         command=lambda p=f_path: edit_file(p))
            else:
                btn_edit = ctk.CTkButton(row_frame, text="校對", width=65, height=26, font=ctk.CTkFont(size=11),
                                         state="disabled", fg_color="gray", text_color="lightgray")
            btn_edit.pack(side="left", padx=3)
            
            # 按鈕 3：資料夾
            btn_dir = ctk.CTkButton(row_frame, text="資料夾", width=75, height=26, font=ctk.CTkFont(size=11),
                                    fg_color="transparent", border_width=1, text_color=("gray10", "#DCE4EE"),
                                    command=lambda p=f_path: open_folder(p))
            btn_dir.pack(side="left", padx=3)
            
        # 確定按鈕
        btn_close = ctk.CTkButton(dialog, text="確定", command=dialog.destroy, width=120)
        btn_close.pack(pady=15)

if __name__ == "__main__":
    import multiprocessing
    import sys
    import traceback
    import os
    import io
    
    # 強制將標準輸出與標準錯誤輸出設為 UTF-8 (修正 Windows cp950 編碼錯誤)
    if sys.stdout is not None and isinstance(sys.stdout, io.TextIOWrapper):
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except Exception:
            pass
    if sys.stderr is not None and isinstance(sys.stderr, io.TextIOWrapper):
        try:
            sys.stderr.reconfigure(encoding='utf-8')
        except Exception:
            pass
    
    # Enable multiprocessing support for frozen executables
    multiprocessing.freeze_support()
    
    # 避免在 PyInstaller 封裝沒有 console 模式下 (特別是 macOS) 因為 print 導致閃退
    if getattr(sys, 'frozen', False):
        if sys.stdout is None:
            sys.stdout = open(os.devnull, 'w')
        if sys.stderr is None:
            sys.stderr = open(os.devnull, 'w')
        if sys.platform == 'darwin':
            # 在 macOS 的 App Bundle 中，任何 print 輸出都可能引發崩潰，因此一律丟棄
            sys.stdout = open(os.devnull, 'w')
            sys.stderr = open(os.devnull, 'w')

    # Global exception handler to show errors in GUI before crashing
    def show_error(exc_type, exc_value, tb):
        err_msg = "".join(traceback.format_exception(exc_type, exc_value, tb))
        try:
            messagebox.showerror("Unhandled Error (未預期的錯誤)", f"發生錯誤導致程式崩潰:\n\n{err_msg}")
        except:
            pass # Creating messagebox failed
        sys.__excepthook__(exc_type, exc_value, tb)

    sys.excepthook = show_error

    # Windows DPI awareness fix
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except:
        pass
        
    app = App()
    app.mainloop()
