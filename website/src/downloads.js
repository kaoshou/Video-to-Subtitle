/* Versioned filenames without version-pinned website links or duplicate assets.
   Without JS/network/API quota, the original latest-release links still work. */
(async function () {
    'use strict';
    const links = [...document.querySelectorAll('[data-release-platform]')];
    if (!links.length) return;
    const repository = 'https://github.com/kaoshou/Video-to-Subtitle';
    const suffixes = {
        'windows-portable': 'Windows_x64_Portable.zip',
        'windows-setup': 'Windows_x64_Setup.exe',
        'macos': 'macOS_arm64.dmg'
    };
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 5000);
    try {
        const response = await fetch('https://api.github.com/repos/kaoshou/Video-to-Subtitle/releases/latest',
            {signal: controller.signal, headers: {Accept: 'application/vnd.github+json'}});
        if (!response.ok) return;
        const release = await response.json();
        if (!release || release.draft !== false || release.prerelease !== false ||
                !/^v\d+\.\d+\.\d+$/.test(release.tag_name) || !Array.isArray(release.assets)) return;
        for (const link of links) {
            const suffix = suffixes[link.dataset.releasePlatform];
            if (!suffix) continue;
            const name = `VideoToSubtitle_${release.tag_name}_${suffix}`;
            const expected = `${repository}/releases/download/${release.tag_name}/${name}`;
            const asset = release.assets.find(item => item && item.name === name &&
                item.state === 'uploaded' && item.browser_download_url === expected);
            if (asset) link.href = expected;
        }
    } catch {
        // Keep functional, keyboard-accessible links to the latest release.
    } finally {
        clearTimeout(timer);
    }
})();
