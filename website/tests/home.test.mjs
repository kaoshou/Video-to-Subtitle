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
    assert.match(html, /影片留在電腦，/);
    assert.match(html, /字幕安心生成。/);
    assert.match(html, /https:\/\/github\.com\/kaoshou\/Video-to-Subtitle\/releases\/latest/);
    assert.match(html, /\/Video-to-Subtitle\/guide\//);
    for (const asset of ['screenshot_main.png', 'screenshot_editor.png', 'screenshot_models.png']) assert.ok(html.includes(asset), asset);
    assert.doesNotMatch(html, /fonts\.googleapis|google-analytics|gtag\(/);
    assert.doesNotMatch(html, /主操作介面 · v2\.7\.7/);
  } finally {
    await rm(out, { recursive: true, force: true });
  }
});

test('homepage task entries lead directly to quickstart, proofreading and web-export instructions', async () => {
  const out = await mkdtemp(join(tmpdir(), 'video-subtitle-tasks-'));
  try {
    await buildSite({ repositoryRoot: resolve(import.meta.dirname, '../..'), outputRoot: out });
    const html = await readFile(join(out, 'index.html'), 'utf8');
    const tasks = html.match(/<nav\b[^>]*aria-label="依任務開始"[^>]*>([\s\S]*?)<\/nav>/)?.[1];
    assert.ok(tasks, 'task navigation must be available without JavaScript');
    for (const href of ['#quickstart', '/Video-to-Subtitle/guide/#字幕校對器', '/Video-to-Subtitle/guide/#一般-mp4-字幕匯出網頁']) {
      assert.ok(tasks.includes(`href="${href}"`), `missing task destination ${href}`);
    }
    for (const file of ['VideoToSubtitle.exe', 'VideoToSubtitle.dmg']) {
      assert.ok(html.includes(`href="https://github.com/kaoshou/Video-to-Subtitle/releases/latest/download/${file}"`));
    }
    assert.match(html, /<a[^>]*href="\/Video-to-Subtitle\/assets\/screenshot_main.png"[^>]*>[\s\S]*?<img/);
  } finally {
    await rm(out, { recursive: true, force: true });
  }
});
