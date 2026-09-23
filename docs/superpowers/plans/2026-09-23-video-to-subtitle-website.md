# Video to Subtitle Official Website Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立並發布繁體中文 Video to Subtitle 官方網站，提供精簡首頁、依 v2.7.7 核對的完整使用手冊，以及與桌面 Release 隔離的 GitHub Pages 自動部署。

**Architecture:** `website/` 內的小型 Node.js 靜態產生器會把首頁資料與 `docs/USER_GUIDE.zh-TW.md` 轉成兩個靜態路由，再複製既有真實截圖與應用程式圖示。Node 內建測試固定路由、內容、連結、資產與工作流程契約；獨立 GitHub Pages workflow 只發布 `website/dist`，桌面建置 workflow 只在產品來源變更時執行。

**Tech Stack:** Node.js 22、ES modules、`markdown-it` 15.0.2、Node `node:test`、語意化 HTML、原生 CSS、GitHub Pages Actions。

**Spec:** `docs/superpowers/specs/2026-09-23-video-to-subtitle-website-design.md`

## Global Constraints

- 公開網站根路徑固定為 `/Video-to-Subtitle/`，完整手冊固定為 `/Video-to-Subtitle/guide/`。
- 網站全程使用繁體中文，不建立語言選擇頁或英文路由。
- `docs/USER_GUIDE.zh-TW.md` 是完整手冊唯一內容來源；不得另維護一份手寫 HTML 手冊。
- 首頁使用 `app_icon.png`、`screenshot_main.png`、`screenshot_editor.png`、`screenshot_models.png` 四個既有資產，不生成或杜撰產品畫面。
- 所有下載動作連至 `https://github.com/kaoshou/Video-to-Subtitle/releases/latest`，不得硬編版本號或 Release 資產網址。
- 一般發行版使用者不需安裝 Python、FFmpeg 或 `mlx-whisper`；這些只可出現在明確標示的開發者章節。
- 不加入外部字型、分析追蹤、前端框架、自訂網域或第三方託管資源。
- 網站／文件提交不得觸發 `.github/workflows/python-app.yml` 的桌面建置及 Release 工作。
- `website/dist/` 是建置輸出，不提交版本控制。

## Review Focus

- GitHub Pages 子路徑：直接開啟首頁或 `/guide/` 時，CSS、圖示、圖片與站內連結都必須保留 `/Video-to-Subtitle/` 前綴；Task 1 與 Task 4 的路由／完整性測試固定此行為。
- Markdown 不可信內容：手冊中的原始 HTML 或 `<script>` 必須顯示為文字而非執行；Task 2 的轉換測試固定 `html: false`。
- 重複中文標題：目錄錨點不得重複；Task 2 測試固定第二個相同標題產生 `-2` 後綴。
- 遺失或空白截圖：建置必須明確失敗，不得發布破圖頁面；Task 4 的資產缺失測試固定此行為。
- 純文件提交：README、手冊與網站來源變更不得觸發桌面 Release；Task 5 的 workflow 契約測試固定正向 `paths` 清單與 Pages 隔離。

---

## File Map

- `docs/USER_GUIDE.zh-TW.md`：v2.7.7 完整繁中使用手冊，也是網站手冊唯一來源。
- `README.md`：新增官方網站／手冊入口，修正一般 macOS 使用者的過時安裝指示。
- `website/package.json`、`website/package-lock.json`：網站建置與測試命令、鎖定的 Markdown 依賴。
- `website/build.mjs`：組裝首頁與手冊、複製資產、驗證產物。
- `website/src/paths.mjs`：集中管理 `/Video-to-Subtitle/` 路由與安全資產路徑。
- `website/src/layout.mjs`：共用 `<head>`、導覽列、頁尾與頁面框架。
- `website/src/content.mjs`：首頁繁中內容與區塊 HTML。
- `website/src/guide.mjs`：Markdown 解析、標題錨點、目錄及連結改寫。
- `website/src/site.css`：品牌色、排版、截圖、手冊與響應式樣式。
- `website/tests/routes.test.mjs`：路徑及基礎輸出契約。
- `website/tests/guide.test.mjs`：Markdown 安全、目錄與完整手冊內容契約。
- `website/tests/home.test.mjs`：首頁內容、CTA 與真實資產契約。
- `website/tests/site-integrity.test.mjs`：輸出連結、替代文字與缺失資產契約。
- `website/tests/workflow.test.mjs`：Pages 發布及桌面 Release 隔離契約。
- `.github/workflows/deploy-pages.yml`：測試、建置並部署 GitHub Pages。
- `.github/workflows/python-app.yml`：加入產品來源 `paths`，避免網站提交建立 Release。

### Task 1: Static site foundation and project-site routes

**Files:**
- Create: `website/package.json`
- Create: `website/package-lock.json`
- Create: `website/build.mjs`
- Create: `website/src/paths.mjs`
- Create: `website/src/layout.mjs`
- Create: `website/tests/routes.test.mjs`

**Interfaces:**
- Produces: `routeFor(page: 'home' | 'guide'): string` and `assetPath(name: string): string` from `website/src/paths.mjs`.
- Produces: `escapeHtml(value: unknown): string` and `renderLayout({ title, description, page, body }): string` from `website/src/layout.mjs`.
- Produces: `buildSite({ repositoryRoot?, outputRoot? }): Promise<string>` and `validateOutput(outputRoot): Promise<void>` from `website/build.mjs`.
- Consumes later: Tasks 2–4 import these exact functions; do not rename them.

- [ ] **Step 1: Add the package manifest and route tests**

Create `website/package.json`:

```json
{
  "private": true,
  "type": "module",
  "scripts": {
    "build": "node build.mjs",
    "test": "node --test tests/*.test.mjs"
  },
  "dependencies": {
    "markdown-it": "15.0.2"
  },
  "engines": {
    "node": ">=22 <23"
  }
}
```

Create `website/tests/routes.test.mjs` with these assertions:

