# 一般影片網頁匯出：v2.7.9 驗證紀錄

日期：2026-10-08。基準：618d2e1；v2.7.9 發布驗證。使用者已授權測試通過後推送與發布；跨平台結果以本版本 GitHub Actions 紀錄為準。

## 本次發布檢查

- 本機 Python 3.13：76 項測試，72 通過；2 項 Windows 專用與 2 項原生 GUI 測試略過。
- 本機 Python 3.12／Tk 9／CustomTkinter 6：另行啟用 `VTS_RUN_GUI_TESTS=1`，兩項真實介面整合測試皆通過，涵蓋缺字幕後恢復、進階欄位、自動配對、按鈕匯出與重新載入；沒有使用假控制項。
- 播放器 4 項及網站 13 項測試通過；網站建置成功。修正手冊連結，舊截圖仍明確標示其實際 v2.7.8 來源，截圖中繼資料檢查保留。
- CI 已加入 Windows／macOS 原生介面測試，以及完整執行檔 `--test-web-export` 合成影片匯出／重讀驗證。發布工作必須等待跨平台建置及安全測試通過。
- 首次 Windows CI 抓到 handle rename 路徑缺少 NUL 結尾，造成回報完成卻未輸出至預期名稱。補足結尾後，Windows 的 GUI 匯出、資料夾碰撞、分塊複製、取消與合成影片 smoke 已通過；另修正測試讀取 UTF-8 HTML／JS 時誤用系統 cp1252 的問題。初次失敗紀錄：[37720674613](https://github.com/kaoshou/Video-to-Subtitle/actions/runs/37720674613)；修正驗證：[37720877757](https://github.com/kaoshou/Video-to-Subtitle/actions/runs/37720877757)。
- 最終 [跨平台回歸 37721322035](https://github.com/kaoshou/Video-to-Subtitle/actions/runs/37721322035) 全綠：Windows 與 macOS 各執行 76 項，74 通過、2 項僅適用另一平台的測試略過；兩平台的真實 GUI 操作均通過。Windows junction 與 PowerShell 安全測試亦通過。播放器 4 項、網站 13 項通過。

## 已取得的本機證據

- 2026-10-08，macOS、Python 3.13：介面美化與流程狀態改版後執行 74 項測試，72 通過、2 項 Windows 專用測試略過，不計入 Windows 平台驗證成功。
- PyAV 19.0.0／Pillow 12.3.0：真實合成 H.264 MP4 探測、完整複製、字幕解析、封面重新編碼、載入／搬移／另存測試。
- Node 22.16.0：`node --test tests/player/*.test.mjs`，4 項通過（包含多組偏好案例）。jsdom 為 DOM 測試，不是影片引擎。
- 網站原有 13 項測試通過，網站 build 成功。
- `py_compile` 主程式與新 GUI 成功；這不等於視窗操作已驗收。
- Codex 內建瀏覽器、本機 HTTP：實際播放 state `paused: false`、時間推進；切換英文並跳轉至 0.01 秒時，字幕為 `Standalone subtitle test`；關閉字幕後重載仍關閉。metadata 與無章節單欄已視覺檢查。
- 實際瀏覽器發現停用 TextTrack.cues 可為 null，已以 RED→GREEN 修正初始化中斷；新舊模式 DOM 測試都覆蓋。
- 獨立審查的兩項 Important 已重現並修正：自動預設不得寫入觀眾偏好；清理競態改為保留非空暫存，不按可能被替換的檔名刪除。
- 2026-10-08 的新規則取代先前「唯一候選才加入」：12 項純表單測試涵蓋同檔名／語系自動配對、多語一起加入、同語系 VTT 優先、無語系使用 und、重新掃描、手動設定保留、輸出碰撞及符號連結排除。新增真實 MP4＋無語系 SRT 自動配對→匯出→重新載入測試，驗證不用設定語言且播放器標籤為「預設字幕」。
- 本次獨立 UI 審查發現 ComboBox 的暫態刪字會清掉預設字幕；已改為在選取完成、失去焦點或提交時讀取完整值，並以 RED→GREEN 測試修正。
- Python 3.12／Tk 9／CustomTkinter 6 的新視窗程序可進入 Tk 主事件迴圈（程序堆疊確認），不等於畫面與操作驗收。
- 2026-10-08：新增就緒條件測試（沒有影片／字幕、探測失敗、重複或無效語言、失效預設不可建立；工作中不可重複提交），並修正手動輸入預設字幕後的按鈕狀態更新。獨立審查未發現阻擋問題；提出的輸入更新問題已以失敗→通過測試修正。
- 以 PyInstaller 6.22.3、Python 3.12.14 製作僅載入真實 WebExportDialog 的本機 macOS arm64 預覽包成功；不是完整主程式 Release，也不代表已執行或視覺驗收。最後輸出位於 `/private/tmp/vts-autosubs.Qsk5hY/dist-final/Subtitle Web Preview.app`。

## 發布成品門檻

正式 [Build Cross-Platform Executables](https://github.com/kaoshou/Video-to-Subtitle/actions/workflows/python-app.yml) 在 main 上重新執行完整驗證，Release 工作必須同時等候下列工作成功：

- Windows EXE 與 macOS App／DMG 完整建置與上傳。
- 兩平台使用打包成品執行 `--test-web-export`，實際產生合成 MP4、兩軌字幕、匯出並重新讀取播放器包，驗證內含資源。
- macOS 隔離主機 MLX 模組後的 Metal 運算與音訊解碼模組 smoke test。
- 兩平台 Python／原生介面／安全回歸與播放器／網站測試。

預檢成品建置見 [37721096262](https://github.com/kaoshou/Video-to-Subtitle/actions/runs/37721096262)。該次 workflow 的測試收尾錯誤另以後續全綠回歸修正；不能把該 workflow 整體列為成功。兩者之間只改動測試的 Tk 回呼清理，產品程式碼相同。以 main 正式 workflow 的最終結果確認公開成品。

## 尚未涵蓋的情境

- Windows Chrome／Edge、macOS Safari／Chrome × file://／HTTP 的播放、字幕、跳轉、全螢幕及窄版實測。
- 原生新對話框完整畫面檢查與新截圖：先前桌面工具回報 Mac 鎖定；使用者已暫停截圖作業。不以示意圖代替驗收證據。真實控制項操作已有上述自動測試證據，與視覺驗收分開記錄。
- 更完整的跨平台競態與真實 GUI 生命週期測試。
- 內建瀏覽器的 file:// 導覽被安全政策拒絕，未嘗試繞過；全螢幕按鈕操作後未進入全螢幕，不能計為成功。
- 審查列為 Minor 的待辦：GUI 已新增探測時長與影片大小，尚未顯示包含資源的匯出總大小；底層仍執行磁碟空間驗證。

`scripts/smoke_web_export.py <空白測試目錄>` 可產生不含私人資料的短片、兩軌字幕及實際輸出包，供後續瀏覽器驗證。程式不下載模型、不上傳資料、不覆寫既有輸出包。

先在候選分支執行功能回歸，不觸發 Release；通過後推送 main，由正式流程再次驗證並發布。完整瀏覽器／編碼／硬體矩陣仍未窮盡，不以自動測試宣稱所有使用情境均已驗收。
