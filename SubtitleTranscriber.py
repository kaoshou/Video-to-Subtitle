
import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
import customtkinter as ctk
import webbrowser
import platform
import time

# Import core logic from transcriber.py
from transcriber import SubtitleTranscriber

# --- 嘗試匯入拖曳功能庫 (tkinterdnd2) ---
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    DND_AVAILABLE = True
except ImportError:
    DND_AVAILABLE = False
    print("提示: 若要啟用檔案拖曳功能，請執行 pip install tkinterdnd2")

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

class App(BaseClass):
    def __init__(self):
        super().__init__()
        
        self.title("Video to Subtitle - 本地語音轉字幕工具")
        self.geometry("780x720")
        
        # 初始化變數
        self.transcriber = None
        self.is_running = False
        self.cancel_flag = False
        self.file_list = [] # 儲存多個檔案路徑
        self.model_var = ctk.StringVar(value="medium")
        self.device_var = ctk.StringVar(value="cpu")
        self.format_var = ctk.StringVar(value="srt")
        self.zh_tw_var = ctk.BooleanVar(value=False) 
        self.translate_en_var = ctk.BooleanVar(value=False) 

        # Grid configuration
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1) # Main content expands

        # 建構 UI
        self.create_widgets()
        self.setup_dnd()

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
                                             values=["tiny", "base", "small", "medium", "large-v3"])
        self.combo_model.grid(row=1, column=1, padx=15, pady=5, sticky="ew")
        
        self.label_device = ctk.CTkLabel(self.settings_frame, text="運算單元:")
        self.label_device.grid(row=1, column=2, padx=15, pady=5, sticky="e")
        
        device_values = ["cpu", "cuda"] if platform.system() != "Darwin" else ["cpu"]
        self.combo_device = ctk.CTkOptionMenu(self.settings_frame, variable=self.device_var, values=device_values)
        self.combo_device.grid(row=1, column=3, padx=15, pady=5, sticky="ew")

        # Row 2: Format & Checkbox
        self.label_fmt = ctk.CTkLabel(self.settings_frame, text="輸出格式:")
        self.label_fmt.grid(row=2, column=0, padx=15, pady=5, sticky="e")
        self.combo_fmt = ctk.CTkOptionMenu(self.settings_frame, variable=self.format_var, 
                                           values=["srt", "vtt", "txt", "tsv", "json"])
        self.combo_fmt.grid(row=2, column=1, padx=15, pady=5, sticky="ew")
        
        # Checkboxes 
        self.chk_frame = ctk.CTkFrame(self.settings_frame, fg_color="transparent")
        self.chk_frame.grid(row=2, column=2, columnspan=2, sticky="w")
        
        self.chk_zhtw = ctk.CTkCheckBox(self.chk_frame, text="強制繁體中文", variable=self.zh_tw_var, command=self.on_check_zhtw)
        self.chk_zhtw.pack(side="left", padx=15, pady=5)

        self.chk_trans = ctk.CTkCheckBox(self.chk_frame, text="翻譯成英文", variable=self.translate_en_var, command=self.on_check_trans)
        self.chk_trans.pack(side="left", padx=15, pady=5)

        self.label_hint = ctk.CTkLabel(self.settings_frame, text="提示: 勾選「強制繁體中文」可避免出現簡體字。", text_color="gray")
        self.label_hint.grid(row=3, column=0, columnspan=4, padx=15, pady=(5, 10), sticky="w")

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

        # Progress Bar
        self.progressbar = ctk.CTkProgressBar(self.main_frame, orientation="horizontal", height=12)
        self.progressbar.grid(row=3, column=0, sticky="ew", pady=(0, 10))
        self.progressbar.set(0) # 0%

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

        # Right: About Button
        self.btn_about = ctk.CTkButton(self.controls_frame, text="關於本程式 (About)", command=self.show_about, 
                                       width=120, fg_color="transparent", border_width=1, text_color=("gray10", "#DCE4EE"))
        self.btn_about.pack(side="right")

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
        
    def change_appearance_mode_event(self, new_appearance_mode: str):
        ctk.set_appearance_mode(new_appearance_mode)

    def on_check_zhtw(self):
        if self.zh_tw_var.get() and self.translate_en_var.get():
            self.label_hint.configure(text="注意: 若勾選「翻譯成英文」，則「強制繁體中文」將無效 (輸出為英文)。", text_color="orange")
        else:
            self.label_hint.configure(text="提示: 勾選「強制繁體中文」可避免出現簡體字。", text_color="gray")

    def on_check_trans(self):
        self.on_check_zhtw()

    def show_about(self):
        # Create a new Toplevel window
        about_window = ctk.CTkToplevel(self)
        about_window.title("關於本程式")
        about_window.geometry("500x600")
        about_window.resizable(False, False)
        
        # Ensure it stays on top and grabs focus
        about_window.transient(self)
        about_window.grab_set()
        
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
        ctk.CTkLabel(scroll_frame, text="Version 2.0.0").pack(pady=(0, 20))

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
            ("FFmpeg", "LGPL v2.1+ / GPL v2+", "https://ffmpeg.org"),
            ("CustomTkinter", "MIT License", "https://github.com/TomSchimansky/CustomTkinter"),
            ("tkinterdnd2", "MIT License", "https://github.com/pmgagne/tkinterdnd2")
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
        self.after(0, lambda: self.progressbar.set(value))

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
        
        self.log_textbox.configure(state="normal")
        self.log_textbox.delete("0.0", "end")
        self.log_textbox.configure(state="disabled")
        
        self.progressbar.set(0) # Reset progress

        thread = threading.Thread(target=self.process_batch)
        thread.daemon = True
        thread.start()

    def process_batch(self):
        try:
            model_size = self.model_var.get()
            device = self.device_var.get()
            output_fmt = self.format_var.get()
            compute_type = "int8" if device == "cpu" else "float16"
            
            use_zh_tw = self.zh_tw_var.get()
            translate_to_en = self.translate_en_var.get()
            
            task = "translate" if translate_to_en else "transcribe"
            initial_prompt = "以下是使用台灣繁體中文撰寫的字幕。" if (use_zh_tw and not translate_to_en) else None

            self.log(f"--- 批次任務開始: 共 {len(self.file_list)} 個檔案 ---")
            
            # --- 初始化轉錄核心與模型載入 (含錯誤處理) ---
            # 先嘗試用預設路徑 (系統緩存)
            # 若發生權限錯誤，詢問使用者是否改用本地 ./models 目錄
            
            current_download_root = None
            
            # 建立或更新實例 (先用預設路徑)
            if not self.transcriber:
                self.transcriber = SubtitleTranscriber(model_size, device, compute_type)
            else:
                 # 若參數變更，重新建立
                if self.transcriber.model_size != model_size or self.transcriber.device != device:
                     self.transcriber = SubtitleTranscriber(model_size, device, compute_type)

            # 嘗試載入模型
            try:
                self.transcriber.load_model(self.log)
            except Exception as e:
                error_str = str(e).lower()
                # 檢查是否為權限或存取相關錯誤
                if "permission denied" in error_str or "access is denied" in error_str or "read-only file system" in error_str or "oserror" in error_str:
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
                    # 其他錯誤直接拋出
                    raise e

            check_cancel = lambda: self.cancel_flag

            completed_count = 0
            
            for idx, file_path in enumerate(self.file_list):
                if self.cancel_flag:
                    break
                
                self.log(f"\n>> 正在處理 ({idx+1}/{len(self.file_list)}): {os.path.basename(file_path)}")
                self.update_progress(0) # Reset progress bar for next file
                
                try:
                    result = self.transcriber.run(
                        file_path, 
                        log_callback=self.log,
                        progress_callback=self.update_progress,
                        cancel_check_callback=check_cancel,
                        output_format=output_fmt,
                        initial_prompt=initial_prompt,
                        task=task 
                    )
                    
                    if result:
                        completed_count += 1
                    else:
                        self.log(f"檔案 {idx+1} 已中止。")
                        
                except Exception as e:
                    self.log(f"檔案 {os.path.basename(file_path)} 發生錯誤: {e}")
                    # Continue to next file? Yes, usually batch should continue.
                    continue

            if self.cancel_flag:
                self.log("\n--- 批次任務已手動取消 ---")
                messagebox.showwarning("已取消", "批次轉錄已中止。")
            else:
                self.log(f"\n--- 批次任務完成: 成功 {completed_count} / {len(self.file_list)} ---")
                messagebox.showinfo("任務完成", f"批次處理結束！\n共成功轉錄 {completed_count} 個檔案。")
            
        except Exception as e:
            error_msg = str(e)
            self.log(f"核心錯誤中止: {error_msg}")
            messagebox.showerror("發生錯誤", f"無法執行轉換:\n\n{error_msg}")
        
        finally:
            self.is_running = False
            self.update_progress(0)
            self.status_label.configure(text="就緒 - 等待下一個任務")
            self.after(0, lambda: self.btn_run.configure(state="normal"))
            self.after(0, lambda: self.btn_add.configure(state="normal"))
            self.after(0, lambda: self.btn_clear.configure(state="normal"))
            self.after(0, lambda: self.btn_cancel.configure(state="disabled", text="取消 (Cancel)"))

if __name__ == "__main__":
    import multiprocessing
    import sys
    import traceback
    
    # Enable multiprocessing support for frozen executables
    multiprocessing.freeze_support()
    
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
