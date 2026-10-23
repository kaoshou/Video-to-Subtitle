import test from 'node:test';
import assert from 'node:assert/strict';
import { JSDOM } from 'jsdom';
import { renderLayout } from '../src/layout.mjs';
import { renderHome } from '../src/content.mjs';
import { renderGuide } from '../src/guide.mjs';

// Removing a destination's tabindex breaks focus transfer even though its hash
// still scrolls into view. These checks exercise the rendered focus boundary.
test('the skip link destination can receive focus on both site routes', () => {
  for (const page of ['home', 'guide']) {
    const dom = new JSDOM(renderLayout({ title: '測試', description: '', page, body: '<h1>內容</h1>' }));
    try {
      const { document } = dom.window;
      const destination = document.querySelector(document.querySelector('.skip-link').hash);
      destination.focus();
      assert.equal(document.activeElement, destination, page);
      assert.equal(destination.tabIndex, -1, 'skip destination must not add a tab stop');
    } finally {
      dom.window.close();
    }
  }
});

test('quickstart and guide contents destinations can receive keyboard focus', () => {
  const guide = renderGuide('## 第一章\n\n### 操作\n\n#### 細節');
  const dom = new JSDOM(renderHome() + guide.html);
  try {
    const { document } = dom.window;
    for (const id of ['quickstart', '第一章', '操作', '細節']) {
      const destination = document.getElementById(id);
      destination.focus();
      assert.equal(document.activeElement, destination, id);
      assert.equal(destination.tabIndex, -1, 'anchor destinations must not add tab stops');
    }
  } finally {
    dom.window.close();
  }
});

test('wide guide tables and code examples provide named keyboard scroll regions', () => {
  const guide = renderGuide('## 檔名對照\n\n| 語言 | 檔名 |\n| --- | --- |\n| 繁中 | media.zh-TW.srt |\n\n```text\nmedia.zh-TW.srt\n```');
  const dom = new JSDOM(guide.html);
  try {
    const { document } = dom.window;
    for (const content of document.querySelectorAll('table, pre')) {
      const region = content.closest('[role="region"]');
      assert.ok(region, `${content.tagName} needs an operable scroll container`);
      region.focus();
      assert.equal(document.activeElement, region);
      assert.equal(region.tabIndex, 0);
      assert.equal(document.getElementById(region.getAttribute('aria-labelledby')).textContent, '檔名對照');
    }
    assert.equal(document.querySelectorAll('table th[scope="col"]').length, 2);
  } finally {
    dom.window.close();
  }
});
