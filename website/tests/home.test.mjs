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
