import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { renderLayout } from './src/layout.mjs';

const websiteRoot = fileURLToPath(new URL('.', import.meta.url));

async function writePage(outputRoot, path, html) {
  const directory = join(outputRoot, path);
  await mkdir(directory, { recursive: true });
  await writeFile(join(directory, 'index.html'), html);
}

export async function validateOutput(outputRoot) {
  for (const route of ['index.html', 'guide/index.html']) {
    const html = await readFile(join(outputRoot, route), 'utf8');
    if ((html.match(/<main\b/g) || []).length !== 1) throw new Error(`Expected one main landmark: ${route}`);
  }
}

export async function buildSite({ repositoryRoot = resolve(websiteRoot, '..'), outputRoot = join(websiteRoot, 'dist') } = {}) {
  void repositoryRoot;
  await writePage(outputRoot, '', renderLayout({ title: '本地語音轉字幕工具', description: '本機執行的影音轉字幕工具', page: 'home', body: '<section><h1>Video to Subtitle</h1></section>' }));
  await writePage(outputRoot, 'guide', renderLayout({ title: '完整使用手冊', description: 'Video to Subtitle 完整使用手冊', page: 'guide', body: '<article><h1>完整使用手冊</h1></article>' }));
  await validateOutput(outputRoot);
  return outputRoot;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await buildSite();
