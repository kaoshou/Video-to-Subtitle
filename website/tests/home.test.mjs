import test from 'node:test';
import assert from 'node:assert/strict';
import { copyFile, mkdir, mkdtemp, readFile, writeFile, rm } from 'node:fs/promises';
import { JSDOM } from 'jsdom';
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

test('hero always links to latest downloads regardless of source version', async () => {
  const root = resolve(import.meta.dirname, '../..');
  const fixture = await mkdtemp(join(tmpdir(), 'video-subtitle-downloads-'));
  try {
    await mkdir(join(fixture, 'docs'));
    await copyFile(join(root, 'docs/USER_GUIDE.zh-TW.md'), join(fixture, 'docs/USER_GUIDE.zh-TW.md'));
    for (const asset of ['app_icon.png', 'screenshot_main.png', 'screenshot_editor.png', 'screenshot_models.png', 'screenshot_advanced.png']) {
      await copyFile(join(root, asset), join(fixture, asset));
    }
    await mkdir(join(fixture, 'docs/images'));
    await copyFile(join(root, 'docs/images/batch-flow.svg'), join(fixture, 'docs/images/batch-flow.svg'));
    for (const version of ['9.1.2', '9.1.3']) {
      await writeFile(join(fixture, 'pyproject.toml'), '[project]\nversion = "' + version + '"\n');
      const outputRoot = join(fixture, version);
      await buildSite({ repositoryRoot: fixture, outputRoot });
      const dom = new JSDOM(await readFile(join(outputRoot, 'index.html'), 'utf8'));
      try {
        const buttons = [...dom.window.document.querySelectorAll('.home-hero .hero-actions a')];
        assert.equal(buttons.length, 3, 'The installer must be directly available next to the portable download');
        assert.deepEqual(buttons.map(a => a.href), [
          'https://github.com/kaoshou/Video-to-Subtitle/releases/latest',
          'https://github.com/kaoshou/Video-to-Subtitle/releases/latest',
          'https://github.com/kaoshou/Video-to-Subtitle/releases/latest'
        ]);
        assert.deepEqual(buttons.map(a=>a.dataset.releasePlatform), ['windows-portable','windows-setup','macos']);
        assert.ok(buttons.every(a => a.textContent.trim().startsWith('下載')));
      } finally { dom.window.close(); }
    }
  } finally { await rm(fixture, { recursive: true, force: true }); }
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
    const dom = new JSDOM(html);
    try {
      for (const anchor of dom.window.document.querySelectorAll('.hero-actions a')) {
        assert.match(anchor.href, /\/releases\/latest$/);
      }
    } finally { dom.window.close(); }
    assert.match(html, /<a[^>]*href="\/Video-to-Subtitle\/assets\/screenshot_main.png"[^>]*>[\s\S]*?<img/);
  } finally {
    await rm(out, { recursive: true, force: true });
  }
});
