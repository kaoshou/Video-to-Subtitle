#!/usr/bin/env node
/** Real Chromium checks against trusted synthetic player packages and a built site.
 * npm ci --prefix tests/browser
 * PLAYWRIGHT_BROWSERS_PATH=/isolated/path node scripts/smoke_accessibility_browser.mjs \
 *   --media /tmp/synthetic-270s.mp4 --report-dir /tmp/accessibility-report
 * No media, focus, geometry, download, or accessibility APIs are mocked.
 */
import assert from 'node:assert/strict';
import { cp, mkdir, mkdtemp, readFile, readdir, stat, writeFile } from 'node:fs/promises';
import { createServer } from 'node:http';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import { dirname, extname, join, resolve, sep } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const TITLE = '數位教學｜影片字幕與教材製作';
const TAGS = ['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa'];
const PROFILES = [
    { name: 'desktop', viewport: { width: 1440, height: 1000 }, mobile: false },
    { name: 'mobile', viewport: { width: 390, height: 844 }, mobile: true }
];
const usage = `Usage: node scripts/smoke_accessibility_browser.mjs --media FILE --report-dir DIR
  --source-root DIR    Player source tree (default: repository containing this script)
  --baseline-root DIR  Optional original source tree for default-state visual comparison
  --site-dir DIR       Built website (default: website/dist when present)
  --chromium FILE      Optional isolated Chromium executable
  --help              Show usage
Requires pinned Playwright and axe-core under tests/browser, plus isolated headless Chromium.
The media must be trusted synthetic MP4, at least 260 seconds. Reports contain synthetic data.
External requests are blocked; the built website uses an ephemeral localhost-only server.
Axe violations fail the run. Full incomplete results remain in report.json for manual review;
an automated pass is not a WCAG conformance claim or a substitute for assistive-technology QA.`;

function options(argv) {
    const out = {};
    for (let i = 0; i < argv.length; i++) {
        const key = argv[i];
        if (key === '--help') out[key] = true;
        else if (['--media', '--report-dir', '--source-root', '--baseline-root', '--site-dir', '--chromium'].includes(key)) {
            assert.ok(argv[i + 1] && !argv[i + 1].startsWith('--'), `${key} requires a value`);
            out[key] = resolve(argv[++i]);
        } else throw new Error(`Unknown argument: ${key}`);
    }
    if (!out['--help']) {
        assert.ok(out['--media'], '--media is required; media mocking is intentionally unsupported');
        assert.ok(out['--report-dir'], '--report-dir is required');
    }
    out['--source-root'] ||= root;
    return out;
}

function cueText(language, index) {
    const token = `${language === 'en' ? 'EN' : 'ZH'}${String(index).padStart(3, '0')}`;
    const sentence = language === 'en'
        ? 'Prepare accessible teaching materials, review the subtitles, and share the complete lesson.'
        : '準備數位教材，校對影片字幕，讓每位學習者都能閱讀完整課程內容。';
    return `[${token}] ${sentence}${index < 2 ? ' needle' : ''}${index === 0 ? ' <script>window.__transcriptInjected=true</script> & "教材"' : ''}`;
}

async function fixture(parent, sourceRoot, mode, media, suffix = '') {
    const folder = join(parent, `${mode}${suffix}`);
    await mkdir(folder, { recursive: true });
    await cp(join(sourceRoot, 'assets/evercam_player/css'), join(folder, 'css'), { recursive: true });
    await cp(join(sourceRoot, 'assets/evercam_player/js'), join(folder, 'js'), { recursive: true });
    const template = await readFile(join(sourceRoot, `assets/${mode === 'standalone' ? 'standalone_player' : 'evercam_player'}/index.html`), 'utf8');
    await writeFile(join(folder, 'index.html'), template.replaceAll('{{TITLE}}', TITLE));
    const config = { title: TITLE, author: '數位教材工作室', organization: '教學資源中心',
        packageId: `accessibility-smoke-${mode}`, duration: 270, defaultSubtitle: 'zh-TW',
        src: [{ src: 'media.mp4', type: 'video/mp4' }],
        index: [{ time: 0, title: '課程介紹與教材準備' }, { time: 90000, title: '字幕校對與閱讀設定' }, { time: 180000, title: '匯出教材與分享課程' }] };
    if (mode === 'standalone') config.mode = 'standalone';
    await writeFile(join(folder, mode === 'standalone' ? 'player-config.js' : 'config.js'),
        `window.${mode === 'standalone' ? 'VTS_PLAYER_CONFIG' : 'config'} = ${JSON.stringify(config)};\n`);
    const tracks = ['zh-TW', 'en'].map(language => ({ language, cues: Array.from({ length: 260 }, (_, index) => ({
        start: index, end: index + 0.9, text: cueText(language, index)
    })) }));
    await writeFile(join(folder, 'subtitles-data.js'), `window.EVERCAM_SUBTITLES = ${JSON.stringify({ tracks })};\n`);
    await cp(media, join(folder, 'media.mp4'));
    return folder;
}

