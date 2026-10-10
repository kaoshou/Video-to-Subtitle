import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { JSDOM } from 'jsdom';
import { buildSite } from '../build.mjs';

// Removing the shipped script, interception, close handlers or focus restoration
// must break these tests. Native modal focus trapping is verified in a browser.
async function fixture(t) {
  const out = await mkdtemp(join(tmpdir(), 'vts-lightbox-'));
  t.after(() => rm(out, { recursive: true, force: true }));
  await buildSite({ outputRoot: out });
  const dom = new JSDOM(await readFile(join(out, 'index.html'), 'utf8'), {
    url: 'https://kaoshou.github.io/Video-to-Subtitle/', runScripts: 'outside-only'
  });
  t.after(() => dom.window.close());
  const { window } = dom;
  const { document } = window;
  const script = document.querySelector('script[src$="/lightbox.js"]');
  assert.ok(script, 'built homepage must load its lightbox script');
  // jsdom has no top-layer renderer; provide only the native dialog boundary.
  window.HTMLDialogElement.prototype.showModal = function () { this.open = true; };
  window.HTMLDialogElement.prototype.close = function () {
    this.open = false;
    this.dispatchEvent(new window.Event('close'));
  };
  window.eval(await readFile(join(out, 'assets/lightbox.js'), 'utf8'));
  return { window, document, triggers: [...document.querySelectorAll('.image-zoom')] };
}

test('every screenshot opens in-page with its own image and accessible description', async t => {
  const { window, document, triggers } = await fixture(t);
  assert.ok(triggers.length >= 3);
  for (const trigger of triggers) {
    assert.notEqual(trigger.target, '_blank');
    trigger.focus();
    const click = new window.MouseEvent('click', { bubbles: true, cancelable: true });
    trigger.dispatchEvent(click);
    assert.equal(click.defaultPrevented, true);
    const dialog = document.querySelector('dialog');
    assert.ok(dialog.open);
    assert.equal(dialog.querySelector('img').src, trigger.href);
    assert.equal(dialog.querySelector('img').alt, trigger.querySelector('img').alt);
    assert.ok(document.getElementById(dialog.getAttribute('aria-labelledby')).textContent);
    assert.equal(document.activeElement, dialog.querySelector('button'));
    assert.ok(document.documentElement.classList.contains('lightbox-open'));
    dialog.querySelector('button').click();
    assert.equal(dialog.open, false);
    assert.equal(document.activeElement, trigger);
    assert.equal(document.documentElement.classList.contains('lightbox-open'), false);
  }
});

test('image clicks stay open; background and native Escape cancel close the lightbox', async t => {
  const { window, document, triggers } = await fixture(t);
  triggers[0].click();
  const dialog = document.querySelector('dialog');
  dialog.querySelector('img').click();
  assert.ok(dialog.open);
  dialog.click();
  assert.equal(dialog.open, false);
  triggers[0].click();
  dialog.dispatchEvent(new window.Event('cancel', { cancelable: true }));
  assert.equal(dialog.open, false);
  assert.equal(document.activeElement, triggers[0]);
});