```js
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { routeFor, assetPath } from '../src/paths.mjs';
import { renderLayout } from '../src/layout.mjs';
import { buildSite } from '../build.mjs';

const root = resolve(import.meta.dirname, '../..');

test('project-site routes retain the GitHub Pages prefix', () => {
  assert.equal(routeFor('home'), '/Video-to-Subtitle/');
  assert.equal(routeFor('guide'), '/Video-to-Subtitle/guide/');
  assert.equal(assetPath('site.css'), '/Video-to-Subtitle/assets/site.css');
  assert.throws(() => routeFor('missing'), /Unsupported page/);
  assert.throws(() => assetPath('../secret'), /Unsafe asset/);
});

test('layout exposes Traditional Chinese navigation without JavaScript', () => {
  const html = renderLayout({ title: '測試', description: '說明', page: 'home', body: '<p>內容</p>' });
  assert.match(html, /<html lang="zh-TW">/);
  assert.match(html, /href="\/Video-to-Subtitle\/guide\/"/);
  assert.match(html, /href="\/Video-to-Subtitle\/assets\/site\.css"/);
  assert.doesNotMatch(html, /English|選擇語言/);
});

test('build emits homepage and guide deep links', async () => {
  const out = await mkdtemp(join(tmpdir(), 'video-subtitle-routes-'));
  try {
    await buildSite({ repositoryRoot: root, outputRoot: out });
    for (const page of ['index.html', 'guide/index.html']) {
      assert.match(await readFile(join(out, page), 'utf8'), /Video to Subtitle/);
    }
  } finally {
    await rm(out, { recursive: true, force: true });
  }
});
```

- [ ] **Step 2: Run the route test and confirm the missing modules fail**

Run: `node --test website/tests/routes.test.mjs`

Expected: FAIL with `ERR_MODULE_NOT_FOUND` for `website/src/paths.mjs`.

- [ ] **Step 3: Implement safe paths and the shared layout**

Create `website/src/paths.mjs`:

```js
const base = '/Video-to-Subtitle/';

export function routeFor(page) {
  if (page === 'home') return base;
  if (page === 'guide') return `${base}guide/`;
  throw new TypeError(`Unsupported page: ${page}`);
}

export function assetPath(name) {
  if (!/^[a-z0-9][a-z0-9._-]*$/i.test(name)) throw new TypeError(`Unsafe asset: ${name}`);
  return `${base}assets/${name}`;
}
```

Create `website/src/layout.mjs`:

```js
import { assetPath, routeFor } from './paths.mjs';

export function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[character]);
}

export function renderLayout({ title, description, page, body }) {
  const home = routeFor('home');
  const guide = routeFor('guide');
  const current = name => name === page ? ' aria-current="page"' : '';
  return `<!doctype html>
<html lang="zh-TW"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>${escapeHtml(title)} · Video to Subtitle</title><meta name="description" content="${escapeHtml(description)}">
<link rel="canonical" href="https://kaoshou.github.io${routeFor(page)}"><link rel="icon" href="${assetPath('app_icon.png')}"><link rel="stylesheet" href="${assetPath('site.css')}">
</head><body><a class="skip-link" href="#main">跳至主要內容</a>
<header class="site-header"><nav class="nav-wrap" aria-label="主要導覽"><a class="brand" href="${home}"><img src="${assetPath('app_icon.png')}" alt="Video to Subtitle 圖示" width="34" height="34">Video to Subtitle</a><div class="nav-links"><a href="${home}"${current('home')}>首頁</a><a href="${guide}"${current('guide')}>完整手冊</a><a href="https://github.com/kaoshou/Video-to-Subtitle">GitHub</a><a class="nav-download" href="https://github.com/kaoshou/Video-to-Subtitle/releases/latest">下載</a></div></nav></header>
<main id="main">${body}</main>
<footer class="site-footer"><div class="container"><span>© Video to Subtitle</span><a href="https://github.com/kaoshou/Video-to-Subtitle">GitHub</a><a href="https://github.com/kaoshou/Video-to-Subtitle/releases">Releases</a><a href="${guide}">完整手冊</a><span>鄭郁翰 Yu-Han Cheng</span></div></footer></body></html>`;
}
```

- [ ] **Step 4: Add the minimum build entry points**

Create `website/build.mjs` with these public signatures and initial route output:

```js
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { renderLayout } from './src/layout.mjs';

const websiteRoot = fileURLToPath(new URL('.', import.meta.url));

async function writePage(outputRoot, path, html) {
  const directory = join(outputRoot, path);
  await mkdir(directory, { recursive: true });
  await writeFile(join(directory, 'index.html'), html);
}

export async function validateOutput(outputRoot) {
  for (const route of ['index.html', 'guide/index.html']) {
    const html = await readFile(join(outputRoot, route), 'utf8');
    if ((html.match(/<main\b/g) || []).length !== 1) throw new Error(`Expected one main landmark: ${route}`);
  }
}

export async function buildSite({ repositoryRoot = resolve(websiteRoot, '..'), outputRoot = join(websiteRoot, 'dist') } = {}) {
  void repositoryRoot;
  await writePage(outputRoot, '', renderLayout({ title: '本地語音轉字幕工具', description: '本機執行的影音轉字幕工具', page: 'home', body: '<section><h1>Video to Subtitle</h1></section>' }));
  await writePage(outputRoot, 'guide', renderLayout({ title: '完整使用手冊', description: 'Video to Subtitle 完整使用手冊', page: 'guide', body: '<article><h1>完整使用手冊</h1></article>' }));
  await validateOutput(outputRoot);
  return outputRoot;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await buildSite();
```

- [ ] **Step 5: Install the locked dependency and run the route test**

Run: `npm install --prefix website`

Expected: creates `website/package-lock.json` with `markdown-it` 15.0.2.

Run: `node --test website/tests/routes.test.mjs`

Expected: PASS, 3 tests.

- [ ] **Step 6: Commit the foundation**

```bash
git add website/package.json website/package-lock.json website/build.mjs website/src/paths.mjs website/src/layout.mjs website/tests/routes.test.mjs
git commit -m "feat(web): add static site foundation"
```

### Task 2: Canonical v2.7.7 Traditional Chinese user guide

