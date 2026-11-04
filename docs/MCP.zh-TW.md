# AI 工具連接（可選 MCP）

MCP 讓支援本機工具的 AI 客戶端操作已授權的影音資料夾：在本機轉錄、讀取字幕、分批翻譯，再建立多語字幕播放器。功能預設關閉；一般轉錄不需要啟用。啟用後背景服務可獨立工作，不必一直開著主視窗。

本工具不要求填入 API key。翻譯由你選用的 AI 客戶端與帳號處理，可能使用訂閱額度、消耗 token 或產生額外費用；免費額度、速率限制與資料政策由該服務決定。一般 ChatGPT／Gemini 網站不會因為寫入本機 MCP 設定就自動連上。

## 啟用與測試

1. 主畫面「開始產生字幕」同一列，按「AI 工具連接」。視窗會讀取既有權限；單純開啟不會啟用或改寫 AI 客戶端設定。
2. 加入必要的影音資料夾，勾選「允許 AI 工具存取指定資料夾」，按「套用權限」。授權包含讀取支援的影音／字幕，以及在影片旁建立新的播放器資料夾，請確認資料夾範圍。
3. 若需要語音轉錄，先在既有模型管理介面下載模型。MCP 發現模型缺少、不完整或無法讀取時會拒絕轉錄，不會代為下載、修復或刪除模型。已有 SRT／VTT 可直接匯入。
4. 按「偵測工具安裝與設定」，選擇 AI 客戶端，再按「設定工具」。確認畫面上的設定路徑、授權範圍、新舊項目與備份提示後，才同意寫入。這不會跳過客戶端自身的信任與工具批准，也不會自動重啟 AI 客戶端。
5. 按「自我測試」檢查本機 STDIO 協定與背景服務。接著在 AI 客戶端依其指引重新載入設定、審閱工具權限，實際要求列出授權資料夾，才能確認該客戶端連線。

「偵測到」、「設定完成」、「本機自我測試通過」和「真實 AI 客戶端連線成功」是不同階段。未知格式、明確不支援的版本、唯讀／管理員管理設定、JSONC 或衝突項目會轉為手動設定，請勿改寫其他工具的設定來繞過限制。

設定視窗可用 Tab／Shift+Tab 巡覽，Enter／Space 啟用按鈕；手動設定文字可選取複製。視窗下方保留套用、測試與關閉操作；「更新工作狀態」會顯示已接受的工作，並可要求合作式取消。

## 客戶端設定方式

下表表示提供的設定介面；不是已測試所有客戶端版本或完成真實帳號連線的保證。實際能力與信任流程仍以客戶端為準。

| 客戶端 | 本工具提供的方式 |
| --- | --- |
| Codex 桌面／CLI／IDE | 本機 `mcp_servers` TOML 項目預覽與同意後套用；保留其他設定與註解。 |
| Claude Code | 使用者層級 `mcpServers` 項目；不改專案信任設定。 |
| Claude Desktop | 「匯出 Claude MCPB」產生新的套件檔，再由使用者於 Desktop 審閱並安裝。需包含獨立啟動器的封裝版。 |
| Gemini CLI、Antigravity、Cursor | 已知 JSON 格式的項目預覽與同意後套用；不確定的舊路徑需手動處理。 |
| VS Code | 先由 VS Code 開啟使用者 MCP 設定，或明確選擇專案 `.vscode/mcp.json`；使用 `servers` 格式。含註解的 JSONC 請手動設定。 |
| GitHub Copilot 獨立設定 | 使用其 `mcpServers` 設定檔；與 VS Code 的使用者設定分開選擇。 |
| OpenCode | `mcp` 下的本機指令陣列；JSONC 或管理設定請手動處理。 |
| Windsurf、其他 MCP 工具 | 手動設定；Windsurf 目前版本相容性仍需使用者核對。 |

