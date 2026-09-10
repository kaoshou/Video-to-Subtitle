# -*- coding: utf-8 -*-
"""
EverCam 網頁課程字幕播放器整合模組
與開源專案 evercam-subtitle-player (https://github.com/kaoshou/evercam-subtitle-player) 深度整合，
提供 EverCam 課程專案自動辨識、字幕原生解析轉檔、subtitles-data.js 生成與播放器一鍵自動部署功能。
"""

import os
import sys
import re
import json
import html
import shutil
from datetime import datetime, timezone

SUPPORTED_VIDEO_EXTENSIONS = {".mp4", ".m4v", ".webm", ".mov", ".mkv", ".mp3", ".wav"}


def get_evercam_assets_dir():
    """取得內建 evercam_player 前端資產目錄路徑 (相容源碼模式與 PyInstaller 打包環境)"""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        base_dir = getattr(sys, "_MEIPASS")
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    
    asset_dir = os.path.join(base_dir, "assets", "evercam_player")
    return asset_dir


def is_evercam_folder(folder_path):
    """
    檢查指定目錄是否符合 EverCam 課程專案特徵
    條件：目錄存在、包含 config.js，且包含 media.mp4 或常見影音檔案
    """
    if not folder_path or not os.path.isdir(folder_path):
        return False
    
    config_file = os.path.join(folder_path, "config.js")
    if not os.path.isfile(config_file):
        return False
    
    # 檢查是否含有 media.mp4 或其他影音檔
    for item in os.listdir(folder_path):
        ext = os.path.splitext(item)[1].lower()
        if ext in SUPPORTED_VIDEO_EXTENSIONS:
            return True
            
    return False


def detect_evercam_project(path):
    """
    自給定檔案或目錄路徑，自動溯源檢測是否屬於 EverCam 專案
    回傳: (is_evercam: bool, course_folder: str or None)
    """
    if not path or not os.path.exists(path):
        return False, None
    
    if os.path.isdir(path):
        if is_evercam_folder(path):
            return True, os.path.abspath(path)
        return False, None
    
    # 若傳入的是檔案路徑，檢查其父目錄
    parent_dir = os.path.dirname(os.path.abspath(path))
    if is_evercam_folder(parent_dir):
        return True, parent_dir
        
    return False, None


def _canonical_language(lang_code):
    """將語言代碼標準化為 BCP 47 格式 (如 zh-tw -> zh-TW, en -> en)"""
    if not lang_code:
        return "zh-TW"
    parts = lang_code.split("-")
    if len(parts) == 1:
        return parts[0].lower()
    
    norm = [parts[0].lower()]
    for p in parts[1:]:
        if len(p) == 2:
            norm.append(p.upper())
        elif len(p) == 4:
            norm.append(p.capitalize())  # 如 Hant, Hans
        else:
            norm.append(p)
    return "-".join(norm)


def _convert_to_seconds(timecode_str):
    """將時間代碼字串 (00:01:23,456 或 01:23.456) 轉換為秒數 (float)"""
    s = timecode_str.strip()
    match = re.search(r"^(?:(\d+):)?(\d{2}):(\d{2})[,.](\d{1,3})", s)
    if not match:
        raise ValueError(f"無效的時間代碼: {timecode_str}")
    
    hours_str, minutes_str, seconds_str, fraction_str = match.groups()
    hours = int(hours_str) if hours_str else 0
    minutes = int(minutes_str)
    seconds = int(seconds_str)
    fraction_padded = fraction_str.ljust(3, "0")[:3]
    ms = int(fraction_padded)
    
    total_seconds = hours * 3600 + minutes * 60 + seconds + ms / 1000.0
    return round(total_seconds, 3)


def _clean_cue_text(text):
    """清理字幕內容：替換換行、去除 HTML 標籤與特殊標記"""
    if not text:
        return ""
    clean = re.sub(r"(?i)<br\s*/?>", "\n", text)
    clean = re.sub(r"\{[^\}]+\}", "", clean)  # 去除 ASS/SSA 標籤
    clean = re.sub(r"<[^>]+>", "", clean)     # 去除 HTML 標籤
    clean = html.unescape(clean)
    return clean.strip()


