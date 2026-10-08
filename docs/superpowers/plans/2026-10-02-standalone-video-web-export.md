# Standalone Video Web Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓使用者將單支 MP4 與多語字幕匯出為可移動、可離線播放、可重新編輯的網頁，保留既有 EverCam 功能。

**Architecture:** 新增獨立資料驗證、匯出與桌面對話框，共用現有播放器與安全檔案操作。先完成安全串流與資料契約，再接播放器及 GUI；最終以排他目錄發布作為成功邊界。一般模式不經 EverCam 原地部署。

**Tech Stack:** Python 3.11+、unittest、CustomTkinter、PyAV、Pillow、原生 JavaScript/CSS、Node test runner、PyInstaller、GitHub Actions。

**Spec:** `docs/superpowers/specs/2026-10-02-standalone-video-web-export-design.md`

## Global Constraints

- 單支 MP4、多語字幕切換、可設定初始字幕或關閉字幕。
- 不重新編碼、不新增章節、不自動上傳、不變更辨識引擎；不變更版本號、不推送、不發布。
- 標題／作者／單位／簡介上限分別為 200／100／200／5,000 Unicode 字元，文字只作為資料。
- 字幕只接受 UTF-8／UTF-8 BOM SRT 或 VTT；至少一軌、語言不重複，超時提示不截斷。
- 封面只接受本機 PNG／JPEG，最多 20 MiB／2,500 萬像素，重新編碼清除中繼資料。
- `web-export.json` 限制 1 MiB；`schemaVersion: 1`、`kind: video-to-subtitle-web`，不執行輸入包的 JS。
- 一般包使用 `player-config.js` 與 `window.VTS_PLAYER_CONFIG`，不能產生 `config.js`；`index: []`。
- MP4 以 4 MiB 區塊複製；保持原檔不變，取消與失敗不得留下假成功的正式輸出。
- 另存新包，不覆寫既有目錄；同專案保留 package ID，全新專案使用新 ID。
- Windows／macOS、安全測試、file://／HTTP 真實播放與打包驗證分別列出證據；未測不宣稱通過。

## Review Focus

1. 匯出時關閉視窗或在發布後取消：不能對已銷毀 GUI 回呼或刪除成功包（Task 1、5）。
2. 中文、emoji、引號、HTML 字串及 Windows 保留檔名：文字如實顯示，檔名跨平台合法（Task 2、4）。
3. 多筆轉錄部分失敗或輸出含語言後綴：完成捷徑只能配對實際來源，不能靠列表序號／猜檔名（Task 5）。
4. 搬移後載入缺檔包、刪除預設字幕、同名不同專案：可補檔，預設需重選，偏好不串用（Task 2、4、5）。
5. 磁碟不足、來源在讀取中變更、發布前競爭與清理被替換：外部檔案不受損，殘留位置明示（Task 1、3）。

---

## Files and responsibilities

- `safe_files.py`：新增受控串流与暫存目錄生命週期，保留舊 API。
- `web_export_model.py`：資料型別、欄位／語言／清單驗證、標題狀態。
- `web_export.py`：安全讀取、嚴格字幕驗證、媒體／封面處理、載入與匯出。
- `web_export_dialog.py`：獨立 GUI 與背景工作，不匯入主程式造成循環。
- `assets/standalone_player/index.html`：一般版頁面外框；共用 `assets/evercam_player/js/evercam-modern.js` 及 CSS。
- `SubtitleTranscriber.py`：只接入口、完成來源配對、對話框，不重構轉錄流程。
- `tests/test_web_export_*.py`、`tests/player/*.test.mjs`：新功能與回歸；既有安全測試保留。
- `VideoToSubtitle.spec`、CI workflows、繁中手冊／網站：打包與驗收完成後同步。

### Task 1: 安全串流與整包排他發布

**Files:** Modify `safe_files.py`; create `tests/test_web_export_io.py`; retain `tests/test_safe_files.py`.

**Interfaces:**
- `SafeDirectory.open_read(name: str) -> ContextManager[BinaryIO]`：固定已開啟的一般檔案，支援 seek，拒絕 link/reparse。
- `StagedDirectory(parent: SafeDirectory)` context manager，提供 `directory: SafeDirectory`。
- `StagedDirectory.copy_from(source: BinaryIO, name: str, *, progress: Callable[[int], None], cancelled: Callable[[], bool]) -> int`：4 MiB 分塊、前後 fstat，進度為此次檔案累計 bytes。
- `StagedDirectory.publish(name: str) -> Path`：同父目錄、排他、至多一次；已發布後退出不刪除。
- `ExportCancelled(InterruptedError)`；清理失敗用例外屬性 `staging_path: Path` 保留實際路徑，不遮蔽原始錯誤。