官方設定參考：[Codex](https://learn.chatgpt.com/docs/extend/mcp)、[Claude Code](https://code.claude.com/docs/en/mcp)、[Claude Desktop](https://support.claude.com/en/articles/10949351-getting-started-with-local-mcp-servers-on-claude-desktop)、[Gemini CLI](https://geminicli.com/docs/tools/mcp-server/)、[Antigravity](https://antigravity.google/docs/mcp)、[Cursor](https://cursor.com/docs/mcp)、[VS Code／Copilot](https://code.visualstudio.com/docs/agents/reference/mcp-configuration)、[OpenCode](https://opencode.ai/docs/mcp-servers/)。

## 資料如何流動

```text
已授權的本機影音 → 本機模型轉錄 → 字幕文字分批交給 AI
                                     ↓
影片旁的新多語播放器 ← 伺服器保留原時間軸 ← AI 回傳純文字譯文
```

本機模型處理影音；外部 AI 客戶端可能把讀取的字幕、詞彙表與翻譯要求送往雲端。這不是全程離線承諾，請先確認教材、學生資料與機密內容是否適合交給選用的服務。私人狀態目錄有檔案權限保護，但不是加密資料庫。

AI 工具只能使用已授權根目錄、相對位置與伺服器產生的識別碼，不能取得 shell、任意絕對路徑、網址下載、帳號設定或模型管理權限。字幕和詞彙表是待處理資料；即使其中出現「忽略前述規則」等文字，也不能當作操作指令。

設定修改前會備份整份舊設定，可能包含其他伺服器的秘密，請妥善保管私人備份。移除時只移除本工具管理且未被外部修改的項目，保留後來新增的其他設定；不會整份回復舊檔覆蓋新內容。

## 翻譯與播放器流程

可對 AI 提出：「請先列出我授權的課程，匯入指定影片的中文字幕，翻成英文和日文，保留原時間軸，最後輸出這兩種語言的播放器；完成後提醒我人工校對。」先確認 AI 選對檔案與語言，再允許後續工具呼叫。

工具會回傳各自的輸入結構，AI 應依實際 schema 操作：

1. `get_status` 取得根目錄 ID，`list_media` 分頁列出影音與字幕。
2. `start_transcription` 接受轉錄工作後，用 `get_job` 查詢；或用 `import_subtitle` 匯入現有字幕。
3. `read_transcript` 分頁閱讀／搜尋；每種語言用 `prepare_translation` 建立指定來源版本的草稿。
4. 用 `get_translation_batch` 讀取批次，再用 `submit_translation_batch` 回傳相同 cue ID 的純文字。每批最多 50 段、8000 個來源 Unicode 字元；不能由 AI 修改時間軸。
5. 所有批次完成後，對每種語言執行 `finalize_translation`。以明確的已完成 `track_ids` 呼叫 `export_player`，再查詢匯出工作。最多選 32 種語言；要求的語言未完成時不會偷偷省略。若只想先匯出部分語言，請明確指定。

譯文標記為待人工審閱。來源字幕改變會使舊版本失效，需重新匯入／轉錄；不要拿舊 cue ID 拼接新來源。重送完全相同的 `request_id` 與內容會取得原結果，內容不同會衝突。已失敗或中斷的請求可能需要明確使用新的 request ID 重試；不會假裝從模型解碼途中接續。

匯出在原影片旁建立新資料夾；名稱碰撞會加 `-2`、`-3`，不覆寫原影音、字幕或既有播放器。請保留整包影片與網頁檔案。新播放器沿用逐字稿搜尋、點擊跳轉、跟隨播放、語言切換、閱讀設定、HTML／TXT 下載與鍵盤操作；播放器取得焦點時 Space 播放／暫停、方向鍵快退／快轉，輸入欄位保留原本按鍵用途。完整操作見[使用手冊](USER_GUIDE.zh-TW.md#網頁播放器的逐字稿搜尋)。

## 背景工作、停用與運算單元

關閉主視窗、設定視窗或 AI 客戶端，不會取消已接受的工作。按「停用存取」會立即拒絕新的內容存取；可選「完成已接受工作」或「取消已接受工作」。取消是合作式處理，正在執行的原生推論可能需先返回，不會強制終止模型程序。

啟用期間，背景服務在沒有工作與處理中的連線、閒置五分鐘後退出；停用後會在已接受工作完成且連線處理結束時正常退出。模型子程序先結束才釋放共用運算鎖，避免 GUI 與 MCP 同時佔用模型。工作之間可能重新載入已下載模型，不代表再次下載。

CPU、NVIDIA CUDA 與 Apple Silicon MLX 沿用既有核心與硬體限制。GUI／MCP 的 CPU／CUDA 預設啟用批次與自動大小；既有 GUI 數字設定保留。MLX 使用原生路徑，不套用這些批次大小。效能依設備與模型而異，沒有保證加速倍數。

`start_transcription.settings` 保留整數 `batch_size`（2～32），另提供 `batch_mode`：

| 設定 | 行為 |
| --- | --- |
| 未提供 mode 與 size | `batch_mode: "auto"`；模型載入後、實際執行時估算，不在排隊時探測。 |
| 只提供 `batch_size: 8` 等既有整數 | 視為 manual，沿用既有呼叫方式且不讀資源。 |
| `batch_mode: "manual"` | 未給 size 時使用 4；可手動選 2～32，32 屬進階選項。 |
| `batch_mode: "auto"` 加 `batch_size` | 回報 `INVALID_ARGUMENT`；移除 size 或改為 manual。 |
| `batch_acceleration: false` | 使用標準路徑，略過自動資源探測。MLX/MPS 亦略過。 |

自動與 GUI 共用核心：依可用而非總 RAM／VRAM、模型、精度與實體核心保守估算，CPU 最高 8、CUDA 最高 16；資料不明保守選 2，嚴重 RAM 壓力可改用標準。完整預留空間與估算表見[使用指南](USER_GUIDE.zh-TW.md#批次加速試用)。這些數值未經跨硬體基準量測，不保證最快或避免所有 OOM；手動不改精度。OOM 與品質回退沿用安全重試，`get_job.result.batch_decision`（有提供時）回傳 `requested_mode`、`effective_size`（null 表示標準／原生）與有限 `reason` 代碼；自動規劃另附已知安全字串 `rationale` 說明可用資料／壓力／估算原因。回退時更新實際大小與 reason，rationale 保留原自動規劃依據；排隊紀錄保留的是要求的選擇。

若主視窗在首次啟用 MCP 前已載入直接運算的模型，請正常關閉並重新開啟，再啟用；這是釋放程序內原生快取的要求，不會刪除模型。其他工作持有運算鎖時，請等待完成或正常關閉持有模型的 GUI。

## 更新、移除與修復

封裝版使用獨立、固定版本雜湊的 STDIO 啟動器；明確啟用時才複製到私人穩定路徑。客戶端設定不會指向暫時解壓目錄。主應用程式仍是後端；移動免安裝版、刪除或搬移應用程式後，請開啟新的位置，使用「修復啟動檔」，重新套用啟用權限，再檢查客戶端設定與自我測試。缺少內附啟動器時需安裝包含 MCP 的封裝版，不能以系統 Python 冒充獨立 MCPB。

Windows MCP 版安裝程式在更新／解除安裝前以「完成已接受工作」停用存取；仍有背景工作或 GUI 持有模型時會中止維護，請等待或正常關閉 GUI 再試，不會強殺工作。即使維護中止，MCP 仍保持停用；完成後可自行重新啟用。不會刪除模型、結果、使用者設定或私人設定備份。

沒有 MCP 內附檔案的舊版不會被傳入其不支援的維護參數。若啟動器與驗證描述檔只剩其一，安裝程式會拒絕更新／移除，請先還原同版本完整安裝再停用；此時無法保證已成功撤銷授權。兩個辨識檔都被外部刪除時無法與舊版可靠區分，請在可用的主程式中先停用，勿以刪檔代替停用。

macOS 與免安裝版手動替換／刪除前，請先在「AI 工具連接」停用，等待工作完成並正常關閉 GUI。若還要移除 AI 客戶端項目，可先用「移除設定」；已由外部修改的項目請在該客戶端手動移除。保留的啟動器不代表仍有存取權，停用政策會持續阻擋新內容。

## 開發與驗證界線

來源碼啟用 MCP 需另裝可選套件：`python -m pip install "mcp>=1.30,<2" "tomlkit>=0.13,<1"`。一般 GUI 啟動不會匯入 MCP SDK。建置先執行 `pyinstaller MCPLauncher.spec`，再執行 `pyinstaller VideoToSubtitle.spec`；GUI 封裝內含經雜湊驗證的薄型啟動器，不另複製 Whisper／影音／GUI 相依套件。

來源煙霧測試：`python scripts/smoke_mcp.py`。完整封裝可執行主應用程式的 `--test-mcp`，或以腳本的 `--launcher`、`--backend` 指定兩個凍結執行檔；使用合成 MP4／字幕、暫存政策、空的子程序 PATH，完成匯入→兩語翻譯→播放器，不下載模型或修改真實 AI 設定。`--mcp-disable` 與 `--mcp-maintenance` 是可信本機管理入口，不是 AI 工具。

本次已驗證來源協定與 macOS arm64 的獨立啟動器／凍結後端合成流程。該本機建置未包含可用的 MLX 相依套件，是 CPU／MCP 煙霧建置，不代表完整正式版本認證。原生 Windows 安裝、ACL／命名管線、客戶端建立程序時的視窗行為、真實 AI 客戶端與 Claude MCPB 安裝同意、真實 CPU／CUDA／MLX 模型推論均需在相應環境另行驗證。

Windows 啟動器使用保留 STDIO 的 console 執行檔與 `hide-early`，而不是沒有標準輸入輸出的 GUI 執行檔；依 [PyInstaller 說明](https://pyinstaller.org/en/stable/feature-notes.html)，此模式只隱藏自己擁有的主控台。尚未做原生客戶端測試，不能保證所有情況都完全沒有視窗閃爍。
