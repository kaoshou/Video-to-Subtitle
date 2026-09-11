import os
import sys
import platform
import datetime
import shutil
import time
from tqdm.auto import tqdm
import json
import logging

def ensure_ffmpeg_path():
    """
    確保系統環境變數 PATH 包含常見的 FFmpeg 安裝路徑。
    特別是針對 macOS GUI 應用程式（Finder / .app 啟動時不會繼承 shell 的 PATH），
    自動補充 Homebrew (/opt/homebrew/bin, /usr/local/bin) 等常用二進位路徑。
    返回目前找到的 ffmpeg 絕對路徑，若找不到則返回 None。
    """
    system_paths = os.environ.get("PATH", "").split(os.pathsep)
    extra_paths = []
    
    if platform.system() == "Darwin":
        # macOS 常見 Homebrew、MacPorts 與使用者 local bin 路徑
        extra_paths = [
            "/opt/homebrew/bin",
            "/opt/homebrew/sbin",
            "/usr/local/bin",
            "/usr/local/sbin",
            "/opt/local/bin",
            os.path.expanduser("~/.local/bin"),
            os.path.expanduser("~/bin"),
        ]
    elif platform.system() == "Windows":
        # Windows 常見 WinGet 與預設安裝路徑
        extra_paths = [
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Links"),
            os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"), "ffmpeg", "bin"),
        ]
    else:
        # Linux
        extra_paths = [
            "/usr/local/bin",
            "/usr/bin",
            "/bin",
            os.path.expanduser("~/.local/bin"),
        ]
        
    # 加入當前 Python 直譯器所在目錄與 Scripts/bin 目錄 (適用於虛擬環境)
    if sys.executable:
        py_dir = os.path.dirname(os.path.abspath(sys.executable))
        extra_paths.append(py_dir)
        extra_paths.append(os.path.join(py_dir, "bin"))
        extra_paths.append(os.path.join(py_dir, "Scripts"))
        
    # 若存在 PyInstaller 打包暫存目錄 (_MEIPASS)
    if hasattr(sys, "_MEIPASS"):
        extra_paths.append(sys._MEIPASS)
        
    # 加入專案目錄與內建 bin 目錄
    script_dir = os.path.dirname(os.path.abspath(__file__))
    extra_paths.append(script_dir)
    extra_paths.append(os.path.join(script_dir, "ffmpeg"))
    extra_paths.append(os.path.join(script_dir, "bin"))

    # 依序檢查並加入尚未存在於 PATH 的目錄 (macOS 下優先全面注入 Homebrew 與 Local 路徑)
    for p in extra_paths:
        if p and (platform.system() == "Darwin" or os.path.isdir(p)) and p not in system_paths:
            system_paths.insert(0, p)
            
    os.environ["PATH"] = os.pathsep.join(system_paths)
    return shutil.which("ffmpeg")

# 模組載入時立即執行一次 PATH 補齊
ensure_ffmpeg_path()

def setup_ssl_certificates():
    """全域配置 SSL 根憑證路徑，特別解決 macOS 官方 Python 未執行憑證安裝導致的 SSL 失敗"""
    try:
        import certifi
        ca_path = certifi.where()
        if ca_path and os.path.exists(ca_path):
            os.environ.setdefault("SSL_CERT_FILE", ca_path)
            os.environ.setdefault("REQUESTS_CA_BUNDLE", ca_path)
    except Exception:
        pass
        
    if platform.system() == "Darwin":
        for cand in ["/etc/ssl/cert.pem", "/opt/homebrew/etc/ca-certificates/cert.pem", "/usr/local/etc/openssl/cert.pem"]:
            if os.path.exists(cand):
                os.environ.setdefault("SSL_CERT_FILE", cand)
                break

setup_ssl_certificates()

