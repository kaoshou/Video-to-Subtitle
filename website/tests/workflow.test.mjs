import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';

test('Pages workflow builds and deploys only the generated site', async () => {
  const yaml = await readFile(resolve(import.meta.dirname, '../../.github/workflows/deploy-pages.yml'), 'utf8');
  for (const expected of ['branches: [main]', "'website/**'", "'docs/USER_GUIDE.zh-TW.md'", "'screenshot_main.png'", "'screenshot_editor.png'", "'screenshot_models.png'", "'app_icon.png'", 'workflow_dispatch:', 'npm ci --prefix website', 'npm test --prefix website', 'npm run build --prefix website', 'path: website/dist', 'name: github-pages', 'pages: write', 'id-token: write']) {
    assert.ok(yaml.includes(expected), expected);
  }
  assert.doesNotMatch(yaml, /softprops\/action-gh-release|tag_name:/);
});

test('desktop release workflow ignores pure website and documentation changes', async () => {
  const yaml = await readFile(resolve(import.meta.dirname, '../../.github/workflows/python-app.yml'), 'utf8');
  for (const productPath of ["'SubtitleTranscriber.py'", "'transcriber.py'", "'evercam_integration.py'", "'assets/evercam_player/**'", "'VideoToSubtitle.spec'", "'app_icon.*'", "'pyproject.toml'", "'.github/workflows/python-app.yml'"]) {
    assert.ok(yaml.includes(productPath), productPath);
  }
  assert.doesNotMatch(yaml, /'website\/\*\*'|'docs\/\*\*'|'README\.md'/);
});

test('README links the official site and canonical guide and drops stale packaged-app advice', async () => {
  const readme = await readFile(resolve(import.meta.dirname, '../../README.md'), 'utf8');
  assert.match(readme, /https:\/\/kaoshou\.github\.io\/Video-to-Subtitle\//);
  assert.match(readme, /docs\/USER_GUIDE\.zh-TW\.md/);
  const userFlow = readme.slice(readme.indexOf('## 使用流程'), readme.indexOf('## 🛠️ 開發與建置'));
  assert.doesNotMatch(userFlow, /brew install ffmpeg|pip install mlx-whisper/);
});