async function settle(page) {
    await page.evaluate(() => new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done))));
}

async function seek(page, time) {
    await page.locator('video').evaluate((video, target) => new Promise((done, reject) => {
        if (Math.abs(video.currentTime - target) < 0.001 && !video.seeking) return done();
        const timer = setTimeout(() => reject(new Error(`Native seek timed out: ${target}`)), 12000);
        video.addEventListener('seeked', () => { clearTimeout(timer); done(); }, { once: true });
        video.currentTime = target;
    }), time);
    await settle(page);
}

async function geometry(page) {
    return page.evaluate(() => {
        const selectors = ['.course-header', '#video-stage', '.player-card', '.chapter-card'];
        return Object.fromEntries(selectors.map(selector => {
            const el = document.querySelector(selector);
            if (!el) return [selector, null];
            const { x, y, width, height } = el.getBoundingClientRect();
            const style = getComputedStyle(el);
            return [selector, { x, y, width, height, background: style.background, color: style.color }];
        }));
    });
}

async function noOverflow(page, label) {
    const state = await page.evaluate(() => ({ viewport: innerWidth, width: document.documentElement.scrollWidth,
        offenders: [...document.querySelectorAll('body *')].filter(el => {
            const r = el.getBoundingClientRect();
            return r.width && r.right > innerWidth + 2 && getComputedStyle(el).position !== 'fixed';
        }).slice(0, 12).map(el => `${el.tagName.toLowerCase()}#${el.id}.${el.className}`) }));
    assert.ok(state.width <= state.viewport + 2, `${label}: horizontal page overflow ${JSON.stringify(state)}`);
    return state;
}

async function axeScan(page, label, result, axeSource) {
    if (!await page.evaluate(() => Boolean(window.axe))) await page.addScriptTag({ content: axeSource });
    const scan = await page.evaluate(tags => window.axe.run(document, {
        runOnly: { type: 'tag', values: tags }, resultTypes: ['violations', 'incomplete', 'passes', 'inapplicable']
    }), TAGS);
    result.axe.push({ label, url: scan.url, timestamp: scan.timestamp, testEngine: scan.testEngine,
        violations: scan.violations, incomplete: scan.incomplete,
        passes: scan.passes.map(rule => ({ id: rule.id, nodes: rule.nodes.length })),
        inapplicable: scan.inapplicable.map(rule => rule.id) });
    assert.equal(scan.violations.length, 0, `${label}: ${scan.violations.map(v => `${v.id} (${v.nodes.length} nodes)`).join(', ')}`);
}

async function step(result, label, run) {
    try { const details = await run(); result.checks.push({ label, status: 'passed', ...(details === undefined ? {} : { details }) }); }
    catch (error) {
        result.checks.push({ label, status: 'failed', error: error.stack || String(error) });
        console.log(`  FAIL ${result.name} ${label}: ${error.message}`);
    }
}

async function screenshot(page, result, opts, label, fullPage = false) {
    const file = `${result.name}-${label}.png`;
    await page.screenshot({ path: join(opts['--report-dir'], file), fullPage, animations: 'disabled' });
    result.screenshots.push(file);
}

async function openTranscript(page, mode) {
    if (await page.locator('#transcript-panel').evaluate(el => el.hidden)) {
        await page.locator(mode === 'standalone' ? '#transcript-toggle' : '#transcript-tab').click();
    }
    await settle(page);
}

async function downloadTranscript(page, selector, result, opts, label) {
    if (!await page.locator('#reading-settings').evaluate(el => el.open)) await page.locator('#reading-settings > summary').click();
    const pending = page.waitForEvent('download');
    await page.locator(selector).click();
    const download = await pending;
    assert.equal(await download.failure(), null, 'Browser download completed');
    const file = `${result.name}-${label}${extname(download.suggestedFilename())}`;
    await download.saveAs(join(opts['--report-dir'], file));
    return { filename: file, suggestedFilename: download.suggestedFilename(), content: await readFile(join(opts['--report-dir'], file), 'utf8') };
}

function allCues(content, language) {
    const prefix = language === 'en' ? 'EN' : 'ZH';
    for (let index = 0; index < 260; index++) assert.ok(content.includes(`[${prefix}${String(index).padStart(3, '0')}]`), `Missing exported ${prefix} cue ${index}`);
    assert.equal((content.match(new RegExp(`\\[${prefix}\\d{3}\\]`, 'g')) || []).length, 260, 'Exactly 260 selected-language cues exported');
    assert.ok(!content.includes(language === 'en' ? '[ZH' : '[EN'), 'Export excludes the other language');
}

