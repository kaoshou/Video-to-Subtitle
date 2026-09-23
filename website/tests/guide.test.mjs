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
