import MarkdownIt from 'markdown-it';
import { escapeHtml } from './layout.mjs';
import { assetPath } from './paths.mjs';

const markdown = new MarkdownIt({ html: false, linkify: true, typographer: false });
const guideImages = new Map([
  ['../screenshot_main.png', 'screenshot_main.png'],
  ['../screenshot_editor.png', 'screenshot_editor.png'],
  ['../screenshot_models.png', 'screenshot_models.png'],
  ['../screenshot_advanced.png', 'screenshot_advanced.png'],
  ['images/batch-flow.svg', 'batch-flow.svg']
]);
const renderImage = markdown.renderer.rules.image;
markdown.renderer.rules.image = (tokens, index, options, env, renderer) => {
  const token = tokens[index];
  return `<a class="image-zoom guide-image" href="${escapeHtml(token.attrGet('src'))}" aria-label="放大查看：${escapeHtml(token.content)}">` +
    renderImage(tokens, index, options, env, renderer) + '</a>';
};

function scrollRegion(token) {
  const name = token.meta?.headingId
    ? `aria-labelledby="${escapeHtml(token.meta.headingId)}"`
    : 'aria-label="可水平捲動的範例"';
  return `<div class="guide-scroll" role="region" tabindex="0" ${name}>`;
}

const renderFence = markdown.renderer.rules.fence;
markdown.renderer.rules.fence = (tokens, index, options, env, renderer) =>
  scrollRegion(tokens[index]) + renderFence(tokens, index, options, env, renderer) + '</div>\n';
markdown.renderer.rules.table_open = (tokens, index, options, env, renderer) =>
  scrollRegion(tokens[index]) + renderer.renderToken(tokens, index, options);
markdown.renderer.rules.table_close = (tokens, index, options, env, renderer) =>
  renderer.renderToken(tokens, index, options) + '</div>\n';

export function rewriteGuideHref(href) {
  if (href === '../README.md') return 'https://github.com/kaoshou/Video-to-Subtitle#readme';
  if (/^(https?:|mailto:|#)/i.test(href)) return href;
  throw new Error(`Unresolved guide link: ${href}`);
}

function plainText(inline) {
  return (inline.children || []).map(token => token.content || '').join('');
}

function slugFor(text) {
  return text.normalize('NFKC').toLowerCase().replace(/[^\p{L}\p{N}]+/gu, '-').replace(/^-|-$/g, '') || 'section';
}

export function renderGuide(source) {
  const tokens = markdown.parse(source, {});
  const usedIds = new Set();
  const toc = [];
  let headingId;
  for (let index = 0; index < tokens.length; index++) {
    const token = tokens[index];
    if (token.type === 'heading_open') {
      const label = plainText(tokens[index + 1]);
      const base = slugFor(label);
      let id = base;
      let suffix = 2;
      while (usedIds.has(id)) id = `${base}-${suffix++}`;
      usedIds.add(id);
      token.attrSet('id', id);
      token.attrSet('tabindex', '-1');
      headingId = id;
      const level = Number(token.tag.slice(1));
      if (level === 2 || level === 3) toc.push({ level, id, label });
    }
    if (token.type === 'table_open' || token.type === 'fence') token.meta = { headingId };
    if (token.type === 'th_open') token.attrSet('scope', 'col');
    if (token.type === 'inline') {
      for (const child of token.children || []) {
        if (child.type === 'link_open') child.attrSet('href', rewriteGuideHref(child.attrGet('href')));
        if (child.type === 'image') {
          const file = guideImages.get(child.attrGet('src'));
          if (!file) throw new Error(`Unresolved guide image: ${child.attrGet('src')}`);
          child.attrSet('src', assetPath(file));
          child.attrSet('loading', 'lazy');
        }
      }
    }
  }
  return { html: markdown.renderer.render(tokens, markdown.options, {}), toc };
}