def parse_subtitles_to_cues(subtitle_path):
    """
    解析 SRT 或 WebVTT 字幕檔，提取時間軸與文字
    回傳: list[dict] [{'start': 1.23, 'end': 4.56, 'text': '...'}]
    """
    if not os.path.isfile(subtitle_path):
        return []
    
    # 支援 UTF-8 (含 UTF-8 BOM 自動消除)
    with open(subtitle_path, "r", encoding="utf-8-sig", errors="replace") as f:
        content = f.read()
        
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    lines = content.split("\n")
    cues = []
    line_index = 0
    total_lines = len(lines)
    
    while line_index < total_lines:
        line = lines[line_index].strip()
        if "-->" not in line:
            line_index += 1
            continue
            
        timing_parts = re.split(r"\s+-->\s+", line, maxsplit=1)
        if len(timing_parts) != 2:
            line_index += 1
            continue
            
        start_token = timing_parts[0].strip()
        end_token = timing_parts[1].strip().split()[0]  # 排除 VTT 可能帶有的樣式設定如 line:0%
        
        try:
            start_sec = _convert_to_seconds(start_token)
            end_sec = _convert_to_seconds(end_token)
        except Exception:
            line_index += 1
            continue
            
        line_index += 1
        text_lines = []
        while line_index < total_lines and lines[line_index].strip():
            text_lines.append(lines[line_index])
            line_index += 1
            
        clean_text = _clean_cue_text("\n".join(text_lines))
        if clean_text and end_sec > start_sec:
            cues.append({
                "start": start_sec,
                "end": end_sec,
                "text": clean_text
            })
            
        line_index += 1
        
    return cues


def generate_subtitles_data_js(course_folder):
    """
    掃描 EverCam 課程目錄中的所有字幕檔，編譯生成標準 subtitles-data.js
    支援 media.<lang>.srt, media.<lang>.vtt 以及通用 media.srt / media.vtt
    回傳: (success: bool, message: str, payload: dict)
    """
    if not is_evercam_folder(course_folder):
        return False, f"指定路徑非合法 EverCam 課程目錄: {course_folder}", {}
        
    subtitle_pattern = re.compile(r"^media\.([A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*)\.(srt|vtt)$", re.IGNORECASE)
    generic_pattern = re.compile(r"^media\.(srt|vtt)$", re.IGNORECASE)
    
    all_files = sorted(os.listdir(course_folder))
    named_subs = []
    generic_subs = []
    
    for fname in all_files:
        fpath = os.path.join(course_folder, fname)
        if not os.path.isfile(fpath):
            continue
            
        m = subtitle_pattern.match(fname)
        if m:
            named_subs.append((fname, _canonical_language(m.group(1))))
            continue
            
        m_gen = generic_pattern.match(fname)
        if m_gen:
            generic_subs.append(fname)
            
    # 若已有 zh-TW 具名檔案，generic 不覆蓋；若無則 generic 視為 zh-TW
    has_zh_tw = any(lang.lower() == "zh-tw" for _, lang in named_subs)
    final_sub_list = list(named_subs)
    
    if not has_zh_tw and generic_subs:
        # 取第一個 generic 檔案作為預設繁體中文
        final_sub_list.insert(0, (generic_subs[0], "zh-TW"))
        
    tracks = []
    used_languages = set()
    
    for fname, lang in final_sub_list:
        lang_key = lang.lower()
        if lang_key in used_languages:
            continue  # 同一語言只保留一個
            
        sub_path = os.path.join(course_folder, fname)
        cues = parse_subtitles_to_cues(sub_path)
        
        used_languages.add(lang_key)
        tracks.append({
            "language": lang,
            "source": fname,
            "cues": cues
        })
        
    default_lang = None
    if "zh-tw" in used_languages:
        default_lang = "zh-TW"
    elif tracks:
        default_lang = tracks[0]["language"]
        
    payload = {
        "version": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "defaultLanguage": default_lang,
        "tracks": tracks
    }
    
    js_content = (
        "/* Generated by Video to Subtitle. Do not edit by hand. */\n"
        f"window.EVERCAM_SUBTITLES = {json.dumps(payload, ensure_ascii=False, indent=2)};\n"
    )
    
    out_path = os.path.join(course_folder, "subtitles-data.js")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(js_content)
        
    track_summary = ", ".join([f"{t['language']}({len(t['cues'])}條)" for t in tracks]) if tracks else "無字幕軌"
    return True, f"成功編譯字幕資料 ({track_summary})", payload


