import { assetPath, routeFor } from './paths.mjs';
import { escapeHtml } from './layout.mjs';

const latest = 'https://github.com/kaoshou/Video-to-Subtitle/releases/latest';
const guide = routeFor('guide');
const chapter = id => guide + '#' + id;

export const content = {
  eyebrow: 'Video to Subtitle · 本地語音轉字幕工具',
  heroText: '把錄好的課程變成可校對的字幕，再整理成自己的網頁教材。轉錄在你的電腦完成，影音不必上傳。',
  steps: [
    { title: '準備程式與模型', text: '開啟下載好的程式，在「模型儲存管理」預先下載模型。先用一段 30–60 秒短片練習。', check: '程式能開啟，模型顯示已下載', link: '模型選擇指南', anchor: '模型選擇指南', image: 'screenshot_models.png', alt: '模型管理畫面；正式操作時請確認模型下載完成' },
    { title: '加入影片，選 SRT', text: '拖入短片，選擇已下載的模型。不確定運算單元時先選 CPU，輸出格式先用 SRT。', check: '清單中有影片，輸出格式是 SRT', link: '第一次轉錄', anchor: '第一次轉錄', image: 'screenshot_main.png', alt: '主畫面的影片清單、模型與輸出設定' },
    { title: '開始轉錄，找到字幕', text: '按「開始轉錄」。完成後選「開啟目錄」，字幕預設就在原影片旁，使用相同主檔名。', check: '找得到與影片同名的 .srt 檔', link: '輸出格式說明', anchor: '輸出格式', image: 'screenshot_main.png', alt: '主畫面的開始轉錄按鈕與進度區' },
    { title: '邊播放，邊校對', text: '開啟「字幕校對」，核對人名、專有名詞與出現時間。編輯前先備份原字幕，再儲存修改。', check: '儲存後重新開啟，修改有保留', link: '字幕校對操作', anchor: '字幕校對器', image: 'screenshot_editor.png', alt: '字幕校對器的文字清單與影片同步預覽' }
  ],
  questions: [
    ['沒有顯示卡也能使用嗎？', '可以，選 CPU 即可轉錄，不需要獨立顯示卡。相容的 NVIDIA 環境可用 CUDA，Apple Silicon Mac 可用 MLX 加速；速度依硬體、模型與影音長度而異。', '運算單元'],
    ['第一次為什麼要下載模型？', '模型是用來辨識聲音的資料。第一次使用或切換到尚未下載的模型時，需要網路與足夠磁碟空間；先下載並試轉一段短片，再帶到離線環境使用。', '模型儲存管理'],
    ['產生的字幕存在哪裡？', '預設儲存在原影音的同一個資料夾。例如「課程.mp4」會搭配「課程.srt」。轉錄完成後，可按「開啟目錄」查看結果。', '第一次轉錄'],
    ['影片會被上傳到網路嗎？', '桌面程式的轉錄在本機執行，不會把影音送到雲端辨識。下載模型與檢查更新需要網路；建立字幕網頁也只是產生本機檔案，不會自動發布。', '離線使用'],
    ['已經有 SRT，還需要重新轉錄嗎？', '不需要。可以直接用「編輯現有字幕」校對；要製作網頁，將 MP4 與同主檔名的 SRT／VTT 放在同一資料夾，再開啟一般影片＋字幕工具。', '一般-mp4-字幕匯出網頁']
  ]
};

// Original line icons made from simple geometry. No external assets or requests.
function icon(name) {
  const paths = {
    video: '<rect x="3" y="4" width="18" height="16" rx="3"/><path d="m10 8 6 4-6 4z"/>',
    edit: '<path d="M14 5 19 10M4 20l5-1L21 7a2.8 2.8 0 0 0-4-4L5 15zM13 20h8"/>',
    web: '<rect x="2" y="3" width="20" height="18" rx="3"/><path d="M2 8h20M6 5.5h.1M9 5.5h.1M6 12h5v5H6zM14 12h4M14 16h4"/>',
    check: '<path d="m5 12 4 4L19 6"/>',
    arrow: '<path d="M4 12h16m-6-6 6 6-6 6"/>'
  };
  return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + paths[name] + '</svg>';
}

