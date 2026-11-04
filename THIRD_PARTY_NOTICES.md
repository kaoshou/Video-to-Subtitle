# 第三方元件與授權聲明

Video to Subtitle 使用下列開源元件。各元件的著作權、授權及商標均屬原權利人；本清單不變更本專案自身的授權，也不表示各元件採用相同授權。

最近加入的 AI 連接使用 MCP Python SDK、tomlkit；硬體批次估算使用 psutil，以及 Windows／Linux 的 nvidia-ml-py。本次介面改善與模型清單沿用既有 CustomTkinter、Tkinter 及 Python 標準函式庫，沒有新增 UI 框架。

| 元件 | 用途 | 授權／上游 |
| --- | --- | --- |
| MCP Python SDK | 可選的本機 MCP 通訊 | [MIT](https://github.com/modelcontextprotocol/python-sdk/blob/main/LICENSE) |
| tomlkit | 保留註解的 AI 工具 TOML 設定編輯 | [MIT](https://github.com/python-poetry/tomlkit/blob/master/LICENSE) |
| psutil | CPU／記憶體資源資訊 | [BSD-3-Clause](https://github.com/giampaolo/psutil/blob/master/LICENSE) |
| nvidia-ml-py | NVIDIA 記憶體資訊；不包含 GPU 驅動 | [BSD-2-Clause](https://pypi.org/project/nvidia-ml-py/) |
| faster-whisper / CTranslate2 | CPU／CUDA 語音辨識 | [MIT](https://github.com/SYSTRAN/faster-whisper)、[MIT](https://github.com/OpenNMT/CTranslate2) |
| MLX / mlx-whisper | Apple Silicon 語音辨識 | [MIT](https://github.com/ml-explore/mlx)、[MIT](https://github.com/ml-explore/mlx-examples/tree/main/whisper) |
| CustomTkinter | 原生桌面介面 | [MIT](https://github.com/TomSchimansky/CustomTkinter) |
| tkinterdnd2 / TkDND | 檔案拖放 | [MIT 與所附 TkDND 授權](https://github.com/pmgagne/tkinterdnd2) |
| PyAV | 影音容器讀取與影格處理 | [BSD-3-Clause](https://github.com/PyAV-Org/PyAV)；所連結原生影音函式庫另依各自授權 |
| Pillow | 圖片處理 | [MIT-CMU／PIL Software License 及所附第三方條款](https://github.com/python-pillow/Pillow/blob/main/LICENSE) |
| sounddevice / PortAudio | 音訊播放 | [MIT 與所附 PortAudio 聲明](https://github.com/spatialaudio/python-sounddevice) |
| OpenCC | 台灣繁體中文轉換 | [Apache-2.0](https://github.com/BYVoid/OpenCC) |
| huggingface-hub | 模型快取與下載 | [Apache-2.0](https://github.com/huggingface/huggingface_hub) |
| tomli | Python 舊版本 TOML 讀取 | [MIT](https://github.com/hukkin/tomli) |
| NumPy | 數值處理 | [BSD-3-Clause 及所附第三方條款](https://numpy.org/doc/stable/license.html) |
| Python / Tcl / Tk | 執行環境與視窗元件 | [Python 與所附元件授權](https://docs.python.org/3/license.html) |
| PyInstaller | 獨立執行檔封裝 | [GPL 與 bootloader exception](https://pyinstaller.org/en/stable/license.html) |
| evercam-subtitle-player | EverCam／MP4 網頁播放器整合來源 | [上游專案](https://github.com/kaoshou/evercam-subtitle-player) |
| markdown-it | 僅網站文件建置 | [MIT](https://github.com/markdown-it/markdown-it) |
| jsdom / Playwright | 僅測試與畫面驗證 | [MIT](https://github.com/jsdom/jsdom)、[Apache-2.0](https://github.com/microsoft/playwright) |

## 封裝中的原文與原生元件

封裝流程從建置環境中已安裝套件收集其 LICENSE、NOTICE、COPYING、COPYRIGHT 等原文，隨主程式及 MCP 啟動器附於 `licenses/`，並保留原套件名稱、版本與檔案路徑。這些原文可能包含同一套件內其他元件的著作權與授權；應一併保留。不同版本的名稱或條款可能不同，以實際散布版本所附原文為準。

PyAV wheels 所附 FFmpeg 函式庫、Pillow 影像編碼器、PortAudio、Tcl/Tk、NumPy／MLX 原生函式庫等，不能只用 Python 套件的授權名稱概括。FFmpeg 的 LGPL／GPL 適用性依實際編譯選項決定；自行更換二進位檔或進行再散布時，請核對其原始聲明、來源及[官方授權說明](https://ffmpeg.org/legal.html)。套件未附原文時，不會自動捏造授權文件，應依上游與實際二進位檔補足所需材料。

Whisper 模型權重另由使用者下載；各模型庫及其衍生版本的模型卡與授權應分別核對。NVIDIA NVML／CUDA 的系統驅動與執行環境也適用其各自條款。
