import { assetPath, routeFor } from './paths.mjs';
import { escapeHtml } from './layout.mjs';

export const content = {
  eyebrow: 'Windows 與 macOS 的本地語音轉字幕工具',
  heroTitle: '影片留在電腦，<em>字幕安心生成。</em>',
  heroText: '加入影音、選擇模型，便能在自己的電腦產生字幕。完成後直接校對時間軸與文字，不必把教材上傳到雲端。',
  steps: [
    ['01', '加入影音', '拖曳單一檔案、整批影音或 EverCam 課程資料夾。'],
    ['02', '選擇模型與輸出', '依電腦效能選擇模型，再指定 SRT、VTT、TXT、TSV 或 JSON。'],
    ['03', '產生並校對', '開始批次轉錄，完成後在內建編輯器同步檢查影片與字幕。']
  ],
  features: [
    ['本機執行', '影音只在自己的電腦處理；下載好模型後可離線轉錄。'],
    ['多檔案批次', '一次加入多段影片或音訊，自動依序產生字幕。'],
    ['提示與熱詞', '加入講題背景、專有名詞與人名，協助改善輸出內容。'],
    ['字幕校對', '一邊播放影音，一邊調整文字、時間軸、分割與合併。'],
    ['模型管理', '查看下載狀態、預先下載、變更儲存磁碟或清除快取。'],
    ['EverCam 整合', '辨識既有課程資料夾，產生字幕並升級為現代播放器。']
  ]
};

export function renderHome() {
  const latest = 'https://github.com/kaoshou/Video-to-Subtitle/releases/latest';
  const guide = routeFor('guide');
  const steps = content.steps.map(([number, title, text]) => `<li class="step-card"><span>${escapeHtml(number)}</span><h3>${escapeHtml(title)}</h3><p>${escapeHtml(text)}</p></li>`).join('');
  const features = content.features.map(([title, text]) => `<li class="feature-card"><h3>${escapeHtml(title)}</h3><p>${escapeHtml(text)}</p></li>`).join('');
  return `<section class="hero"><div class="container hero-grid"><div class="hero-copy"><p class="eyebrow">${escapeHtml(content.eyebrow)}</p><h1>${content.heroTitle}</h1><p class="hero-text">${escapeHtml(content.heroText)}</p><div class="hero-actions"><a class="button button-primary" href="${latest}">下載最新版 ↗</a><a class="button button-secondary" href="${guide}">閱讀完整手冊 →</a></div><p class="hero-meta">開放原始碼 · 免費使用 · 本機轉錄</p></div><figure class="hero-visual"><img src="${assetPath('screenshot_main.png')}" alt="Video to Subtitle 主畫面，顯示檔案清單、模型、運算單元與輸出設定"><figcaption>主操作介面示意</figcaption></figure></div></section>
<section class="section quickstart"><div class="container"><div class="section-intro"><p class="section-kicker">01 / 快速上手</p><h2>三步完成第一份字幕。</h2></div><ol class="step-grid">${steps}</ol><a class="text-link" href="${guide}">查看逐步操作與模型建議 →</a></div></section>
<section class="section features"><div class="container"><div class="section-intro"><p class="section-kicker">02 / 主要功能</p><h2>從轉錄到校對，都在同一個工具。</h2></div><ul class="feature-grid">${features}</ul></div></section>
<section class="section previews"><div class="container"><div class="section-intro"><p class="section-kicker">03 / 真實介面</p><h2>轉錄、校對、模型管理，一目了然。</h2></div><div class="screenshot-grid"><figure class="screenshot-card"><img src="${assetPath('screenshot_main.png')}" alt="Video to Subtitle 主操作介面" loading="lazy"><figcaption>主操作介面</figcaption></figure><figure class="screenshot-card"><img src="${assetPath('screenshot_editor.png')}" alt="字幕校對器與影音同步播放器" loading="lazy"><figcaption>字幕校對器與影音同步播放器</figcaption></figure><figure class="screenshot-card"><img src="${assetPath('screenshot_models.png')}" alt="Whisper 模型快取與儲存管理視窗" loading="lazy"><figcaption>模型快取與儲存管理</figcaption></figure></div></div></section>
<section class="section platforms"><div class="container"><div class="section-intro"><p class="section-kicker">04 / 平台</p><h2>Windows 與 macOS 都能使用。</h2></div><div class="platform-grid"><article><h3>Windows</h3><p>下載單一 VideoToSubtitle.exe；可使用 CPU，具備相容 NVIDIA 環境時也可選 CUDA。</p></article><article><h3>macOS</h3><p>下載 VideoToSubtitle.dmg；Apple Silicon 可使用 MLX。發行版不需另外安裝 Python 或 FFmpeg。</p></article></div></div></section>
<section class="section privacy"><div class="container privacy-inner"><div><p class="section-kicker">05 / 隱私</p><h2>影音不必離開你的電腦。</h2><p>模型下載完成後即可離線轉錄。自動字幕仍可能誤判，發布前請使用內建校對器核對內容。</p></div><span class="privacy-mark" aria-hidden="true">LOCAL</span></div></section>
<section class="section final-cta"><div class="container final-cta-inner"><div><p class="section-kicker">06 / 完整手冊</p><h2>需要更多設定與排解資訊？</h2><p>從安裝、模型與進階選項，到字幕校對與 EverCam 轉換，都整理在完整手冊中。</p></div><a class="button button-primary" href="${guide}">閱讀完整手冊 →</a></div></section>`;
}