**Files:**
- Create: `docs/USER_GUIDE.zh-TW.md`
- Create: `website/src/guide.mjs`
- Create: `website/tests/guide.test.mjs`
- Modify: `website/build.mjs`

**Interfaces:**
- Consumes: `routeFor('home' | 'guide')` from Task 1.
- Produces: `rewriteGuideHref(href: string): string` and `renderGuide(source: string): { html: string, toc: Array<{ level: number, id: string, label: string }> }`.
- `buildSite()` must read exactly `docs/USER_GUIDE.zh-TW.md` and render it to `guide/index.html`.

- [ ] **Step 1: Write guide safety and coverage tests**

Create `website/tests/guide.test.mjs`:

```js
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { renderGuide } from '../src/guide.mjs';
import { buildSite } from '../build.mjs';

test('Markdown is escaped and duplicate headings receive stable anchors', () => {
  const source = '## 模型管理\n## 模型管理\n[首頁](../README.md)\n\n<script>bad</script>';
  const { html, toc } = renderGuide(source);
  assert.match(html, /id="模型管理"/);
  assert.match(html, /id="模型管理-2"/);
  assert.match(html, /https:\/\/github\.com\/kaoshou\/Video-to-Subtitle#readme/);
  assert.match(html, /&lt;script&gt;bad&lt;\/script&gt;/);
  assert.equal(toc.length, 2);
  assert.throws(() => renderGuide('[錯誤](missing.md)'), /Unresolved guide link/);
});

test('built guide covers the complete v2.7.7 workflow without stale package instructions', async () => {
  const out = await mkdtemp(join(tmpdir(), 'video-subtitle-guide-'));
  try {
    await buildSite({ repositoryRoot: resolve(import.meta.dirname, '../..'), outputRoot: out });
    const html = await readFile(join(out, 'guide/index.html'), 'utf8');
    for (const heading of ['Windows 安裝與啟動', 'macOS 安裝與啟動', '第一次轉錄', '模型選擇指南', '完整轉錄設定', '字幕校對器', '模型儲存管理', 'EverCam 數位課程', '常見問題', '從原始碼執行']) {
      assert.ok(html.includes(heading), heading);
    }
    assert.match(html, /使用發行版不需安裝 Python、FFmpeg 或 mlx-whisper/);
    assert.doesNotMatch(html, /brew install ffmpeg/);
    assert.match(html, /class="guide-toc"/);
  } finally {
    await rm(out, { recursive: true, force: true });
  }
});
```

- [ ] **Step 2: Run the guide tests and confirm the renderer is missing**

Run: `node --test website/tests/guide.test.mjs`

Expected: FAIL with `ERR_MODULE_NOT_FOUND` for `website/src/guide.mjs`.

- [ ] **Step 3: Implement the Markdown renderer**

Create `website/src/guide.mjs`:

```js
import MarkdownIt from 'markdown-it';

const markdown = new MarkdownIt({ html: false, linkify: true, typographer: false });

export function rewriteGuideHref(href) {
  if (href === '../README.md') return 'https://github.com/kaoshou/Video-to-Subtitle#readme';
  if (/^(https?:|mailto:|#)/i.test(href)) return href;
  throw new Error(`Unresolved guide link: ${href}`);
}

function plainText(inline) {
  return (inline.children || []).map(token => token.content || '').join('');
}

function slugFor(text) {
  return text.normalize('NFKC').toLowerCase().replace(/[^\p{L}\p{N}]+/gu, '-').replace(/^-|-$/g, '') || 'section';
}

export function renderGuide(source) {
  const tokens = markdown.parse(source, {});
  const counts = new Map();
  const toc = [];
  for (let index = 0; index < tokens.length; index++) {
    const token = tokens[index];
    if (token.type === 'heading_open') {
      const label = plainText(tokens[index + 1]);
      const base = slugFor(label);
      const count = (counts.get(base) || 0) + 1;
      counts.set(base, count);
      const id = count === 1 ? base : `${base}-${count}`;
      token.attrSet('id', id);
      const level = Number(token.tag.slice(1));
      if (level === 2 || level === 3) toc.push({ level, id, label });
    }
    if (token.type === 'inline') {
      for (const child of token.children || []) {
        if (child.type === 'link_open') child.attrSet('href', rewriteGuideHref(child.attrGet('href')));
        if (child.type === 'image') throw new Error('Unexpected local image in guide');
      }
    }
  }
  return { html: markdown.renderer.render(tokens, markdown.options, {}), toc };
}
```

- [ ] **Step 4: Write the canonical guide from verified v2.7.7 behavior**

Create `docs/USER_GUIDE.zh-TW.md` with these exact top-level sections and concrete content from `SubtitleTranscriber.py`, `transcriber.py`, `evercam_integration.py`, README v2.7.0–v2.7.7, and the three current screenshots:

```markdown
# Video to Subtitle 完整使用手冊（繁體中文）

> 本工具在本機處理影音。除首次下載語音模型與手動檢查更新外，影音內容不會上傳至雲端。自動產生的字幕仍應由人工核對。

## 下載與系統需求
### Windows 安裝與啟動
### macOS 安裝與啟動
## 第一次轉錄
## 模型選擇指南
## 完整轉錄設定
### 運算單元
### 輸出格式
### 強制繁體中文與翻譯英文
### 前導提示與熱詞補強
### 進階設定
## 多檔案批次處理
## 字幕校對器
### 影音同步預覽與播放控制
### 編輯時間與文字
### 分割、合併與鍵盤操作
## 模型儲存管理
## 離線使用
## EverCam 數位課程
## 更新程式
## 常見問題
## 從原始碼執行
## 取得協助
```

The guide body must state all of the following facts explicitly:

- Supported inputs: MP4, MP3, MKV, WAV, MOV, AVI, M4A, FLAC, OGG, WEBM.
- Models: tiny (about 75 MB), base (about 145 MB), small (about 480 MB), medium (about 1.5 GB), large-v3 (about 3.1 GB), large-v3-turbo (about 1.6 GB).
- Outputs: SRT, VTT, TXT, TSV, JSON.
- Windows devices are CPU/CUDA; macOS devices are CPU/MLX. CUDA setup is optional and must link to official NVIDIA cuDNN and CTranslate2 documentation.
- `large-v3-turbo` is the recommended balance; do not promise exact speed on all hardware.
- The packaged v2.7.7 macOS app uses bundled PyAV/MLX components. Include the exact sentence `使用發行版不需安裝 Python、FFmpeg 或 mlx-whisper。`
- Explain prompt vs. comma-separated hotwords, file import for hotwords, Traditional Chinese interaction, translation precedence, and the 35-character overflow safeguard without presenting it as a hard linguistic guarantee.
- Explain editor search, row selection, video seek, CC overlay, ±0.5 seconds, previous/next, split `Ctrl+K`, merge `Ctrl+J`, playback speeds, volume/mute, F11/maximize, and Save & Close.
- Explain model pre-download, resumable downloads, custom storage path, free-space display, cache removal, and `[已下載]`/`[未下載]` labels.
- Explain EverCam folder/config.js discovery, `subtitles-data.js`, original `index.html` backup as `index.evercam-original.html`, single/batch conversion, and browser preview.
- Separate packaged-app instructions from developer commands. Only the developer section may show `pip install ...` or `pip install mlx-whisper`.
- End with links to GitHub Issues, Releases, and README.

- [ ] **Step 5: Connect the guide to the build**

Modify `website/build.mjs` to require and read `docs/USER_GUIDE.zh-TW.md`, then replace the placeholder guide body with:

```js
const source = await readFile(join(repositoryRoot, 'docs/USER_GUIDE.zh-TW.md'), 'utf8');
const guide = renderGuide(source);
const toc = guide.toc.map(item => `<li class="toc-level-${item.level}"><a href="#${escapeHtml(item.id)}">${escapeHtml(item.label)}</a></li>`).join('');
const guideBody = `<div class="container guide-shell"><aside class="guide-sidebar"><nav class="guide-toc" aria-label="本頁目錄"><strong>本頁目錄</strong><ol>${toc}</ol></nav></aside><article class="guide-article">${guide.html}</article></div>`;
await writePage(outputRoot, 'guide', renderLayout({ title: '完整使用手冊', description: 'Video to Subtitle v2.7.7 完整繁體中文使用手冊', page: 'guide', body: guideBody }));
```

Import `stat`, `renderGuide`, and `escapeHtml`, then add the initial source guard before `buildSite()`:

```js
async function required(path) {
  try {
    const info = await stat(path);
    if (!info.isFile() || info.size === 0) throw new Error('empty');
    return path;
  } catch {
    throw new Error(`Missing required site source: ${path}`);
  }
}
```

Call `await required(join(repositoryRoot, 'docs/USER_GUIDE.zh-TW.md'))` before reading the guide. Task 4 retains this signature and extends its use to every publication asset.

- [ ] **Step 6: Run the guide and route tests**

Run: `npm test --prefix website`

Expected: PASS for all route and guide tests.

- [ ] **Step 7: Commit the verified guide**

```bash
git add docs/USER_GUIDE.zh-TW.md website/build.mjs website/src/guide.mjs website/tests/guide.test.mjs
git commit -m "docs: add complete Traditional Chinese user guide"
```

### Task 3: Concise homepage content and real product previews

**Files:**
- Create: `website/src/content.mjs`
- Create: `website/tests/home.test.mjs`
- Modify: `website/build.mjs`

**Interfaces:**
- Consumes: `assetPath()`, `routeFor()`, and `escapeHtml()` from Task 1.
- Produces: `content: object` and `renderHome(): string`.
- `buildSite()` must call `renderHome()` for `index.html` and copy the four approved root assets to `website/dist/assets/`.

- [ ] **Step 1: Write the homepage contract test**

Create `website/tests/home.test.mjs`:

```js
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { buildSite } from '../build.mjs';

test('homepage gives a concise first-run path and uses genuine screenshots', async () => {
  const out = await mkdtemp(join(tmpdir(), 'video-subtitle-home-'));
  try {
    await buildSite({ repositoryRoot: resolve(import.meta.dirname, '../..'), outputRoot: out });
    const html = await readFile(join(out, 'index.html'), 'utf8');
    assert.match(html, /影片留在電腦，<em>字幕安心生成。<\/em>/);
    assert.match(html, /https:\/\/github\.com\/kaoshou\/Video-to-Subtitle\/releases\/latest/);
    assert.match(html, /\/Video-to-Subtitle\/guide\//);
    for (const asset of ['screenshot_main.png', 'screenshot_editor.png', 'screenshot_models.png']) assert.ok(html.includes(asset), asset);
    for (const step of ['加入影音', '選擇模型與輸出', '產生並校對']) assert.ok(html.includes(step), step);
    for (const feature of ['本機執行', '多檔案批次', '字幕校對', '模型管理', 'EverCam']) assert.ok(html.includes(feature), feature);
    assert.doesNotMatch(html, /fonts\.googleapis|google-analytics|gtag\(/);
  } finally {
    await rm(out, { recursive: true, force: true });
  }
});
```

- [ ] **Step 2: Run the homepage test and confirm content is absent**

Run: `node --test website/tests/home.test.mjs`

Expected: FAIL because the current placeholder homepage lacks the approved headline and screenshots.

- [ ] **Step 3: Implement the homepage content model and renderer**

Create `website/src/content.mjs`. Export a `content` object containing:

```js
export const content = {
  eyebrow: 'Windows 與 macOS 的本地語音轉字幕工具',
  heroTitle: '影片留在電腦，<em>字幕安心生成。</em>',
  heroText: '加入影音、選擇模型，便能在自己的電腦產生字幕。完成後直接校對時間軸與文字，不必把教材上傳到雲端。',
  steps: [
    ['01', '加入影音', '拖曳單一檔案、整批影音或 EverCam 課程資料夾。'],
    ['02', '選擇模型與輸出', '依電腦效能選擇模型，再指定 SRT、VTT、TXT、TSV 或 JSON。'],
    ['03', '產生並校對', '開始批次轉錄，完成後在內建編輯器同步檢查影片與字幕。']
  ]
};
```

