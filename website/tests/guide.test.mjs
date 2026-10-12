import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { renderGuide } from '../src/guide.mjs';
import { buildSite } from '../build.mjs';

test('Markdown is escaped and duplicate headings receive stable anchors', () => {
  const source = '## 模型管理\n## 模型管理\n## 模型管理-2\n[首頁](../README.md)\n\n<script>bad</script>';
  const { html, toc } = renderGuide(source);
  assert.match(html, /id="模型管理"/);
  assert.match(html, /id="模型管理-2"/);
  assert.match(html, /id="模型管理-2-2"/);
  assert.equal(new Set(toc.map(item => item.id)).size, toc.length);
  assert.match(html, /https:\/\/github\.com\/kaoshou\/Video-to-Subtitle#readme/);
  assert.match(html, /&lt;script&gt;bad&lt;\/script&gt;/);
  assert.equal(toc.length, 3);
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
    assert.match(html, /MLX.*熱詞.*VAD.*單字時間戳/s);
    assert.match(html, /large-v3-turbo.*不適合.*翻譯/s);
    assert.match(html, /EverCam 網頁轉換.*批次掃描母目錄/s);
    assert.match(html, /media.*srt.*vtt/s);
    assert.match(html, /啟動時.*自動.*更新/s);
  } finally {
    await rm(out, { recursive: true, force: true });
  }
});

test('guide renders language filename examples and common language codes as a table', async () => {
  const source = await readFile(resolve(import.meta.dirname, '../../docs/USER_GUIDE.zh-TW.md'), 'utf8');
  const { html, toc } = renderGuide(source);
  assert.ok(toc.some(item => item.label === '字幕檔名與自動配對規則'));
  assert.ok(toc.some(item => item.label === '常見語系代碼對照表'));
  const languageTable = html.match(/<table>[\s\S]*?<th>字幕語言<\/th>[\s\S]*?<\/table>/)?.[0];
  assert.ok(languageTable, 'language reference must render as a native HTML table');
  for (const code of ['zh-TW', 'zh-CN', 'en', 'ja', 'ko', 'vi', 'id', 'th', 'my', 'es', 'pt', 'ru', 'fr', 'de', 'it', 'ms', 'fil', 'hi', 'ar']) {
    assert.ok(languageTable.includes(`<code>media.${code}.srt</code>`), code);
  }
  assert.match(html, /改檔名不會翻譯字幕/);
  assert.match(html, /同語系只加入一份/);
  assert.match(html, /EverCam 的無語系/);
  assert.match(html, /一般 MP4 的無語系字幕則是/);
});