def check_ffmpeg_available():
    """
    檢查系統中是否可用 ffmpeg，並返回 (is_available: bool, ffmpeg_path: str, friendly_error_message: str)
    """
    ffmpeg_path = ensure_ffmpeg_path()
    if ffmpeg_path:
        return True, ffmpeg_path, ""
        
    sys_name = platform.system()
    if sys_name == "Darwin":
        msg = (
            "【系統未偵測到 FFmpeg 影音轉碼工具】\n\n"
            "在 macOS (特別是 Apple Silicon MLX 模式) 下進行語音轉錄，需要使用 FFmpeg 進行音訊解碼。\n\n"
            "【解決方式】\n"
            "1. 請開啟 macOS 的「終端機」(Terminal)\n"
            "2. 執行以下指令安裝：\n"
            "   brew install ffmpeg\n\n"
            "（若您尚未安裝 Homebrew，請先前往 https://brew.sh 依說明安裝）"
        )
    elif sys_name == "Windows":
        msg = (
            "【系統未偵測到 FFmpeg 影音轉碼工具】\n\n"
            "進行音訊解碼需要 FFmpeg 工具。\n\n"
            "【解決方式】\n"
            "1. 開啟 PowerShell 並執行：winget install Gyan.FFmpeg\n"
            "2. 或從官方網站下載 ffmpeg.exe 並放置於系統 PATH 或本程式目錄中。"
        )
    else:
        msg = (
            "【系統未偵測到 FFmpeg 影音轉碼工具】\n\n"
            "請使用 Linux 套件管理員安裝，例如：sudo apt install ffmpeg 或 sudo dnf install ffmpeg"
        )
    return False, None, msg

try:
    import opencc
    converter = opencc.OpenCC('s2twp.json') # 簡體到繁體 (台灣慣用語)
except ImportError:
    converter = None
    logging.warning("尚未安裝 opencc，將無法支援強制轉換繁體功能，請執行 pip install opencc")


# 模型資訊對照表 (用於顯示預估大小、說明與磁碟空間檢查)
MODEL_INFO = {
    "tiny": {"repo_id": "Systran/faster-whisper-tiny", "mlx_repo": "mlx-community/whisper-tiny", "approx_size_mb": 75, "desc": "極速模型 (約 75 MB)"},
    "base": {"repo_id": "Systran/faster-whisper-base", "mlx_repo": "mlx-community/whisper-base", "approx_size_mb": 145, "desc": "基礎模型 (約 145 MB)"},
    "small": {"repo_id": "Systran/faster-whisper-small", "mlx_repo": "mlx-community/whisper-small", "approx_size_mb": 480, "desc": "標準模型 (約 480 MB)"},
    "medium": {"repo_id": "Systran/faster-whisper-medium", "mlx_repo": "mlx-community/whisper-medium", "approx_size_mb": 1500, "desc": "中型模型 (約 1.5 GB)"},
    "large-v3": {"repo_id": "Systran/faster-whisper-large-v3", "mlx_repo": "mlx-community/whisper-large-v3", "approx_size_mb": 3100, "desc": "高精準大型模型 (約 3.1 GB)"},
    "large-v3-turbo": {"repo_id": "mobiuslabsgmbh/faster-whisper-large-v3-turbo", "mlx_repo": "mlx-community/whisper-large-v3-turbo", "approx_size_mb": 1600, "desc": "極速大模型 (約 1.6 GB)"},
}


def check_disk_space(target_dir, required_mb):
    """
    檢查指定路徑所在磁碟的可用空間是否足夠
    返回 (free_mb, is_enough)
    """
    try:
        p = os.path.abspath(target_dir)
        while not os.path.exists(p):
            parent = os.path.dirname(p)
            if parent == p:
                break
            p = parent
        usage = shutil.disk_usage(p)
        free_mb = usage.free / (1024 * 1024)
        return free_mb, free_mb >= required_mb
    except Exception:
        # 若系統不支援或檢測失敗，放行不阻擋
        return 999999, True


class CorruptedModelError(RuntimeError):
    """本地模型快取檔案損毀或不完整例外"""
    def __init__(self, message, model_size, cache_dir=None):
        super().__init__(message)
        self.model_size = model_size
        self.cache_dir = cache_dir