Add the remaining homepage data and renderer. The feature list is:

```js
features: [
  ['本機執行', '影音只在自己的電腦處理；下載好模型後可離線轉錄。'],
  ['多檔案批次', '一次加入多段影片或音訊，自動依序產生字幕。'],
  ['提示與熱詞', '用主題背景、專有名詞與人名，引導模型更貼近內容。'],
  ['字幕校對', '一邊播放影音，一邊調整文字、時間軸、分割與合併。'],
  ['模型管理', '查看下載狀態、預先下載、變更儲存磁碟或清除快取。'],
  ['EverCam 整合', '辨識既有課程資料夾，產生字幕並升級為現代播放器。']
]
```

Implement `renderHome()` with the exact section order:

```js
export function renderHome() {
  const latest = 'https://github.com/kaoshou/Video-to-Subtitle/releases/latest';
  const guide = routeFor('guide');
  const steps = content.steps.map(([number, title, text]) => `<li class="step-card"><span>${escapeHtml(number)}</span><h3>${escapeHtml(title)}</h3><p>${escapeHtml(text)}</p></li>`).join('');
  const features = content.features.map(([title, text]) => `<li class="feature-card"><h3>${escapeHtml(title)}</h3><p>${escapeHtml(text)}</p></li>`).join('');
  return `<section class="hero"><div class="container hero-grid"><div class="hero-copy"><p class="eyebrow">${escapeHtml(content.eyebrow)}</p><h1>${content.heroTitle}</h1><p class="hero-text">${escapeHtml(content.heroText)}</p><div class="hero-actions"><a class="button button-primary" href="${latest}">下載最新版 ↗</a><a class="button button-secondary" href="${guide}">閱讀完整手冊 →</a></div><p class="hero-meta">開放原始碼 · 免費使用 · 本機轉錄</p></div><figure class="hero-visual"><img src="${assetPath('screenshot_main.png')}" alt="Video to Subtitle 主畫面，顯示檔案清單、模型、運算單元與輸出設定"><figcaption>主操作介面 · v2.7.7</figcaption></figure></div></section>
<section class="section quickstart"><div class="container"><div class="section-intro"><p class="section-kicker">01 / 快速上手</p><h2>三步完成第一份字幕。</h2></div><ol class="step-grid">${steps}</ol><a class="text-link" href="${guide}">查看逐步操作與模型建議 →</a></div></section>
<section class="section features"><div class="container"><div class="section-intro"><p class="section-kicker">02 / 主要功能</p><h2>從轉錄到校對，都在同一個工具。</h2></div><ul class="feature-grid">${features}</ul></div></section>
<section class="section previews"><div class="container"><div class="section-intro"><p class="section-kicker">03 / 真實介面</p><h2>轉錄、校對、模型管理，一目了然。</h2></div><div class="screenshot-grid"><figure class="screenshot-card"><img src="${assetPath('screenshot_main.png')}" alt="Video to Subtitle 主操作介面" loading="lazy"><figcaption>主操作介面</figcaption></figure><figure class="screenshot-card"><img src="${assetPath('screenshot_editor.png')}" alt="字幕校對器與影音同步播放器" loading="lazy"><figcaption>字幕校對器與影音同步播放器</figcaption></figure><figure class="screenshot-card"><img src="${assetPath('screenshot_models.png')}" alt="Whisper 模型快取與儲存管理視窗" loading="lazy"><figcaption>模型快取與儲存管理</figcaption></figure></div></div></section>
<section class="section platforms"><div class="container"><div class="section-intro"><p class="section-kicker">04 / 平台</p><h2>Windows 與 macOS 都能使用。</h2></div><div class="platform-grid"><article><h3>Windows</h3><p>下載單一 VideoToSubtitle.exe；可使用 CPU，具備相容 NVIDIA 環境時也可選 CUDA。</p></article><article><h3>macOS</h3><p>下載 VideoToSubtitle.dmg；Apple Silicon 可使用 MLX。發行版不需另外安裝 Python 或 FFmpeg。</p></article></div></div></section>
<section class="section privacy"><div class="container privacy-inner"><div><p class="section-kicker">05 / 隱私</p><h2>影音不必離開你的電腦。</h2><p>模型下載完成後即可離線轉錄。自動字幕仍可能誤判，發布前請使用內建校對器核對內容。</p></div><span class="privacy-mark" aria-hidden="true">LOCAL</span></div></section>
<section class="section final-cta"><div class="container final-cta-inner"><div><p class="section-kicker">06 / 完整手冊</p><h2>需要更多設定與排解資訊？</h2><p>從安裝、模型與進階選項，到字幕校對與 EverCam 轉換，都整理在完整手冊中。</p></div><a class="button button-primary" href="${guide}">閱讀完整手冊 →</a></div></section>`;
}
```

- [ ] **Step 4: Copy the approved assets during build**

Modify `website/build.mjs` to require and copy:

```js
const requiredAssets = [
  ['app_icon.png', 'app_icon.png'],
  ['screenshot_main.png', 'screenshot_main.png'],
  ['screenshot_editor.png', 'screenshot_editor.png'],
  ['screenshot_models.png', 'screenshot_models.png']
];
```

Create `website/dist/assets/`, copy each asset there, and replace the placeholder homepage body with `renderHome()`:

```js
await mkdir(join(outputRoot, 'assets'), { recursive: true });
for (const [source, target] of requiredAssets) {
  await required(join(repositoryRoot, source));
  await copyFile(join(repositoryRoot, source), join(outputRoot, 'assets', target));
}
await writePage(outputRoot, '', renderLayout({ title: '本地語音轉字幕工具', description: content.heroText, page: 'home', body: renderHome() }));
```

Import `copyFile`, `renderHome`, and `content`. Task 4 will add stylesheet copying once `site.css` exists.

- [ ] **Step 5: Run homepage, guide, and route tests**

Run: `npm test --prefix website`

Expected: PASS for all current tests.

- [ ] **Step 6: Commit the homepage**

