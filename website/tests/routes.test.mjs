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