def clear_model_cache(model_size, download_root=None, device="cpu"):
    """
    清除指定模型的本地快取資料夾，以便重新乾淨下載
    返回 (bool, str) 代表是否成功及說明訊息
    """
    clean_size = model_size.split()[0].strip()
    is_mlx = device in ["mps", "mlx"]
    if is_mlx:
        repo_id = MODEL_INFO.get(clean_size, {}).get("mlx_repo", f"mlx-community/whisper-{clean_size}")
    else:
        import faster_whisper
        repo_id = faster_whisper.utils._MODELS.get(clean_size) or MODEL_INFO.get(clean_size, {}).get("repo_id", f"Systran/faster-whisper-{clean_size}")
        
    cache_dir = download_root if download_root else os.path.expanduser("~/.cache/huggingface/hub")
    repo_folder = os.path.join(cache_dir, "models--" + repo_id.replace("/", "--"))
    
    deleted = False
    if os.path.exists(repo_folder):
        try:
            shutil.rmtree(repo_folder)
            deleted = True
        except Exception as e:
            return False, f"無法刪除快取資料夾 {repo_folder}: {e}"
            
    # 如果 download_root 直接存放 model.bin 與 config.json (獨立目錄模式)
    if download_root and os.path.isdir(download_root):
        for f in ["model.bin", "config.json", "tokenizer.json", "vocabulary.txt"]:
            fp = os.path.join(download_root, f)
            if os.path.isfile(fp):
                try:
                    os.remove(fp)
                    deleted = True
                except Exception:
                    pass
                    
    return True, f"已成功清除模型 [{clean_size}] 的快取檔案。"


def check_model_downloaded(model_size, download_root=None, device="cpu"):
    """
    快速檢測指定模型是否已下載至本地（含基礎大小完整性檢查，不發送網路請求）
    返回 True 表示已下載/離線可用，False 表示未下載或檔案損毀
    """
    clean_size = model_size.split()[0].strip()
    if device in ["mps", "mlx"]:
        try:
            import huggingface_hub
            repo_id = f"mlx-community/whisper-{clean_size}"
            huggingface_hub.snapshot_download(repo_id, local_files_only=True, cache_dir=download_root)
            return True
        except Exception:
            return False
    else:
        try:
            import faster_whisper
            # 若為自訂目錄直接存放檔案
            if download_root and os.path.isdir(download_root):
                direct_files = ["model.bin", "config.json"]
                if all(os.path.exists(os.path.join(download_root, f)) for f in direct_files):
                    # 檔案完整性檢查：model.bin 至少需大於 5MB (最小的 tiny 模型也有 75MB)
                    m_bin = os.path.join(download_root, "model.bin")
                    if os.path.getsize(m_bin) > 5 * 1024 * 1024:
                        return True
                    else:
                        return False
            
            # 使用 faster_whisper 快取檢查
            snapshot_dir = faster_whisper.download_model(clean_size, cache_dir=download_root, local_files_only=True)
            if snapshot_dir and os.path.isdir(snapshot_dir):
                m_bin = os.path.join(snapshot_dir, "model.bin")
                # 核心權重檔案必須確實存在，且大小必須大於 5MB (避免 incomplete 或剛建立目錄之元數據)
                if not os.path.exists(m_bin):
                    return False
                if os.path.getsize(m_bin) < 5 * 1024 * 1024:
                    return False
                return True
            return False
        except Exception:
            return False



try:
    from huggingface_hub.utils import tqdm as hf_tqdm
    BaseTqdm = hf_tqdm
except Exception:
    BaseTqdm = tqdm