```bash
git add website/build.mjs website/src/content.mjs website/tests/home.test.mjs
git commit -m "feat(web): add concise Traditional Chinese homepage"
```

### Task 4: Responsive visual system and output integrity

**Files:**
- Create: `website/src/site.css`
- Create: `website/tests/site-integrity.test.mjs`
- Modify: `website/build.mjs`
- Modify: `website/src/layout.mjs`

**Interfaces:**
- Consumes: all rendered HTML and route helpers from Tasks 1–3.
- Extends: `validateOutput(outputRoot)` to validate two routes, all local links, non-empty assets, one main landmark, image alt text, and guide table of contents.
- Produces: no new JavaScript API; the output remains usable without JavaScript.

- [ ] **Step 1: Write output-integrity and missing-asset tests**

Create `website/tests/site-integrity.test.mjs`:

```js
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { buildSite, validateOutput } from '../build.mjs';

const root = resolve(import.meta.dirname, '../..');

test('all generated local links and assets resolve under the project prefix', async () => {
  const out = await mkdtemp(join(tmpdir(), 'video-subtitle-integrity-'));
  try {
    await buildSite({ repositoryRoot: root, outputRoot: out });
    await validateOutput(out);
    const path = join(out, 'guide/index.html');
    const html = await readFile(path, 'utf8');
    await writeFile(path, html.replace('/Video-to-Subtitle/assets/site.css', '/Video-to-Subtitle/assets/missing.css'));
    await assert.rejects(validateOutput(out), /Unresolved site asset/);
  } finally {
    await rm(out, { recursive: true, force: true });
  }
});

test('missing genuine screenshots block publication', async () => {
  const out = await mkdtemp(join(tmpdir(), 'video-subtitle-missing-'));
  try {
    await assert.rejects(buildSite({ repositoryRoot: out, outputRoot: join(out, 'dist') }), /Missing required site source/);
  } finally {
    await rm(out, { recursive: true, force: true });
  }
});
```

- [ ] **Step 2: Run integrity tests and confirm validation is incomplete**

Run: `node --test website/tests/site-integrity.test.mjs`

Expected: FAIL because the build does not yet require screenshots or validate unresolved assets.

- [ ] **Step 3: Complete build validation**

Import `stat` and `sep`, then replace the initial validator with:

```js
const routeFiles = ['index.html', 'guide/index.html'];

async function required(path) {
  try {
    const info = await stat(path);
    if (!info.isFile() || info.size === 0) throw new Error('empty');
    return path;
  } catch {
    throw new Error(`Missing required site source: ${path}`);
  }
}

export async function validateOutput(outputRoot) {
  const root = resolve(outputRoot);
  for (const route of routeFiles) {
    const html = await readFile(join(root, route), 'utf8');
    if ((html.match(/<main\b/g) || []).length !== 1) throw new Error(`Expected one main landmark: ${route}`);
    if (route === 'guide/index.html' && !/<nav class="guide-toc"(?:\s|>)/.test(html)) throw new Error(`Missing guide contents: ${route}`);
    for (const match of html.matchAll(/<img\b[^>]*>/g)) {
      if (!/\balt="[^"]+"/.test(match[0])) throw new Error(`Missing image alternative: ${route}`);
    }
    for (const match of html.matchAll(/\b(?:href|src)="([^"]+)"/g)) {
      const href = match[1];
      if (/^(https?:|mailto:|#)/i.test(href)) continue;
      if (!href.startsWith('/Video-to-Subtitle/')) throw new Error(`Invalid project-site path: ${route}: ${href}`);
      const relative = decodeURIComponent(href.slice('/Video-to-Subtitle/'.length).split('#')[0].split('?')[0]);
      const target = resolve(root, relative);
      if (target !== root && !target.startsWith(root + sep)) throw new Error(`Path escapes site: ${href}`);
      try {
        const info = await stat(target);
        if (info.isDirectory()) await required(join(target, 'index.html'));
        else if (info.size === 0) throw new Error('empty');
      } catch {
        throw new Error(`Unresolved site asset: ${route}: ${href}`);
      }
    }
  }
  for (const [, asset] of requiredAssets) await required(join(root, 'assets', asset));
  await required(join(root, 'assets', 'site.css'));
}
```

Before building, call `required()` for the Markdown guide, stylesheet, app icon, and all three screenshots. Copy the stylesheet before validating:

```js
await required(join(websiteRoot, 'src/site.css'));
await copyFile(join(websiteRoot, 'src/site.css'), join(outputRoot, 'assets/site.css'));
await validateOutput(outputRoot);
```

- [ ] **Step 4: Implement the responsive blue visual system**

Create `website/src/site.css` with these tokens and minimum layout contracts:

```css
:root {
  --ink: #10233f;
  --muted: #5d6f86;
  --blue: #267dc2;
  --blue-dark: #155f9c;
  --sky: #eaf5fd;
  --line: #cfe0ec;
  --paper: #ffffff;
  --soft: #f5f9fc;
  --shadow: 0 28px 70px rgba(24, 83, 128, .18);
  color-scheme: light;
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body { margin: 0; color: var(--ink); background: var(--paper); font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans TC", sans-serif; line-height: 1.7; }
img { display: block; max-width: 100%; height: auto; }
a { color: inherit; }
.container, .nav-wrap { width: min(1180px, calc(100% - 48px)); margin-inline: auto; }
.hero { background: radial-gradient(circle at 78% 36%, #d9efff 0, transparent 42%), linear-gradient(145deg, #fbfdff, #edf7fd); overflow: hidden; }
.hero-grid { min-height: 650px; display: grid; grid-template-columns: .92fr 1.08fr; align-items: center; gap: 48px; padding-block: 76px 92px; }
.hero h1 { margin: 22px 0; font-size: clamp(3rem, 5.4vw, 5.7rem); line-height: 1.06; letter-spacing: -.065em; }
.hero h1 em { color: var(--blue-dark); font-style: normal; }
.hero-visual img { border: 1px solid var(--line); border-radius: 18px; box-shadow: var(--shadow); transform: rotate(-1.5deg); }
.button { display: inline-flex; min-height: 46px; align-items: center; justify-content: center; padding: 10px 18px; border-radius: 999px; text-decoration: none; font-weight: 700; }
.button-primary { color: white; background: var(--blue-dark); }
.button-secondary { border: 1px solid var(--line); background: rgba(255,255,255,.82); }
.section { padding-block: 96px; }
.step-grid, .feature-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 18px; list-style: none; padding: 0; }
.screenshot-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }
.screenshot-card:first-child { grid-column: 1 / -1; }
.guide-shell { display: grid; grid-template-columns: 250px minmax(0, 760px); gap: 64px; align-items: start; padding-block: 64px 100px; }
.guide-toc { position: sticky; top: 92px; max-height: calc(100vh - 120px); overflow: auto; }
.guide-article { min-width: 0; }
.guide-article pre { overflow: auto; padding: 18px; border-radius: 12px; background: #10233f; color: #edf7fd; }
.guide-article :is(h2, h3) { scroll-margin-top: 96px; }
@media (max-width: 900px) {
  .hero-grid, .guide-shell { grid-template-columns: 1fr; }
  .guide-toc { position: static; max-height: none; }
  .step-grid, .feature-grid { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 640px) {
  .container, .nav-wrap { width: min(100% - 32px, 1180px); }
  .hero-grid { min-height: 0; gap: 28px; padding-block: 54px 70px; }
  .hero h1 { font-size: clamp(2.65rem, 12vw, 4rem); }
  .hero-visual img { transform: none; }
  .step-grid, .feature-grid, .screenshot-grid { grid-template-columns: 1fr; }
  .screenshot-card:first-child { grid-column: auto; }
}
```

Complete the stylesheet for header, skip link, focus-visible states, section headings, cards, captions, platform/privacy blocks, guide tables, blockquotes, inline code, footer, and print-friendly guide output. Maintain a minimum 4.5:1 contrast ratio for normal text.

- [ ] **Step 5: Run all tests and production build**

Run: `npm test --prefix website && npm run build --prefix website`

Expected: all tests PASS; `website/dist/index.html`, `website/dist/guide/index.html`, and five files under `website/dist/assets/` exist and are non-empty.

- [ ] **Step 6: Commit styling and integrity checks**

```bash
git add website/build.mjs website/src/layout.mjs website/src/site.css website/tests/site-integrity.test.mjs
git commit -m "test(web): verify responsive accessible Pages output"
```

### Task 5: README entry points and CI workflow isolation

**Files:**
- Modify: `README.md:6-13`
- Modify: `README.md:144-187`
- Modify: `.github/workflows/python-app.yml:6-9`
- Create: `.github/workflows/deploy-pages.yml`
- Create: `website/tests/workflow.test.mjs`

**Interfaces:**
- Consumes: `website/package-lock.json`, test script, build script, and `website/dist` from Tasks 1–4.
- Produces: Pages workflow contract and product-source-only desktop workflow trigger.

- [ ] **Step 1: Write workflow and README contract tests**

Create `website/tests/workflow.test.mjs`:

```js
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';

test('Pages workflow builds and deploys only the generated site', async () => {
  const yaml = await readFile(resolve(import.meta.dirname, '../../.github/workflows/deploy-pages.yml'), 'utf8');
  for (const expected of ['branches: [main]', "'website/**'", "'docs/USER_GUIDE.zh-TW.md'", "'screenshot_main.png'", "'screenshot_editor.png'", "'screenshot_models.png'", "'app_icon.png'", 'workflow_dispatch:', 'npm ci --prefix website', 'npm test --prefix website', 'npm run build --prefix website', 'path: website/dist', 'name: github-pages', 'pages: write', 'id-token: write']) {
    assert.ok(yaml.includes(expected), expected);
  }
  assert.doesNotMatch(yaml, /softprops\/action-gh-release|tag_name:/);
});

test('desktop release workflow ignores pure website and documentation changes', async () => {
  const yaml = await readFile(resolve(import.meta.dirname, '../../.github/workflows/python-app.yml'), 'utf8');
  for (const productPath of ["'SubtitleTranscriber.py'", "'transcriber.py'", "'evercam_integration.py'", "'assets/evercam_player/**'", "'VideoToSubtitle.spec'", "'app_icon.*'", "'pyproject.toml'", "'.github/workflows/python-app.yml'"]) {
    assert.ok(yaml.includes(productPath), productPath);
  }
  assert.doesNotMatch(yaml, /'website\/\*\*'|'docs\/\*\*'|'README\.md'/);
});

test('README links the official site and canonical guide and drops stale packaged-app advice', async () => {
  const readme = await readFile(resolve(import.meta.dirname, '../../README.md'), 'utf8');
  assert.match(readme, /https:\/\/kaoshou\.github\.io\/Video-to-Subtitle\//);
  assert.match(readme, /docs\/USER_GUIDE\.zh-TW\.md/);
  const userFlow = readme.slice(readme.indexOf('## 使用流程'), readme.indexOf('## 🛠️ 開發與建置'));
  assert.doesNotMatch(userFlow, /brew install ffmpeg|pip install mlx-whisper/);
});
```

- [ ] **Step 2: Run workflow tests and confirm missing Pages workflow fails**

Run: `node --test website/tests/workflow.test.mjs`

Expected: FAIL with `ENOENT` for `.github/workflows/deploy-pages.yml`.

- [ ] **Step 3: Add official website and guide links to README**

Immediately below the main `# Video to Subtitle` heading add:

```markdown
🌐 [官方網站](https://kaoshou.github.io/Video-to-Subtitle/) ｜ 📖 [完整使用手冊（繁體中文）](docs/USER_GUIDE.zh-TW.md) ｜ 📥 [下載最新版](https://github.com/kaoshou/Video-to-Subtitle/releases/latest)
```

In the ordinary user flow, replace the stale macOS FFmpeg/`mlx-whisper` requirement with a note that the v2.7.7 DMG already contains the required runtime components and link to the full guide. Keep `pip install mlx-whisper` only under `## 🛠️ 開發與建置 (開發者)`.

