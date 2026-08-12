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
    def __init__(self, model_size="small", device="cpu", compute_type="int8", download_root=None, cpu_threads=4):
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.download_root = download_root
        self.cpu_threads = cpu_threads
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
                    cpu_threads=self.cpu_threads,
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

    def run(self, file_path, log_callback=None, progress_callback=None, cancel_check_callback=None, output_format="srt", initial_prompt=None, task="transcribe", force_zh_tw=False, max_chars=35, hotwords=None, clean_punctuation="space", word_timestamps=True, spacing=True, case_correction=True, vad_filter=True):
        """
        執行轉錄
        output_format: "srt", "vtt", "txt", "tsv", "json"
        initial_prompt: 用於引導模型輸出的提示詞 (例如強制繁體中文)
        task: "transcribe" (轉錄) 或 "translate" (翻譯成英文)
        force_zh_tw: (bool) 是否透過 opencc 將所有文字強制轉為台灣繁體中文
        max_chars: (int) 單行防溢出最大字數上限 (預設 35 字，採用自然語意與停頓切分)
        hotwords: (str) 專有名詞 / 熱詞補強關鍵字 (以逗號分隔)
        clean_punctuation: (str) "none", "remove", "space"
        word_timestamps: (bool) 是否啟用單字級時間戳
        """
        print(f"DEBUG: run() called for file: {file_path}")
        if max_chars is None or max_chars < 25:
            max_chars = 35 if task != "translate" else 80
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
                
            log_callback(f"精準時間軸: {'開啟' if word_timestamps else '關閉'}")
            log_callback(f"VAD 靜音過濾: {'開啟' if vad_filter else '關閉'}")
            log_callback(f"標點符號處理: {clean_punctuation}")
        
        # 準備參數
        transcribe_options = {
            "beam_size": 5,
            "task": task,
            "vad_filter": vad_filter, # 啟用 Voice Activity Detection
            "vad_parameters": dict(min_silence_duration_ms=500) if vad_filter else None, 
            "word_timestamps": word_timestamps,
            "condition_on_previous_text": False # 關閉上下文關聯，避免模型陷入長句幻覺的無限迴圈
        }
        if initial_prompt:
            transcribe_options["initial_prompt"] = initial_prompt
        
        if hotwords:
            transcribe_options["hotwords"] = hotwords

        if log_callback:
            log_callback(">> 🚀 正在進行語音辨識與轉錄中，請耐心等候... (依硬體效能可能需要數十秒至數分鐘)")

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
            log_lang = info.language.upper() if hasattr(info, 'language') and info.language else "UNKNOWN"
            log_prob = getattr(info, 'language_probability', 1.0)
            log_callback(f"偵測來源語言: {log_lang} (信心度: {log_prob:.2f})")
            log_callback(f"影片長度: {datetime.timedelta(seconds=int(total_duration))}")
        
        ext = f".{output_format.lower()}"
        suffix = ".en" if task == "translate" else ""
        
        base_output_path = os.path.splitext(file_path)[0] + suffix + ext
        output_path = base_output_path
        
        counter = 1
        while os.path.exists(output_path):
            path_no_ext = os.path.splitext(base_output_path)[0]
            output_path = f"{path_no_ext}_{counter}{ext}"
            counter += 1
        
        print(f"DEBUG: Output path determined: {output_path}")

        json_results = []
        txt_results = []
        file_handle = None
        
        try:
            if output_format.lower() not in ["json", "txt"]:
                file_handle = open(output_path, "w", encoding="utf-8")
                if output_format.lower() == "vtt":
                    file_handle.write("WEBVTT\n\n")
                elif output_format.lower() == "tsv":
                    file_handle.write("start\tend\ttext\n")

            print("DEBUG: Starting segment loop...")
            import re
            
            # --- 建立長度優化用的分段器 (Streaming Segmenter) ---
            class StreamingSegmenter:
                def __init__(self, max_chars=35, gap_threshold=0.45, hotwords_str=None):
                    if max_chars is None or max_chars < 25:
                        self.max_chars = 35 if task != "translate" else 80
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
                    
                    protected_text = raw_text
                    if getattr(self, 'multi_word_hotwords', None):
                        for hw in self.multi_word_hotwords:
                            pattern = re.compile(re.escape(hw), re.IGNORECASE)
                            protected_text = pattern.sub(lambda m: m.group(0).replace(" ", "\uE000"), protected_text)
                    
                    protected_text = re.sub(r'(?<=[a-zA-Z0-9#+\-.])\s+(?=[a-zA-Z0-9])', '\uE000', protected_text)
                    protected_text = re.sub(r'(?<=[a-zA-Z0-9])\.(?=[a-zA-Z0-9])', '\uE001', protected_text)
                    protected_text = re.sub(r'(?<=[0-9]),(?=[0-9])', '\uE002', protected_text)
                    
                    chunks = re.split(r'([，。！？；、,.?;!\n\s])', protected_text)
                    merged_chunks = []
                    
                    for k in range(0, len(chunks) - 1, 2):
                        chunk_text = chunks[k].strip()
                        delimiter = chunks[k+1]
                        if chunk_text:
                            merged_chunks.append(chunk_text + delimiter)
                        elif merged_chunks:
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
                        needs_extra_space = False
                        if not any(self.current_piece['text'].endswith(punc) for punc in self.all_punctuations + [" "]):
                             if not p['text'].startswith(" "):
                                 needs_extra_space = True
                        
                        space = " " if needs_extra_space else ""
                        combined_text = self.current_piece['text'] + space + p['text']
                        has_strong_punc = any(self.current_piece['text'].endswith(punc) for punc in self.strong_punctuations)
                        has_weak_punc = any(self.current_piece['text'].endswith(punc) for punc in ["，", "；", "、", ",", ";"])
                        
                        should_break = False
                        if has_strong_punc:
                            should_break = True
                        elif gap >= self.gap_threshold: # 自然停頓超過 0.45s
                            should_break = True
                        elif has_weak_punc and gap > 0.18: # 逗號+停頓
                            should_break = True
                        elif len(combined_text) >= self.max_chars: # 達到單行防溢出安全上限 (預設 35 字)
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

            # --- 建立基於單字級時間戳的精準自然分段器 (WordBasedSegmenter) ---
            class WordBasedSegmenter:
                def __init__(self, max_chars=35, gap_threshold=0.45):
                    if max_chars is None or max_chars < 25:
                        self.max_chars = 35 if task != "translate" else 80
                    else:
                        self.max_chars = max_chars
                    self.gap_threshold = gap_threshold
                    self.current_words = []
                    self.strong_punctuations = ["。", "！", "？", ".", "?", "!", "\n"]
                    self.all_punctuations = ["，", "。", "！", "？", "；", "、", ",", ".", "?", ";", "!", "\n"]
                    
                def get_clean_len(self, words_list):
                    text = "".join((w.word if hasattr(w, 'word') else w.get('word', '')) for w in words_list)
                    return len(re.sub(r'[，。！？；、,.?;!\s]', '', text))

                def find_best_split_index(self):
                    n = len(self.current_words)
                    if n <= 1:
                        return n

                    total_clean_len = self.get_clean_len(self.current_words)
                    # 長度未達到防溢出上限，不強行切分
                    if total_clean_len < self.max_chars:
                        return n

                    best_idx = n
                    min_penalty = 999999.0

                    # 尋找最適防溢出切分點
                    for i in range(1, n):
                        words_before = self.current_words[:i]
                        words_after = self.current_words[i:]
                        
                        len_before = self.get_clean_len(words_before)
                        len_after = self.get_clean_len(words_after)
                        
                        # 偏向在中央區域防溢出切分
                        penalty = abs(len_before - (total_clean_len / 2)) * 0.8
                        
                        # 極短行保護
                        if len_before < 4:
                            penalty += 40.0
                        if len_after < 4:
                            penalty += 40.0
                        
                        w_prev = self.current_words[i-1]
                        w_next = self.current_words[i]
                        
                        w_prev_text = w_prev.word if hasattr(w_prev, 'word') else w_prev.get('word', '')
                        w_next_text = w_next.word if hasattr(w_next, 'word') else w_next.get('word', '')
                        
                        w_prev_clean = w_prev_text.strip()
                        w_next_clean = w_next_text.strip()
                        
                        w_prev_end = w_prev.end if hasattr(w_prev, 'end') else w_prev.get('end', 0.0)
                        w_next_start = w_next.start if hasattr(w_next, 'start') else w_next.get('start', 0.0)
                        
                        gap = w_next_start - w_prev_end
                        
                        # 下一行開頭保護 (黏性字防拆)
                        if w_next_clean in ["的", "了", "得", "著", "地", "之"]:
                            penalty += 45.0
                        if w_next_clean in ["與", "或", "和", "於", "在", "以", "對", "為", "跟", "同"]:
                            penalty += 25.0
                        if w_next_clean in ["%", "個", "張", "本", "秒", "分", "元", "次", "度", "台", "輛", "間", "名", "位", "件"]:
                            penalty += 40.0
                        if w_next_clean in ["嗎", "呢", "吧", "啊", "呀", "喔", "哈"]:
                            penalty += 50.0

                        # 上一行結尾保護 (前綴/介詞防拆)
                        if w_prev_clean in ["第"]:
                            penalty += 45.0
                        if w_prev_clean in ["小", "大", "老", "副", "總", "超", "單", "雙", "多", "少", "無", "有"]:
                            penalty += 35.0
                        if w_prev_clean in ["被", "把", "讓", "令", "使", "代"]:
                            penalty += 40.0
                        if w_prev_clean in ["最", "太", "很", "更", "極", "越"]:
                            penalty += 35.0

                        # 英數與符號邊界防拆
                        if re.match(r'[a-zA-Z0-9]', w_prev_clean[-1:]) and re.match(r'[a-zA-Z0-9]', w_next_clean[0:1]):
                            penalty += 60.0
                        if re.match(r'[0-9]', w_prev_clean[-1:]) and w_next_clean == "%":
                            penalty += 60.0
                        
                        # 標點優選獎勵
                        if any(w_prev_text.endswith(punc) for punc in self.all_punctuations):
                            if any(w_prev_text.endswith(punc) for punc in self.strong_punctuations):
                                penalty -= 50.0
                            else:
                                penalty -= 35.0
                                
                        # 聲音發音連貫保護 (同單詞/語音流動)
                        if gap <= 0.03:
                            penalty += 30.0
                        elif gap > 0.15:
                            penalty -= min(gap, 0.8) * 35.0
                            
                        if penalty < min_penalty:
                            min_penalty = penalty
                            best_idx = i
                            
                    return best_idx

                def process_words(self, words_list):
                    results = []
                    
                    for w_item in words_list:
                        w_text = w_item.word if hasattr(w_item, 'word') else w_item.get('word', '')
                        w_start = w_item.start if hasattr(w_item, 'start') else w_item.get('start', 0.0)
                        
                        if not w_text.strip():
                            continue
                            
                        should_split = False
                        
                        if self.current_words:
                            prev_word = self.current_words[-1]
                            prev_end = prev_word.end if hasattr(prev_word, 'end') else prev_word.get('end', 0.0)
                            prev_text = prev_word.word if hasattr(prev_word, 'word') else prev_word.get('word', '')
                            gap = w_start - prev_end
                            
                            # 1. 停頓超過閾值 (0.45s) -> 自然語意停頓切分
                            if gap >= self.gap_threshold:
                                should_split = True
                            # 2. 強標點 (句號/問號/驚嘆號) 結束 -> 必定切分
                            elif any(prev_text.endswith(punc) for punc in self.strong_punctuations):
                                should_split = True
                            # 3. 弱標點 (逗號/分號) + 自然停頓 (0.18s) -> 子句切分
                            elif any(prev_text.endswith(punc) for punc in ["，", "；", "、", ",", ";"]) and gap >= 0.18:
                                should_split = True
                            # 4. 單行防溢出保護：只有在字數達標 (>= max_chars, 預設 35 字) 時才考慮切分
                            else:
                                clean_len = self.get_clean_len(self.current_words)
                                if clean_len >= self.max_chars:
                                    should_split = True
                                        
                        if should_split and self.current_words:
                            split_idx = self.find_best_split_index()
                            words_to_output = self.current_words[:split_idx]
                            self.current_words = self.current_words[split_idx:]
                            
                            if words_to_output:
                                seg_start = words_to_output[0].start if hasattr(words_to_output[0], 'start') else words_to_output[0].get('start', 0.0)
                                seg_end = words_to_output[-1].end if hasattr(words_to_output[-1], 'end') else words_to_output[-1].get('end', 0.0)
                                seg_text = "".join((w.word if hasattr(w, 'word') else w.get('word', '')) for w in words_to_output)
                                results.append({
                                    'start': seg_start,
                                    'end': seg_end,
                                    'text': seg_text
                                })
                                
                        self.current_words.append(w_item)
                        
                    return results

                def flush(self):
                    results = []
                    while self.current_words:
                        clean_len = self.get_clean_len(self.current_words)
                        if clean_len >= self.max_chars:
                            split_idx = self.find_best_split_index()
                            words_to_output = self.current_words[:split_idx]
                            self.current_words = self.current_words[split_idx:]
                        else:
                            words_to_output = self.current_words
                            self.current_words = []
                            
                        if words_to_output:
                            seg_start = words_to_output[0].start if hasattr(words_to_output[0], 'start') else words_to_output[0].get('start', 0.0)
                            seg_end = words_to_output[-1].end if hasattr(words_to_output[-1], 'end') else words_to_output[-1].get('end', 0.0)
                            seg_text = "".join((w.word if hasattr(w, 'word') else w.get('word', '')) for w in words_to_output)
                            results.append({
                                'start': seg_start,
                                'end': seg_end,
                                'text': seg_text
                            })
                    return results

            segmenter = StreamingSegmenter(max_chars=max_chars, hotwords_str=hotwords)
            word_segmenter = WordBasedSegmenter(max_chars=max_chars)
            use_word_segmenter = False
            output_i = 0
            
            # --- 字幕後處理美化與清理 ---
            def post_process_text(text):
                if not text:
                    return ""
                
                # 1. 強制簡轉繁
                if force_zh_tw and task == "transcribe" and converter:
                    text = converter.convert(text)
                    
                # 2. 熱詞大小寫校正
                if hotwords and task == "transcribe" and case_correction:
                    hw_list = [w.strip() for w in re.split(r'[,\n，]', hotwords) if w.strip()]
                    for hw in hw_list:
                        pattern = re.compile(r'(?<![a-zA-Z0-9])' + re.escape(hw) + r'(?![a-zA-Z0-9])', re.IGNORECASE)
                        text = pattern.sub(hw, text)

                # 3. 中英文混排自動空格 (CJK 漢字與英數字邊界)
                if spacing:
                    text = re.sub(r'([\u4e00-\u9fa5])([a-zA-Z0-9])', r'\1 \2', text)
                    text = re.sub(r'([a-zA-Z0-9])([\u4e00-\u9fa5])', r'\1 \2', text)

                # 4. 標點符號處理
                chinese_punc = r"[，。！？；、：（）「」『』——……“”]"
                if clean_punctuation == "remove":
                    text = re.sub(chinese_punc, "", text)
                    text = re.sub(r'(?<![a-zA-Z0-9])[.,?!;:"\'(){}\[\]\-+](?![a-zA-Z0-9])', '', text)
                    text = re.sub(r'[.,?!;:\s]+$', '', text)
                elif clean_punctuation == "space":
                    text = re.sub(chinese_punc, " ", text)
                    text = re.sub(r'(?<![a-zA-Z0-9])[.,?!;:"\'(){}\[\]\-+](?![a-zA-Z0-9])', ' ', text)
                    text = re.sub(r'\s+', ' ', text)

                return text.strip()
            
            def handle_segment_output(start_sec, end_sec, text, output_index):
                text = post_process_text(text)
                if not text:
                    return

                try:
                    print(f"DEBUG: Segment {output_index}: {start_sec:.2f}-{end_sec:.2f} {text[:20]}...")
                except UnicodeEncodeError:
                    print(f"DEBUG: Segment {output_index}: {start_sec:.2f}-{end_sec:.2f} (character print omitted due to encoding)")

                if log_callback:
                    log_timestamp = self.format_timestamp(start_sec)
                    log_callback(f"[{log_timestamp}] {text}")

                if output_format.lower() == "json":
                    json_results.append({
                        "id": output_index,
                        "start": start_sec,
                        "end": end_sec,
                        "text": text
                    })
                elif output_format.lower() == "txt":
                    txt_results.append(text)
                elif file_handle:
                    if output_format.lower() == "tsv":
                        file_handle.write(f"{int(start_sec * 1000)}\t{int(end_sec * 1000)}\t{text}\n")
                    else:
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
                    
                    if not raw_text:
                        continue

                    words = None
                    if hasattr(segment, 'words') and segment.words is not None:
                        words = segment.words
                    elif isinstance(segment, dict) and 'words' in segment:
                        words = segment['words']
                except Exception as e:
                    print(f"DEBUG: Error extracting segment properties: {e}")
                    continue
                
                clean_text = re.sub(r'[，。！？；、,.?;!\s]', '', raw_text)
                clean_len = len(clean_text)

                # 若啟用的 word_timestamps 且有單字列表
                if word_timestamps and words and len(words) > 0:
                    w_start = words[0].start if hasattr(words[0], 'start') else words[0].get('start', seg_start)
                    w_end = words[-1].end if hasattr(words[-1], 'end') else words[-1].get('end', seg_end)
                    
                    # 1. 常規自然段落 (<= max_chars)：直接保留 Whisper 原生自然 Segment，精準毫秒對齊
                    if clean_len <= max_chars:
                        handle_segment_output(w_start, w_end, raw_text, output_i)
                        output_i += 1
                    else:
                        # 2. 超長 Segment：僅在該 Segment 內部依據標點/空格或停頓安全拆分
                        sub_segs = word_segmenter.process_words(words)
                        sub_segs.extend(word_segmenter.flush())
                        for r_seg in sub_segs:
                            handle_segment_output(r_seg['start'], r_seg['end'], r_seg['text'], output_i)
                            output_i += 1
                else:
                    # 無單字級時間戳
                    if clean_len <= max_chars:
                        handle_segment_output(seg_start, seg_end, raw_text, output_i)
                        output_i += 1
                    else:
                        sub_segs = segmenter.process(raw_text, seg_start, seg_end)
                        sub_segs.extend(segmenter.flush())
                        for r_seg in sub_segs:
                            handle_segment_output(r_seg['start'], r_seg['end'], r_seg['text'], output_i)
                            output_i += 1

                if progress_callback and total_duration > 0:
                    progress = min(seg_end / total_duration, 1.0)
                    progress_callback(progress)
                
            print("DEBUG: Segment loop finished.")
            if output_format.lower() == "json":
                with open(output_path, "w", encoding="utf-8") as f:
                    json.dump(json_results, f, ensure_ascii=False, indent=2)
            elif output_format.lower() == "txt":
                with open(output_path, "w", encoding="utf-8") as f:
                    current_para = "　　"
                    for idx, seg_text in enumerate(txt_results):
                        if current_para.strip() and not current_para.endswith(" ") and not seg_text.startswith(" "):
                            last_char = current_para[-1:]
                            first_char = seg_text[0:1]
                            if re.match(r'[a-zA-Z0-9]', last_char) and re.match(r'[a-zA-Z0-9]', first_char):
                                current_para += " "
                        
                        current_para += seg_text
                        
                        has_strong_punc = any(seg_text.endswith(p) for p in ["。", "！", "？", ".", "!", "?", "\n"])
                        if (len(current_para) > 140 and has_strong_punc) or idx == len(txt_results) - 1:
                            f.write(f"{current_para.strip()}\n\n")
                            current_para = "　　"
            
            if progress_callback:
                progress_callback(1.0)

        finally:
            if file_handle:
                file_handle.close()
        
        end_time = datetime.datetime.now()
        duration = end_time - start_time
        
        if log_callback:
            log_callback(f"--------------------------------------------------")
            log_callback(f"任務結束時間: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
            log_callback(f"總耗時: {duration}")
            log_callback(f"檔案已儲存於: {output_path}")
        
        return output_path