def deploy_evercam_player(course_folder, source_srt=None, target_lang="zh-TW"):
    """
    一鍵部署 EverCam 現代化網頁播放器至指定課程目錄：
    1. 若有新轉錄的字幕檔，標準化放置至課程目錄 (如 media.zh-TW.srt)
    2. 自動備份原始 index.html 為 index.evercam-original.html (安全無損)
    3. 複製播放器靜態資源 (index.html, css/, js/, tools/, 更新字幕.cmd 等)
    4. 原生生成最新 subtitles-data.js
    回傳: (success: bool, message: str, index_html_path: str)
    """
    if not is_evercam_folder(course_folder):
        return False, "目標路徑不是合法的 EverCam 課程目錄 (未包含 config.js 或影片檔案)", ""
        
    assets_dir = get_evercam_assets_dir()
    if not os.path.isdir(assets_dir):
        return False, f"未找到播放器內建資產目錄: {assets_dir}", ""
        
    # 步驟 1: 處理傳入的新字幕
    if source_srt and os.path.isfile(source_srt):
        canon_lang = _canonical_language(target_lang)
        target_name = f"media.{canon_lang}.srt"
        dest_srt_path = os.path.join(course_folder, target_name)
        
        # 若來源檔案不在課程目錄下，或檔名非標準格式，複製並規範化
        if os.path.abspath(source_srt) != os.path.abspath(dest_srt_path):
            try:
                shutil.copy2(source_srt, dest_srt_path)
            except Exception as e:
                return False, f"複製字幕檔案失敗: {e}", ""
                
    # 步驟 2: 安全備份原始首頁
    original_index = os.path.join(course_folder, "index.html")
    backup_index = os.path.join(course_folder, "index.evercam-original.html")
    
    if os.path.isfile(original_index) and not os.path.isfile(backup_index):
        try:
            # 檢查原始首頁是否已經是新版播放器
            with open(original_index, "r", encoding="utf-8", errors="ignore") as f:
                content_sample = f.read(2048)
            if "evercam-subtitle-player" not in content_sample and "EVERCAM_SUBTITLES" not in content_sample:
                shutil.copy2(original_index, backup_index)
        except Exception as e:
            print(f"DEBUG: 備份原始首頁時發生非致命錯誤: {e}")
            
    # 步驟 3: 部署播放器靜態檔案
    try:
        for item in os.listdir(assets_dir):
            s_item = os.path.join(assets_dir, item)
            d_item = os.path.join(course_folder, item)
            
            # 若為 subtitles-data.js，由下一步驟動態生成，此處不覆蓋既有字幕
            if item == "subtitles-data.js":
                continue
                
            if os.path.isdir(s_item):
                if os.path.exists(d_item):
                    shutil.rmtree(d_item)
                shutil.copytree(s_item, d_item)
            else:
                shutil.copy2(s_item, d_item)
    except Exception as e:
        return False, f"部署播放器資源失敗: {e}", ""
        
    # 步驟 4: 原生生成 subtitles-data.js
    ok, msg, _ = generate_subtitles_data_js(course_folder)
    if not ok:
        return False, f"部署成功但產生字幕資料時發生錯誤: {msg}", original_index
        
    return True, "EverCam 字幕播放器部署成功！", original_index
