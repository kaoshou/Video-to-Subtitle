import MarkdownIt from 'markdown-it';

const markdown = new MarkdownIt({ html: false, linkify: true, typographer: false });

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
      const level = Number(token.tag.slice(1));
      if (level === 2 || level === 3) toc.push({ level, id, label });
    }
    if (token.type === 'inline') {
      for (const child of token.children || []) {
        if (child.type === 'link_open') child.attrSet('href', rewriteGuideHref(child.attrGet('href')));
        if (child.type === 'image') throw new Error('Unexpected local image in guide');
      }
    }
  }
  return { html: markdown.renderer.render(tokens, markdown.options, {}), toc };
}