class _DownloadProgressTqdm(BaseTqdm):
    """
    自訂 Tqdm 類別，攔截 Hugging Face 下載字節流並即時計算進度百分比、速度與 ETA
    """
    _log_callback = None
    _progress_callback = None
    _cancel_check_callback = None
    _last_update_time = 0.0
    _last_log_time = 0.0
    _last_log_pct = -10.0
    _start_time = 0.0

    @classmethod
    def reset(cls, log_cb=None, prog_cb=None, cancel_cb=None):
        cls._log_callback = log_cb
        cls._progress_callback = prog_cb
        cls._cancel_check_callback = cancel_cb
        cls._last_update_time = 0.0
        cls._last_log_time = 0.0
        cls._last_log_pct = -10.0
        cls._start_time = 0.0

    def __init__(self, *args, **kwargs):
        # 移除 huggingface_hub 內部傳入但原生 tqdm 不支援的額外參數 (如 'name')
        kwargs.pop("name", None)
        self.is_bytes_bar = (kwargs.get("unit") == "B")
        super().__init__(*args, **kwargs)
        if self.is_bytes_bar and _DownloadProgressTqdm._start_time == 0.0:
            _DownloadProgressTqdm._start_time = time.time()
            _DownloadProgressTqdm._last_update_time = 0.0 # 初次保持 0.0，確保首次 update 立即觸發 UI 回呼

    def update(self, n=1):
        super().update(n)
        if _DownloadProgressTqdm._cancel_check_callback and _DownloadProgressTqdm._cancel_check_callback():
            raise InterruptedError("使用者已手動取消模型下載。")

        if not self.is_bytes_bar:
            return

        now = time.time()
        # 限制更新頻率在約 80ms，避免過度刷新影響 UI
        if now - _DownloadProgressTqdm._last_update_time >= 0.08 or (self.total and self.n >= self.total):
            _DownloadProgressTqdm._last_update_time = now
            total = self.total if self.total and self.total > 0 else 0
            current = self.n
            fraction = (current / total) if total > 0 else 0.0
            percent = fraction * 100.0

            elapsed = now - _DownloadProgressTqdm._start_time
            speed_bps = (current / elapsed) if elapsed > 0.1 else 0.0
            if speed_bps >= 1024 * 1024:
                speed_str = f"{speed_bps / (1024 * 1024):.1f} MB/s"
            elif speed_bps >= 1024:
                speed_str = f"{speed_bps / 1024:.1f} KB/s"
            else:
                speed_str = f"{speed_bps:.0f} B/s"

            if total > current and speed_bps > 1024:
                remaining_secs = int((total - current) / speed_bps)
                mins = remaining_secs // 60
                secs = remaining_secs % 60
                eta_str = f"{mins:02d}:{secs:02d}"
            else:
                eta_str = "--:--"

            downloaded_mb = current / (1024 * 1024)
            total_mb = total / (1024 * 1024)

            info_dict = {
                "percent": percent,
                "fraction": fraction,
                "downloaded_mb": downloaded_mb,
                "total_mb": total_mb,
                "speed_str": speed_str,
                "eta_str": eta_str,
                "current_bytes": current,
                "total_bytes": total,
            }

            if _DownloadProgressTqdm._progress_callback:
                try:
                    _DownloadProgressTqdm._progress_callback(fraction, info_dict)
                except Exception as e:
                    print(f"DEBUG: progress_callback error: {e}")

            # 定期日誌輸出 (每 10% 或每 5 秒輸出一次)
            if percent - _DownloadProgressTqdm._last_log_pct >= 10.0 or (now - _DownloadProgressTqdm._last_log_time >= 5.0):
                _DownloadProgressTqdm._last_log_pct = percent
                _DownloadProgressTqdm._last_log_time = now
                if _DownloadProgressTqdm._log_callback:
                    try:
                        _DownloadProgressTqdm._log_callback(
                            f"  > 下載進度: {percent:5.1f}% ({downloaded_mb:.1f} MB / {total_mb:.1f} MB) | 速度: {speed_str} | 預估剩餘: {eta_str}"
                        )
                    except Exception as log_err:
                        print(f"DEBUG: log_callback error: {log_err}")



