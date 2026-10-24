## 相關聲明
本工具僅供學習與個人使用。使用者需自行承擔使用本軟體所產生的風險。不負任何擔保。

**開發者**: 崑山科技大學 鄭郁翰 (Yu-Han Cheng) | kaoshou@gmail.com 

# Video to Subtitle (本地語音轉字幕工具)

🌐 [官方網站](https://kaoshou.github.io/Video-to-Subtitle/) ｜ 📖 [完整使用手冊（繁體中文）](docs/USER_GUIDE.zh-TW.md) ｜ 📥 [下載最新版](https://github.com/kaoshou/Video-to-Subtitle/releases/latest)
本工具是考量了教育部將於 115 學年度起推動之政策要求，針對遠距數位課程須提供完整字幕內容，或建置合理之輔助資源配套措施，以落實保障學生平等受教權而生的解決方案。工具開發初期主要源自個人實際使用需求，考量許多教師在製作數位教材時亦面臨相同挑戰，所以將本工具整理並分享給大家使用。

基於 faster-whisper (OpenAI Whisper 的高效能實作) 模型的本地端桌面應用程式，幫它套上一層圖形介面，簡化 Whisper 的操作流程，使用者僅需進行簡單設定，即可完成影片轉換為字幕檔案（SRT、VTT）的作業，讓大家都可以簡易使用。由於程式於本機端執行，無須將影音檔案上傳至雲端，可充分利用使用者電腦算力生成影片字幕，兼具安全、免費與隱私保障，是一項可以安心的語音轉字幕解決方案。

其實目前網路上已有許多基於 Whisper 的字幕產生工具，部分採雲端服務模式，需上傳影片檔案，存在隱私疑慮，或需購買點數並受使用次數限制；另有部分本地端工具，則功能眾多或在操作流程上較為繁瑣，難以一次完成所需作業。本程式係基於實際教學與教材製作情境所開發，使用功能單純，期能以最少步驟完成字幕轉換，提升教師在製作數位教材時的效率與便利性。(字幕使用前請務必核對與校正)

![主操作介面](screenshot_main.png)

本文三張介面截圖均擷取自 **v2.7.12**，使用 Linux 雲端虛擬顯示環境與示範影音／字幕，並非真實轉錄成果。Windows／macOS 的字型與視窗外觀可能略有差異；下載的正式安裝檔仍為 Windows 與 macOS 版本。

## 🚀 v2.8.2 更新說明

- 改善 Windows 安裝完成後的自動啟動流程，透過桌面啟動程式。
- 模型因權限或系統限制暫時無法讀取時，顯示明確的存取提示，不再誤判為快取損毀或要求清除模型。
- 保留已下載模型、安全防護與原有 CPU／CUDA／MLX 轉錄流程。
- [完整更新說明](docs/releases/v2.8.2.md)。

## 🚀 v2.8.1 更新說明

- 改善模型下載與載入流程，直接使用檢查完成的模型資料夾，減少下載後仍無法載入的情況。
- 模型狀態區分「已下載」「下載未完成」「未下載」與「無法讀取」，缺少檔案時可接續下載，保留原有模型快取。
- 避免模型管理視窗與主畫面同時下載；統一模型儲存路徑的顯示、開啟及載入行為。
- 改善 Windows 在 SD 卡與 FAT／exFAT 磁碟上的 EverCam 網頁轉換相容性，保留安全檢查與原始網頁備份。
- 官網並列 Windows 免安裝版與安裝版下載，另提供 macOS 版，並補充安裝版啟動方式說明。
- [完整更新說明](docs/releases/v2.8.1.md)。

## 🚀 v2.8.0 更新說明

- 一般 MP4＋字幕與 EverCam 網頁播放器新增收合式「閱讀設定」，保留原有版面與藍綠配色。
- 逐字稿可調整 100%～200% 字級、1.5／1.8／2 倍行距與高對比模式，支援記住設定及一鍵恢復預設。
- 新增閱讀版 HTML 與純文字 TXT 下載，匯出所選語言的完整逐字稿，不受搜尋或分頁限制；時間標記可自由選擇。
- 閱讀版依段落整理內容，保留 EverCam 章節與字幕語言，支援離線閱讀、瀏覽器列印及另存 PDF。
- 改善播放器鍵盤操作、選單焦點、進度與音量提示，加入跳至播放器／逐字稿連結。
- 改善官方網站與手冊的鍵盤導覽、窄螢幕排版、表格捲動、系統強制色彩及減少動態支援。
- 統一 README、網站與歷史版本介紹，以功能新增、改善與修正為主。
- [完整更新說明](docs/releases/v2.8.0.md)。

## 🚀 v2.7.16 更新說明

- 修正 Windows「開啟網頁」只啟動瀏覽器的問題，一般影片、EverCam 與 OpenCam 均可開啟對應輸出頁面。
- 轉錄完成清單新增「OpenCam 播放器」徽章與「OpenCam 置入字幕」入口，省去額外的置入詢問視窗。
- 一般影片與 EverCam 逐字稿新增「跟隨播放」，反白並捲動至目前字幕；預設關閉，搜尋期間暫停跟隨。
- 改善長逐字稿的段落載入、跳轉定位、語言切換與視窗縮放操作，保留手動載入前後段功能。
- [完整更新說明](docs/releases/v2.7.16.md)。

## 🚀 v2.7.15 更新說明

- 修正 Windows 安裝版及免安裝版的繁體轉換元件封裝，改善勾選「強制繁體中文」後仍出現簡體字的問題。
- 繁體轉換在語音辨識後統一處理，適用 SRT、VTT、TXT、TSV 與 JSON，不需調整前導提示。
- 啟用強制繁體時先檢查元件，並在任務日誌顯示啟用狀態；元件異常時提供明確錯誤提示。
- 更新時保留使用者設定、模型快取及影音檔案；英文翻譯模式維持原有流程。
- [完整更新說明](docs/releases/v2.7.15.md)。

## 🚀 v2.7.14 更新說明

- 新增 Windows x64 繁體中文安裝版，內含 Python 與必要套件，保留原有免安裝 EXE 與 macOS DMG。
- 安裝時一次展開執行環境，減少後續啟動的重複解壓等待；可自訂安裝位置及桌面捷徑。
- Windows 安裝版與免安裝版共用使用者資料夾中的設定；更新、重裝與解除安裝保留設定、模型及影音。
- 修正首頁開啟 OpenCam 工具視窗後被首頁遮住的問題，開啟時自動提升至前景。
- [完整更新說明](docs/releases/v2.7.14.md)。

## 🚀 v2.7.13 更新說明

- 新增「網頁播放器 → OpenCam 置入字幕」，支援 OpenCam schemaVersion 1 專案，直接整合 SRT／VTT 並保留原有影片、網頁及章節。
- 可選取或拖入 OpenCam 資料夾、media.mp4、index.html 或 opencam-player.js，轉錄後可接續置入字幕。
- 支援無字幕專案與多語字幕；更新相同語系時保留其他語系，每次置入前建立備份。
- EverCam 與一般 MP4 播放器新增逐字稿搜尋、關鍵字標示、語言切換及點選時間跳轉。
- EverCam 採用「章節／逐字稿」分頁；一般 MP4 預設收合逐字稿，窄視窗時閱讀面板移至影片下方。
- 完整手冊補充語系檔名對照、字幕置入、備份還原與逐字稿操作說明。
- [完整更新說明](docs/releases/v2.7.13.md)。

## 🚀 v2.7.12 更新說明

- 保留藍白配色，為待處理清單增加底色、邊框與留白，讓清單與背景清楚區隔。
- 調整轉換設定標題、背景及欄位間距，以獨立卡片呈現進階設定。
- 改善小視窗與高縮放下的進階設定展開定位，優先顯示第一個選項。
- 標題列、首頁、關於本程式與更新檢查統一使用本次啟動版本。
- 更新 README 與官方網站的主畫面、字幕校對器及模型管理截圖。
- [完整更新說明](docs/releases/v2.7.12.md)。

## 🚀 v2.7.11 更新說明

- 改善 Windows 建立字幕網頁時的檔案占用錯誤，資源寫入並關閉後再發布完整資料夾。
- 保留原始影片、字幕與既有輸出，持續提供安全寫入、符號連結防護及暫存保留機制。
- 改善占用錯誤提示，詳細資訊加入程式版本、處理階段與資源名稱，方便排查問題。
- [完整更新說明](docs/releases/v2.7.11.md)。

## 🚀 v2.7.10 更新說明

- 改善 Windows 字幕網頁匯出的短暫檔案占用處理，提供簡短提示及可展開的錯誤詳細資訊。
- 一般 MP4 與 EverCam 視窗支援拖入影片，自動配對同資料夾的同名／語系 SRT、VTT。
- EverCam 工具列分行排列，改善長路徑、高縮放下的按鈕遮蔽。
- 修正 macOS 選影片後出現黑色選單視窗的問題；進階設定展開後自動捲入可見範圍。
- 加高模型管理「完成」按鈕，調整下載與取消操作空間，改善字幕編輯器縮放及底部操作區。
- [完整更新說明](docs/releases/v2.7.10.md)。

## 🚀 v2.7.9 更新說明

- 新增「網頁播放器 → 一般影片＋字幕」，選擇 MP4 即自動配對同名或帶語系編碼的 SRT／VTT；同語系優先採用 VTT。
- 預設以影片檔名作為標題，在影片旁建立新的播放器資料夾，可直接離線開啟。
- 簡化操作介面，顯示影片、字幕摘要及就緒狀態，進階設定以收合方式呈現。
- 可自訂標題、作者、單位、簡介、封面、字幕語言及輸出位置，也能手動加入字幕。
- 支援載入既有網頁設定並另存新資料夾，保留原始影片、字幕與既有輸出。
- [完整更新說明](docs/releases/v2.7.9.md)。

## 🚀 v2.7.8 更新說明

- 加強字幕編輯器的檔案寫入，原始碼預覽改在記憶體處理，儲存採用安全暫存與替換。
- 加強 EverCam 首頁備份及播放器部署，拒絕不安全的符號連結；備份失敗時保留原首頁。
- 同步保護 Windows 字幕更新工具，檢查 junction／reparse point。
- 保留多語字幕、原首頁備份與額外自訂資源。
- [完整更新說明](docs/releases/v2.7.8.md)。

## 🚀 v2.7.7 更新說明

- 修正 macOS「加入檔案」閃退，改善 Apple MLX GPU 加速元件載入。
- 整合 PyAV 音訊解碼，macOS 發行版不需另行安裝 FFmpeg。

## 🚀 v2.7.6 更新說明

- 修正 macOS MLX 模組載入問題，補齊加速所需元件。
- 改善轉錄日誌，提供更清楚的錯誤資訊。

## 🚀 v2.7.5 更新說明

- 整合 EverCam 課程辨識、首頁備份與 HTML5 字幕播放器部署。
- 轉錄完成清單加入課程徽章、字幕校對及單堂／批次網頁轉換入口。

## 🚀 v2.7.4 更新說明

- 新增自訂前導提示，支援講題背景、語境與專有用語。
- 精簡進階設定排列，改善子視窗開啟效果與主視窗標題。

## 🚀 v2.7.3 更新說明

- 改善 macOS DMG 壓縮與下載體積。
- 保留原生 App Bundle 的安裝與啟動方式。

## 🚀 v2.7.2 更新說明

- macOS 改用原生 App Bundle，減少啟動時的解壓等待。
- 轉錄與多媒體元件改為按需載入，加快主畫面開啟。

## 🚀 v2.7.1 更新說明

- 字幕校對器加入即時字幕疊加、CC 開關、分割與合併快捷鍵。
- 新增多倍速播放，改善字幕跳轉、macOS 音訊解碼與更新檢查。

## 🚀 v2.7.0 更新說明

- 字幕校對器整合影音同步播放、字幕定位、音量及靜音控制。
- 新增可調整的左右分割面板、最大化與全螢幕操作。

## 📸 軟體介面一覽

### 1. 軟體主操作介面
簡潔直觀的操作中心，整合多檔案拖曳清單、模型即時狀態標示、運算單元切換、繁簡台灣慣用語轉換與即時轉錄進度。
![主操作介面](screenshot_main.png)

### 2. 全新高效字幕校對編輯器與影音同步播放器
專業級字幕校對工作區，提供千筆字幕秒開的結構化表格與毫秒級對齊的影音播放器：
* **雙向即時聯動**：單擊任一條字幕畫面立刻精準跳轉；影片播放或快轉時字幕清單自動捲動對齊並高亮。
* **左右可調分割面板**：滑鼠拖曳中間分割線可依需求自由拉大影片區域或展開字幕列表，影片畫面自動等比例平滑縮放。
* **原生音訊串流與音量控制**：清晰立體聲音質，具備 0%~100% 音量滑桿調節、動態圖示反饋與一鍵靜音/記憶還原。
* **視窗縮放與最大化**：支援自由拖拉視窗邊框調整大小、一鍵視窗最大化（Maximize）、快捷鍵 `F11` 與雙擊標題列放大。
![字幕校對編輯與影音同步播放器](screenshot_editor.png)

### 3. 模型快取與儲存管理介面
全方位掌控本地 Whisper 模型資產，離線使用更安心：
* **自訂儲存路徑**：可自由變更模型存放磁區（如移至 D 槽），並即時顯示該磁區剩餘可用空間。
* **本地狀態清晰標示**：一目了然各模型的下載狀態（`已下載` / `未下載`）、檔案預估大小與功能說明。
* **一鍵預先下載與快取清除**：支援手動預先下載指定模型（附帶下載進度條與狀態即時更新），並可隨時一鍵清除特定模型快取釋放空間。
![模型儲存管理與預先下載](screenshot_models.png)

## ✨ 主要功能
* **支援最新 `large-v3-turbo` 與多模型切換**：整合 `tiny`、`base`、`small`、`medium`、`large-v3` 及 `large-v3-turbo`，下拉選單即時標示本地下載狀態。
* **自訂前導提示詞 (Initial Prompt)**：支援自訂講題背景、文風語境或特定主題用語，並與「強制繁體中文」智慧融合，有效提升模型對整體語意與風格的精確理解。
* **熱詞補強 (Hotwords)**：針對專有名詞、程式碼方法名稱、術語或人名提供引導辨識，大幅提升教學影片術語的精準度。
* **自然語意與停頓斷句策略 (Segmentation Strategy)**：改採語音停頓與標點符號自然斷句，尊重語音段落與單字級毫秒時間軸，避免語意碎裂。
* **本地執行與隱私安全**：除初次下載模型外，完全離線執行，基於 faster-whisper (Windows/Linux) 或 mlx-whisper (Mac)，影音資料絕不上傳雲端。
* **支援多檔案批次處理**：可一次加入多個檔案進行排程轉換，轉錄完成後提供獨立的多任務檔案管理彈窗。
* **軟體內建字幕快速校對面板**：提供「編輯現有字幕檔」功能，支援 `.srt`、`.vtt` 時間軸列表編輯與 `.txt` 大幅面文字潤飾，無須記事本即可一鍵無損儲存。
* **多格式輸出**：支援輸出 SRT, VTT, TXT, TSV, JSON 等常見格式。
* **支援拖曳檔案 (Drag & Drop)**：直接將多個檔案拖入視窗即可加入清單，並自動過濾非影音格式。
* **EverCam 數位教材一鍵轉換**：深度整合 [evercam-subtitle-player](https://github.com/kaoshou/evercam-subtitle-player)，自動偵測 EverCam 錄影專案，轉錄字幕後可一鍵將舊式 EverCam 課程網頁升級為支援字幕、搜尋與現代介面的 HTML5 播放頁面。

## 使用流程
  1. **選擇要轉換的檔案**：點擊「加入檔案...」按鈕或**直接將檔案或資料夾拖曳至程式視窗**。
      - **一般影音格式**：支援 MP4, MP3, MKV, WAV, MOV, AVI, M4A, FLAC, OGG, WEBM 等常見格式。
      - **EverCam 數位課程專案**：可直接將整個 EverCam 課程資料夾拖入程式視窗，或點選「加入檔案...」選取課程目錄下的影音檔案（或 `config.js`），系統自動溯源偵測並提示標記為 EverCam 課程專案。
  2. **設定準確度 (Model)**：依據需求選擇模型大小（選單會標示 `[已下載]` 或 `[未下載]`）
      - **Tiny / Base**：速度最快，但準確度較低。
      - **Small / Medium**：速度與準確度的平衡點 (一般用途推薦)。
      - **Large-v3-Turbo**：⭐⭐⭐ 強烈推薦！速度接近 Medium，準確率逼近 Large-v3，性價比最高。
      - **Large-v3**：準確度最高，但運算時間較長，需要較大顯存/記憶體。
  3. **選擇運算單元與格式**：
      - **運算單元**：Windows 可選 cpu / cuda；macOS 上可選 cpu / mlx (Apple Silicon GPU，將自動啟用 MLX 框架加速)。
          - 若要在 Windows 使用 CUDA 加速，需安裝對應版本的 [cuDNN](https://developer.nvidia.com/cudnn) 。詳情請參閱 [CTranslate2 文件](https://opennmt.net/CTranslate2/installation.html)。
          - v2.7.7 的 macOS DMG 已包含執行所需的 PyAV 與 MLX；一般使用者不需另行安裝 Python、FFmpeg 或 mlx-whisper。完整步驟請參閱[繁體中文使用手冊](docs/USER_GUIDE.zh-TW.md)。
      - **輸出格式**：可選擇 SRT, VTT, TXT, TSV 或 JSON。
      - **進階功能**：可視需求勾選「強制繁體中文」(自動轉台灣繁體)或「翻譯成英文」。
  4. **開始生成**：點選「開始轉錄」按鈕，程式將自動處理清單中的所有檔案。底部進度條會顯示當前檔案的處理進度。
  5. **轉換完畢、校對與 EverCam 網頁轉換**：
      - 轉換完成後會彈出自適應美化檔案管理面板，可直接在軟體內一鍵「開啟字幕」、「字幕校對」或「開啟目錄」。
      - **EverCam 專案現代化升級**：若處理 EverCam 專案，單檔列提供「EverCam網頁轉換」按鈕，底部提供「🚀 立即轉換為 EverCam 網頁播放器 / 一鍵轉換全部的 EverCam 網頁」按鈕。點擊後 0.1 秒自動無損升級為現代化 HTML5 字幕播放器並於預設瀏覽器中直接開啟預覽！
  6. **整合與發布**：後續可根據遠距教學平台之功能掛上字幕檔，或者將字幕檔與影片進行結合。

## 模型下載位置
這個程式使用的是 faster-whisper 函式庫，預設會將模型下載到 Hugging Face 的快取目錄中。
根據作業系統，模型存放的位置如下：
  * Windows
    >通常位於： ``` C:\Users\使用者名稱\.cache\huggingface\hub ```
    >
    >在此資料夾內，您會看到類似 models--Systran--faster-whisper-small 的資料夾，裡面就是模型檔案
    >
    >該資料夾是一個隱藏資料夾，您可能需要在檔案總管中開啟「顯示隱藏的項目」才看得到
    
  * macOS
    >通常位於： ```/Users/使用者名稱/.cache/huggingface/hub```
    >
    >.cache 也是隱藏資料夾。您可以在 Finder 中按下 Cmd + Shift + . (句號) 來顯示隱藏檔案，或者在終端機中使用 open ~/.cache/huggingface/hub 直接開啟

**提示**：若上述路徑無權限寫入 (例如在實驗室或公用電腦)，程式會詢問是否改將模型下載到程式所在資料夾下的 `models` 目錄，請放心使用。

## 📥 下載與啟動 (一般 Windows 使用者)
如果您不需要修改程式碼，請直接下載執行檔。
1. 下載程式：[前往 Releases 頁面](https://github.com/kaoshou/Video-to-Subtitle/releases) 下載最新的 VideoToSubtitle.exe。
2. 執行：雙擊 EXE 檔案即可開始使用。初次開啟需要稍待片刻。

### Windows 安裝版（自 v2.7.14 起）

新增 `VideoToSubtitle-Setup-v<版本>.exe` 安裝包，採用 PyInstaller 資料夾式封裝；Python 與必要套件在安裝時解壓，之後啟動不需每次重新解壓。既有免安裝 EXE 繼續保留。請從[官方 Releases](https://github.com/kaoshou/Video-to-Subtitle/releases/latest) 下載 `VideoToSubtitle-Setup-v2.8.2.exe` 或後續版本；請勿把編譯器 Inno Setup 的安裝包當成本程式。

安裝精靈使用繁體中文，預設只安裝給目前使用者，可選安裝位置及桌面捷徑，亦可從「開始」功能表啟動／Windows「已安裝的應用程式」解除安裝。不需事先安裝 Python 或外部 FFmpeg。Windows x64、Windows 10／11 為目標平台；實際自動驗證環境見建置紀錄。

Windows 封裝版的設定保存在 `%LOCALAPPDATA%\VideoToSubtitle\config.json`；模型保留既有使用者快取或自選路徑。更新與解除安裝不刪除設定、模型或影音。安裝版與新版免安裝版共用同一使用者設定；原始碼與 macOS 的設定位置維持不變。

首次使用模型仍需下載；CUDA 仍需要相容 NVIDIA 顯示卡與驅動。啟動較快不代表轉錄速度變快；請在實際電腦試用比較，無須停用防毒或新增排除項目。更新或解除安裝前請先關閉程式。

## 🛠️ 開發與建置 (開發者)
若您希望從原始碼執行或自行打包，請參考以下步驟。

1. **環境需求**
    - Python 3.10 ~ 3.12 (推薦使用 **Python 3.11**，各平台二進位相容性最佳)

2. **安裝相依套件**
   也可建立虛擬環境 (Virtual Environment):
    ```bash
    python -m venv venv
    # Windows:
    .venv\Scripts\activate
    # macOS/Linux:
    source venv/bin/activate
    ```
    安裝所需套件 (Windows / 一般環境):
    ```bash
    pip install customtkinter tkinterdnd2 faster-whisper opencc av pillow sounddevice pyinstaller
    ```
    (若為 Mac 開發者並需啟用 MPS 硬體加速，請額外安裝 `mlx-whisper`):
    ```bash
    pip install mlx-whisper
    ```

3. **執行程式**
   ```bash
   python SubtitleTranscriber.py
   ```

4. **使用 PyInstaller 打包為執行檔**
    專案已內建完整維護之規格檔，直接執行：
    ```bash
    pyinstaller VideoToSubtitle.spec
    ```
    打包完成後，執行檔將位於 `dist/VideoToSubtitle.exe` (Windows) 或 `dist/VideoToSubtitle.app` (macOS)。

5. **Windows 安裝版建置（Python 3.11 x64 + Inno Setup 6.7.3）**

   在 PowerShell 中使用相同 spec：

   ```powershell
   $env:VTS_WINDOWS_BUNDLE = 'onedir'
   pyinstaller --noconfirm --distpath dist/windows-install --workpath build/windows-install VideoToSubtitle.spec
   $version = python -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])"
   $source = (Resolve-Path 'dist/windows-install/VideoToSubtitle').Path
   $output = Join-Path $PWD 'dist/installer'
   & 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe' "/DAppVersion=$version" "/DSourceDir=$source" "/DOutputDir=$output" packaging/windows/VideoToSubtitle.iss
   Remove-Item Env:VTS_WINDOWS_BUNDLE
   ```

   `ISCC.exe` 的路徑請依編譯器實際安裝位置調整；使用者不需安裝此編譯器。6.7.3 的 `Languages` 目錄需補入[繁中語言檔（固定來源）](https://raw.githubusercontent.com/jrsoftware/issrc/f8e83fddb902d35811d1d352d2556725a4442cdb/Files/Languages/ChineseTraditional.isl)，SHA256 為 `031684fc769259291fd563338b5abe20b7753c88ab5a2976b83a80788deb8455`。CI 會校驗編譯器及語言檔，再測試真實安裝、獨立 EXE 啟動、網頁匯出、重裝及解除安裝。手動選 `windows_only` 僅建置試用成品，不會發布 Release。啟動報告的第一次是首次 GUI 取樣，先前已執行匯出驗證，不代表磁碟／防毒冷啟動。Inno Setup 的使用條件請參考其[官方網站](https://jrsoftware.org/isinfo.php)。

## 📚 使用的第三方專案與授權
本工具使用了以下開源專案：
| 專案 | 授權 | 用途 |
|------|------|------|
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | MIT | 核心語音辨識引擎 (基於 CTranslate2) |
| [CTranslate2](https://github.com/OpenNMT/CTranslate2) | MIT | 高效能 Transformer 推論引擎 (Backend) |
| [mlx-whisper](https://github.com/ml-explore/mlx-examples/tree/main/whisper) | MIT | Apple Silicon GPU (MPS) 專用高速語音辨識框架 |
| [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter) | MIT | 現代化 GUI 介面框架 |
| [tkinterdnd2](https://github.com/pmgagne/tkinterdnd2) | MIT | GUI 檔案拖放支援 |
| [PyAV (av)](https://github.com/PyAV-Org/PyAV) | BSD-2-Clause | 原生影音幀解碼、音訊重採樣與時間軸精準定位 |
| [Pillow](https://github.com/python-pillow/Pillow) | HPND | 影像自適應等比例縮放與畫布渲染 |
| [sounddevice](https://github.com/spatialaudio/python-sounddevice) | MIT | 跨平台低延遲音訊串流輸出 (PortAudio) |
| [OpenCC](https://github.com/BYVoid/OpenCC) | Apache-2.0 | 精準的繁簡中文轉換庫 |
| [tomli](https://github.com/hukkin/tomli) | MIT | 支援 Python 舊版本讀取 pyproject.toml 設定檔 |
| [huggingface-hub](https://github.com/huggingface/huggingface_hub) | Apache-2.0 | 語音辨識模型下載與快取儲存通道 |
| [evercam-subtitle-player](https://github.com/kaoshou/evercam-subtitle-player) | - | 提供 EverCam 傳統數位課程現代化 HTML5 字幕播放器網頁轉換模組 |
# 一般影片字幕網頁

「網頁播放器 → 一般影片＋字幕」可將 MP4 與 SRT／VTT 匯出為無章節側欄的離線網頁，自訂標題、作者、單位、簡介與封面，並切換多語字幕。重新編輯會另存新包，不覆寫原始資料。

「網頁播放器 → OpenCam 置入字幕」可將 SRT／VTT 直接加入 OpenCam 的 `opencam-player.js`，不改動原網頁、影片或章節。支援原本沒有字幕的專案與多語字幕；同語系更新、其他語系保留，每次寫入前建立不覆蓋的完整備份。轉錄 OpenCam 的 `media.mp4` 完成後，結果清單會在檔名後顯示「OpenCam 播放器」徽章；需要時按該列的「OpenCam 置入字幕」，不再額外跳出詢問，也不會自動修改播放器。詳見[OpenCam 字幕置入手冊](docs/USER_GUIDE.zh-TW.md#opencam-網頁播放器字幕置入)。

選擇 MP4 後，自動載入同資料夾內的同檔名字幕與帶語系碼字幕（例如 `課程.vtt`、`課程.zh-TW.srt`、`課程.en.vtt`）；同語系優先 VTT，無語系顯示「預設字幕」，不必逐軌設定。主畫面只需選影片並建立網頁，其他參數保留在「進階設定」。

**自 v2.7.9 起提供。** 操作與限制見[繁體中文完整手冊](docs/USER_GUIDE.zh-TW.md#一般-mp4字幕匯出網頁)。影片不重新編碼，請用實際目標瀏覽器確認播放相容性。

v2.7.10 改善：兩個網頁轉換視窗都可拖入影片；一般 MP4 自動配對字幕，EverCam 則從課程影片尋找所屬課程。原生介面統一字體、配色與操作區，改善長路徑／高縮放下的按鈕遮蔽。Windows 寫入遇到短暫檔案占用會有限次重試，持續占用則保留錯誤詳細資訊，不跳過原有安全檢查。