- [ ] 寫測試 `test_chunked_copy`：reader 拒絕 `read(-1)`，每次要求 <= 4*1024*1024，輸出 bytes 相等，進度單調。
- [ ] 加入 `test_cancel_before_publish`、`test_late_cancel_keeps_published`、`test_source_mutation`、`test_competing_destination`、`test_cleanup_replacement`；確認來源／競爭目錄／外部 sentinel bytes 不變。
- [ ] 執行 `python3 -m unittest discover -s tests -p 'test_web_export_io.py' -v`，確認因新介面不存在而失敗。
- [ ] 實作 anchored no-follow 開啟與獨占建立檔案；複製前後比較同一 fd 的 size、mtime_ns 及實讀 bytes，flush/fsync。
- [ ] 實作 macOS renameatx_np RENAME_EXCL、Linux renameat2 RENAME_NOREPLACE；不支援時拒絕降級。Windows 使用持有可 rename handle 的 no-replace 發布，避免關閉固定 handle 再按路徑 rename 的競態；父目錄保持固定。測試 handle 共享與關閉順序。
- [ ] cleanup 記錄自己建立的檔案／目錄及身分，按反向順序逐項安全移除；非預期項目留下並報告，不使用廣泛遞迴刪除。
- [ ] 執行新測試及 `python3 -m unittest discover -s tests -p 'test_safe_files.py' -v`；本機全可執行案例 PASS，Windows junction／handle 案例加入 Windows CI，不把 skip 計為驗證成功。
- [ ] 保留可獨立審閱的變更；依規格，commit 另待授權。

### Task 2: 輸入資料、嚴格解析與清單載入

**Files:** Create `web_export_model.py`, `web_export.py`, `tests/test_web_export_model.py`, `tests/test_web_export_inputs.py`.

**Interfaces:**
- immutable dataclasses `Metadata(title, author='', organization='', description='')`、`SubtitleSource(path: Path, language: str)`。
- `ExportRequest(video: Path, subtitles: tuple[SubtitleSource, ...], metadata: Metadata, output_parent: Path, folder_name: str, default_subtitle: str, poster: Path|None = None, package_id: str|None = None)`。
- `ValidationIssue(field: str, message: str, severity: str)`，severity 僅 `error`／`warning`。
- `validate_request(request: ExportRequest) -> list[ValidationIssue]`；`canonical_language(value: str) -> str`、`validate_folder_name(value: str) -> str`，無效值 raise ValueError。
- `TitleState` methods `select_video(path: Path)`、`edit(text: str)`、`use_filename()`，properties `value: str`、`dirty: bool`。
- `inspect_inputs(request: ExportRequest) -> list[ValidationIssue]`；`load_package(folder: Path) -> LoadedPackage`，後者包含 `request: ExportRequest` 及 `issues: list[ValidationIssue]`，缺檔可回填修復，畸形清單拒絕。

- [ ] 寫欄位邊界測試（200/201、100/101、200/201、5000/5001）、Unicode、空標題、手動標題與還原自動；assert 換影片不覆寫 dirty title。
- [ ] 測試 `CON`、`aux.txt`、ADS、分隔符、尾端空白／句點拒絕；語言大小寫規範化及重複拒絕；刪除預設軌的設定無效。
- [ ] 寫實際 SRT/VTT 測試：BOM、NOTE/STYLE 區塊、重疊、文字標記、空 cue、損壞／負數／非有限／倒序時間；合法重疊接受，錯誤提供檔名和行定位。字幕文字不執行或任意翻譯改寫。
- [ ] 寫清單 round-trip、>1 MiB、布林冒充版本數字、未知 schema、路徑穿越、URL、link、缺檔、搬移測試；輸入 `index.html`/JS 故意放惡意內容但不得讀取執行。
- [ ] 執行 `python3 -m unittest discover -s tests -p 'test_web_export_*.py' -v`，先記錄對應 RED。
- [ ] 實作資料驗證及有界 JSON 讀取；語言採明確受支援 BCP47 子集合（primary 2–3 英文字、可選 script 4 字與 region 2 字／3 數字），不接受任意檔名字串。
- [ ] 用 Task 1 的已開啟 file object 探測 PyAV、讀字幕與 Pillow，拒絕偽裝 MP4／無影片流；不以解碼成功保證瀏覽器相容。封面 decode 前檢查 bytes／pixels，再重新編碼。
- [ ] 保留 EverCam 原有容錯解析器不變；新嚴格解析輸出同樣 cue 結構。補真實短 MP4 fixture 的有效／無影片流測試，不下載辨識模型。
- [ ] 重跑上述測試，預期 PASS；PyAV／Pillow 相關測試需安裝既有依賴，不以 mock 取代全部整合證據。