def download_model_with_progress(model_size, download_root=None, device="cpu", log_callback=None, progress_callback=None, cancel_check_callback=None):
    """
    下載指定模型並提供詳細百分比進度、速度、ETA 及完整例外處理
    返回下載後的快取路徑
    """
    clean_size = model_size.split()[0].strip()
    is_mlx = device in ["mps", "mlx"]
    
    # 決定 Hugging Face Repo ID
    if is_mlx:
        repo_id = MODEL_INFO.get(clean_size, {}).get("mlx_repo", f"mlx-community/whisper-{clean_size}")
    else:
        import faster_whisper
        repo_id = faster_whisper.utils._MODELS.get(clean_size) or MODEL_INFO.get(clean_size, {}).get("repo_id", f"Systran/faster-whisper-{clean_size}")
        
    cache_dir = download_root if download_root else os.path.expanduser("~/.cache/huggingface/hub")
    
    # 1. 檢查是否已下載
    if check_model_downloaded(clean_size, download_root=download_root, device=device):
        if log_callback:
            log_callback(f"[快取就緒] 模型 '{clean_size}' 已存在於本地快取中，無須重新下載。")
        return cache_dir

    # 2. 檢查磁碟剩餘空間
    approx_mb = MODEL_INFO.get(clean_size, {}).get("approx_size_mb", 1500)
    free_mb, is_enough = check_disk_space(cache_dir, approx_mb + 300) # 保留 300MB 緩衝
    if not is_enough:
        err_msg = (
            f"[錯誤] 磁碟剩餘空間不足！\n\n"
            f"目標儲存路徑: {os.path.abspath(cache_dir)}\n"
            f"磁碟可用空間: {free_mb:.1f} MB\n"
            f"模型所需空間: 約 {approx_mb} MB (需保留至少 {approx_mb + 300} MB 空間)\n\n"
            f"【解決方案】\n"
            f"請至主畫面右下角的「模型儲存管理」，將儲存路徑變更至其他空間充裕的磁碟（例如 D 槽或外部硬碟）。"
        )
        if log_callback:
            log_callback(err_msg)
        raise RuntimeError(err_msg)

    # 3. 準備下載前資訊提示
    if log_callback:
        log_callback(f"--------------------------------------------------")
        log_callback(f"開始下載模型: {clean_size} ({MODEL_INFO.get(clean_size, {}).get('desc', '約 500MB~2GB')})")
        log_callback(f"儲存目錄: {os.path.abspath(cache_dir)}")
        log_callback(f"來源伺服器: Hugging Face ({repo_id})")
        log_callback(f"正在連線並取得檔案資訊，請稍候...")

    # 4. 初始化進度條與回調
    _DownloadProgressTqdm.reset(log_callback, progress_callback, cancel_check_callback)
    
    import huggingface_hub
    allow_patterns = None if is_mlx else [
        "config.json",
        "preprocessor_config.json",
        "model.bin",
        "tokenizer.json",
        "vocabulary.*",
    ]

    try:
        if cancel_check_callback and cancel_check_callback():
            raise InterruptedError("使用者已手動取消模型下載。")
            
        kwargs = {
            "cache_dir": download_root,
            "tqdm_class": _DownloadProgressTqdm,
            "etag_timeout": 15,
        }
        if allow_patterns:
            kwargs["allow_patterns"] = allow_patterns
            
        snapshot_path = huggingface_hub.snapshot_download(repo_id, **kwargs)
        
        # 下載完成回呼 100%
        if progress_callback:
            try:
                progress_callback(1.0, {
                    "percent": 100.0,
                    "fraction": 1.0,
                    "downloaded_mb": approx_mb,
                    "total_mb": approx_mb,
                    "speed_str": "--",
                    "eta_str": "00:00"
                })
            except Exception:
                pass

        if log_callback:
            log_callback(f"[成功] 模型 '{clean_size}' 下載完成！正在校驗與載入中...")
            
        return snapshot_path

    except InterruptedError as e:
        if log_callback:
            log_callback("[已取消] 使用者已手動取消模型下載。")
        raise e
        
    except Exception as e:
        error_str = str(e).lower()
        print(f"DEBUG: Download error: {e}")
        
        # 1. SSL 安全憑證錯誤 (公司內網/防毒軟體干擾)
        ssl_keywords = ["certificate_verify_failed", "sslcerterror", "self signed", "certificate verify failed"]
        if any(k in error_str for k in ssl_keywords):
            friendly_msg = (
                f"模型下載失敗：SSL 安全連線驗證失敗！\n\n"
                f"【可能原因】\n"
                f"您的電腦目前所在的網路（如公司/學校內部網路、公共 Wi-Fi）或電腦內安裝的防毒軟體正在進行 SSL 深度封包檢測，導致無法建立對 Hugging Face 的加密連線。\n\n"
                f"【解決步驟】\n"
                f"1. 請檢查防毒軟體（如卡巴斯基、趨勢等）是否有開啟「HTTPS/SSL 掃描」，可暫時將其關閉。\n"
                f"2. 若處於公司內網，建議切換至手機熱點或其他無憑證攔截的網路環境完成下載。\n"
                f"3. 下載完成後即支援永久離線使用。"
            )
            if log_callback:
                log_callback(f"[錯誤] SSL 憑證驗證失敗，無法安全連接伺服器。")
            raise RuntimeError(friendly_msg)

        # 2. 網路連線逾時 / 無法連線
        net_keywords = [
            "connectionerror", "connection error", "getaddrinfo", "max retries exceeded", 
            "timed out", "timeout", "offline mode", "unreachable", "localentrynotfound",
            "couldn't connect", "could not resolve", "failed to establish",
            "connection refused", "connection reset", "network is down",
            "cannot reach host", "cant reach host", "network unreachable"
        ]
        is_net_err = any(k in error_str for k in net_keywords)
        try:
            import requests
            if isinstance(e, requests.exceptions.RequestException):
                is_net_err = True
        except ImportError:
            pass

        if is_net_err:
            friendly_msg = (
                f"模型下載失敗 (模型: {clean_size})\n\n"
                "【原因】\n"
                "首次執行或使用新模型時，系統需要連線至 Hugging Face (huggingface.co) 下載模型權重檔案。\n"
                "目前偵測到無網路連線、連線逾時或伺服器連線中斷。\n\n"
                "【解決步驟】\n"
                "1. 請檢查您的網際網路連線是否正常 (若在公司/學校內網，可能需要設定代理或檢查防火牆)。\n"
                "2. 本程式支援「斷點續傳」，網路恢復後再次點擊，將自動從上次進度繼續下載。\n"
                "3. 您可透過主畫面右下角的「模型儲存管理」視窗預先下載模型，無須先載入影音檔案。"
            )
            if log_callback:
                log_callback(f"[錯誤] 網路連線失敗，無法下載模型 '{clean_size}'。")
            raise RuntimeError(friendly_msg)
            
        # 3. 磁碟空間或寫入錯誤
        if "no space left on device" in error_str or "disk full" in error_str:
            friendly_msg = (
                f"模型下載失敗：磁碟空間已滿！\n\n"
                f"儲存路徑 {os.path.abspath(cache_dir)} 空間不足。\n"
                f"請清理磁碟空間或至「模型儲存管理」切換至其他磁碟。"
            )
            if log_callback:
                log_callback("[錯誤] 磁碟空間不足，下載中止。")
            raise RuntimeError(friendly_msg)
            
        # 4. 存取權限不足
        if "permission denied" in error_str or "access is denied" in error_str:
            friendly_msg = (
                f"模型下載失敗：存取權限不足！\n\n"
                f"系統無法寫入目錄: {os.path.abspath(cache_dir)}\n"
                f"建議點擊右下角「模型儲存管理」更改儲存路徑至有完整讀寫權限的資料夾。"
            )
            if log_callback:
                log_callback("[錯誤] 存取權限不足，無法寫入模型目錄。")
            raise RuntimeError(friendly_msg)

        # 5. Windows 長路徑限制
        if os.name == 'nt' and ("path too long" in error_str or ("filenotfound" in error_str and len(os.path.abspath(cache_dir)) > 200)):
            friendly_msg = (
                f"模型下載失敗：路徑長度超過 Windows 限制！\n\n"
                f"目前儲存路徑層級過深 ({len(os.path.abspath(cache_dir))} 字元)。\n"
                f"【解決方案】\n"
                f"請至「模型儲存管理」將模型路徑設定為較短的路徑（例如 'C:\\whisper_models' 或 'D:\\models'）。"
            )
            if log_callback:
                log_callback("[錯誤] 路徑長度超過 Windows 系統限制。")
            raise RuntimeError(friendly_msg)


        if log_callback:
            log_callback(f"[錯誤] 模型下載異常: {e}")
        raise e


