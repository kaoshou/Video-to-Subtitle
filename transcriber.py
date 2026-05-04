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
            if self.device in ["mps", "mlx"]:
                print("DEBUG: Initializing MLX Whisper for Apple Silicon...")
                try:
                    import mlx_whisper
                except ImportError:
                    msg = "要啟用 Apple MLX 框架加速 (Mac GPU)，請先安裝 mlx-whisper 套件：\n請執行 `pip install mlx-whisper`"
                    if log_callback:
                        log_callback("錯誤: " + msg)
                    raise RuntimeError(msg)
                
                self.model_type = "mlx-whisper"
                # MLX-Whisper 模型前綴，例如 mlx-community/whisper-small
                self.mlx_model_path = f"mlx-community/whisper-{self.model_size}"
                if log_callback:
                    log_callback(f"MLX 框架準備就緒，預計使用 HuggingFace 模型: {self.mlx_model_path}")
                print("DEBUG: MLX whisper config ready.")
            else:
                print("DEBUG: Initializing WhisperModel...")
                self.model = WhisperModel(
                    self.model_size, 
                    device=self.device, 
                    compute_type=self.compute_type,
                    download_root=self.download_root
                )
                self.model_type = "faster-whisper"
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

    def run(self, file_path, log_callback=None, progress_callback=None, cancel_check_callback=None, output_format="srt", initial_prompt=None, task="transcribe", force_zh_tw=False, max_chars=20, hotwords=None):
        """
        執行轉錄
        output_format: "srt", "vtt", "txt", "tsv", "json"
        initial_prompt: 用於引導模型輸出的提示詞 (例如強制繁體中文)
        task: "transcribe" (轉錄) 或 "translate" (翻譯成英文)
        force_zh_tw: (bool) 是否透過 opencc 將所有文字強制轉為台灣繁體中文
        max_chars: (int) 每行建議最大字數
        hotwords: (str) 專有名詞 / 熱詞補強關鍵字 (以逗號分隔)
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
            
            if hotwords:
                log_callback(f"啟用熱詞補強: {hotwords}")
        
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
        
        if hotwords:
            transcribe_options["hotwords"] = hotwords

        # 執行轉錄
        try:
            if getattr(self, "model_type", "faster-whisper") == "mlx-whisper":
                print("DEBUG: calling MLX whisper transcribe...")
                if log_callback:
                    log_callback("提示: 使用 Apple MLX 框架進行超高速轉錄...\n(註: 此套件轉換時將無法回報即時段落進度，請耐心等候)")
                
                native_options = {
                    "task": task,
                    "condition_on_previous_text": False
                }
                if initial_prompt:
                    native_options["initial_prompt"] = initial_prompt
                    
                import mlx_whisper
                result = mlx_whisper.transcribe(
                    file_path, 
                    path_or_hf_repo=self.mlx_model_path,
                    **native_options
                )
                
                class FakeInfo:
                    def __init__(self, lang, dur):
                        self.language = lang
                        self.duration = dur
                        self.language_probability = 1.0
                        
                class FakeSegment:
                    def __init__(self, s, e, t):
                        self.start = s
                        self.end = e
                        self.text = t
                        
                # 簡單抓取最後時間為總長度，因為 mlx-whisper 不提供整體 video info
                audio_duration = result["segments"][-1]["end"] if result["segments"] else 0.0
                    
                info = FakeInfo(result.get("language", "unknown"), audio_duration)
                segments = [FakeSegment(s["start"], s["end"], s["text"]) for s in result["segments"]]
                
                print("DEBUG: MLX whisper transcribe finished.")
                
            else:
                print("DEBUG: calling faster-whisper transcribe...")
                segments, info = self.model.transcribe(file_path, **transcribe_options)
                print("DEBUG: faster-whisper transcribe returned generator.")

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
            import re
            
            # --- 建立長度優化用的分段器 (Streaming Segmenter) ---
            class StreamingSegmenter:
                def __init__(self, max_chars=20, gap_threshold=0.8, hotwords_str=None):
                    # 如果使用者沒排定，則根據模式給予預設值
                    if max_chars is None or max_chars <= 0:
                        self.max_chars = 22 if task != "translate" else 80
                    else:
                        self.max_chars = max_chars
                    self.gap_threshold = gap_threshold
                    self.current_piece = None
                    self.strong_punctuations = ["。", "！", "？", ".", "?", "!", "\n"]
                    self.all_punctuations = ["，", "。", "！", "？", "；", "、", ",", ".", "?", ";", "!", "\n"]
                    
                    self.multi_word_hotwords = []
                    if hotwords_str:
                        hw_list = [h.strip() for h in hotwords_str.split(',') if h.strip()]
                        self.multi_word_hotwords = sorted([h for h in hw_list if " " in h], key=len, reverse=True)

                def process(self, raw_text, start, end):
                    results = []
                    pieces = []
                    
                    # 保護熱詞中的空白，暫時替換為 \uE000 (Private Use Area 字元)
                    protected_text = raw_text
                    if getattr(self, 'multi_word_hotwords', None):
                        for hw in self.multi_word_hotwords:
                            pattern = re.compile(re.escape(hw), re.IGNORECASE)
                            protected_text = pattern.sub(lambda m: m.group(0).replace(" ", "\uE000"), protected_text)
                    
                    # 保護一般英數字之間的空白，避免英文單字（如 Main Camera, Demo Project）被切斷
                    protected_text = re.sub(r'(?<=[a-zA-Z0-9#+\-.])\s+(?=[a-zA-Z0-9])', '\uE000', protected_text)
                    
                    # 保護英數字之間的標點 (如 config.txt, 1,000)，避免被 re.split 切斷
                    protected_text = re.sub(r'(?<=[a-zA-Z0-9])\.(?=[a-zA-Z0-9])', '\uE001', protected_text)
                    protected_text = re.sub(r'(?<=[0-9]),(?=[0-9])', '\uE002', protected_text)
                    
                    # 將空白也納入標點分割範圍 (為了讓中文字幕有空格可斷句)
                    chunks = re.split(r'([，。！？；、,.?;!\n\s])', protected_text)
                    merged_chunks = []
                    
                    for k in range(0, len(chunks) - 1, 2):
                        chunk_text = chunks[k].strip()
                        delimiter = chunks[k+1]
                        if chunk_text:
                            # 正常的文字 + 標點/空格
                            merged_chunks.append(chunk_text + delimiter)
                        elif merged_chunks:
                            # 處理連續標點或多格空白
                            merged_chunks[-1] += delimiter
                        elif delimiter.strip() or delimiter == " ":
                            merged_chunks.append(delimiter)
                    
                    if len(chunks) % 2 == 1 and chunks[-1].strip():
                        merged_chunks.append(chunks[-1].strip())
                    
                    total_chars = sum(len(c) for c in merged_chunks)
                    if total_chars == 0:
                        return []
                    
                    curr_start = start
                    seg_duration = end - start
                    for c in merged_chunks:
                        ratio = len(c) / total_chars
                        duration = seg_duration * ratio
                        # 還原熱詞與特殊標點中的字元
                        restored_text = c.replace("\uE000", " ").replace("\uE001", ".").replace("\uE002", ",")
                        
                        pieces.append({
                            'start': curr_start,
                            'end': curr_start + duration,
                            'text': restored_text
                        })
                        curr_start += duration
                            
                    for p in pieces:
                        p_text = p['text'].strip()
                        if not p_text:
                            continue
                            
                        if not self.current_piece:
                            self.current_piece = {'start': p['start'], 'end': p['end'], 'text': p['text']}
                            continue
                            
                        gap = p['start'] - self.current_piece['end']
                        
                        # 決定是否補空格：如果前一段結尾沒有標點且沒格空，且目前這段開頭也沒空，則補一個空格
                        needs_extra_space = False
                        if not any(self.current_piece['text'].endswith(punc) for punc in self.all_punctuations + [" "]):
                             if not p['text'].startswith(" "):
                                 needs_extra_space = True
                        
                        space = " " if needs_extra_space else ""
                        combined_text = self.current_piece['text'] + space + p['text']
                        
                        has_strong_punc = any(self.current_piece['text'].endswith(punc) for punc in self.strong_punctuations)
                        
                        # 檢查是否為英數字之間的空白 (不應視為斷句用的標點)
                        is_english_space = False
                        if self.current_piece['text'].endswith(" ") or space == " ":
                            prev_char = self.current_piece['text'].strip()[-1:] if self.current_piece['text'].strip() else ""
                            next_char = p['text'].strip()[0:1] if p['text'].strip() else ""
                            if prev_char and next_char:
                                if re.match(r'[a-zA-Z0-9#+\-.]', prev_char) and re.match(r'[a-zA-Z0-9]', next_char):
                                    is_english_space = True
                        
                        has_any_punc = False
                        for punc in self.all_punctuations + [" "]:
                            if self.current_piece['text'].endswith(punc):
                                if punc == " " and is_english_space:
                                    continue
                                has_any_punc = True
                                break
                        
                        should_break = False
                        
                        # 邏輯判斷是否該斷句
                        if len(combined_text) > self.max_chars and has_any_punc:
                            should_break = True
                        elif len(combined_text) > self.max_chars + 12: # 強制切斷點
                            should_break = True
                        elif gap > self.gap_threshold:
                            should_break = True
                        elif has_strong_punc and len(self.current_piece['text']) > 12:
                            should_break = True
                            
                        if should_break:
                            results.append(self.current_piece)
                            self.current_piece = {'start': p['start'], 'end': p['end'], 'text': p['text']}
                        else:
                            self.current_piece['end'] = p['end']
                            self.current_piece['text'] = combined_text
                            
                    return results

                def flush(self):
                    if self.current_piece:
                        res = [self.current_piece]
                        self.current_piece = None
                        return res
                    return []

            segmenter = StreamingSegmenter(max_chars=max_chars, hotwords_str=hotwords)
            output_i = 0
            
            def handle_segment_output(start_sec, end_sec, text, output_index):
                # --- 強制簡轉繁 ---
                if force_zh_tw and task == "transcribe" and converter:
                    original_text = text
                    text = converter.convert(text)
                    if original_text != text:
                        try:
                            pass # print(f"DEBUG: Converted simplified to traditional: {original_text} -> {text}")
                        except UnicodeEncodeError:
                            pass

                try:
                    print(f"DEBUG: Segment {output_index}: {start_sec:.2f}-{end_sec:.2f} {text[:20]}...")
                except UnicodeEncodeError:
                    print(f"DEBUG: Segment {output_index}: {start_sec:.2f}-{end_sec:.2f} (character print omitted due to encoding)")

                # 在介面上顯示進度
                if log_callback:
                    log_timestamp = self.format_timestamp(start_sec)
                    log_callback(f"[{log_timestamp}] {text}")

                # 處理各格式輸出
                if output_format.lower() == "json":
                    json_results.append({
                        "id": output_index,
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
                            file_handle.write(f"{output_index + 1}\n")
                            file_handle.write(f"{start_time_str} --> {end_time_str}\n")
                            file_handle.write(f"{text}\n\n")
                        elif output_format.lower() == "vtt":
                            file_handle.write(f"{start_time_str} --> {end_time_str}\n")
                            file_handle.write(f"{text}\n\n")

            for _, segment in enumerate(segments):
                # 檢查是否取消
                if cancel_check_callback and cancel_check_callback():
                    print("DEBUG: Task cancelled by user.")
                    if log_callback:
                        log_callback(">>> 使用者取消了作業 <<<")
                    if file_handle:
                        file_handle.write("\n[Interrupted by User]\n")
                    return None 
                
                try:
                    raw_text = segment.text.strip() if hasattr(segment, 'text') else segment['text'].strip()
                    seg_start = segment.start if hasattr(segment, 'start') else segment['start']
                    seg_end = segment.end if hasattr(segment, 'end') else segment['end']
                except Exception as e:
                    print(f"DEBUG: Error extracting segment properties: {e}")
                    continue
                
                # 取得重新切割後的小段落
                refined_segments = segmenter.process(raw_text, seg_start, seg_end)
                
                for r_seg in refined_segments:
                    handle_segment_output(r_seg['start'], r_seg['end'], r_seg['text'], output_i)
                    output_i += 1

                # 更新總體進度條 (因為進度條使用 end_sec，我們直接用原本 segment 的 end_sec 即可)
                if progress_callback and total_duration > 0:
                    progress = min(seg_end / total_duration, 1.0)
                    progress_callback(progress)

            # 處理最後殘留的段落
            leftovers = segmenter.flush()
            for r_seg in leftovers:
                handle_segment_output(r_seg['start'], r_seg['end'], r_seg['text'], output_i)
                output_i += 1
                
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
