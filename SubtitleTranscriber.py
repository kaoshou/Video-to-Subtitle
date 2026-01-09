import os
import datetime
import threading
import tkinter as tk
from tkinter import filedialog, ttk, messagebox, scrolledtext
from faster_whisper import WhisperModel
import webbrowser
import json
import platform

# --- 嘗試匯入拖曳功能庫 (tkinterdnd2) ---
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    DND_AVAILABLE = True
except ImportError:
    DND_AVAILABLE = False
    print("提示: 若要啟用檔案拖曳功能，請執行 pip install tkinterdnd2")

# --- 核心邏輯區 ---

class SubtitleTranscriber:
    def __init__(self, model_size="small", device="cpu", compute_type="int8"):
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.model = None

    def load_model(self, log_callback):
        """載入模型 (第一次執行會自動下載)"""
        log_callback(f"正在載入模型: {self.model_size} (Device: {self.device})...")
        log_callback("初次執行需下載模型檔案 (約 500MB - 2GB)，請稍候...")
        try:
            self.model = WhisperModel(self.model_size, device=self.device, compute_type=self.compute_type)
            log_callback("模型載入完成！")
        except Exception as e:
            # 錯誤捕捉邏輯
            error_str = str(e).lower()
            if "cudnn" in error_str or "cublas" in error_str or "load symbol" in error_str or "dll" in error_str:
                friendly_msg = (
                    "啟動 GPU 模式失敗。\n"
                    "原因: 找不到必要的 NVIDIA 驅動程式或 cuDNN 函式庫。\n"
                    "解決方案: 請將「運算單元」切換為 'cpu' 模式。"
                )
                log_callback("錯誤: 缺少 GPU 函式庫，請切換至 CPU 模式。")
                raise RuntimeError(friendly_msg)
            
            log_callback(f"模型載入失敗: {e}")
            raise e

    def format_timestamp(self, seconds, separator=","):
        """
        將秒數轉換為時間戳格式
        SRT 使用逗號 (,) 分隔毫秒: HH:MM:SS,mmm
        VTT 使用點號 (.) 分隔毫秒: HH:MM:SS.mmm
        """
        td = datetime.timedelta(seconds=seconds)
        total_seconds = int(td.total_seconds())
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        secs = total_seconds % 60
        millis = int(td.microseconds / 1000)
        return f"{hours:02}:{minutes:02}:{secs:02}{separator}{millis:03}"

    def run(self, file_path, log_callback, progress_callback, cancel_check_callback=None, output_format="srt", initial_prompt=None, task="transcribe"):
        """
        執行轉錄
        output_format: "srt", "vtt", "txt", "tsv", "json"
        initial_prompt: 用於引導模型輸出的提示詞 (例如強制繁體中文)
        task: "transcribe" (轉錄) 或 "translate" (翻譯成英文)
        """
        if not self.model:
            self.load_model(log_callback)

        # --- 記錄開始時間 ---
        start_time = datetime.datetime.now()
        log_callback(f"--------------------------------------------------")
        log_callback(f"任務開始時間: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        log_callback(f"處理檔案: {os.path.basename(file_path)}")
        log_callback(f"任務模式: {'翻譯成英文' if task == 'translate' else '原語轉錄'}")
        log_callback(f"輸出格式: {output_format.upper()}")
        
        if initial_prompt and task == "transcribe":
            log_callback(f"啟用提示詞優化: {initial_prompt}")
        
        # 準備參數
        transcribe_options = {
            "beam_size": 5,
            "task": task  # 新增 task 參數
        }
        if initial_prompt:
            transcribe_options["initial_prompt"] = initial_prompt

        # 執行轉錄
        segments, info = self.model.transcribe(file_path, **transcribe_options)
        
        log_callback(f"偵測來源語言: {info.language.upper()} (信心度: {info.language_probability:.2f})")
        
        # 決定副檔名
        ext = f".{output_format.lower()}"
        # 如果是翻譯模式，在檔名後加上 .en 標示
        suffix = ".en" if task == "translate" else ""
        
        # 初始輸出路徑
        base_output_path = os.path.splitext(file_path)[0] + suffix + ext
        output_path = base_output_path
        
        # 檢查檔案是否存在，若存在則自動編號 (避免覆蓋)
        counter = 1
        while os.path.exists(output_path):
            path_no_ext = os.path.splitext(base_output_path)[0]
            output_path = f"{path_no_ext}_{counter}{ext}"
            counter += 1
        
        # 用於收集 JSON 資料
        json_results = []
        
        try:
            # 如果不是 JSON，先開啟檔案準備寫入
            file_handle = None
            if output_format.lower() != "json":
                file_handle = open(output_path, "w", encoding="utf-8")
                
                # 寫入標頭
                if output_format.lower() == "vtt":
                    file_handle.write("WEBVTT\n\n")
                elif output_format.lower() == "tsv":
                    file_handle.write("start\tend\ttext\n")

            for i, segment in enumerate(segments):
                # 檢查是否取消
                if cancel_check_callback and cancel_check_callback():
                    log_callback(">>> 使用者取消了作業 <<<")
                    if file_handle:
                        file_handle.write("\n[Interrupted by User]\n")
                    return None 

                text = segment.text.strip()
                start_sec = segment.start
                end_sec = segment.end
                
                # 在介面上顯示進度
                log_timestamp = self.format_timestamp(start_sec)
                log_callback(f"[{log_timestamp}] {text}")

                # 處理各格式輸出
                if output_format.lower() == "json":
                    json_results.append({
                        "id": i,
                        "start": start_sec,
                        "end": end_sec,
                        "text": text
                    })
                
                elif file_handle:
                    if output_format.lower() == "txt":
                        file_handle.write(f"{text}\n")
                    
                    elif output_format.lower() == "tsv":
                        # TSV 標準: start(ms) end(ms) text
                        file_handle.write(f"{int(start_sec * 1000)}\t{int(end_sec * 1000)}\t{text}\n")
                    
                    else:
                        # SRT / VTT
                        separator = "." if output_format.lower() == "vtt" else ","
                        start_time_str = self.format_timestamp(start_sec, separator)
                        end_time_str = self.format_timestamp(end_sec, separator)
                        
                        if output_format.lower() == "srt":
                            file_handle.write(f"{i + 1}\n")
                            file_handle.write(f"{start_time_str} --> {end_time_str}\n")
                            file_handle.write(f"{text}\n\n")
                        elif output_format.lower() == "vtt":
                            file_handle.write(f"{start_time_str} --> {end_time_str}\n")
                            file_handle.write(f"{text}\n\n")

            # 迴圈結束後，如果是 JSON 則寫入檔案
            if output_format.lower() == "json":
                with open(output_path, "w", encoding="utf-8") as f:
                    json.dump(json_results, f, ensure_ascii=False, indent=2)

        finally:
            if file_handle:
                file_handle.close()
        
        # --- 記錄結束時間與耗時 ---
        end_time = datetime.datetime.now()
        duration = end_time - start_time
        
        log_callback(f"--------------------------------------------------")
        log_callback(f"任務結束時間: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
        log_callback(f"總耗時: {duration}")
        log_callback(f"檔案已儲存於: {output_path}")
        
        return output_path

# --- 圖形介面區 (UI) ---

class App:
    def __init__(self, root):
        self.root = root
        self.root.title("Video to Subtitle - 本地語音轉字幕工具")
        self.root.geometry("780x740") # 調整高度
        
        # 定義顏色與變數
        self.colors = {
            "bg_main": "#f4f6f9",
            "bg_card": "#ffffff",
            "primary": "#0078d7",
            "primary_hover": "#005a9e",
            "danger": "#d9534f",
            "danger_hover": "#c9302c",
            "text": "#333333",
            "text_light": "#666666"
        }

        self.root.configure(bg=self.colors["bg_main"])
        
        # --- 樣式設定 ---
        self.style = ttk.Style()
        self.style.theme_use('clam') 
        
        default_font = ("Microsoft JhengHei UI", 10)
        self.style.configure(".", font=default_font, background=self.colors["bg_main"], foreground=self.colors["text"])
        self.style.configure("Card.TFrame", background=self.colors["bg_card"], relief="flat")
        self.style.configure("Modern.TLabelframe", 
                             background=self.colors["bg_card"], 
                             relief="solid", borderwidth=1, bordercolor="#e0e0e0")
        self.style.configure("Modern.TLabelframe.Label", 
                             font=("Microsoft JhengHei UI", 11, "bold"), 
                             foreground=self.colors["primary"], background=self.colors["bg_card"])
        self.style.configure("Modern.TEntry", padding=5, relief="flat", borderwidth=1)
        self.style.configure("TButton", padding=6, font=("Microsoft JhengHei UI", 10))
        self.style.configure("Accent.TButton", 
                             font=("Microsoft JhengHei UI", 11, "bold"), 
                             background=self.colors["primary"], foreground="white", borderwidth=0, focuscolor="none")
        self.style.map("Accent.TButton", 
                       background=[("active", self.colors["primary_hover"]), ("disabled", "#cccccc")],
                       foreground=[("disabled", "#ffffff")])
        self.style.configure("Danger.TButton", 
                             font=("Microsoft JhengHei UI", 11, "bold"), 
                             background=self.colors["danger"], foreground="white", borderwidth=0, focuscolor="none")
        self.style.map("Danger.TButton", 
                       background=[("active", self.colors["danger_hover"]), ("disabled", "#cccccc")],
                       foreground=[("disabled", "#ffffff")])
        
        self.style.configure("TCheckbutton", background=self.colors["bg_card"], font=("Microsoft JhengHei UI", 10))

        # 初始化變數
        self.transcriber = None
        self.is_running = False
        self.cancel_flag = False
        self.path_var = tk.StringVar()
        self.model_var = tk.StringVar(value="small")
        self.device_var = tk.StringVar(value="cpu")
        self.format_var = tk.StringVar(value="srt")
        self.zh_tw_var = tk.BooleanVar(value=False) 
        self.translate_en_var = tk.BooleanVar(value=False) # 翻譯成英文選項

        # 建構 UI
        self.create_menu()
        self.create_widgets()
        self.setup_dnd()

    def setup_dnd(self):
        if DND_AVAILABLE:
            try:
                self.root.drop_target_register(DND_FILES)
                self.root.dnd_bind('<<Drop>>', self.on_drop)
            except Exception as e:
                print(f"拖曳功能初始化失敗: {e}")

    def on_drop(self, event):
        file_path = event.data
        if file_path.startswith('{') and file_path.endswith('}'):
            file_path = file_path[1:-1]
        if '}' in file_path: 
            file_path = file_path.split('}')[0]
            if file_path.startswith('{'):
                file_path = file_path[1:]
        self.path_var.set(file_path)
        self.status_var.set(f"已載入檔案: {os.path.basename(file_path)}")
        self.btn_run.focus_set()

    def create_menu(self):
        menubar = tk.Menu(self.root)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="開啟影片 (Open)", command=self.browse_file)
        file_menu.add_separator()
        file_menu.add_command(label="離開 (Exit)", command=self.root.quit)
        menubar.add_cascade(label="檔案 (File)", menu=file_menu)
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="關於本程式 (About)", command=self.show_about)
        menubar.add_cascade(label="說明 (Help)", menu=help_menu)
        self.root.config(menu=menubar)

    def create_widgets(self):
        main_container = ttk.Frame(self.root, padding=20)
        main_container.pack(fill="both", expand=True)

        header_frame = ttk.Frame(main_container)
        header_frame.pack(fill="x", pady=(0, 20))
        title_label = ttk.Label(header_frame, text="AI 語音轉字幕工具", 
                                font=("Microsoft JhengHei UI", 20, "bold"), foreground=self.colors["text"])
        title_label.pack(anchor="w")
        
        os_name = platform.system()
        subtitle_text = "使用 OpenAI Whisper 本地端模型"
        if os_name == "Darwin":
            subtitle_text += " (macOS M-Chip Optimized)"
        subtitle_label = ttk.Label(header_frame, text=subtitle_text, 
                                   font=("Microsoft JhengHei UI", 10), foreground=self.colors["text_light"])
        subtitle_label.pack(anchor="w")

        # --- 卡片 1: 檔案選擇 ---
        frame_file = ttk.LabelFrame(main_container, text=" 1. 影片來源 ", padding=15, style="Modern.TLabelframe")
        frame_file.pack(fill="x", pady=(0, 15))
        file_inner = ttk.Frame(frame_file, style="Card.TFrame")
        file_inner.pack(fill="x")
        entry_path = ttk.Entry(file_inner, textvariable=self.path_var, font=("Consolas", 10))
        entry_path.pack(side="left", fill="x", expand=True, padx=(0, 10), ipady=3)
        btn_browse = ttk.Button(file_inner, text="瀏覽檔案...", command=self.browse_file)
        btn_browse.pack(side="right")

        # --- 卡片 2: 設定選項 ---
        frame_settings = ttk.LabelFrame(main_container, text=" 2. 轉換設定 ", padding=15, style="Modern.TLabelframe")
        frame_settings.pack(fill="x", pady=(0, 15))
        
        # Row 0: 選項
        ttk.Label(frame_settings, text="準確度 (Model):", background=self.colors["bg_card"]).grid(row=0, column=0, padx=(0, 5), sticky="w")
        combo_model = ttk.Combobox(frame_settings, textvariable=self.model_var, 
                                   values=["tiny", "base", "small", "medium", "large-v3"], 
                                   state="readonly", width=10)
        combo_model.grid(row=0, column=1, sticky="w")
        
        ttk.Label(frame_settings, text="運算單元:", background=self.colors["bg_card"]).grid(row=0, column=2, padx=(15, 5), sticky="w")
        
        if os_name == "Darwin":
            device_values = ["cpu"]
        else:
            device_values = ["cpu", "cuda"]
            
        combo_device = ttk.Combobox(frame_settings, textvariable=self.device_var, 
                                    values=device_values, 
                                    state="readonly", width=8)
        combo_device.grid(row=0, column=3, sticky="w")
        if self.device_var.get() not in device_values:
            self.device_var.set("cpu")

        ttk.Label(frame_settings, text="輸出格式:", background=self.colors["bg_card"]).grid(row=0, column=4, padx=(15, 5), sticky="w")
        combo_format = ttk.Combobox(frame_settings, textvariable=self.format_var, 
                                   values=["srt", "vtt", "txt", "tsv", "json"], 
                                   state="readonly", width=8)
        combo_format.grid(row=0, column=5, sticky="w")

        # Row 1: 進階選項 (Checkbox)
        # 用一個 frame 來裝兩個 checkbox 讓排列更整齊
        checkbox_frame = ttk.Frame(frame_settings, style="Card.TFrame")
        checkbox_frame.grid(row=1, column=0, columnspan=6, sticky="w", pady=(10, 0))

        chk_zhtw = ttk.Checkbutton(checkbox_frame, text="強制繁體中文 (Traditional Chinese)", 
                                   variable=self.zh_tw_var, style="TCheckbutton", command=self.on_check_zhtw)
        chk_zhtw.pack(side="left", padx=(0, 20))

        chk_trans = ttk.Checkbutton(checkbox_frame, text="翻譯成英文字幕 (Translate to English)", 
                                   variable=self.translate_en_var, style="TCheckbutton", command=self.on_check_trans)
        chk_trans.pack(side="left")

        # Row 2: 提示文字
        self.hint_label = ttk.Label(frame_settings, text="提示: 勾選「強制繁體中文」可避免出現簡體字。", 
                  font=("Microsoft JhengHei UI", 9), foreground=self.colors["text_light"], 
                  background=self.colors["bg_card"])
        self.hint_label.grid(row=2, column=0, columnspan=6, sticky="w", pady=(5, 0))

        # --- 按鈕區 ---
        frame_action = ttk.Frame(main_container)
        frame_action.pack(fill="x", pady=(0, 15))
        self.btn_run = ttk.Button(frame_action, text="開始生成 (Start)", command=self.start_thread, style="Accent.TButton", cursor="hand2")
        self.btn_run.pack(side="left", fill="x", expand=True, padx=(0, 10), ipady=8)
        self.btn_cancel = ttk.Button(frame_action, text="取消 (Cancel)", command=self.cancel_task, style="Danger.TButton", state="disabled", cursor="hand2")
        self.btn_cancel.pack(side="right", fill="x", expand=True, padx=(0, 0), ipady=8)

        # --- 紀錄區 ---
        frame_log = ttk.LabelFrame(main_container, text=" 執行紀錄 ", padding=(10, 5), style="Modern.TLabelframe")
        frame_log.pack(fill="both", expand=True)
        self.txt_log = scrolledtext.ScrolledText(frame_log, height=10, state="disabled", 
                                                 font=("Consolas", 10), bg="#fcfcfc", relief="flat", padx=5, pady=5)
        self.txt_log.pack(fill="both", expand=True)

        # 狀態列
        self.status_var = tk.StringVar(value="就緒 - 請選擇影片檔案 (支援拖曳載入)")
        status_bar = ttk.Label(self.root, textvariable=self.status_var, background="#e9ecef", anchor="w", padding=(15, 5), font=("Microsoft JhengHei UI", 9))
        status_bar.pack(side="bottom", fill="x")

    def on_check_zhtw(self):
        # 如果勾選了繁體中文，且英文翻譯也被勾選，則提示使用者 (因為翻譯成英文會忽略繁體設定)
        if self.zh_tw_var.get() and self.translate_en_var.get():
            self.hint_label.config(text="注意: 若勾選「翻譯成英文」，則「強制繁體中文」將無效 (輸出為英文)。", foreground=self.colors["danger"])
        else:
            self.update_hint()

    def on_check_trans(self):
        # 更新提示
        self.on_check_zhtw()

    def update_hint(self):
        os_name = platform.system()
        base_hint = "提示: "
        if self.zh_tw_var.get():
            base_hint += "已啟用繁體中文優化。"
        elif self.translate_en_var.get():
            base_hint += "目前模式為將字幕翻譯成英文。"
        else:
            base_hint += "模型越大越準確，但速度越慢。"
            
        if os_name == "Darwin":
            base_hint += " (Apple Silicon Mac 建議使用 CPU 模式)"
            
        self.hint_label.config(text=base_hint, foreground=self.colors["text_light"])

    def show_about(self):
        about_text = (
            "Video to Subtitle(本地語音轉字幕工具)\n"
            "版本: 1.7.0 \n\n"
            "【開發人員資訊】\n"
            "開發人員: 鄭郁翰 (Cheng, Yu-Han)\n"
            "E-mail: kaoshou@gmail.com\n\n"
            "--------------------------------------------------\n"
            "【開源專案與授權宣告 (Open Source)】\n"
            "本軟體使用以下開源專案：\n\n"
            "1. faster-whisper (MIT License)\n"
            "   https://github.com/SYSTRAN/faster-whisper\n\n"
            "2. CTranslate2 (MIT License)\n"
            "   https://github.com/OpenNMT/CTranslate2\n\n"
            "3. FFmpeg (LGPL v2.1+ / GPL v2+)\n"
            "   https://ffmpeg.org\n\n"           
            "4. tkinterdnd2 (MIT License)\n"
            "   https://github.com/pmgagne/tkinterdnd2\n"
        )
        messagebox.showinfo("關於本程式", about_text)

    def log(self, msg):
        def _update():
            self.txt_log.config(state="normal")
            self.txt_log.insert(tk.END, msg + "\n")
            self.txt_log.see(tk.END)
            self.txt_log.config(state="disabled")
            self.status_var.set(msg) 
        self.root.after(0, _update)

    def browse_file(self):
        filename = filedialog.askopenfilename(
            filetypes=[("Media Files", "*.mp4 *.mp3 *.mkv *.wav *.mov *.avi *.m4a"), ("All Files", "*.*")]
        )
        if filename:
            self.path_var.set(filename)
            self.btn_run.focus_set()

    def cancel_task(self):
        if self.is_running:
            if messagebox.askyesno("取消確認", "確定要停止目前的轉錄任務嗎？"):
                self.cancel_flag = True
                self.btn_cancel.config(text="正在停止...", state="disabled")

    def start_thread(self):
        if self.is_running: return
        file_path = self.path_var.get()
        if not file_path or not os.path.exists(file_path):
            messagebox.showerror("錯誤", "請先選擇有效的影片檔案！")
            return

        self.is_running = True
        self.cancel_flag = False
        self.btn_run.config(state="disabled")
        self.btn_cancel.config(state="normal", text="取消 (Cancel)")
        self.txt_log.config(state="normal")
        self.txt_log.delete(1.0, tk.END)
        self.txt_log.config(state="disabled")
        
        thread = threading.Thread(target=self.process_video, args=(file_path,))
        thread.daemon = True
        thread.start()

    def process_video(self, file_path):
        try:
            model_size = self.model_var.get()
            device = self.device_var.get()
            output_fmt = self.format_var.get()
            compute_type = "int8" if device == "cpu" else "float16"
            
            # 設定任務類型與提示詞
            use_zh_tw = self.zh_tw_var.get()
            translate_to_en = self.translate_en_var.get()
            
            task = "translate" if translate_to_en else "transcribe"
            
            # 提示詞僅在「轉錄」且勾選「繁體」時有效。
            # 若選翻譯成英文，initial_prompt 效果有限且不需要中文提示。
            initial_prompt = "以下是使用台灣繁體中文撰寫的字幕。" if (use_zh_tw and not translate_to_en) else None

            self.transcriber = SubtitleTranscriber(model_size, device, compute_type)
            check_cancel = lambda: self.cancel_flag

            result = self.transcriber.run(
                file_path, 
                log_callback=self.log,
                progress_callback=None,
                cancel_check_callback=check_cancel,
                output_format=output_fmt,
                initial_prompt=initial_prompt,
                task=task # 傳入任務類型
            )
            
            if result:
                messagebox.showinfo("任務完成", f"成功！\n\n檔案已儲存至:\n{result}")
            else:
                self.log("--- 使用者已中止任務 ---")
                messagebox.showwarning("已取消", "字幕生成已手動中止。")
            
        except Exception as e:
            error_msg = str(e)
            self.log(f"錯誤中止: {error_msg}")
            messagebox.showerror("發生錯誤", f"無法執行轉換:\n\n{error_msg}")
        
        finally:
            self.is_running = False
            self.status_var.set("就緒 - 等待下一個任務")
            self.root.after(0, lambda: self.btn_run.config(state="normal"))
            self.root.after(0, lambda: self.btn_cancel.config(state="disabled", text="取消 (Cancel)"))

if __name__ == "__main__":
    if DND_AVAILABLE:
        root = TkinterDnD.Tk()
    else:
        root = tk.Tk()
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except:
        pass
    app = App(root)
    root.mainloop()