### Task 3: 可重新載入的完整網頁匯出

**Files:** Modify `web_export.py`; create `tests/test_web_export_package.py`.

**Interfaces:**
- `export_package(request: ExportRequest, *, app_version: str, progress: Callable[[int, int], None], cancelled: Callable[[], bool], accept_warnings: bool = False) -> ExportResult`。
- `ExportResult(folder: Path, index_path: Path, package_id: str)`；成功只在 publish 返回後回傳。
- 消費 Task 1 的 staging 與 Task 2 型別；所有輸入在匯出時重新安全驗證，不能信任 GUI 預檢結果。

- [ ] 寫 `test_export_reload_move_reexport`：影片 bytes 一致、UTF-8 字幕、清單無來源絕對路徑、移動後重載、另存保留 package ID、旧包逐檔雜湊不變。
- [ ] 測試新專案不同 ID、未接受警告拒絕、磁碟不足、讀取中断、發布競爭、取消；assert 正式輸出不存在且原檔 bytes 不變。
- [ ] 測試包內固定檔名／引用完整、無 `config.js`／更新字幕.cmd、`is_evercam_folder(output) is False`，不複製來源的任意自訂檔。
- [ ] 執行 `python3 -m unittest discover -s tests -p 'test_web_export_package.py' -v`，確認 RED。
- [ ] 實作預檢空間（資料總量加 max(64 MiB, 5%) 保留量）；複製至私有 staging，生成 manifest／runtime JS／字幕 JS／可信任 CSS、JS、HTML。發布前再次驗證受管理引用與取消。
- [ ] 使用 json.dumps 序列化 JS 資料並處理特殊 Unicode；HTML title 用 html.escape。manifest 使用 video `{path: 'media.mp4', duration?: number}`、字幕 `{language, path}`，與載入器使用相同 schema。
- [ ] 載入包不複製任意舊 HTML／JS；資源從目前可信任 app assets 重建。資源缺失時明確失敗，不產生空白成功包。
- [ ] 重跑新測試及既有安全測試，預期 PASS；測試記錄覆蓋取消與清理殘留的具體回報。

### Task 4: 共用播放器的一般模式

**Files:** Create `assets/standalone_player/index.html`, `tests/player/standalone.test.mjs`; modify `assets/evercam_player/js/evercam-modern.js`, `assets/evercam_player/css/evercam-modern.css`.

**Interfaces:** 使用規格的 `window.VTS_PLAYER_CONFIG`，缺少時回退 `window.config`；字幕仍為 `window.EVERCAM_SUBTITLES`。新增 DOM `course-organization`、`course-description`；舊模板缺少節點時安全略過。

- [ ] 寫 Node DOM 行為測試：standalone 無章節卡、有置中單欄標記；EverCam 有／無章節維持舊顯示；空 metadata 隱藏。
- [ ] 測試 title／description／字幕的 `<script>`、引號與換行只經 textContent；同名不同 package ID 偏好隔離、現存有效偏好優先、失效偏好回退預設、off、localStorage throw 仍初始化。
- [ ] 執行 `node --test tests/player/*.test.mjs`，確認新行為 RED，而舊 EverCam 基線仍 PASS。
- [ ] 新模板使用相同控制 DOM 與本機 script，單獨存放；CSS 只以 standalone class 覆蓋版面。字幕 key `vts.subtitle.<packageId>`，EverCam 原 key 不變；不改字幕外觀儲存契約。
- [ ] 修正 metadata、章節高度與字幕初始化分支；保留既有鍵盤、倍速、全螢幕及 PiP 能力偵測。
- [ ] 執行 Node 測試及 Task 3 真實匯出，預期 PASS；瀏覽器實測另列 Task 6，不能由 DOM stub 推導播放成功。

### Task 5: 桌面操作與完成捷徑

**Files:** Create `web_export_dialog.py`, `tests/test_web_export_dialog.py`; modify `SubtitleTranscriber.py`.

