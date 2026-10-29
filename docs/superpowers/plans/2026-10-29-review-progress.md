# 字幕校對提醒與分階段進度 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改動字幕輸出的前提下提供編輯器校對提醒與可信的階段進度。

**Architecture:** 小型獨立診斷模組負責有限數值判斷、時間對應及重複檢查；轉錄器以可選回呼傳送診斷與階段，GUI 在主執行緒更新。診斷僅保留本次工作階段，失敗批次嘗試的資料不發布。

**Tech Stack:** 現有 Python、unittest、CustomTkinter／ttk、faster-whisper、mlx-whisper；不新增依賴。

**Spec:** `docs/superpowers/specs/2026-10-29-review-progress.md`

## Global Constraints

- 不改動字幕文字與格式、安全發布及既有標準／批次路徑。
- 不升版、不推送、不發布；課程術語範本僅研究。
- 所有 Tk 更新在主執行緒；未知進度不捏造百分比。
- 模型信心資料不持久化；修改字幕後不得錯用舊資料。

## Review Focus

- 分割／合併／原始文字重載後提醒仍指向正確字幕。
- 批次失敗重試、取消、回呼失敗不洩漏錯誤診斷或影響輸出。
- MLX 沒有逐段進度或信心時誠實顯示，不阻擋原生推論。
- 舊字幕、TXT 及無診斷輸出仍可正常開啟／儲存。
- 計時器在關閉、取消或立即開始下一次工作時不更新錯誤工作。

---

### Task 1: 純診斷與階段資料

**Files:** Create `subtitle_review.py`, `tests/test_subtitle_review.py`.

**Interfaces:** `collect_segment_review(segment) -> list[dict]` 產生 start/end/text/reasons；`review_cues(cues, evidence=()) -> dict[int, list[str]]` 以最終字幕零起算索引傳回原因。只對重疊時間且文字未改變的內容沿用信心提醒。

- [ ] 先寫測試：低信心、正常與缺失資訊、NaN、重複、時間反轉、時間重疊、切段對應、文字修改與無診斷；執行確認新增行為缺失。
- [ ] 實作以上函式，限制輸入與非有限數值；不對停頓標記。
- [ ] 執行 `python -m unittest discover -s tests -p test_subtitle_review.py`，再執行完整測試；確認通過後提交本地變更。

### Task 2: 轉錄器事件與安全診斷交付

**Files:** Modify `transcriber.py`; Create `tests/test_transcription_events.py`.

**Interfaces:** `run(..., review_callback=None, stage_callback=None)`；成功發布後 `review_callback(output_path, evidence)`；`stage_callback(stage, detail='')`，階段代碼由測試固定。新增參數在尾端且可選，保留原回傳值及既有進度回呼。

- [ ] 先以替代辨識器測試標準成功、批次重試僅交付成功資料、取消不交付、MLX 缺失 metadata、回呼例外不破壞輸出，確認缺失行為失敗。
- [ ] 在真正工作的邊界發送事件，擷取原始辨識段診斷；每次重試獨立收集；安全發布後才交付診斷與完成事件。
- [ ] 執行新測試與完整測試；確認字幕內容、時間軸及取消／安全發布測試未改變，提交本地變更。

### Task 3: 編輯器提醒與主視窗階段計時

**Files:** Modify `SubtitleTranscriber.py`; Create `tests/test_review_progress_gui.py`.

**Interfaces:** `SubtitleEditorWindow(..., review_evidence=None)`；主視窗依完整輸出路徑保留診斷並傳至既有校對入口。現有搜尋與「僅待校對」以交集篩選；選取後顯示原因，不新增大型對話框。

- [ ] 先寫 GUI 測試：摘要／篩選、編輯文字／時間、分割合併、原始文字重載、舊字幕／TXT、假時鐘下階段耗時、取消／關閉／新工作使舊計時失效；確認失敗。
- [ ] 實作小型提醒區與非顏色單一辨識的標記；接入新回呼，將階段狀態與一般日誌分開；使用工作代碼與 after 計時避免舊事件污染。
- [ ] 執行 `VTS_RUN_GUI_TESTS=1 python -m unittest discover -s tests`、網站既有測試與建置、`git diff --check`；人工檢視編輯器與主視窗畫面，提交本地變更。

### Task 4: 說明、研究與最終審查

**Files:** Modify `docs/USER_GUIDE.zh-TW.md`; Create `docs/development/COURSE_TERMINOLOGY_RESEARCH.zh-TW.md`.

- [ ] 說明提醒非錯誤判定、工作階段限制與各階段意義；研究報告連結官方來源並區別三種後端，不實作範本。
- [ ] 依 executing-plans 要求進行一次獨立整體審查；重要問題以新增失敗測試後修正，重跑完整測試。
- [ ] 提供本機測試結果與實際畫面，保留本地分支等待使用者測試；不推送／升版／發布。
