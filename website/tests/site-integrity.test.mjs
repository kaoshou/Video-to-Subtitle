import test from 'node:test';
import assert from 'node:assert/strict';
import { copyFile, mkdir, mkdtemp, readFile, writeFile, rm } from 'node:fs/promises';
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
    await writeFile(path, html.replace('href="#下載與系統需求"', 'href="#不存在的章節"'));
    await assert.rejects(validateOutput(out), /Unresolved page fragment/);
    await writeFile(path, html);
    await writeFile(path, html.replace('/Video-to-Subtitle/assets/site.css', '/Video-to-Subtitle/assets/missing.css'));
    await assert.rejects(validateOutput(out), /Unresolved site asset/);
  } finally {
    await rm(out, { recursive: true, force: true });
  }
});

test('missing genuine screenshots block publication', async () => {
  const fixture = await mkdtemp(join(tmpdir(), 'video-subtitle-missing-'));
  const out = join(fixture, 'dist');
  try {
    await mkdir(join(fixture, 'docs'));
    await copyFile(join(root, 'docs/USER_GUIDE.zh-TW.md'), join(fixture, 'docs/USER_GUIDE.zh-TW.md'));
    for (const asset of ['app_icon.png', 'screenshot_main.png', 'screenshot_editor.png']) {
      await copyFile(join(root, asset), join(fixture, asset));
    }
    await assert.rejects(buildSite({ repositoryRoot: fixture, outputRoot: out }), /screenshot_models\.png/);
  } finally {
    await rm(fixture, { recursive: true, force: true });
  }
});