- [ ] **Step 4: Restrict the desktop build workflow to product sources**

Replace `.github/workflows/python-app.yml` lines 6–9 with:

```yaml
on:
  push:
    branches: [ "main" ]
    paths:
      - 'SubtitleTranscriber.py'
      - 'transcriber.py'
      - 'evercam_integration.py'
      - 'assets/evercam_player/**'
      - 'VideoToSubtitle.spec'
      - 'app_icon.*'
      - 'pyproject.toml'
      - '.github/workflows/python-app.yml'
  workflow_dispatch:
```

This positive list intentionally excludes `website/**`, `docs/**`, screenshots, and README.

- [ ] **Step 5: Add the dedicated Pages workflow**

Create `.github/workflows/deploy-pages.yml`:

```yaml
name: Deploy Video to Subtitle Website

on:
  push:
    branches: [main]
    paths:
      - 'website/**'
      - 'docs/USER_GUIDE.zh-TW.md'
      - 'screenshot_main.png'
      - 'screenshot_editor.png'
      - 'screenshot_models.png'
      - 'app_icon.png'
      - '.github/workflows/deploy-pages.yml'
  pull_request:
    paths:
      - 'website/**'
      - 'docs/USER_GUIDE.zh-TW.md'
      - 'screenshot_main.png'
      - 'screenshot_editor.png'
      - 'screenshot_models.png'
      - 'app_icon.png'
      - '.github/workflows/deploy-pages.yml'
  workflow_dispatch:

concurrency:
  group: pages-${{ github.ref }}
  cancel-in-progress: true

jobs:
  build:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pages: read
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '22'
          cache: npm
          cache-dependency-path: website/package-lock.json
      - run: npm ci --prefix website
      - run: npm test --prefix website
      - run: npm run build --prefix website
      - uses: actions/configure-pages@v5
        if: github.ref == 'refs/heads/main'
      - uses: actions/upload-pages-artifact@v4
        if: github.ref == 'refs/heads/main'
        with:
          path: website/dist

  deploy:
    if: github.ref == 'refs/heads/main'
    needs: build
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pages: write
      id-token: write
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - uses: actions/deploy-pages@v4
        id: deployment
```

- [ ] **Step 6: Run every website test and build**

Run: `npm test --prefix website && npm run build --prefix website`

Expected: all tests PASS and the production build succeeds.

- [ ] **Step 7: Commit documentation entry points and workflows**

```bash
git add README.md .github/workflows/python-app.yml .github/workflows/deploy-pages.yml website/tests/workflow.test.mjs
git commit -m "ci: deploy official website with GitHub Pages"
```

### Task 6: Local visual QA, publication, and live verification

**Files:**
- Verify: `website/dist/index.html`
- Verify: `website/dist/guide/index.html`
- Verify: GitHub Actions runs and `https://kaoshou.github.io/Video-to-Subtitle/`

**Interfaces:**
- Consumes: complete static output and workflows from Tasks 1–5.
- Produces: a verified live GitHub Pages website; no additional source interface.

- [ ] **Step 1: Run a clean install, full test suite, and production build**

Run:

```bash
npm ci --prefix website
npm test --prefix website
npm run build --prefix website
git diff --check
git status --short
```

Expected: all tests PASS; build succeeds; `git diff --check` prints nothing; only intentional source changes, if any, appear in status.

- [ ] **Step 2: Serve the production output locally**

Run: `python3 -m http.server 4173 --directory website/dist`

Expected: server listens on `http://127.0.0.1:4173/` and both `/` and `/guide/` return HTTP 200.

- [ ] **Step 3: Inspect desktop and mobile layouts in a browser**

Open `/` and `/guide/` at approximately 1440 px and 390 px viewport widths. Verify:

- hero text does not overlap the main screenshot;
- all three screenshots remain legible and preserve aspect ratio;
- CTA buttons and header links are keyboard-focusable;
- narrow layout has no horizontal scrolling;
- guide table of contents remains reachable on mobile;
- Chinese headings do not create clipped lines;
- internal anchors move the target heading below the sticky header.

If any check fails, add a focused regression assertion where practical, patch the smallest CSS/HTML unit, rerun `npm test --prefix website && npm run build --prefix website`, and commit with `fix(web): correct responsive layout`.

- [ ] **Step 4: Confirm GitHub authentication and push the completed branch**

Run: `gh auth status`

Expected: authenticated as `kaoshou` with repository and workflow permissions. If the stored token is invalid, stop and request interactive GitHub re-authentication; do not claim publication.

After branch integration approved by the finishing workflow, push the resulting `main` commit:

Run: `git push origin main`

Expected: push succeeds without force and without triggering `Build Cross-Platform Executables` for website-only changes.

- [ ] **Step 5: Enable GitHub Pages Actions source if needed**

First run:

```bash
gh api repos/kaoshou/Video-to-Subtitle/pages
```

Expected: `build_type` is `workflow`. If the endpoint returns 404, run:

```bash
gh api --method POST repos/kaoshou/Video-to-Subtitle/pages -f build_type=workflow
```

If it exists with another source, run:

```bash
gh api --method PUT repos/kaoshou/Video-to-Subtitle/pages -f build_type=workflow
```

Read the response back and require `build_type: workflow` before continuing.

- [ ] **Step 6: Watch the deployment and verify the live site**

Run:

```bash
gh run list --repo kaoshou/Video-to-Subtitle --workflow deploy-pages.yml --limit 1
curl -I https://kaoshou.github.io/Video-to-Subtitle/
curl -I https://kaoshou.github.io/Video-to-Subtitle/guide/
```

Copy the `databaseId` from the first command and run `gh run watch <databaseId> --repo kaoshou/Video-to-Subtitle --exit-status`. Expected: the Pages run concludes successfully and both public URLs return HTTP 200. Open the live homepage and guide once more to confirm CSS and images load from the project subpath.

- [ ] **Step 7: Record final evidence**

Report the live URL, guide URL, commit SHA, local test count, GitHub Actions result, and any repository setting that still requires the owner. Do not report the site as published if authentication, Pages configuration, deployment, or HTTP verification remains incomplete.
