import os
import datetime
from faster_whisper import WhisperModel
import json
import logging

try:
    import opencc
    converter = opencc.OpenCC('s2twp.json') # 簡體到繁體 (台灣慣用語)
except ImportError:
    converter = None
    logging.warning("尚未安裝 opencc，將無法支援強制轉換繁體功能，請執行 pip install opencc")


class SubtitleTranscriber:
    def __init__(self, model_size="small", device="cpu", compute_type="int8", download_root=None):
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.download_root = download_root
        self.model = None

    def load_model(self, log_callback):
        """載入模型 (第一次執行會自動下載)"""
        print(f"DEBUG: load_model called. Model size: {self.model_size}, Device: {self.device}, Root: {self.download_root}")
        # 如果模型已經載入，直接返回
        if self.model: 
            print("DEBUG: Model already loaded.")
            return
        
        if log_callback:
            log_callback(f"正在載入模型: {self.model_size} (Device: {self.device})...")
            model_path = os.path.abspath(self.download_root) if self.download_root else os.path.abspath(os.path.expanduser("~/.cache/huggingface/hub"))
            log_callback(f"模型儲存路徑: {model_path}")
            log_callback("初次執行需下載模型檔案 (約 500MB - 2GB)，請稍候...")
        try:
            print("DEBUG: Initializing WhisperModel...")
            self.model = WhisperModel(
                self.model_size, 
                device=self.device, 
                compute_type=self.compute_type,
                download_root=self.download_root
            )
            print("DEBUG: WhisperModel initialized successfully.")
            if log_callback:
                log_callback("模型載入完成！")
        except Exception as e:
            print(f"DEBUG: Error in load_model: {e}")
            # 錯誤捕捉邏輯
            error_str = str(e).lower()
            if "cudnn" in error_str or "cublas" in error_str or "load symbol" in error_str or "dll" in error_str:
                friendly_msg = (
                    "啟動 GPU 模式失敗。\n"
                    "原因: 找不到必要的 NVIDIA 驅動程式或 cuDNN 函式庫。\n"
                    "解決方案: 請將「運算單元」切換為 'cpu' 模式。"
                )
                if log_callback:
                    log_callback("錯誤: 缺少 GPU 函式庫，請切換至 CPU 模式。")
                raise RuntimeError(friendly_msg)
            
            if log_callback:
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

    def run(self, file_path, log_callback=None, progress_callback=None, cancel_check_callback=None, output_format="srt", initial_prompt=None, task="transcribe", force_zh_tw=False):
        """
        執行轉錄
        output_format: "srt", "vtt", "txt", "tsv", "json"
        initial_prompt: 用於引導模型輸出的提示詞 (例如強制繁體中文)
        task: "transcribe" (轉錄) 或 "translate" (翻譯成英文)
        force_zh_tw: (bool) 是否透過 opencc 將所有文字強制轉為台灣繁體中文
        """
        print(f"DEBUG: run() called for file: {file_path}")
        if not self.model:
            print("DEBUG: Model not loaded in run(), calling load_model()...")
            self.load_model(log_callback)

        # --- 記錄開始時間 ---
        start_time = datetime.datetime.now()
        if log_callback:
            log_callback(f"--------------------------------------------------")
            log_callback(f"任務開始時間: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
            log_callback(f"處理檔案: {os.path.basename(file_path)}")
            
            model_path = os.path.abspath(self.download_root) if self.download_root else os.path.abspath(os.path.expanduser("~/.cache/huggingface/hub"))
            log_callback(f"模型存放路徑: {model_path}")
            
            mode_text = "翻譯成英文 (Translate to English)" if task == "translate" else "原語轉錄 (Transcribe)"
            log_callback(f"任務模式: {mode_text}")
            log_callback(f"輸出格式: {output_format.upper()}")
        
            if initial_prompt and task == "transcribe":
                log_callback(f"啟用提示詞優化: {initial_prompt}")
        
        # 準備參數
        transcribe_options = {
            "beam_size": 5,
            "task": task,
            "vad_filter": True, # 啟用 Voice Activity Detection (只在有人聲時才進行語音辨識)
            "vad_parameters": dict(min_silence_duration_ms=500), # 靜音超過 0.5 秒就切斷
            "condition_on_previous_text": False # 關閉上下文關聯，避免模型陷入長句幻覺的無限迴圈
        }
        if initial_prompt:
            transcribe_options["initial_prompt"] = initial_prompt

        # 執行轉錄 (取得 generator)
        print("DEBUG: calling self.model.transcribe...")
        try:
            segments, info = self.model.transcribe(file_path, **transcribe_options)
            print("DEBUG: self.model.transcribe returned generator.")
        except Exception as e:
            print(f"DEBUG: Error calling model.transcribe: {e}")
            raise e
        
        total_duration = info.duration
        print(f"DEBUG: Video info - Duration: {total_duration}, Language: {info.language}")

        if log_callback:
            log_callback(f"偵測來源語言: {info.language.upper()} (信心度: {info.language_probability:.2f})")
            log_callback(f"影片長度: {datetime.timedelta(seconds=int(total_duration))}")
        
        # 決定副檔名
        ext = f".{output_format.lower()}"
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
        
        print(f"DEBUG: Output path determined: {output_path}")

        # 用於收集 JSON 資料
        json_results = []
        file_handle = None
        
        try:
            # 如果不是 JSON，先開啟檔案準備寫入
            if output_format.lower() != "json":
                file_handle = open(output_path, "w", encoding="utf-8")
                
                # 寫入標頭
                if output_format.lower() == "vtt":
                    file_handle.write("WEBVTT\n\n")
                elif output_format.lower() == "tsv":
                    file_handle.write("start\tend\ttext\n")

            print("DEBUG: Starting segment loop...")
            for i, segment in enumerate(segments):
                # 檢查是否取消
                if cancel_check_callback and cancel_check_callback():
                    print("DEBUG: Task cancelled by user.")
                    if log_callback:
                        log_callback(">>> 使用者取消了作業 <<<")
                    if file_handle:
                        file_handle.write("\n[Interrupted by User]\n")
                    return None 
                
                text = segment.text.strip()
                start_sec = segment.start
                end_sec = segment.end
                
                # --- 強制簡轉繁 ---
                if force_zh_tw and task == "transcribe" and converter:
                    original_text = text
                    text = converter.convert(text)
                    if original_text != text:
                        print(f"DEBUG: Converted simplified to traditional: {original_text} -> {text}")

                print(f"DEBUG: Segment {i}: {start_sec}-{end_sec} {text[:20]}...")

                # 更新進度條
                if progress_callback and total_duration > 0:
                    progress = min(end_sec / total_duration, 1.0)
                    progress_callback(progress)

                # 在介面上顯示進度
                if log_callback:
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

            print("DEBUG: Segment loop finished.")
            # 迴圈結束後，如果是 JSON 則寫入檔案
            if output_format.lower() == "json":
                with open(output_path, "w", encoding="utf-8") as f:
                    json.dump(json_results, f, ensure_ascii=False, indent=2)
            
            # 確保進度條跑完
            if progress_callback:
                progress_callback(1.0)

        finally:
            if file_handle:
                file_handle.close()
        
        # --- 記錄結束時間與耗時 ---
        end_time = datetime.datetime.now()
        duration = end_time - start_time
        
        if log_callback:
            log_callback(f"--------------------------------------------------")
            log_callback(f"任務結束時間: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
            log_callback(f"總耗時: {duration}")
            log_callback(f"檔案已儲存於: {output_path}")
        
        return output_path
