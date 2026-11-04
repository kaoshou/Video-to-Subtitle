import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { renderGuide, rewriteGuideHref } from '../src/guide.mjs';
import { renderHome } from '../src/content.mjs';

test('MCP guide renders setup, privacy, model selection and workflow screenshots', async () => {
  const source = await readFile(new URL('../../docs/MCP.zh-TW.md', import.meta.url), 'utf8');
  const guide = renderGuide(source);
  for (const term of ['Codex', 'Antigravity', 'large-v3-turbo', 'screenshot_mcp_connect.png', 'screenshot_mcp_jobs.png', 'screenshot_mcp_advanced.png', '雲端']) {
    assert.ok(guide.html.includes(term), term);
  }
  assert.equal(rewriteGuideHref('MCP.zh-TW.md'), '/Video-to-Subtitle/mcp/');
  assert.equal(rewriteGuideHref('USER_GUIDE.zh-TW.md#批次加速試用'), '/Video-to-Subtitle/guide/#批次加速-試用');
  assert.equal(rewriteGuideHref('USER_GUIDE.zh-TW.md#' + encodeURIComponent('批次加速試用')), '/Video-to-Subtitle/guide/#批次加速-試用');
  assert.throws(() => rewriteGuideHref('../private.json'), /Unresolved/);
});

test('homepage promotes optional AI collaboration and explains cloud text processing', () => {
  const html = renderHome();
  assert.ok(html.includes('/Video-to-Subtitle/mcp/'));
  assert.match(html, /v2\.10\.0/);
  assert.match(html, /MCP 預設關閉/);
  assert.match(html, /字幕文字到所選雲端服務/);
  assert.doesNotMatch(html, /批次大小預設 4/);
});
