import { mkdir, readFile, stat, writeFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { escapeHtml, renderLayout } from './src/layout.mjs';
import { renderGuide } from './src/guide.mjs';

const websiteRoot = fileURLToPath(new URL('.', import.meta.url));

async function writePage(outputRoot, path, html) {
  const directory = join(outputRoot, path);
  await mkdir(directory, { recursive: true });
  await writeFile(join(directory, 'index.html'), html);
}

async function required(path) {
  try {
    const info = await stat(path);
    if (!info.isFile() || info.size === 0) throw new Error('empty');
    return path;
  } catch {
    throw new Error(`Missing required site source: ${path}`);
  }
}

export async function validateOutput(outputRoot) {
  for (const route of ['index.html', 'guide/index.html']) {
    const html = await readFile(join(outputRoot, route), 'utf8');
    if ((html.match(/<main\b/g) || []).length !== 1) throw new Error(`Expected one main landmark: ${route}`);
  }
}

export async function buildSite({ repositoryRoot = resolve(websiteRoot, '..'), outputRoot = join(websiteRoot, 'dist') } = {}) {
  const guidePath = join(repositoryRoot, 'docs/USER_GUIDE.zh-TW.md');
  await required(guidePath);
  await writePage(outputRoot, '', renderLayout({ title: '本地語音轉字幕工具', description: '本機執行的影音轉字幕工具', page: 'home', body: '<section><h1>Video to Subtitle</h1></section>' }));
  const source = await readFile(guidePath, 'utf8');
  const guide = renderGuide(source);
  const toc = guide.toc.map(item => `<li class="toc-level-${item.level}"><a href="#${escapeHtml(item.id)}">${escapeHtml(item.label)}</a></li>`).join('');
  const guideBody = `<div class="container guide-shell"><aside class="guide-sidebar"><nav class="guide-toc" aria-label="本頁目錄"><strong>本頁目錄</strong><ol>${toc}</ol></nav></aside><article class="guide-article">${guide.html}</article></div>`;
  await writePage(outputRoot, 'guide', renderLayout({ title: '完整使用手冊', description: 'Video to Subtitle v2.7.7 完整繁體中文使用手冊', page: 'guide', body: guideBody }));
  await validateOutput(outputRoot);
  return outputRoot;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await buildSite();
