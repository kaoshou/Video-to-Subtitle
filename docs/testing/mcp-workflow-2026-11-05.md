# MCP 工作流程增強：本機驗證紀錄

日期：2026-11-05。分支：`codex/optional-mcp-design`。範圍：預檢、階段進度、接續查詢、翻譯品質與術語檢查、完成摘要。沒有推送、合併、改版本、建置 Windows 包或發布 Release。

## 結果

| 驗證 | 結果 |
| --- | --- |
| `/private/tmp/vts-mcp-validation-env/bin/python -m unittest discover -s tests` | 607 項：501 通過、106 依平台／原生介面條件略過；exit 0。 |
| `node --test tests/player/standalone.test.mjs` | 43／43 通過；exit 0。 |
| `python scripts/test_mcp_gui_isolated.py`（上述 Python 環境） | 原生介面每項各自執行一次，24／24 通過；沒有自動重試或隱藏失敗。 |
| 真實 STDIO 與官方 MCP SDK | 一般及 CP1252 主控台環境，握手、列工具、匯入雙語字幕、匯出與授權拒絕測試通過。 |
| 檔案與字幕 | 合成影音測試覆蓋同名輸出保留、取消、來源變更、權限撤回及三種播放器。原時間軸保留。 |

模型推論以受控引擎測試事件、模型回報與校對證據傳遞；不是新的 CPU／CUDA／MLX 效能或語音品質評測。沒有下載、刪除或清空使用者模型，也沒有把使用者影音上傳到遠端。

## 測試過程修正

- 全套初跑有三項失敗：`test_source_stdio_smoke_imports_two_languages_and_exports_player`、`test_stdio_unicode_is_utf8_even_with_cp1252_host_console`、`test_official_client_subprocess_handshake_list_call_and_shared_broker`。原因為舊 smoke 固定要求恰有 13 個工具；新增三個唯讀工具後，改驗證必需工具與禁止設定工具的邊界，重跑通過。
- 原生介面同程序整批測試曾以 `alloc: invalid block`／Tcl shared-object 錯誤終止；修改前提交 `4fb618d` 的隔離暫存副本也重現。原本測試紀錄已指出 Tk 9 反覆建立、銷毀 interpreter 的間歇問題。此處新增獨立程序測試方式，沒有宣稱修正原生 Tk 銷毀問題。正常單次開啟／關閉等行為已由各測試覆蓋；不推論所有實體環境皆安全。
- 舊翻譯字幕不得沿用原語言的 ASR 校對結果，新增測試先失敗，再修正為未檢查。
- 最後檢查發現 OpenCam／EverCam 摘要只列新加入字幕。兩種保留日文字幕測試先失敗，再改以完成的私人播放器資料計算實際語言與段數，保留字幕無檢查紀錄時列為未檢查。

## 設計取捨

1. 沿用唯讀工具與 AI 指引，不新增每次必答的確認權杖。AI 客戶端可能未遵循說明，但伺服器仍執行模型與安全檢查。
2. 進度依階段，不編造整體百分比或 ETA；代價是沒有單一完成時間預估。
3. 保留啟動回應只有 `job_id` 的相容格式，計畫放在預檢及已授權的 `get_job`；代價是查保存計畫需一次查詢。
4. 回歸測試集中 `test_mcp_workflow.py` 並沿用 `test_mcp_gui.py`，不新增計畫中原本不存在的測試檔名；代價是測試檔名粒度較粗。
5. ASR 只傳校對段數與原因，不把整份辨識證據送進 IPC；代價是 MCP 不提供 ASR 逐段提醒位置。翻譯提醒可分頁查位置。
6. 結構化術語採有上限的 source／target 配對清單，以沿用嚴格 schema 並驗證衝突；代價是 JSON 鍵數較多。
7. 原生 GUI 以獨立程序測試，不為測試改寫產品的 Tk 生命週期；代價是測試較慢，原先同程序多 interpreter 的間歇問題仍保留為已知限制。

## 審閱

依使用者選定的直接執行方式，由作者另做一輪契約、授權／版本、取消、管線訊息、分頁上限、舊資料、摘要來源及播放器檢查；沒有額外開子代理。這是作者自我審閱，不等於獨立審閱或新的正式安全稽核。
