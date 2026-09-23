import { assetPath, routeFor } from './paths.mjs';

export function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, character => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  })[character]);
}

export function renderLayout({ title, description, page, body }) {
  const home = routeFor('home');
  const guide = routeFor('guide');
  const current = name => name === page ? ' aria-current="page"' : '';
  return `<!doctype html>
<html lang="zh-TW"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>${escapeHtml(title)} · Video to Subtitle</title><meta name="description" content="${escapeHtml(description)}">
<link rel="canonical" href="https://kaoshou.github.io${routeFor(page)}"><link rel="icon" href="${assetPath('app_icon.png')}"><link rel="stylesheet" href="${assetPath('site.css')}">
</head><body><a class="skip-link" href="#main">跳至主要內容</a>
<header class="site-header"><nav class="nav-wrap" aria-label="主要導覽"><a class="brand" href="${home}"><img src="${assetPath('app_icon.png')}" alt="Video to Subtitle 圖示" width="34" height="34">Video to Subtitle</a><div class="nav-links"><a href="${home}"${current('home')}>首頁</a><a href="${guide}"${current('guide')}>完整手冊</a><a href="https://github.com/kaoshou/Video-to-Subtitle">GitHub</a><a class="nav-download" href="https://github.com/kaoshou/Video-to-Subtitle/releases/latest">下載</a></div></nav></header>
<main id="main">${body}</main>
<footer class="site-footer"><div class="container"><span>© Video to Subtitle</span><a href="https://github.com/kaoshou/Video-to-Subtitle">GitHub</a><a href="https://github.com/kaoshou/Video-to-Subtitle/releases">Releases</a><a href="${guide}">完整手冊</a><span>鄭郁翰 Yu-Han Cheng</span></div></footer></body></html>`;
}