async function runPlayer(browser, folder, baselineFolder, mode, profile, opts, report, axeSource) {
    const result = { name: `${mode}-${profile.name}`, type: 'player', checks: [], axe: [], screenshots: [], browserErrors: [], blockedRequests: [] };
    report.cases.push(result);
    const context = await browser.newContext({ viewport: profile.viewport, isMobile: profile.mobile, hasTouch: profile.mobile, acceptDownloads: true });
    context.setDefaultTimeout(8000);
    const page = await context.newPage();
    page.on('pageerror', error => result.browserErrors.push(error.message));
    await context.route(/^https?:\/\//, route => { result.blockedRequests.push(route.request().url()); return route.abort(); });
    try {
        await page.goto(pathToFileURL(join(folder, 'index.html')).href);
        await page.waitForFunction(() => document.querySelector('video')?.readyState >= 1 && document.querySelector('#transcript-language')?.options.length === 2);
        await page.locator('video').evaluate(video => video.pause());
        await settle(page);
        result.defaultGeometry = await geometry(page);
        await screenshot(page, result, opts, 'default-preview');
        await step(result, 'real-media-and-default-state', async () => {
            const state = await page.locator('video').evaluate(v => ({ duration: v.duration, readyState: v.readyState, nativeTracks: v.textTracks.length }));
            assert.ok(state.duration >= 260, JSON.stringify(state));
            assert.equal(await page.locator('#transcript-follow').isChecked(), false);
            assert.equal(await page.locator('#transcript-panel').evaluate(el => el.hidden), true);
            await page.locator('video').evaluate(async v => { v.muted = true; await v.play(); });
            await page.waitForFunction(() => document.querySelector('video').currentTime > 0.1);
            await page.locator('video').evaluate(v => { v.pause(); v.muted = false; });
            await seek(page, 150.5);
            await seek(page, 0);
            return state;
        });
        if (baselineFolder) await step(result, 'default-visual-comparison', async () => {
            const baseline = await context.newPage();
            try {
                await baseline.goto(pathToFileURL(join(baselineFolder, 'index.html')).href);
                await baseline.waitForFunction(() => document.querySelector('video')?.readyState >= 1);
                await settle(baseline);
                result.baselineGeometry = await geometry(baseline);
                await baseline.screenshot({ path: join(opts['--report-dir'], `${result.name}-baseline-default.png`) });
                result.screenshots.push(`${result.name}-baseline-default.png`);
                for (const selector of ['.course-header', '#video-stage', '.player-card', '.chapter-card']) {
                    const before = result.baselineGeometry[selector], after = result.defaultGeometry[selector];
                    assert.ok(before && after, `Geometry target absent: ${selector}`);
                    // The reading-tools row can legitimately make the whole player card taller.
                    for (const key of selector === '.player-card' ? ['x', 'y', 'width'] : ['x', 'y', 'width', 'height'])
                        assert.ok(Math.abs(before[key] - after[key]) <= 2, `${selector}.${key}: ${before[key]} -> ${after[key]}`);
                    assert.equal(after.background, before.background, `${selector} default background`);
                    assert.equal(after.color, before.color, `${selector} default foreground`);
                }
            } finally { await baseline.close(); }
        });
        await step(result, 'axe-initial', () => axeScan(page, 'initial', result, axeSource));
        await step(result, 'manual-check-footer-contrast', async () => {
            // Axe cannot resolve this text's decorative pseudo-elements. For
            // the known solid page background, independently measure WCAG's
            // text ratio rather than silently treating "incomplete" as pass.
            const samples = await page.evaluate(() => {
                const rgb = value => value.match(/[\d.]+/g).slice(0, 3).map(Number);
                const luminance = values => values.map(v => { v /= 255; return v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4; })
                    .reduce((sum, value, i) => sum + value * [.2126, .7152, .0722][i], 0);
                const background = luminance(rgb(getComputedStyle(document.body).backgroundColor));
                return ['.keyboard-hints', '.keyboard-hints kbd'].map(selector => {
                    const foreground = luminance(rgb(getComputedStyle(document.querySelector(selector)).color));
                    return { selector, ratio: (Math.max(foreground, background) + .05) / (Math.min(foreground, background) + .05) };
                });
            });
            for (const sample of samples) assert.ok(sample.ratio >= 4.5, `${sample.selector}: ${sample.ratio.toFixed(2)}:1 is below 4.5:1`);
            return samples;
        });
        await step(result, 'skip-to-transcript-keyboard', async () => {
            const skip = page.locator('a[href="#transcript-heading"]').first();
            assert.equal(await skip.count(), 1, 'Transcript skip link exists');
            await skip.focus();
            await page.keyboard.press('Enter');
            assert.equal(await page.locator('#transcript-panel').evaluate(el => el.hidden), false);
            assert.equal(await page.evaluate(() => document.activeElement.id), 'transcript-heading');
        });
        await openTranscript(page, mode);
        await screenshot(page, result, opts, 'transcript-preview');
        await step(result, 'axe-transcript', () => axeScan(page, 'transcript', result, axeSource));
        await step(result, 'native-cue-seek-and-follow', async () => {
            await page.locator('.transcript-item').nth(5).click();
            await page.waitForFunction(() => Math.abs(document.querySelector('video').currentTime - 5) < 2);
            await page.locator('video').evaluate(v => v.pause());
            await page.locator('#transcript-follow').check();
            await seek(page, 250.5);
            const active = page.locator('.transcript-item[aria-current="true"]');
            assert.ok((await active.textContent()).includes('[ZH250]'));
            const visible = await active.evaluate(el => {
                const a = el.getBoundingClientRect(), b = document.querySelector('#transcript-list').getBoundingClientRect();
                return a.top >= b.top - 1 && a.bottom <= b.bottom + 1;
            });
            assert.ok(visible, 'Current cue is within the transcript scroll viewport');
        });
        await step(result, 'stage-shortcuts-native-media', async () => {
            assert.equal(await page.locator('#video-stage').getAttribute('tabindex'), '0');
            await seek(page, 100);
            await page.locator('#video-stage').focus();
            await page.keyboard.press('ArrowRight');
            await page.waitForFunction(() => Math.abs(document.querySelector('video').currentTime - 110) < 0.2);
            await page.keyboard.press('ArrowLeft');
            await page.waitForFunction(() => Math.abs(document.querySelector('video').currentTime - 100) < 0.2);
            const muted = await page.locator('video').evaluate(v => v.muted);
            await page.keyboard.press('m');
            assert.equal(await page.locator('video').evaluate(v => v.muted), !muted);
            await page.keyboard.press('Space');
            await page.waitForFunction(() => !document.querySelector('video').paused);
            await page.keyboard.press('Space');
            await page.waitForFunction(() => document.querySelector('video').paused);
            for (const modifier of ['Control', 'Meta']) {
                const before = await page.locator('video').evaluate(v => v.currentTime);
                await page.keyboard.press(`${modifier}+ArrowRight`);
                assert.ok(Math.abs((await page.locator('video').evaluate(v => v.currentTime)) - before) < 0.2, `${modifier} shortcut must remain available`);
            }
            await page.keyboard.press('f');
            try {
                await page.waitForFunction(() => Boolean(document.fullscreenElement || document.webkitFullscreenElement || document.querySelector('.is-frame-fullscreen')));
                await page.keyboard.press('Escape');
            } finally {
                // Native browser fullscreen exits asynchronously. Restore the fixture even
                // if an assertion failed, so later independent checks remain meaningful.
                await page.evaluate(async () => { if (document.fullscreenElement) await document.exitFullscreen(); });
                await page.keyboard.press('Escape');
                await settle(page);
            }
        });
        await step(result, 'form-controls-and-native-range-keys', async () => {
            await page.locator('video').evaluate(v => { v.pause(); v.muted = false; });
            await seek(page, 100);
            await page.locator('#transcript-search').fill('');
            await page.locator('#transcript-search').press('m');
            await page.locator('#transcript-search').press('Space');
            assert.equal(await page.locator('video').evaluate(v => v.muted), false);
            assert.equal(await page.locator('video').evaluate(v => v.paused), true);
            assert.equal(await page.locator('#transcript-search').inputValue(), 'm ');
            await page.locator('#transcript-search').fill('');
            const range = page.locator('#seek-slider');
            await range.focus();
            const before = Number(await range.inputValue());
            await page.keyboard.press('ArrowRight');
            assert.ok(Number(await range.inputValue()) > before, 'Range retains native arrow adjustment');
        });
        await step(result, 'speed-menu-keyboard-and-escape', async () => {
            await page.locator('#speed-button').focus();
            await page.keyboard.press('Enter');
            const first = await page.evaluate(() => document.activeElement.dataset.value);
            assert.ok(await page.evaluate(() => Boolean(document.activeElement.closest('#speed-menu'))), 'Opening speed menu places focus inside');
            await page.keyboard.press('ArrowDown');
            assert.notEqual(await page.evaluate(() => document.activeElement.dataset.value), first);
            const selectedSpeed = await page.evaluate(() => Number(document.activeElement.dataset.value));
            await page.keyboard.press('Enter');
            assert.equal(await page.locator('video').evaluate(v => v.playbackRate), selectedSpeed, 'Keyboard selection changes native playback rate');
            assert.equal(await page.locator('#speed-menu').evaluate(el => el.hidden), true);
            assert.equal(await page.evaluate(() => document.activeElement.id), 'speed-button');
            await page.locator('#speed-button').click();
            await page.keyboard.press('Escape');
            assert.equal(await page.locator('#speed-menu').evaluate(el => el.hidden), true);
            assert.equal(await page.evaluate(() => document.activeElement.id), 'speed-button');
            await page.locator('#speed-button').click();
            await page.locator('#speed-menu button[data-value="1"]').click();
            await page.locator('video').evaluate(v => v.pause());
        });
        await step(result, 'axe-caption-styles-and-escape', async () => {
            await page.locator('#caption-button').click();
            await page.locator('#caption-menu .menu-link').click();
            await axeScan(page, 'caption-styles', result, axeSource);
            await page.keyboard.press('Escape');
            assert.equal(await page.locator('#caption-menu').evaluate(el => el.hidden), true);
            assert.equal(await page.evaluate(() => document.activeElement.id), 'caption-button');
        });
        // Always close menus even when an earlier assertion reports a failure.
        await page.keyboard.press('Escape');
        await step(result, 'reading-settings-defaults-axe-and-focus', async () => {
            assert.equal(await page.locator('#reading-settings').count(), 1, 'Reading settings exist');
            assert.equal(await page.locator('#reading-settings').evaluate(el => el.open), false);
            assert.equal(await page.locator('#reading-font-size').inputValue(), '100');
            assert.equal(await page.locator('#reading-line-height').inputValue(), '1.5');
            assert.equal(await page.locator('#reading-contrast').inputValue(), 'normal');
            assert.equal(await page.locator('#reading-timestamps').isChecked(), false);
            await page.locator('#reading-settings > summary').click();
            if (!profile.mobile) assert.ok(await page.locator('.reading-settings-panel').evaluate(el => el.scrollHeight <= el.clientHeight + 1), 'Desktop settings should show all controls without unnecessary internal scrolling');
            await screenshot(page, result, opts, 'reading-panel-preview');
            await axeScan(page, 'reading-settings-open', result, axeSource);
            await page.locator('#reading-font-size').focus();
            await page.keyboard.press('Escape');
            assert.equal(await page.locator('#reading-settings').evaluate(el => el.open), false);
            assert.equal(await page.locator('#reading-settings > summary').evaluate(el => el === document.activeElement), true);
        });
        await step(result, 'reading-size-line-height-contrast-and-reset', async () => {
            assert.equal(await page.locator('#reading-settings').count(), 1, 'Reading settings exist');
            if (!await page.locator('#reading-settings').evaluate(el => el.open)) await page.locator('#reading-settings > summary').click();
            const text = page.locator('.transcript-text').first();
            const before = await text.evaluate(el => ({ size: parseFloat(getComputedStyle(el).fontSize), line: parseFloat(getComputedStyle(el).lineHeight) }));
            await page.locator('#reading-font-size').selectOption('200');
            await page.locator('#reading-line-height').selectOption('2');
            const after = await text.evaluate(el => ({ size: parseFloat(getComputedStyle(el).fontSize), line: parseFloat(getComputedStyle(el).lineHeight) }));
            assert.ok(after.size >= before.size * 1.9, `200% increases readable cue text: ${JSON.stringify({ before, after })}`);
            assert.ok(after.line >= after.size * 1.9, 'Selected line height reaches cue text');
            await page.locator('#reading-contrast').selectOption('high');
            assert.equal(await page.locator('body').getAttribute('data-reading-contrast'), 'high');
            await screenshot(page, result, opts, 'large-font-high-contrast-preview');
            await page.locator('#reading-reset').click();
            assert.equal(await page.locator('#reading-font-size').inputValue(), '100');
            assert.equal(await page.locator('#reading-line-height').inputValue(), '1.5');
            assert.equal(await page.locator('#reading-contrast').inputValue(), 'normal');
        });
        await step(result, 'all-selected-language-downloads-with-search-active', async () => {
            assert.equal(await page.locator('#transcript-download-html').count(), 1, 'HTML reading export exists');
            await page.locator('#transcript-language').selectOption('en');
            await page.locator('#transcript-search').fill('needle');
            assert.equal(await page.locator('.transcript-item').count(), 2);
            if (!await page.locator('#reading-settings').evaluate(el => el.open)) await page.locator('#reading-settings > summary').click();
            await page.locator('#reading-timestamps').uncheck();
            const html = await downloadTranscript(page, '#transcript-download-html', result, opts, 'reading-download-en');
            const txt = await downloadTranscript(page, '#transcript-download-txt', result, opts, 'reading-download-en');
            allCues(html.content, 'en'); allCues(txt.content, 'en');
            assert.equal((txt.content.match(/\[\d+:\d{2}\]/g) || []).length, 0, 'Default reading text omits cue timestamps');
            assert.ok(html.content.includes('&lt;script&gt;'), 'HTML export escapes cue markup');
            const reading = await context.newPage();
            try {
                await reading.setContent(html.content);
                assert.equal(await reading.locator('html').getAttribute('lang'), 'en');
                assert.equal(await reading.locator('h1').count(), 1);
                assert.ok((await reading.locator('h1').textContent()).includes(TITLE));
                if (mode === 'evercam') {
                    assert.equal(await reading.locator('article h2').count(), 3, 'All real chapter headings are retained');
                    for (const [index, cue] of [[1, 90], [2, 180]]) {
                        const text = await reading.locator('article h2').nth(index).evaluate(el => el.nextElementSibling.textContent);
                        assert.ok(text.startsWith(cueText('en', cue)), 'Chapter headings precede their actual cue, using millisecond chapter times');
                    }
                }
                assert.equal(await reading.locator('script').count(), 0, 'Cue HTML never creates executable elements');
                assert.equal(await reading.evaluate(() => Boolean(window.__transcriptInjected)), false);
                assert.ok((await reading.locator('body').textContent()).includes(cueText('en', 0)), 'Escaped punctuation survives as readable text');
                assert.ok(/@media\s+print|media=["']print/i.test(html.content), 'Standalone reading document has print CSS');
                await reading.emulateMedia({ media: 'print' });
                await noOverflow(reading, 'printable reading HTML');
                await screenshot(reading, result, opts, 'reading-download-preview');
                await axeScan(reading, 'reading-download-html', result, axeSource);
            } finally { await reading.close(); }
            if (!await page.locator('#reading-settings').evaluate(el => el.open)) await page.locator('#reading-settings > summary').click();
            await page.locator('#reading-timestamps').check();
            const timed = await downloadTranscript(page, '#transcript-download-txt', result, opts, 'reading-download-en-timestamps');
            allCues(timed.content, 'en');
            assert.notEqual(timed.content, txt.content, 'Timestamp option changes downloaded text');
            assert.equal((timed.content.match(/\[\d+:\d{2}\]/g) || []).length, 260, 'Each exported cue receives a timestamp when requested');
            await page.locator('#transcript-language').selectOption('zh-TW');
            const chinese = await downloadTranscript(page, '#transcript-download-html', result, opts, 'reading-download-zh');
            allCues(chinese.content, 'zh-TW');
            assert.equal(await page.evaluate(source => new DOMParser().parseFromString(source, 'text/html').documentElement.lang, chinese.content), 'zh-TW');
            result.downloads = [html, txt, timed, chinese].map(({ filename, suggestedFilename, content }) => ({ filename, suggestedFilename, bytes: Buffer.byteLength(content) }));
            await page.locator('#transcript-search').fill('');
        });
        await step(result, '320px-and-200-percent-root-font-reflow', async () => {
            await page.setViewportSize({ width: 320, height: 900 });
            await page.evaluate(() => { document.documentElement.style.fontSize = '200%'; });
            await settle(page);
            await noOverflow(page, '320px / 200% root font');
            await page.locator('#transcript-search').fill('needle');
            await page.locator('#transcript-language').selectOption('en');
            await page.locator('#transcript-search').focus();
            assert.equal(await page.evaluate(() => document.activeElement.id), 'transcript-search');
            assert.ok(await page.locator('.chapter-card').isVisible(), 'Sidebar stays available at narrow widths');
            await screenshot(page, result, opts, '320px-200percent-reflow-preview');
            await page.evaluate(() => { document.documentElement.style.fontSize = ''; });
            await page.setViewportSize(profile.viewport);
        });
        await step(result, 'forced-colors-and-reduced-motion', async () => {
            await page.emulateMedia({ forcedColors: 'active', reducedMotion: 'reduce' });
            assert.ok(await page.evaluate(() => matchMedia('(forced-colors: active)').matches && matchMedia('(prefers-reduced-motion: reduce)').matches));
            await page.locator('#transcript-search').focus();
            const focus = await page.locator('#transcript-search').evaluate(el => ({ width: getComputedStyle(el).outlineWidth, style: getComputedStyle(el).outlineStyle }));
            assert.ok(focus.style !== 'none' && parseFloat(focus.width) > 0, `Visible forced-color focus: ${JSON.stringify(focus)}`);
            const motions = await page.locator('#transcript-list').evaluate(el => ({ behavior: getComputedStyle(el).scrollBehavior,
                animations: document.getAnimations().filter(a => a.playState === 'running').length }));
            assert.notEqual(motions.behavior, 'smooth', 'Reduced-motion transcript scrolling is immediate');
            assert.equal(motions.animations, 0, 'No continuous animations under reduced motion');
            await page.locator('#transcript-follow').check();
            await seek(page, 250.5);
            await noOverflow(page, 'forced colors');
            await screenshot(page, result, opts, 'forced-colors-reduced-motion-preview');
            await page.emulateMedia({ forcedColors: 'none', reducedMotion: 'no-preference' });
        });
        await step(result, 'no-browser-errors-or-external-requests', async () => {
            assert.deepEqual(result.browserErrors, []);
            assert.deepEqual(result.blockedRequests, []);
        });
    } catch (error) { result.checks.push({ label: 'fixture-load', status: 'failed', error: error.stack || String(error) }); }
    finally {
        result.status = result.checks.some(c => c.status === 'failed') ? 'failed' : 'passed';
        await context.close();
        console.log(`${result.status.toUpperCase()} ${result.name}: ${result.checks.filter(c => c.status === 'failed').map(c => c.label).join(', ') || `${result.checks.length} checks`}`);
    }
}

async function htmlFiles(folder, prefix = '') {
    const found = [];
    for (const entry of await readdir(folder, { withFileTypes: true })) {
        if (entry.isDirectory()) found.push(...await htmlFiles(join(folder, entry.name), `${prefix}${entry.name}/`));
        else if (entry.name.endsWith('.html')) found.push(`${prefix}${entry.name}`);
    }
    return found;
}

async function serve(folder) {
    const home = await readFile(join(folder, 'index.html'), 'utf8');
    const stylesheet = home.match(/<link\b[^>]*rel="stylesheet"[^>]*href="([^"]+)"/i)?.[1];
    assert.ok(stylesheet, 'Built website has a stylesheet');
    const basePath = stylesheet.includes('/assets/') ? stylesheet.slice(0, stylesheet.indexOf('/assets/') + 1) : '/';
    const types = { '.html': 'text/html; charset=utf-8', '.css': 'text/css', '.js': 'text/javascript', '.svg': 'image/svg+xml', '.png': 'image/png', '.woff2': 'font/woff2' };
    const server = createServer(async (request, response) => {
        try {
            const requested = decodeURIComponent(new URL(request.url, 'http://localhost').pathname);
            const localPath = requested.startsWith(basePath) ? requested.slice(basePath.length) : requested.slice(1);
            let path = resolve(folder, localPath);
            assert.ok(path === folder || path.startsWith(folder + sep));
            if ((await stat(path)).isDirectory()) path = join(path, 'index.html');
            response.writeHead(200, { 'Content-Type': types[extname(path)] || 'application/octet-stream' });
            response.end(await readFile(path));
        } catch { response.writeHead(404); response.end('Not found'); }
    });
    await new Promise(done => server.listen(0, '127.0.0.1', done));
    return { url: `http://127.0.0.1:${server.address().port}`, basePath, close: () => new Promise(done => server.close(done)) };
}

async function runWebsite(browser, siteDir, opts, report, axeSource) {
    const server = await serve(siteDir);
    try {
        for (const file of await htmlFiles(siteDir)) for (const profile of PROFILES) {
            const result = { name: `website-${file.replace(/[^a-z0-9]+/gi, '-')}-${profile.name}`, type: 'website', checks: [], axe: [], screenshots: [], browserErrors: [], blockedRequests: [] };
            report.cases.push(result);
            const context = await browser.newContext({ viewport: profile.viewport, isMobile: profile.mobile, hasTouch: profile.mobile });
            const page = await context.newPage();
            page.on('pageerror', error => result.browserErrors.push(error.message));
            page.on('response', response => { if (response.status() >= 400) result.browserErrors.push(`HTTP ${response.status()}: ${response.url()}`); });
            await context.route('**/*', route => {
                if (route.request().url().startsWith(server.url + '/')) return route.continue();
                result.blockedRequests.push(route.request().url()); return route.abort();
            });
            try {
                await page.goto(`${server.url}${server.basePath}${file}`);
                await step(result, 'built-stylesheet-loaded', async () => {
                    assert.ok(await page.evaluate(() => [...document.styleSheets].some(sheet => sheet.href && sheet.cssRules.length > 0)), 'Built CSS loads before accessibility inspection');
                });
                await step(result, 'axe-built-website', () => axeScan(page, 'website-default', result, axeSource));
                await step(result, 'skip-link-keyboard-focus', async () => {
                    await page.keyboard.press('Tab');
                    assert.equal(await page.evaluate(() => document.activeElement.classList.contains('skip-link')), true);
                    await page.keyboard.press('Enter');
                    assert.equal(await page.evaluate(() => document.activeElement === document.querySelector(document.querySelector('.skip-link').hash)), true);
                });
                await screenshot(page, result, opts, 'preview');
                await step(result, '320px-200-percent-root-font-reflow', async () => {
                    await page.setViewportSize({ width: 320, height: 900 });
                    await page.evaluate(() => { document.documentElement.style.fontSize = '200%'; });
                    await settle(page);
                    await noOverflow(page, 'website 320px / 200% root font');
                    for (const el of await page.locator('table, pre').all()) {
                        assert.ok(await el.evaluate(node => Boolean(node.closest('[role="region"][tabindex="0"][aria-labelledby]'))), 'Wide tables/code have named keyboard scroll containers');
                    }
                    await screenshot(page, result, opts, '320px-200percent-reflow-preview');
                });
                await step(result, 'no-page-errors-or-external-requests', async () => {
                    assert.deepEqual(result.browserErrors, []); assert.deepEqual(result.blockedRequests, []);
                });
            } catch (error) { result.checks.push({ label: 'website-load', status: 'failed', error: error.stack || String(error) }); }
            finally {
                result.status = result.checks.some(c => c.status === 'failed') ? 'failed' : 'passed';
                await context.close();
                console.log(`${result.status.toUpperCase()} ${result.name}: ${result.checks.filter(c => c.status === 'failed').map(c => c.label).join(', ') || `${result.checks.length} checks`}`);
            }
        }
    } finally { await server.close(); }
}

async function main() {
    const opts = options(process.argv.slice(2));
    if (opts['--help']) { console.log(usage); return; }
    await mkdir(opts['--report-dir'], { recursive: true });
    const fixtureRoot = await mkdtemp(join(tmpdir(), 'vts-a11y-browser-'));
    const report = { schemaVersion: 1, createdAt: new Date().toISOString(), syntheticOnly: true,
        sourceRoot: opts['--source-root'], baselineRoot: opts['--baseline-root'] || null, fixtureRoot,
        mediaMode: 'native Chromium MP4 decoding, playback, and seeks', accessibilityTags: TAGS,
        limitations: ['Axe incomplete results require human review.', 'No screen-reader, operating-system zoom, or physical mobile-device certification.'], cases: [] };
    let browser;
    try {
        const require = createRequire(join(root, 'tests/browser/package.json'));
        const { chromium } = require('playwright');
        const axeSource = await readFile(require.resolve('axe-core/axe.min.js'), 'utf8');
        report.playwrightVersion = require('playwright/package.json').version;
        report.axeVersion = require('axe-core/package.json').version;
        browser = await chromium.launch({ headless: true, ...(opts['--chromium'] ? { executablePath: opts['--chromium'] } : {}) });
        report.chromiumVersion = browser.version();
        for (const mode of ['standalone', 'evercam']) {
            const folder = await fixture(fixtureRoot, opts['--source-root'], mode, opts['--media']);
            const baseline = opts['--baseline-root'] ? await fixture(fixtureRoot, opts['--baseline-root'], mode, opts['--media'], '-baseline') : null;
            for (const profile of PROFILES) await runPlayer(browser, folder, baseline, mode, profile, opts, report, axeSource);
        }
        const siteDir = opts['--site-dir'] || join(opts['--source-root'], 'website/dist');
        try { await stat(siteDir); await runWebsite(browser, siteDir, opts, report, axeSource); }
        catch (error) { if (opts['--site-dir'] || error.code !== 'ENOENT') throw error; report.website = 'not built; omitted'; }
        report.status = report.cases.every(result => result.status === 'passed') ? 'passed' : 'failed';
    } catch (error) { report.status = 'failed'; report.error = error.stack || String(error); }
    finally {
        if (browser) await browser.close();
        report.summary = { cases: report.cases.length, failedChecks: report.cases.flatMap(c => c.checks).filter(c => c.status === 'failed').length,
            axeViolationRules: report.cases.flatMap(c => c.axe).flatMap(scan => scan.violations).length,
            axeIncompleteRules: report.cases.flatMap(c => c.axe).flatMap(scan => scan.incomplete).length };
        await writeFile(join(opts['--report-dir'], 'report.json'), JSON.stringify(report, null, 2) + '\n');
    }
    console.log(`Report: ${join(opts['--report-dir'], 'report.json')}`);
    console.log(JSON.stringify(report.summary));
    if (report.status !== 'passed') { if (report.error) console.error(report.error); process.exitCode = 1; }
}

main().catch(error => { console.error(error.stack || String(error)); console.error(usage); process.exitCode = 1; });
