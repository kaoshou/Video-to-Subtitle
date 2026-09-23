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
