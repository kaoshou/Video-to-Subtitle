#!/usr/bin/env node
/** Real Chromium geometry smoke for trusted, synthetic shipped-player fixtures.
 * npm ci --prefix tests/browser
 * PLAYWRIGHT_BROWSERS_PATH=/isolated/path node scripts/smoke_player_browser.mjs \
 *   --report-dir /tmp/player-report --media /tmp/synthetic-270-second.mp4
 * Use --mock-media explicitly when testing layout without a media codec. This
 * controls currentTime/events only; Chromium still computes all layout/scrolling.
 */
import assert from 'node:assert/strict';
import { cp, mkdir, mkdtemp, readFile, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const help = `Usage: node scripts/smoke_player_browser.mjs --report-dir DIR (--media FILE | --mock-media)
  --media FILE          Trusted synthetic video, at least 260 seconds, copied into fixtures
  --mock-media          Explicit media-event/currentTime control; no decoding claim
  --report-dir DIR      JSON and screenshots destination (required)
  --chromium FILE       Optional isolated Chromium executable (not a user browser)
  --negative-control    Disable scrolling in fixture copies only; smoke must fail
  --help                Show this usage
Uses pinned Playwright installed under tests/browser and its isolated headless Chromium.
Fixtures and screenshots contain synthetic data only; no network access is allowed.`;

function options(argv) {
    const result = {};
    for (let index = 0; index < argv.length; index++) {
        const key = argv[index];
        if (['--help', '--mock-media', '--negative-control'].includes(key)) result[key] = true;
        else if (['--report-dir', '--media', '--chromium'].includes(key)) {
            assert.ok(argv[index + 1] && !argv[index + 1].startsWith('--'), `${key} needs a value`);
            result[key] = resolve(argv[++index]);
        } else throw new Error(`Unknown option: ${key}`);
    }
    if (result['--help']) return result;
    assert.ok(result['--report-dir'], '--report-dir is required');
    assert.ok(Boolean(result['--media']) !== Boolean(result['--mock-media']), 'Choose exactly one of --media or --mock-media');
    return result;
}

async function fixture(parent, mode, opts) {
    const folder = join(parent, mode);
    await mkdir(folder, { recursive: true });
    await cp(join(root, 'assets/evercam_player/css'), join(folder, 'css'), { recursive: true });
    await cp(join(root, 'assets/evercam_player/js'), join(folder, 'js'), { recursive: true });
    const template = await readFile(join(root, `assets/${mode === 'standalone' ? 'standalone_player' : 'evercam_player'}/index.html`), 'utf8');
    await writeFile(join(folder, 'index.html'), template.replace('{{TITLE}}', 'Synthetic transcript geometry smoke'));
    const config = { title: 'Synthetic transcript geometry smoke', packageId: `browser-smoke-${mode}`,
        duration: 270, defaultSubtitle: 'zh-TW', src: [{ src: 'media.mp4', type: 'video/mp4' }],
        index: [{ time: 0, title: 'Synthetic chapter' }] };
    if (mode === 'standalone') config.mode = 'standalone';
    await writeFile(join(folder, mode === 'standalone' ? 'player-config.js' : 'config.js'),
        `window.${mode === 'standalone' ? 'VTS_PLAYER_CONFIG' : 'config'} = ${JSON.stringify(config)};\n`);
    const tracks = ['zh-TW', 'en'].map(language => ({ language, cues: Array.from({ length: 260 }, (_, index) => ({
        start: index, end: index + 0.9,
        text: `${language === 'en' ? 'English' : '合成字幕'} cue ${index} — ${index < 2 ? 'needle' : 'sample'} transcript text`
    })) }));
    await writeFile(join(folder, 'subtitles-data.js'), `window.EVERCAM_SUBTITLES = ${JSON.stringify({ tracks })};\n`);
    if (opts['--media']) await cp(opts['--media'], join(folder, 'media.mp4'));
    if (opts['--negative-control']) {
        const scriptPath = join(folder, 'js/evercam-modern.js');
        const script = await readFile(scriptPath, 'utf8');
        assert.ok(script.includes('transcriptList.scrollTop = Math.max('), 'Negative control target missing');
        await writeFile(scriptPath, script.replace('transcriptList.scrollTop = Math.max(', 'void Math.max('));
    }
    return folder;
}

// The media double leaves HTMLVideoElement/text tracks, DOM, CSS, focus, and all
// player handlers intact. No geometry methods or scrolling APIs are replaced.
function controlledMedia() {
    const descriptor = Object.getOwnPropertyDescriptor(HTMLMediaElement.prototype, 'currentTime');
    Object.defineProperty(HTMLMediaElement.prototype, 'currentTime', {
        configurable: true,
        get() { return this.__smokeTime ?? 0; },
        set(value) { this.__smokeTime = Number(value); }
    });
    window.__smokeMediaControlled = Boolean(descriptor);
}

async function settle(page) {
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
}

async function state(page) {
    return page.evaluate(() => {
        const list = document.querySelector('#transcript-list');
        const active = list.querySelector('.transcript-item[aria-current="true"]');
        const rect = element => {
            if (!element) return null;
            const { top, bottom, left, right, width, height } = element.getBoundingClientRect();
            return { top, bottom, left, right, width, height };
        };
        return { scrollY, scrollX, listScrollTop: list.scrollTop, listClientHeight: list.clientHeight,
            listRect: rect(list), activeRect: rect(active), activeText: active?.textContent ?? null,
            rows: list.querySelectorAll('.transcript-item').length,
            follow: document.querySelector('#transcript-follow').checked,
            language: document.querySelector('#transcript-language').value,
            panelHidden: document.querySelector('#transcript-panel').hidden,
            hintHidden: document.querySelector('#transcript-follow-hint').hidden,
            time: document.querySelector('video').currentTime,
            textTrackModes: [...document.querySelector('video').textTracks].map(track => track.mode),
            documentHeight: document.documentElement.scrollHeight,
            maximumPageScrollY: document.documentElement.scrollHeight - innerHeight,
            paginationRect: rect(document.querySelector('.transcript-pagination')),
            viewport: { width: innerWidth, height: innerHeight } };
    });
}

function visibleCue(snapshot, expected, label) {
    assert.ok(snapshot.activeText?.includes(expected), `${label}: expected ${expected}, got ${snapshot.activeText}`);
    assert.ok(snapshot.rows <= 100, `${label}: ${snapshot.rows} rows exceeds bounded follow window`);
    assert.ok(snapshot.listClientHeight > 0, `${label}: transcript viewport has no height`);
    assert.ok(snapshot.activeRect.height > 0, `${label}: active row has no height`);
    assert.ok(snapshot.activeRect.top >= snapshot.listRect.top - 1 && snapshot.activeRect.bottom <= snapshot.listRect.bottom + 1,
        `${label}: active row outside real transcript viewport (${JSON.stringify(snapshot)})`);
}

async function seek(page, time, mocked) {
    await page.evaluate(async ({ time, mocked }) => {
        const video = document.querySelector('video');
        if (mocked) {
            video.currentTime = time;
            video.dispatchEvent(new Event('timeupdate'));
            video.dispatchEvent(new Event('seeked'));
        } else {
            await new Promise((resolve, reject) => {
                const timer = setTimeout(() => { video.removeEventListener('seeked', done); reject(new Error(`Native seek timed out at ${time}`)); }, 10000);
                function done() { clearTimeout(timer); resolve(); }
                video.addEventListener('seeked', done, { once: true });
                video.currentTime = time;
            });
        }
    }, { time, mocked });
    await settle(page);
}

// DOM clicks avoid Playwright's own scroll-into-view changing the measured page
// position. The shipped control click/change handlers still receive real events.
async function click(page, selector) {
    await page.locator(selector).evaluate(element => element.click());
    await settle(page);
}

async function runCase(browser, folder, mode, profile, opts, report) {
    const name = `${mode}-${profile.name}`;
    const result = { name, status: 'running', checkpoints: [], browserErrors: [], blockedRequests: [] };
    report.cases.push(result);
    const context = await browser.newContext({ viewport: profile.viewport, isMobile: profile.mobile, hasTouch: profile.mobile });
    const page = await context.newPage();
    page.on('pageerror', error => result.browserErrors.push(error.message));
    await context.route(/^https?:\/\//, route => { result.blockedRequests.push(route.request().url()); return route.abort(); });
    if (opts['--mock-media']) await page.addInitScript(controlledMedia);
    const capture = async (label, screenshot = false) => {
        const snapshot = await state(page);
        result.checkpoints.push({ label, ...snapshot });
        if (screenshot) {
            const file = `${name}-${label}.png`;
            // Full-page mobile screenshots resize Chromium's viewport and can
            // alter scrollY. Keep the viewport fixed while measuring scrolling.
            await page.screenshot({ path: join(opts['--report-dir'], file), fullPage: false });
            result.checkpoints.at(-1).screenshot = file;
        }
        return snapshot;
    };
    const show = mode === 'standalone' ? '#transcript-toggle' : '#transcript-tab';
    const hide = mode === 'standalone' ? '#transcript-toggle' : '#chapters-tab';
    try {
        await page.goto(pathToFileURL(join(folder, 'index.html')).href, { waitUntil: 'load' });
        await page.waitForFunction(() => document.querySelector('#transcript-language').options.length === 2);
        if (!opts['--mock-media']) {
            await page.waitForFunction(() => document.querySelector('video').readyState >= 1, undefined, { timeout: 15000 });
            const media = await page.locator('video').evaluate(video => ({ duration: video.duration, readyState: video.readyState }));
            assert.ok(media.duration >= 260, `Synthetic video must be at least 260 seconds, got ${media.duration}`);
            result.media = media;
            await page.locator('video').evaluate(async video => { video.muted = true; await video.play(); });
            await page.waitForFunction(() => document.querySelector('video').currentTime > 0.1, undefined, { timeout: 10000 });
            await page.locator('video').evaluate(video => video.pause());
            result.nativePlaybackAdvanced = true;
        }
        const initial = await capture('initial');
        assert.equal(initial.follow, false, 'Follow must default off');
        assert.equal(initial.panelHidden, mode !== 'standalone', 'MP4 starts with transcript; EverCam starts with chapters');
        if (mode !== 'standalone') await click(page, show);
        await page.locator('#transcript-list').evaluate(list => list.scrollIntoView({ block: 'center' }));
        await settle(page);
        const beforeOff = await capture('opened-default-off');
        assert.equal(beforeOff.rows, 100, 'Initial transcript renders first 100 cues');
        await seek(page, 150.5, opts['--mock-media']);
        const off = await capture('seek-default-off');
        assert.equal(off.listScrollTop, beforeOff.listScrollTop, 'Default off must leave transcript scroll unchanged');
        assert.equal(off.scrollY, beforeOff.scrollY, 'Default-off seek must leave page scroll unchanged');
        assert.equal(off.activeText, null, 'Cue 150 is beyond initial window until following is enabled');
        const beforeFollow = await state(page);
        await click(page, '#transcript-follow');
        const followed = await capture('follow-cue-150', true);
        visibleCue(followed, 'cue 150', name);
        assert.ok(followed.listScrollTop > 0, 'Following must scroll the transcript list');
        assert.equal(followed.scrollY, beforeFollow.scrollY, 'Following must never scroll the page');
        await seek(page, 150.6, opts['--mock-media']);
        const sameCue = await capture('same-cue');
        assert.equal(sameCue.listScrollTop, followed.listScrollTop, 'Visible current cue should not move again');
        assert.equal(sameCue.scrollY, followed.scrollY, 'Same cue must not scroll the page');
        for (const [time, cue] of [[5.5, 5], [250.5, 250]]) {
            const before = await state(page);
            await seek(page, time, opts['--mock-media']);
            const jumped = await capture(`follow-cue-${cue}`);
            visibleCue(jumped, `cue ${cue}`, name);
            assert.equal(jumped.scrollY, before.scrollY, 'Distant follow seek must leave page scroll unchanged');
        }
        await page.locator('#transcript-search').fill('needle');
        await settle(page);
        const searchBefore = await capture('search-before-seek');
        await seek(page, 150.5, opts['--mock-media']);
        const search = await capture('search-suspended', true);
        assert.equal(search.rows, 2, 'Search results remain limited to matching cues');
        assert.equal(search.listScrollTop, searchBefore.listScrollTop, 'Search must suspend list following');
        assert.equal(search.scrollY, searchBefore.scrollY, 'Search seek must not scroll the page');
        assert.equal(search.hintHidden, false, 'Search suspension hint should be visible');
        await click(page, '#transcript-clear');
        const cleared = await capture('search-clear-resumed');
        visibleCue(cleared, 'cue 150', name);
        assert.equal(cleared.scrollY, search.scrollY, 'Resuming after search must scroll only the transcript');
        assert.equal(cleared.follow, true, 'Clearing search preserves follow selection');
        assert.equal(cleared.hintHidden, true, 'Clearing search removes suspension hint');
        await click(page, '#caption-button');
        await click(page, '#caption-menu button[data-value="off"]');
        await page.locator('#transcript-language').selectOption('en');
        await settle(page);
        const language = await capture('english-captions-off');
        visibleCue(language, 'English cue 150', name);
        assert.equal(language.language, 'en');
        assert.ok(language.textTrackModes.every(mode => mode === 'disabled'), 'Captions remain off while English transcript follows');
        const resizedViewport = profile.mobile ? { width: 844, height: 390 } : { width: 1100, height: 620 };
        await page.setViewportSize(resizedViewport);
        await settle(page);
        const resized = await capture('resized');
        visibleCue(resized, 'English cue 150', name);
        assert.ok(Math.abs(resized.time - 150.5) < 0.01, 'Resize must preserve playback time');
        // Position the page deliberately for a useful landscape screenshot,
        // after checking the resize result; this is not automatic following.
        await page.locator('#transcript-list').evaluate(list => list.scrollIntoView({ block: 'center' }));
        await settle(page);
        visibleCue(await capture('resize-visible', true), 'English cue 150', name);
        await click(page, hide);
        const hiddenBefore = await capture('hidden-before-seek');
        await seek(page, 5.5, opts['--mock-media']);
        const hidden = await capture('hidden-after-seek');
        assert.equal(hidden.panelHidden, true, 'Hidden panel must not open on seek');
        assert.equal(hidden.listScrollTop, hiddenBefore.listScrollTop, 'Hidden panel must not scroll on seek');
        assert.equal(hidden.scrollY, hiddenBefore.scrollY, 'Hidden panel seek must not scroll page');
        await click(page, show);
        visibleCue(await capture('reopened'), 'English cue 5', name);
        await click(page, '#transcript-follow');
        const disabledBefore = await state(page);
        await seek(page, 150.5, opts['--mock-media']);
        const disabled = await capture('unchecked');
        assert.equal(disabled.follow, false);
        assert.equal(disabled.listScrollTop, disabledBefore.listScrollTop, 'Unchecking must stop following');
        assert.equal(disabled.scrollY, disabledBefore.scrollY, 'Unchecked seek must not scroll page');
        assert.deepEqual(result.browserErrors, [], 'No JavaScript page errors');
        assert.deepEqual(result.blockedRequests, [], 'Shipped player must not request network resources');
        result.status = 'passed';
    } catch (error) {
        result.status = 'failed';
        result.error = error.stack || String(error);
        try { await capture('failure', true); } catch { /* Preserve original failure. */ }
    } finally {
        await context.close();
    }
    console.log(`${result.status.toUpperCase()} ${name}${result.error ? `: ${result.error.split('\n')[0]}` : ''}`);
}

async function main() {
    const opts = options(process.argv.slice(2));
    if (opts['--help']) { console.log(help); return; }
    await mkdir(opts['--report-dir'], { recursive: true });
    const fixtureRoot = await mkdtemp(join(tmpdir(), 'vts-browser-smoke-'));
    const report = { schemaVersion: 1, createdAt: new Date().toISOString(),
        syntheticOnly: true, geometry: 'real headless Chromium DOM/CSS bounding rectangles',
        mediaMode: opts['--mock-media'] ? 'controlled currentTime and media events; decoding not tested' : 'native synthetic video playback and seeks',
        negativeControl: Boolean(opts['--negative-control']), fixtureRoot, cases: [] };
    let browser;
    try {
        const require = createRequire(join(root, 'tests/browser/package.json'));
        const { chromium } = require('playwright');
        report.playwrightVersion = require('playwright/package.json').version;
        browser = await chromium.launch({ headless: true, ...(opts['--chromium'] ? { executablePath: opts['--chromium'] } : {}) });
        report.chromiumVersion = browser.version();
        for (const mode of ['standalone', 'evercam']) {
            const folder = await fixture(fixtureRoot, mode, opts);
            for (const profile of [
                { name: 'desktop', viewport: { width: 1440, height: 1000 }, mobile: false },
                { name: 'mobile', viewport: { width: 390, height: 844 }, mobile: true }
            ]) await runCase(browser, folder, mode, profile, opts, report);
        }
        report.status = report.cases.every(result => result.status === 'passed') ? 'passed' : 'failed';
    } catch (error) {
        report.status = 'failed'; report.error = error.stack || String(error);
    } finally {
        if (browser) await browser.close();
        await writeFile(join(opts['--report-dir'], 'report.json'), `${JSON.stringify(report, null, 2)}\n`);
    }
    console.log(`Report: ${join(opts['--report-dir'], 'report.json')}`);
    console.log(`Media: ${report.mediaMode}`);
    if (report.status !== 'passed') { if (report.error) console.error(report.error); process.exitCode = 1; }
}

main().catch(error => { console.error(error.message); console.error(help); process.exitCode = 1; });