class SubtitleTranscriber:
    def __init__(self, model_size="small", device="cpu", compute_type="int8", download_root=None, cpu_threads=4):
        self.model_size = model_size.split()[0].strip()
        self.device = device
        self.compute_type = compute_type
        self.download_root = download_root
        self.cpu_threads = cpu_threads
        self.model = None

    def load_model(self, log_callback=None, progress_callback=None, cancel_check_callback=None):
        """載入模型 (第一次執行會自動下載，支援進度百分比、速度、ETA 與取消控制)"""
        print(f"DEBUG: load_model called. Model size: {self.model_size}, Device: {self.device}, Root: {self.download_root}")
        # 如果模型已經載入，直接返回
        if self.model: 
            print("DEBUG: Model already loaded.")
            return
        
        # 1. 確保模型已下載 (若尚未下載，先呼叫帶進度回饋與例外防護的下載器)
        download_model_with_progress(
            self.model_size,
            download_root=self.download_root,
            device=self.device,
            log_callback=log_callback,
            progress_callback=progress_callback,
            cancel_check_callback=cancel_check_callback
        )
        
        if log_callback:
            log_callback(f"正在載入模型核心: {self.model_size} (Device: {self.device})...")
            model_path = os.path.abspath(self.download_root) if self.download_root else os.path.abspath(os.path.expanduser("~/.cache/huggingface/hub"))
            log_callback(f"模型儲存路徑: {model_path}")

        try:
            if self.device in ["mps", "mlx"]:
                print("DEBUG: Initializing MLX Whisper for Apple Silicon...")
                try:
                    import mlx_whisper
                except Exception as e:
                    import traceback
                    tb_str = traceback.format_exc()
                    print(f"DEBUG: Error importing mlx_whisper: {tb_str}")
                    msg = f"要啟用 Apple MLX 框架加速 (Mac GPU)，請確認已安裝 mlx-whisper 套件。\n\n詳細錯誤原因：{e}"
                    if log_callback:
                        log_callback(f"錯誤: {msg}\n{tb_str}")
                    raise RuntimeError(msg)
                
                self.model_type = "mlx-whisper"
                self.mlx_model_path = f"mlx-community/whisper-{self.model_size}"
                if log_callback:
                    log_callback(f"MLX 框架準備就緒，預計使用模型: {self.mlx_model_path}")
                print("DEBUG: MLX whisper config ready.")
            else:
                print("DEBUG: Initializing WhisperModel...")
                from faster_whisper import WhisperModel
                self.model = WhisperModel(
                    self.model_size, 
                    device=self.device, 
                    compute_type=self.compute_type,
                    cpu_threads=self.cpu_threads,
                    download_root=self.download_root,
                    local_files_only=True # 已由前置下載器下載完成，這裡強制離線載入避免靜默阻塞
                )
                self.model_type = "faster-whisper"
                print("DEBUG: WhisperModel initialized successfully.")
                
            if log_callback:
                log_callback("模型載入完成！")
        except Exception as e:
            print(f"DEBUG: Error in load_model: {e}")
            error_str = str(e).lower()
            
            # 1. 檢查 GPU 驅動/cuDNN 相關錯誤
            if "cudnn" in error_str or "cublas" in error_str or "load symbol" in error_str or "dll" in error_str:
                friendly_msg = (
                    "啟動 GPU 模式失敗。\n"
                    "原因: 找不到必要的 NVIDIA 驅動程式或 cuDNN 函式庫。\n"
                    "解決方案: 請將「運算單元」切換為 'cpu' 模式。"
                )
                if log_callback:
                    log_callback("錯誤: 缺少 GPU 函式庫，請切換至 CPU 模式。")
                raise RuntimeError(friendly_msg)

            # 2. 檢查模型快取是否損毀或檔案不完整
            corrupted_keywords = [
                "unable to open file", "corrupted", "invalid load key", "bad file", 
                "magic number", "unexpected end of file", "cannot open", "badzipfile", "eof"
            ]
            if any(k in error_str for k in corrupted_keywords):
                friendly_msg = (
                    f"模型載入失敗：本地模型檔案損毀或未完整寫入！\n"
                    f"模型規格: {self.model_size}\n\n"
                    f"【原因】\n"
                    f"上次下載被異常強制中斷、非正常關機或防毒軟體鎖定，導致快取檔案不完整。\n\n"
                    f"【建議修復方式】\n"
                    f"可點選「清除快取並重新下載」自動修復損毀檔案。"
                )
                if log_callback:
                    log_callback(f"[錯誤] 模型檔案損毀或無法開啟: {e}")
                raise CorruptedModelError(friendly_msg, model_size=self.model_size, cache_dir=self.download_root)

            # 3. 檢查記憶體不足 (OOM)
            oom_keywords = ["bad_alloc", "out of memory", "cannot allocate memory", "memoryerror", "std::bad_alloc"]
            if any(k in error_str for k in oom_keywords):
                friendly_msg = (
                    f"載入模型失敗：電腦記憶體不足 (Out of Memory)！\n"
                    f"模型: {self.model_size}\n\n"
                    f"【建議解決方案】\n"
                    f"1. 請將「準確度 (Model)」切換為較輕量的模型（例如 'small' 或 'base'）。\n"
                    f"2. 關閉其他佔用高記憶體的應用程式（如瀏覽器多個分頁或大型軟體）後再試。"
                )
                if log_callback:
                    log_callback(f"[錯誤] 記憶體不足，無法載入模型 {self.model_size}。")
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
            self.load_model(log_callback, progress_callback=progress_callback, cancel_check_callback=cancel_check_callback)

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
                print("DEBUG: checking ffmpeg for MLX Whisper...")
                avail, ffmpeg_path, err_msg = check_ffmpeg_available()
                if not avail:
                    if log_callback:
                        log_callback(f"❌ {err_msg}")
                    raise RuntimeError(err_msg)

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
            error_str = str(e).lower()

            # 攔截缺少 ffmpeg 相關錯誤 (例如: [Errno 2] No such file or directory: 'ffmpeg')
            if "ffmpeg" in error_str and ("no such file" in error_str or "not found" in error_str or "errno 2" in error_str):
                _, _, ffmpeg_help = check_ffmpeg_available()
                if log_callback:
                    log_callback(f"\n❌ 影音解碼失敗：系統未安裝或找不到 FFmpeg。\n{ffmpeg_help}")
                raise RuntimeError(ffmpeg_help)
            net_keywords = [
                "connection", "getaddrinfo", "max retries", "timeout", "timed out",
                "huggingface", "offline", "unreachable", "localentrynotfound",
                "couldn't connect", "could not resolve", "failed to establish",
                "connection refused", "ssl", "proxy", "network is down",
                "cannot reach", "cant reach", "entry not found", "cannot find the requested files"
            ]
            if any(k in error_str for k in net_keywords):
                friendly_msg = (
                    f"模型下載/載入失敗\n\n"
                    "【原因】\n"
                    "轉錄需要從網路下載語音模型，但目前無網路連線或連線逾時。\n\n"
                    "【解決方法】\n"
                    "1. 請確認網路連線正常後再次執行。\n"
                    "2. 若為離線環境，請預先下載模型至指定快取目錄。"
                )
                if log_callback:
                    log_callback(f"❌ 網路連線失敗，無法下載模型。請確認網路已連線。")
                raise RuntimeError(friendly_msg)
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
