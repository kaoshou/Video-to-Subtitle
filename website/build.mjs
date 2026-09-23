import { copyFile, mkdir, readFile, stat, writeFile } from 'node:fs/promises';
import { join, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { escapeHtml, renderLayout } from './src/layout.mjs';
import { renderGuide } from './src/guide.mjs';
import { content, renderHome } from './src/content.mjs';

const websiteRoot = fileURLToPath(new URL('.', import.meta.url));
const requiredAssets = [
  ['app_icon.png', 'app_icon.png'],
  ['screenshot_main.png', 'screenshot_main.png'],
  ['screenshot_editor.png', 'screenshot_editor.png'],
  ['screenshot_models.png', 'screenshot_models.png']
];
const routeFiles = ['index.html', 'guide/index.html'];

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
  const root = resolve(outputRoot);
  for (const route of routeFiles) {
    const html = await readFile(join(root, route), 'utf8');
    if ((html.match(/<main\b/g) || []).length !== 1) throw new Error(`Expected one main landmark: ${route}`);
    if (route === 'guide/index.html' && !/<nav class="guide-toc"(?:\s|>)/.test(html)) throw new Error(`Missing guide contents: ${route}`);
    for (const match of html.matchAll(/<img\b[^>]*>/g)) {
      if (!/\balt="[^"]+"/.test(match[0])) throw new Error(`Missing image alternative: ${route}`);
    }
    for (const match of html.matchAll(/\b(?:href|src)="([^"]+)"/g)) {
      const href = match[1];
      if (/^(https?:|mailto:|#)/i.test(href)) continue;
      if (!href.startsWith('/Video-to-Subtitle/')) throw new Error(`Invalid project-site path: ${route}: ${href}`);
      const relative = decodeURIComponent(href.slice('/Video-to-Subtitle/'.length).split('#')[0].split('?')[0]);
      const target = resolve(root, relative);
      if (target !== root && !target.startsWith(root + sep)) throw new Error(`Path escapes site: ${href}`);
      try {
        const info = await stat(target);
        if (info.isDirectory()) await required(join(target, 'index.html'));
        else if (info.size === 0) throw new Error('empty');
      } catch {
        throw new Error(`Unresolved site asset: ${route}: ${href}`);
      }
    }
  }
  for (const [, asset] of requiredAssets) await required(join(root, 'assets', asset));
  await required(join(root, 'assets', 'site.css'));
}

export async function buildSite({ repositoryRoot = resolve(websiteRoot, '..'), outputRoot = join(websiteRoot, 'dist') } = {}) {
  const guidePath = join(repositoryRoot, 'docs/USER_GUIDE.zh-TW.md');
  await required(guidePath);
  await required(join(websiteRoot, 'src/site.css'));
  await mkdir(join(outputRoot, 'assets'), { recursive: true });
  for (const [source, target] of requiredAssets) {
    await required(join(repositoryRoot, source));
    await copyFile(join(repositoryRoot, source), join(outputRoot, 'assets', target));
  }
  await copyFile(join(websiteRoot, 'src/site.css'), join(outputRoot, 'assets/site.css'));
  await writePage(outputRoot, '', renderLayout({ title: '本地語音轉字幕工具', description: content.heroText, page: 'home', body: renderHome() }));
  const source = await readFile(guidePath, 'utf8');
  const guide = renderGuide(source);
  const toc = guide.toc.map(item => `<li class="toc-level-${item.level}"><a href="#${escapeHtml(item.id)}">${escapeHtml(item.label)}</a></li>`).join('');
  const guideBody = `<div class="container guide-shell"><aside class="guide-sidebar"><nav class="guide-toc" aria-label="本頁目錄"><strong>本頁目錄</strong><ol>${toc}</ol></nav></aside><article class="guide-article">${guide.html}</article></div>`;
  await writePage(outputRoot, 'guide', renderLayout({ title: '完整使用手冊', description: 'Video to Subtitle v2.7.7 完整繁體中文使用手冊', page: 'guide', body: guideBody }));
  await validateOutput(outputRoot);
  return outputRoot;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await buildSite();