**Interfaces:** `WebExportDialog(parent, *, app_version: str, video: Path|None = None, subtitles: tuple[SubtitleSource, ...] = ())`；只從模型／匯出模組匯入，不從主程式匯入。

- [ ] 寫標題 dirty、候選僅提示、未知語言需確認、預設軌被移除、缺檔補選的 controller 測試；assert 不能錯配／無確認即匯出。
- [ ] 寫完成配對測試：一成功、一失敗及帶語言後綴結果，僅成功 MP4+SRT/VTT 有捷徑；TXT／音訊結果無捷徑。
- [ ] 寫背景 worker 關閉／取消／錯誤測試：所有 widget 更新在主執行緒，destroy 後不存取；已發布晚取消仍顯示成功。
- [ ] 執行 `python3 -m unittest discover -s tests -p 'test_web_export_dialog.py' -v`，確認 RED。
- [ ] 實作基本欄位、可展開進階設定、字幕表格、載入包、目標預覽與錯誤摘要；用 queue 與主執行緒 after 輪詢。匯出中停用資料編輯，關閉須取消並等待安全結束。
- [ ] 新增主入口選單「網頁播放器」→原 EverCam 對話框／一般影片；原 EverCam dialog 不重寫。
- [ ] 轉錄 result 成功時記錄 result → file_path 明確 mapping，連同完成資料交付主執行緒；保留 `last_completed_files` 舊 list 契約。禁止用來源 list 與成功 list zip 猜配。
- [ ] 成功後提供 Path.as_uri() 網頁預覽及平台開資料夾；重新載入明示「另存新資料夾，不複製自訂 HTML／JS」。
- [ ] 重跑 GUI/controller 與全部 Python 測試，預期 PASS；實際開視窗測試操作與取消，若桌面鎖定記錄限制，不繞過鎖定。

### Task 6: 跨平台驗證、打包及繁中說明

**Files:** Modify `VideoToSubtitle.spec`, `.github/workflows/security-regression.yml`, `.github/workflows/python-app.yml`, `docs/USER_GUIDE.zh-TW.md`, `README.md`, `website/src/content.mjs`; create `tests/test_web_export_packaging.py`, `docs/testing/standalone-web-export.md`.

- [ ] 先新增打包資源／workflow 測試：新模組、standalone template、既有播放器被包含；新路徑能觸發建置，驗證作業本身不發布。確認新增測試 RED。
- [ ] 實作打包配置和 CI 路徑；必要依賴僅既有 av／Pillow，獨立測試不載入模型。保留既有安全測試 Windows／macOS matrix。
- [ ] 本機執行 `python3 -m unittest discover -s tests -v`、`node --test tests/player/*.test.mjs`、`npm --prefix website test`、`npm --prefix website run build`；逐項記錄 commit／平台／數量／skip。
- [ ] 在 Windows／macOS 執行 Python 測試与打包成品匯出 smoke；需要遠端 push／新增 CI 分支時先請使用者授權，不沿用舊版本 main 發布指示。
- [ ] 實测 Windows Chrome／Edge、macOS Safari／Chrome × file://／HTTP，使用已知 H.264/AAC 短片：播放、跳轉、兩軌字幕/off、全螢幕、localStorage 降級、桌面／窄版與 EverCam 有／無章節回歸。記錄瀏覽器版本，不以 WebKit runner 當作 Safari 實測。
- [ ] 更新繁中手冊的最短匯出流程、欄位限制、codec 警告、另存行為及支援範圍；網站首頁只加快速入口、完整細節連手冊。新增真實 GUI 截圖依既有 provenance 規則，不假造版本。
- [ ] 重跑文件／網站測試與 build；記錄未完成平台項目，未取得證據不得寫「跨平台全通過」。
- [ ] 整體 diff 審閱與回歸完成後交付；不自動 commit、push、改版本或 Release。另由使用者決定整合與發布。

## Self-review

- 規格 3–4 → Task 2、5；規格 5–6 → Task 3、4；規格 7 → Task 2、3、5；規格 8 → Task 1、3；規格 9–10 → 全部任務及 Task 6。
- Review Focus 五項均有具名測試步驟；介面與清單 path 欄位由模型統一定義。
- 既有 EverCam 解析、部署、章節與偏好相容性均有回歸要求；不擴張為辨識引擎重構。
- 執行計畫尚待使用者審閱；本文件不是測試成功或功能已完成的聲明。
