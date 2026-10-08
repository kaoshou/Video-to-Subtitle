import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

// Historical captures may stay only with explicit, accurate provenance labels.
// Screenshot work was paused by the user; never relabel pixels as a new version.
test('published screenshots identify their actual capture version and platform', async () => {
  const root = new URL('../../', import.meta.url);
  const version = '2.7.8';
  const readme = await readFile(new URL('README.md', root), 'utf8');
  const { renderHome } = await import('../src/content.mjs');
  assert.ok(readme.includes(`截圖均擷取自 **v${version}**`));
  assert.ok(renderHome().includes(`以下為 v${version} 在 Linux`));
  for (const name of ['screenshot_main.png', 'screenshot_editor.png', 'screenshot_models.png']) {
    const png = await readFile(new URL(name, root));
    const metadata = {};
    for (let offset = 8; offset + 12 <= png.length;) {
      const length = png.readUInt32BE(offset);
      const type = png.toString('ascii', offset + 4, offset + 8);
      const data = png.subarray(offset + 8, offset + 8 + length);
      if (type === 'tEXt') {
        const separator = data.indexOf(0);
        metadata[data.subarray(0, separator).toString('latin1')] = data.subarray(separator + 1).toString('latin1');
      }
      offset += length + 12;
    }
    assert.equal(metadata.Software, `Video to Subtitle ${version}`, `${name}: mislabeled or unverified capture`);
    assert.match(metadata.SourceCommit ?? '', /^[0-9a-f]{40}$/);
    assert.ok(['Linux', 'Windows', 'Darwin'].includes(metadata.Platform), `${name}: missing actual platform`);
    assert.equal(metadata.Content, 'Synthetic demonstration; no personal data');
  }
});
