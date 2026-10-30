# 版本介紹撰寫規範

README 更新摘要、GitHub Release 介紹與官方網站的版本重點，統一以繁體中文說明使用者看得到的功能變化。

- 以「新增」「改善」「修正」整理本次變更，說明操作方式及使用者效益。
- 版本正文放在 `docs/releases/v<版本>.md`；GitHub Release 使用這份正文，不另附自動產生的提交摘要。
- 保持精簡，附上對應平台的下載檔名與完整手冊連結。
- 建置紀錄、測試進度、待辦、驗證矩陣等工程資訊留在 Actions 或開發紀錄，不混入版本介紹。
- 必要的系統需求、使用限制、資料備份及安全提醒放在完整手冊的對應章節；不以沒有依據的相容性或認證宣稱取代說明。
- 更新歷史 Release 時只調整介紹文字，保留原標籤、發布日期及下載成品。
- 自 v2.9.1 起每次 Release 僅提供三個成品：`VideoToSubtitle_v<版本>_macOS_arm64.dmg`、`VideoToSubtitle_v<版本>_Windows_x64_Portable.zip`、`VideoToSubtitle_v<版本>_Windows_x64_Setup.exe`。ZIP 包含原本獨立的 `VideoToSubtitle.exe`；安裝程式不再提供重複別名。
- `scripts/package_release.py` 在原生建置及驗證後整理 `dist/release`，檢查來源、版本與建置主機架構；正式發布只取該處三個對應平台成品。
- README 下載連結指向 `releases/latest`。官網三個下載按鈕初始也指向該頁，再透過 GitHub 最新正式 Release API 取得相符的平台檔名與下載網址，不寫死版本。API 不可用或檔案不存在時仍保留最新 Release 頁面入口；不以重複上傳固定檔名實現最新版連結。