function imageLink(file, alt, className = '', eager = false) {
  return '<a class="image-zoom ' + className + '" href="' + assetPath(file) + '" aria-label="放大查看：' + escapeHtml(alt) + '"><img src="' + assetPath(file) + '" alt="' + escapeHtml(alt) + '"' + (eager ? ' fetchpriority="high"' : ' loading="lazy"') + '></a>';
}

export function renderHome() {
  const tasks = [
    ['video', '我有影片，想產生字幕', '從短片開始，完成第一份 SRT。', '#quickstart'],
    ['edit', '我已有字幕，想修改', '直接開啟字幕，不必重新轉錄。', chapter('字幕校對器')],
    ['web', '我想製作字幕網頁', '一般 MP4 或 EverCam，都有對應流程。', chapter('一般-mp4-字幕匯出網頁')]
  ];
  const steps = content.steps.map((step, index) => '<li class="home-step"><div class="step-heading"><span class="step-number">0' + (index + 1) + '</span><h3>' + escapeHtml(step.title) + '</h3></div><div class="step-detail">' + imageLink(step.image, step.alt, 'step-thumbnail') + '<p>' + escapeHtml(step.text) + '</p></div><p class="step-done">' + icon('check') + '<span><strong>完成確認</strong>' + escapeHtml(step.check) + '</span></p><a class="home-inline-link" href="' + chapter(step.anchor) + '">' + escapeHtml(step.link) + ' ' + icon('arrow') + '</a></li>').join('');
  const questions = content.questions.map(([question, answer, anchor]) => '<details class="home-question"><summary>' + escapeHtml(question) + '<span aria-hidden="true">＋</span></summary><div><p>' + escapeHtml(answer) + '</p><a href="' + chapter(anchor) + '">查看手冊說明 →</a></div></details>').join('');
  return '<div class="home-page">' +
'<section class="home-hero"><div class="container home-hero-grid">' +
  '<div class="home-hero-copy"><p class="eyebrow">' + escapeHtml(content.eyebrow) + '</p><h1><span>影片留在電腦，</span><em>字幕安心生成。</em></h1><p class="home-lead">' + escapeHtml(content.heroText) + '</p>' +
  '<div class="hero-actions"><a class="button button-primary" href="' + latest + '/download/VideoToSubtitle.exe">下載 Windows 版 <span aria-hidden="true">↓</span></a><a class="button button-secondary" href="' + latest + '/download/VideoToSubtitle.dmg">下載 macOS 版 <span aria-hidden="true">↓</span></a></div>' +
  '<div class="home-hero-links"><a href="#quickstart">看快速上手 →</a><a href="' + latest + '">版本資訊與其他下載</a></div><ul class="home-trust" aria-label="工具特色"><li>免費・開放原始碼</li><li>本機轉錄</li><li>無顯卡也能用</li></ul></div>' +
  '<figure class="home-hero-visual"><div class="preview-label"><span>你的字幕工作台</span><span>DESKTOP APP</span></div>' + imageLink('screenshot_main.png', 'Video to Subtitle 主畫面，顯示影片清單與轉錄設定', '', true) + '<figcaption><span>v2.7.12 主操作介面 · Linux 示範</span><span>點擊圖片放大 ↗</span></figcaption></figure>' +
'</div><div class="container home-output-line"><span class="output-label">從一段影片開始</span><span>影片／音訊</span>' + icon('arrow') + '<span>字幕初稿</span>' + icon('arrow') + '<span>人工校對</span>' + icon('arrow') + '<span>字幕檔／網頁教材</span></div></section>' +

'<section class="home-tasks container" aria-labelledby="tasks-title"><div class="home-section-head"><p class="section-kicker">START HERE</p><h2 id="tasks-title">你現在想做什麼？</h2></div><nav class="home-task-list" aria-label="依任務開始">' +
tasks.map(([name, title, text, href]) => '<a class="home-task" href="' + href + '"><span class="task-icon">' + icon(name) + '</span><span><strong>' + title + '</strong><small>' + text + '</small></span><span class="task-arrow">' + icon('arrow') + '</span></a>').join('') + '</nav></section>' +

'<section class="home-quickstart" id="quickstart" aria-labelledby="quickstart-title"><div class="container home-start-layout"><div class="home-start-intro"><p class="section-kicker">YOUR FIRST SUBTITLE</p><h2 id="quickstart-title">第一份字幕，<br>從這四步開始。</h2><p>先練一段短片。<br>其他選項，等需要時再調整。</p><div class="home-preflight"><strong>開始前準備</strong><p>一段 30–60 秒、聲音清楚的影片，以及可下載模型的網路。</p><p>第一次需要下載模型；轉錄時間依電腦效能而異。</p></div><a class="home-inline-link" href="' + chapter('下載與系統需求') + '">安裝與系統需求 ' + icon('arrow') + '</a></div><ol class="home-step-grid">' + steps + '</ol></div></section>' +

'<section class="home-capabilities container" aria-labelledby="features-title"><div class="home-section-head"><p class="section-kicker">ONE WORKFLOW</p><h2 id="features-title">不只產生文字，<br>也讓教材準備得更完整。</h2><p>製作字幕、仔細校對，再選擇適合的分享方式。</p></div><div class="home-feature-grid">' +
'<article class="home-feature"><span class="feature-index">01 / TRANSCRIBE</span><h3>製作字幕</h3><p>多檔案批次轉錄，搭配講題背景與專有名詞提示，整理出可以繼續編輯的初稿。</p><ul><li>影片與音訊都能處理</li><li>SRT、VTT 等多種格式</li><li>本機執行，模型可預先下載</li></ul><a class="home-inline-link" href="' + chapter('多檔案批次處理') + '">認識轉錄功能 ' + icon('arrow') + '</a></article>' +
'<article class="home-feature"><span class="feature-index">02 / REVIEW</span><h3>校對字幕</h3><p>播放影片，同時核對每一句。修改人名、調整時間，讓字幕跟得上原音。</p><ul><li>點選字幕，同步跳轉</li><li>修改文字與起訖時間</li><li>分割、合併與播放控制</li></ul><a class="home-inline-link" href="' + chapter('字幕校對器') + '">認識校對器 ' + icon('arrow') + '</a></article>' +
'<article class="home-feature"><span class="feature-index">03 / PRESENT</span><h3>整理網頁教材</h3><p>已有 MP4 和字幕，就能製作播放器網頁；EverCam 課程則有專用轉換流程。</p><ul><li>自動配對同名／語系字幕</li><li>可調整標題與輸出位置</li><li>匯出資料夾，自行安排分享</li></ul><div class="feature-links"><a href="' + chapter('一般-mp4-字幕匯出網頁') + '">一般 MP4 →</a><a href="' + chapter('evercam-數位課程') + '">EverCam 課程 →</a></div></article></div>' +
'<div class="home-editor-preview"><figure>' + imageLink('screenshot_editor.png', '字幕校對器與影音同步播放器') + '<figcaption>v2.7.12 字幕校對器 · 點擊圖片放大</figcaption></figure><div><p class="section-kicker">THE HUMAN TOUCH</p><h3>AI 先打底，<br>你把關最後一句。</h3><p>自動字幕仍可能誤判。發布前，請特別核對人名、數字、專有名詞與字幕時間。</p><a class="home-inline-link" href="' + chapter('編輯時間與文字') + '">看看如何校對 ' + icon('arrow') + '</a></div></div>' +
'<p class="home-capture-note">以下為 v2.7.12 在 Linux 雲端虛擬顯示環境的真實介面截圖，使用示範素材：本頁主畫面、步驟縮圖與校對器畫面。Windows／macOS 的字型與視窗外觀可能略有差異。</p></section>' +

'<section class="home-faq" id="faq"><div class="container home-faq-layout"><div class="home-section-head"><p class="section-kicker">GOOD TO KNOW</p><h2>開始前，<br>你可能想問。</h2><p>先解決常見疑問。<br>完整設定與排解方式，留在手冊。</p><a class="home-inline-link" href="' + chapter('常見問題') + '">更多疑難排解 ' + icon('arrow') + '</a></div><div class="home-questions">' + questions + '</div></div></section>' +

'<section class="home-closing"><div class="container"><div><p class="section-kicker">READY WHEN YOU ARE</p><h2>下一段教材，<br>讓字幕一起準備好。</h2><p>Windows 與 macOS 發行版，不需另裝 Python 或 FFmpeg。<br>第一次下載模型後，先用短片確認操作。</p></div><div class="home-closing-actions"><a class="button button-primary" href="' + latest + '">下載最新版 ↗</a><a class="home-inline-link" href="' + guide + '">閱讀完整手冊 ' + icon('arrow') + '</a></div></div></section></div>';
}
