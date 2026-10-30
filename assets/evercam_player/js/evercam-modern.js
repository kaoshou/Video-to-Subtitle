// EverCam Subtitle Player: https://github.com/kaoshou/evercam-subtitle-player
(function () {
    "use strict";

    // 章節標題顯示行數：設為 1、2、3……；超出的文字會以省略號收合。
    var CHAPTER_TITLE_LINES = 1;

    var languageLabels = {
        "zh-TW": "正體中文",
        "zh-CN": "簡體中文",
        "zh-Hant": "正體中文",
        "zh-Hans": "簡體中文",
        en: "English",
        ja: "日本語",
        ko: "한국어",
        es: "Español",
        fr: "Français",
        de: "Deutsch",
        vi: "Tiếng Việt",
        th: "ไทย",
        id: "Bahasa Indonesia",
        ms: "Bahasa Melayu"
    };
    var speedOptions = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 2, 3, 5];

    var courseConfig = window.VTS_PLAYER_CONFIG || window.config || {};
    var standalone = courseConfig.mode === "standalone";
    var subtitleData = window.EVERCAM_SUBTITLES || { tracks: [] };
    var chapters = Array.isArray(courseConfig.index) ? courseConfig.index : [];
    var chapterTitleLines = Math.max(1, Math.floor(Number(CHAPTER_TITLE_LINES) || 1));
    var hideChapterNumbers = courseConfig.hideSN === true ||
        Number(courseConfig.hideSN) === 1 ||
        String(courseConfig.hideSN).toLowerCase() === "true";
    var playerCard = document.querySelector(".player-card");
    var chapterCard = document.querySelector(".chapter-card");
    var video = document.getElementById("course-video");
    var videoStage = document.getElementById("video-stage");
    var captionOverlay = document.getElementById("caption-overlay");
    var captionText = document.getElementById("caption-text");
    var loadingSpinner = document.getElementById("loading-spinner");
    var bigPlay = document.getElementById("big-play");
    var playToggle = document.getElementById("play-toggle");
    var muteToggle = document.getElementById("mute-toggle");
    var volumeSlider = document.getElementById("volume-slider");
    var seekSlider = document.getElementById("seek-slider");
    var currentTimeLabel = document.getElementById("current-time");
    var totalTimeLabel = document.getElementById("total-time");
    var courseMeta = document.getElementById("course-meta");
    var courseAuthor = document.getElementById("course-author");
    var courseDuration = document.getElementById("course-duration");
    var fullscreenToggle = document.getElementById("fullscreen-toggle");
    var captionMenuWrap = document.getElementById("caption-menu-wrap");
    var captionButton = document.getElementById("caption-button");
    var captionMenu = document.getElementById("caption-menu");
    var speedButton = document.getElementById("speed-button");
    var speedMenu = document.getElementById("speed-menu");
    var pipToggle = document.getElementById("pip-toggle");
    var chapterList = document.getElementById("chapter-list");
    var chapterEmpty = document.getElementById("chapter-empty");
    var chaptersTab = document.getElementById("chapters-tab");
    var transcriptTab = document.getElementById("transcript-tab");
    var chaptersPanel = document.getElementById("chapters-panel");
    var transcriptPanel = document.getElementById("transcript-panel");
    var transcriptSearch = document.getElementById("transcript-search");
    var transcriptLanguage = document.getElementById("transcript-language");
    var transcriptList = document.getElementById("transcript-list");
    var transcriptStatus = document.getElementById("transcript-status");
    var transcriptMore = document.getElementById("transcript-more");
    var transcriptPrevious = document.getElementById("transcript-previous");
    var transcriptFollow = document.getElementById("transcript-follow");
    var transcriptFollowHint = document.getElementById("transcript-follow-hint");
    var transcriptTracks = [];
    var transcriptMatches = [];
    var transcriptVisibleCount = 100;
    var transcriptVisibleStart = 0;
    var transcriptLastFollowCue = null;
    var transcriptRows = [];
    var readingSettings = document.getElementById("reading-settings");
    var readingAppearance = loadReadingAppearance();
    var chapterButtons = [];
    var nativeTracks = [];
    var activeSubtitleLanguage = "off";
    var preparingPictureInPicture = false;
    var activeChapterIndex = -1;
    var controlsTimer = null;
    var subtitleStorageKey = standalone
        ? "vts.subtitle." + String(courseConfig.packageId)
        : "evercam.subtitle." + String(courseConfig.title || "course");
    var captionAppearanceStorageKey = "evercam.captionAppearance";
    var captionAppearance = loadCaptionAppearance();
    var captionAppearanceStyle = document.createElement("style");
    var captionLanguageView = null;
    var captionStyleView = null;
    document.head.appendChild(captionAppearanceStyle);

    function formatTime(totalSeconds) {
        var seconds = Math.max(0, Math.floor(Number(totalSeconds) || 0));
        var hours = Math.floor(seconds / 3600);
        var minutes = Math.floor((seconds % 3600) / 60);
        var remainder = seconds % 60;
        var parts = [];

        if (hours > 0) {
            parts.push(String(hours));
            parts.push(String(minutes).padStart(2, "0"));
        } else {
            parts.push(String(minutes));
        }
        parts.push(String(remainder).padStart(2, "0"));
        return parts.join(":");
    }

    function readPreference(key) {
        try {
            return window.localStorage.getItem(key);
        } catch (error) {
            return null;
        }
    }

    function savePreference(key, value) {
        try {
            window.localStorage.setItem(key, value);
        } catch (error) {
            // Local playback continues when a browser blocks file-based storage.
        }
    }

    function loadCaptionAppearance() {
        var defaults = { size: "100", theme: "white-black", position: "bottom" };
        var stored = readPreference("evercam.captionAppearance");
        if (!stored) {
            return defaults;
        }

        try {
            var parsed = JSON.parse(stored);
            if (["75", "100", "125", "150", "200"].indexOf(String(parsed.size)) !== -1) {
                defaults.size = String(parsed.size);
            }
            if (["white-black", "yellow-black", "black-white", "white-shadow"].indexOf(parsed.theme) !== -1) {
                defaults.theme = parsed.theme;
            }
            if (["bottom", "middle", "top"].indexOf(parsed.position) !== -1) {
                defaults.position = parsed.position;
            }
        } catch (error) {
            return defaults;
        }
        return defaults;
    }

    function loadReadingAppearance() {
        var value = { size: "100", lineHeight: "1.5", contrast: "normal" };
        try {
            var saved = JSON.parse(readPreference("vts.readingAppearance"));
            if (!saved || typeof saved !== "object") { return value; }
            if (["100", "125", "150", "200"].indexOf(String(saved.size)) !== -1) { value.size = String(saved.size); }
            if (["1.5", "1.8", "2"].indexOf(String(saved.lineHeight)) !== -1) { value.lineHeight = String(saved.lineHeight); }
            if (["normal", "high"].indexOf(saved.contrast) !== -1) { value.contrast = saved.contrast; }
        } catch (error) { /* Unavailable storage does not prevent offline use. */ }
        return value;
    }

    function applyReadingAppearance() {
        transcriptList.style.setProperty("--reading-size", String(Number(readingAppearance.size) / 100));
        transcriptList.style.setProperty("--reading-line-height", readingAppearance.lineHeight);
        document.body.dataset.readingContrast = readingAppearance.contrast;
        document.getElementById("reading-font-size").value = readingAppearance.size;
        document.getElementById("reading-line-height").value = readingAppearance.lineHeight;
        document.getElementById("reading-contrast").value = readingAppearance.contrast;
        savePreference("vts.readingAppearance", JSON.stringify(readingAppearance));
        syncChapterHeight();
        updateTranscriptPosition(true);
    }

    function selectedTranscriptTrack() {
        return transcriptTracks.find(function (track) { return track.language === transcriptLanguage.value; });
    }

    function syncTranscriptDownloads() {
        var track = selectedTranscriptTrack();
        ["transcript-download-html", "transcript-download-txt"].forEach(function (id) {
            var button = document.getElementById(id);
            if (button) { button.disabled = !track || !track.cues.length; }
        });
    }

    function escapeReadingHtml(value) {
        return String(value).replace(/[&<>"']/g, function (character) {
            return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[character];
        });
    }

    function readingDocument(track, timestamps, html) {
        var title = String(courseConfig.title || "未命名課程");
        var sections = standalone ? [] : chapters.map(function (chapter) {
            return { start: chapterStartSeconds(chapter), title: String(chapter.title || "未命名章節") };
        }).sort(function (a, b) { return a.start - b.start; });
        var content = [], paragraph = [], paragraphLength = 0, nextSection = 0, previousEnd = 0;
        function flush() {
            if (!paragraph.length) { return; }
            content.push(html ? "<p>" + paragraph.join(" ") + "</p>" : paragraph.join(" "));
            paragraph = []; paragraphLength = 0;
        }
        track.cues.forEach(function (cue) {
            while (nextSection < sections.length && sections[nextSection].start <= cue.start) {
                flush();
                content.push(html ? "<h2>" + escapeReadingHtml(sections[nextSection].title) + "</h2>" : sections[nextSection].title);
                nextSection += 1;
            }
            if (paragraphLength >= 240 || cue.start - previousEnd > 2) { flush(); }
            var text = cue.text.replace(/\r?\n/g, " ");
            var time = formatTime(cue.start);
            var prefix = timestamps ? (html ? '<time datetime="PT' + cue.start + 'S">[' + time + ']</time> ' : "[" + time + "] ") : "";
            paragraph.push(prefix + (html ? escapeReadingHtml(text) : text));
            paragraphLength += text.length; previousEnd = cue.end;
        });
        flush();
        var note = "本閱讀版由字幕整理；講者、重要聲音及未口述的畫面資訊仍需人工補充與校對。";
        if (!html) { return title + "\n" + track.label + "\n\n" + note + "\n\n" + content.join("\n\n") + "\n"; }
        return '<!doctype html>\n<html lang="' + escapeReadingHtml(track.language) + '"><head><meta charset="utf-8">' +
            '<meta name="viewport" content="width=device-width,initial-scale=1"><title lang="zh-TW">' + escapeReadingHtml(title) + ' — 逐字稿</title>' +
            '<style>html{color-scheme:light}body{margin:0;color:#202124;background:#fff;font:1.125rem/1.8 system-ui,sans-serif}' +
            'main{max-width:72ch;margin:auto;padding:clamp(1rem,4vw,3rem);overflow-wrap:anywhere}h1{font-size:1.8em;line-height:1.4}' +
            'h2{font-size:1.3em;line-height:1.5;margin-top:2em}p{white-space:pre-wrap}time{font-size:.85em;color:#454b50}' +
            'header p{color:#454b50}a{color:#145f62}a:focus-visible{outline:3px solid #145f62;outline-offset:3px}' +
            '@media print{body{font-size:11pt}main{max-width:none;padding:0}h1,h2{break-after:avoid}p{orphans:3;widows:3}}' +
            '@media(forced-colors:active){body{color:CanvasText;background:Canvas}time,header p{color:CanvasText}}</style></head>' +
            '<body><main><header><h1>' + escapeReadingHtml(title) + '</h1><p lang="zh-TW">逐字稿 · ' + escapeReadingHtml(track.label) +
            '</p><p lang="zh-TW">' + note + '</p></header><article lang="zh-TW" aria-label="完整逐字稿"><div lang="' +
            escapeReadingHtml(track.language) + '">' + content.join("\n") + '</div></article></main></body></html>';
    }

    function downloadTranscript(html) {
        var track = selectedTranscriptTrack();
        if (!track || !track.cues.length) { return; }
        var content = readingDocument(track, document.getElementById("reading-timestamps").checked, html);
        var blob = new Blob([html ? content : "\ufeff" + content], { type: (html ? "text/html" : "text/plain") + ";charset=utf-8" });
        var link = document.createElement("a");
        var url = URL.createObjectURL(blob);
        var name = String(courseConfig.title || "課程").replace(/[\\/:*?"<>|\u0000-\u001f]/g, "_").slice(0, 100);
        link.href = url;
        link.download = name + "." + String(track.language).replace(/[^a-zA-Z0-9-]/g, "_") + ".transcript." + (html ? "html" : "txt");
        link.hidden = true; document.body.appendChild(link); link.click(); link.remove();
        window.setTimeout(function () { URL.revokeObjectURL(url); }, 30000);
    }

    function installReadingSettings() {
        if (!readingSettings) { return; }
        [["reading-font-size", "size"], ["reading-line-height", "lineHeight"], ["reading-contrast", "contrast"]].forEach(function (setting) {
            document.getElementById(setting[0]).addEventListener("change", function (event) {
                readingAppearance[setting[1]] = event.target.value; applyReadingAppearance();
            });
        });
        document.getElementById("reading-reset").addEventListener("click", function () {
            readingAppearance = { size: "100", lineHeight: "1.5", contrast: "normal" }; applyReadingAppearance();
        });
        document.getElementById("transcript-download-html").addEventListener("click", function () { downloadTranscript(true); });
        document.getElementById("transcript-download-txt").addEventListener("click", function () { downloadTranscript(false); });
        readingSettings.addEventListener("toggle", function () { if (readingSettings.open) { closeMenus(); } });
        readingSettings.addEventListener("focusout", function (event) {
            if (event.relatedTarget && !readingSettings.contains(event.relatedTarget)) { readingSettings.open = false; }
        });
        document.addEventListener("click", function (event) {
            if (!readingSettings.contains(event.target)) { readingSettings.open = false; }
        });
        applyReadingAppearance(); syncTranscriptDownloads();
    }

    function installPlayerNavigation() {
        var help = document.getElementById("player-help");
        var navigationKeys = Object.create(null);
        document.querySelectorAll('a[href="#video-stage"], a[href="#chapters-heading"], a[href="#transcript-heading"], a[href="#player-help"]').forEach(function (link) {
            var destination = link.getAttribute("href").slice(1);
            if (destination === "chapters-heading" && (standalone || chapters.length === 0)) {
                link.hidden = true;
                link.removeAttribute("accesskey");
                return;
            }
            if (link.accessKey) { navigationKeys[link.accessKey.toLowerCase()] = link; }
            link.addEventListener("click", function (event) {
                event.preventDefault();
                closeMenus();
                if (readingSettings) { readingSettings.open = false; }
                if (destination === "transcript-heading") {
                    activateReadingTab("transcript");
                } else if (destination === "chapters-heading") {
                    activateReadingTab("chapters");
                } else if (destination === "player-help") {
                    help.open = true;
                }
                var target = destination === "player-help" ? help.querySelector("summary") : document.getElementById(destination);
                target.focus();
                if (target.scrollIntoView) { target.scrollIntoView({ block: "nearest" }); }
            });
        });
        // Keep the documented access-key combinations consistent when the
        // browser does not activate native accesskeys. Cancel the default only
        // for an available destination, so it is never activated twice.
        document.addEventListener("keydown", function (event) {
            if (event.defaultPrevented || event.isComposing || event.keyCode === 229 || event.repeat || event.metaKey || !event.altKey) { return; }
            var apple = /Mac|iPhone|iPad/.test(navigator.platform || "");
            if (apple ? !event.ctrlKey : event.ctrlKey) { return; } // Preserve Windows/Linux AltGr typing.
            var link = navigationKeys[event.key.toLowerCase()];
            if (!link || link.hidden) { return; }
            event.preventDefault();
            link.click();
        });
    }

    function setCourseMetadata() {
        var title = courseConfig.title || "未命名課程";
        var author = "";
        var duration = Number(courseConfig.duration) || 0;
        document.title = title;
        document.getElementById("course-title").textContent = title;
        video.setAttribute("aria-label", "課程影片：" + title);

        if (typeof courseConfig.author === "string") {
            author = courseConfig.author.trim();
        } else if (courseConfig.author && typeof courseConfig.author.name === "string") {
            author = courseConfig.author.name.trim();
        }

        courseAuthor.hidden = !author;
        courseAuthor.textContent = author ? "作者：" + author : "";
        var organization = document.getElementById("course-organization");
        var description = document.getElementById("course-description");
        if (organization) {
            organization.textContent = String(courseConfig.organization || "");
            organization.hidden = !organization.textContent;
        }
        if (description) {
            description.textContent = String(courseConfig.description || "");
            description.hidden = !description.textContent;
        }
        if (standalone) {
            chapterCard.setAttribute("aria-label", "逐字稿");
        }
        setCourseDurationMetadata(duration);

        if (courseConfig.poster) {
            video.poster = courseConfig.poster;
        }
        if (Array.isArray(courseConfig.src) && courseConfig.src.length > 0) {
            video.src = courseConfig.src[0].src;
        } else {
            video.src = "media.mp4";
        }

        totalTimeLabel.textContent = formatTime(duration);
    }

    function setCourseDurationMetadata(duration) {
        var safeDuration = Number.isFinite(Number(duration)) ? Number(duration) : 0;
        courseDuration.hidden = safeDuration <= 0;
        courseDuration.textContent = safeDuration > 0 ? "影片長度：" + formatTime(safeDuration) : "";
        var organization = document.getElementById("course-organization");
        courseMeta.hidden = courseAuthor.hidden && courseDuration.hidden && (!organization || organization.hidden);
    }

    function syncChapterHeight() {
        if (window.matchMedia("(max-width: 1040px)").matches) {
            chapterCard.style.height = "";
            return;
        }
        chapterCard.style.height = Math.round(playerCard.getBoundingClientRect().height) + "px";
    }

    function chapterStartSeconds(chapter) {
        return Math.max(0, (Number(chapter.time) || 0) / 1000);
    }

    function buildChapterPresentation() {
        var counters = [];
        var previousDepth = 0;

        return chapters.map(function (chapter, index) {
            var rawDepth = Number.parseInt(chapter.indent, 10);
            var depth = Number.isFinite(rawDepth) && rawDepth >= 0 ? rawDepth : 0;

            if (index === 0) {
                depth = 0;
            } else {
                depth = Math.min(depth, previousDepth + 1);
            }

            counters.length = depth + 1;
            counters[depth] = (counters[depth] || 0) + 1;
            previousDepth = depth;

            return {
                depth: depth,
                number: counters.join(".")
            };
        });
    }

    function renderChapters() {
        var fragment = document.createDocumentFragment();
        var presentation = buildChapterPresentation();
        chapterList.textContent = "";
        chapterList.style.setProperty("--chapter-title-lines", String(chapterTitleLines));
        chapterList.classList.toggle("chapter-list--hide-numbers", hideChapterNumbers);

        chapters.forEach(function (chapter, index) {
            var start = chapterStartSeconds(chapter);
            var nextStart = index + 1 < chapters.length
                ? chapterStartSeconds(chapters[index + 1])
                : Number(courseConfig.duration) || start;
            var button = document.createElement("button");
            var number = document.createElement("span");
            var copy = document.createElement("span");
            var title = document.createElement("span");
            var meta = document.createElement("span");
            var startLabel = document.createElement("span");
            var durationLabel = document.createElement("span");
            var startIcon = document.createElement("span");
            var durationIcon = document.createElement("span");
            var startTime = formatTime(start);
            var chapterDuration = formatTime(Math.max(0, nextStart - start));

            button.type = "button";
            button.className = "chapter-item";
            button.style.setProperty("--chapter-indent", (Math.min(presentation[index].depth, 5) * 12) + "px");
            button.setAttribute("data-depth", String(presentation[index].depth));
            button.setAttribute(
                "aria-label",
                "播放章節" + (hideChapterNumbers ? "：" : " " + presentation[index].number + "：") +
                (chapter.title || "未命名章節")
            );

            number.className = "chapter-number";
            number.textContent = presentation[index].number;
            copy.className = "chapter-copy";
            title.className = "chapter-title";
            title.textContent = chapter.title || "未命名章節";
            meta.className = "chapter-meta";
            startLabel.className = "chapter-start chapter-time";
            startLabel.setAttribute("aria-label", "影片位置 " + startTime);
            startLabel.title = "影片位置 " + startTime;
            startIcon.className = "chapter-time-icon chapter-time-icon--position";
            startIcon.setAttribute("aria-hidden", "true");
            startLabel.appendChild(startIcon);
            startLabel.appendChild(document.createTextNode(startTime));
            durationLabel.className = "chapter-duration chapter-time";
            durationLabel.setAttribute("aria-label", "章節長度 " + chapterDuration);
            durationLabel.title = "章節長度 " + chapterDuration;
            durationIcon.className = "chapter-time-icon chapter-time-icon--duration";
            durationIcon.setAttribute("aria-hidden", "true");
            durationLabel.appendChild(durationIcon);
            durationLabel.appendChild(document.createTextNode(chapterDuration));

            meta.appendChild(startLabel);
            meta.appendChild(durationLabel);
            copy.appendChild(title);
            copy.appendChild(meta);
            if (!hideChapterNumbers) {
                button.appendChild(number);
            }
            button.appendChild(copy);
            button.addEventListener("click", function () {
                seekToChapter(index);
            });

            chapterButtons.push(button);
            fragment.appendChild(button);
        });

        chapterList.appendChild(fragment);
        window.requestAnimationFrame(updateChapterTitleOverflow);
        if (chapters.length > 0) {
            setActiveChapter(0);
        }
        chapterEmpty.hidden = chapters.length > 0;
    }

    function updateChapterTitleOverflow() {
        var titleElements = chapterList.querySelectorAll(".chapter-title");

        Array.prototype.forEach.call(titleElements, function (titleElement) {
            var button = titleElement.closest(".chapter-item");
            button.classList.remove("is-title-clipped");
            var isClipped = titleElement.scrollHeight > titleElement.clientHeight + 1 ||
                titleElement.scrollWidth > titleElement.clientWidth + 1;

            button.classList.toggle("is-title-clipped", isClipped);
        });
    }

    function seekToChapter(index) {
        if (!chapters[index]) {
            return;
        }
        video.currentTime = chapterStartSeconds(chapters[index]);
        setActiveChapter(index);
        playVideo();
    }

    function findActiveChapter(timeSeconds) {
        var found = 0;
        for (var index = 0; index < chapters.length; index += 1) {
            if (chapterStartSeconds(chapters[index]) <= timeSeconds + 0.05) {
                found = index;
            } else {
                break;
            }
        }
        return found;
    }

    function setActiveChapter(index) {
        if (!chapters[index] || activeChapterIndex === index) {
            return;
        }
        if (chapterButtons[activeChapterIndex]) {
            chapterButtons[activeChapterIndex].removeAttribute("aria-current");
        }
        if (chapterButtons[index]) {
            chapterButtons[index].setAttribute("aria-current", "true");
        }
        activeChapterIndex = index;
    }

    function getLanguageLabel(track) {
        // Older MP4 exports stored the language code as a label. Resolve
        // those through the common names while retaining real custom labels.
        return (track.label && track.label !== track.language ? track.label : languageLabels[track.language]) ||
            track.label || track.language || "字幕";
    }

    function createMenuItem(menu, label, value, onSelect) {
        var item = document.createElement("button");
        item.type = "button";
        item.className = "menu-item";
        item.setAttribute("role", "menuitemradio");
        item.setAttribute("aria-checked", "false");
        item.dataset.value = String(value);
        item.textContent = label;
        item.addEventListener("click", function () {
            onSelect(value);
            closeMenus(true);
            showControls();
        });
        menu.appendChild(item);
        return item;
    }

    function markMenuSelection(menu, selectedValue) {
        Array.prototype.forEach.call(menu.querySelectorAll('.menu-item[role="menuitemradio"]'), function (item) {
            item.setAttribute("aria-checked", item.dataset.value === String(selectedValue) ? "true" : "false");
        });
    }

    function prepareCaptionMenu() {
        captionMenu.textContent = "";
        captionLanguageView = document.createElement("div");
        captionLanguageView.className = "caption-menu-view";
        captionLanguageView.setAttribute("role", "menu");
        captionLanguageView.setAttribute("aria-label", "字幕語言");
        captionStyleView = document.createElement("div");
        captionStyleView.className = "caption-menu-view";
        captionStyleView.hidden = true;
        captionStyleView.setAttribute("role", "group");
        captionStyleView.setAttribute("aria-label", "字幕外觀");
        captionMenu.appendChild(captionLanguageView);
        captionMenu.appendChild(captionStyleView);
    }

    function createCaptionSettingRow(labelText, options, currentValue, onChange) {
        var row = document.createElement("div");
        var label = document.createElement("label");
        var select = document.createElement("select");
        var id = "caption-setting-" + labelText;

        row.className = "caption-setting-row";
        label.htmlFor = id;
        label.textContent = labelText;
        select.id = id;
        options.forEach(function (optionData) {
            var option = document.createElement("option");
            option.value = optionData.value;
            option.textContent = optionData.label;
            select.appendChild(option);
        });
        select.value = currentValue;
        select.addEventListener("change", function () {
            onChange(select.value);
            applyCaptionAppearance();
        });
        row.appendChild(label);
        row.appendChild(select);
        captionStyleView.appendChild(row);
        return select;
    }

    function appendCaptionAppearanceControls() {
        var divider = document.createElement("div");
        var appearanceButton = document.createElement("button");
        var header = document.createElement("div");
        var backButton = document.createElement("button");
        var resetButton = document.createElement("button");
        var sizeSelect;
        var themeSelect;
        var positionSelect;

        divider.className = "menu-divider";
        divider.setAttribute("aria-hidden", "true");
        appearanceButton.type = "button";
        appearanceButton.className = "menu-item menu-link";
        appearanceButton.setAttribute("role", "menuitem");
        appearanceButton.textContent = "字幕外觀";
        appearanceButton.addEventListener("click", showCaptionStyleView);
        captionLanguageView.appendChild(divider);
        captionLanguageView.appendChild(appearanceButton);

        header.className = "caption-settings-header";
        backButton.type = "button";
        backButton.className = "caption-back-button";
        backButton.textContent = "字幕外觀";
        backButton.addEventListener("click", showCaptionLanguageView);
        header.appendChild(backButton);
        captionStyleView.appendChild(header);

        sizeSelect = createCaptionSettingRow("字體大小", [
            { value: "75", label: "75%" },
            { value: "100", label: "100%" },
            { value: "125", label: "125%" },
            { value: "150", label: "150%" },
            { value: "200", label: "200%" }
        ], captionAppearance.size, function (value) {
            captionAppearance.size = value;
        });

        themeSelect = createCaptionSettingRow("顯示樣式", [
            { value: "white-black", label: "白字黑底" },
            { value: "yellow-black", label: "黃字黑底" },
            { value: "black-white", label: "黑字白底" },
            { value: "white-shadow", label: "白字無底" }
        ], captionAppearance.theme, function (value) {
            captionAppearance.theme = value;
        });

        positionSelect = createCaptionSettingRow("顯示位置", [
            { value: "bottom", label: "下方" },
            { value: "middle", label: "中央" },
            { value: "top", label: "上方" }
        ], captionAppearance.position, function (value) {
            captionAppearance.position = value;
        });

        resetButton.type = "button";
        resetButton.className = "caption-reset-button";
        resetButton.textContent = "恢復預設值";
        resetButton.addEventListener("click", function () {
            captionAppearance = { size: "100", theme: "white-black", position: "bottom" };
            sizeSelect.value = captionAppearance.size;
            themeSelect.value = captionAppearance.theme;
            positionSelect.value = captionAppearance.position;
            applyCaptionAppearance();
        });
        captionStyleView.appendChild(resetButton);
        var appearanceNote = document.createElement("p");
        appearanceNote.className = "caption-appearance-note";
        appearanceNote.textContent = "無底字幕的對比會受影片畫面影響，建議使用有底色樣式。";
        captionStyleView.appendChild(appearanceNote);
    }

    function showCaptionLanguageView() {
        if (!captionLanguageView || !captionStyleView) {
            return;
        }
        captionLanguageView.hidden = false;
        captionStyleView.hidden = true;
        var selectedLanguage = captionLanguageView.querySelector('[aria-checked="true"]');
        (selectedLanguage || captionLanguageView.querySelector(".menu-item")).focus();
    }

    function showCaptionStyleView() {
        captionLanguageView.hidden = true;
        captionStyleView.hidden = false;
        captionStyleView.querySelector(".caption-back-button").focus();
        showControls();
    }

    function applyCaptionAppearance() {
        var themes = {
            "white-black": { color: "#fff", background: "rgba(0,0,0,.78)", shadow: "0 1px 2px #000" },
            "yellow-black": { color: "#ffe45c", background: "rgba(0,0,0,.84)", shadow: "0 1px 2px #000" },
            "black-white": { color: "#111", background: "rgba(255,255,255,.9)", shadow: "none" },
            "white-shadow": { color: "#fff", background: "transparent", shadow: "0 1px 2px #000, 1px 0 2px #000, -1px 0 2px #000" }
        };
        var theme = themes[captionAppearance.theme] || themes["white-black"];

        captionOverlay.dataset.theme = captionAppearance.theme;
        captionOverlay.className = "caption-overlay caption-position-" + captionAppearance.position;
        captionText.style.fontSize = captionAppearance.size + "%";

        // Retain a native cue style for browser picture-in-picture fallback.
        captionAppearanceStyle.textContent = "#course-video::cue{" +
            "font-size:" + captionAppearance.size + "%;" +
            "color:" + theme.color + ";" +
            "background-color:" + theme.background + ";" +
            "text-shadow:" + theme.shadow + ";}";

        nativeTracks.forEach(function (item) {
            var cues = item.track.cues;
            if (!cues) { return; } // Browsers expose null while the track is disabled.
            for (var index = 0; index < cues.length; index += 1) {
                if (captionAppearance.position === "bottom") {
                    cues[index].snapToLines = true;
                    cues[index].line = -3;
                } else {
                    cues[index].snapToLines = false;
                    cues[index].line = captionAppearance.position === "middle" ? 45 : 8;
                }
            }
        });
        savePreference(captionAppearanceStorageKey, JSON.stringify(captionAppearance));
    }

    function pictureInPictureIsActive() {
        return document.pictureInPictureElement === video ||
            video.webkitPresentationMode === "picture-in-picture";
    }

    function shouldUseNativeCaptions() {
        return preparingPictureInPicture || pictureInPictureIsActive();
    }

    function updateCaptionOverlay() {
        var selected = nativeTracks.find(function (item) {
            return item.language === activeSubtitleLanguage;
        });
        var activeCues;
        var lines = [];

        if (!selected || activeSubtitleLanguage === "off" || shouldUseNativeCaptions()) {
            captionText.textContent = "";
            captionOverlay.hidden = true;
            return;
        }

        activeCues = selected.track.activeCues;
        if (activeCues) {
            for (var index = 0; index < activeCues.length; index += 1) {
                if (activeCues[index].text) {
                    lines.push(activeCues[index].text);
                }
            }
        }
        captionText.textContent = lines.join("\n");
        captionOverlay.hidden = lines.length === 0;
    }

    function syncSubtitleTrackModes() {
        var useNativeRenderer = shouldUseNativeCaptions();
        nativeTracks.forEach(function (item) {
            if (item.language !== activeSubtitleLanguage) {
                item.track.mode = "disabled";
            } else {
                item.track.mode = useNativeRenderer ? "showing" : "hidden";
            }
        });
        updateCaptionOverlay();
    }

    function installSubtitles() {
        var tracks = Array.isArray(subtitleData.tracks) ? subtitleData.tracks : [];
        var Cue = window.VTTCue || window.TextTrackCue;

        if (tracks.length === 0 || typeof Cue !== "function") {
            captionMenuWrap.hidden = false;
            captionButton.disabled = true;
            captionButton.setAttribute("aria-label", "沒有可用的字幕");
            captionButton.title = "尚未加入字幕";
            return;
        }

        prepareCaptionMenu();
        createMenuItem(captionLanguageView, "關閉", "off", setSubtitleLanguage);
        tracks.forEach(function (trackData) {
            var label = getLanguageLabel(trackData);
            var language = trackData.language || "und";
            var nativeTrack = video.addTextTrack("subtitles", label, language);
            nativeTrack.mode = "hidden";

            (trackData.cues || []).forEach(function (cueData) {
                var start = Number(cueData.start);
                var end = Number(cueData.end);
                if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) {
                    return;
                }
                try {
                    var cue = new Cue(start, end, String(cueData.text || ""));
                    cue.line = -3;
                    nativeTrack.addCue(cue);
                } catch (error) {
                    // Ignore one malformed cue and retain the rest of the language.
                }
            });
            nativeTrack.mode = "disabled";
            nativeTracks.push({ language: language, track: nativeTrack });
            nativeTrack.addEventListener("cuechange", updateCaptionOverlay);
            createMenuItem(captionLanguageView, label, language, setSubtitleLanguage);
        });

        appendCaptionAppearanceControls();

        captionMenuWrap.hidden = false;
        captionButton.disabled = false;
        captionButton.title = "字幕";
        var languages = nativeTracks.map(function (item) { return item.language; });
        var preferred = readPreference(subtitleStorageKey);
        var defaultLanguage = preferred && (languages.indexOf(preferred) !== -1 || (standalone && preferred === "off"))
            ? preferred
            : (standalone ? courseConfig.defaultSubtitle : subtitleData.defaultLanguage);

        if ((!standalone || defaultLanguage !== "off") && (!defaultLanguage || languages.indexOf(defaultLanguage) === -1)) {
            defaultLanguage = languages.indexOf("zh-TW") !== -1 ? "zh-TW" : languages[0];
        }
        setSubtitleLanguage(defaultLanguage || "off", !standalone);
    }

    function setSubtitleLanguage(language, persist) {
        activeSubtitleLanguage = language;
        syncSubtitleTrackModes();
        applyCaptionAppearance();
        captionButton.classList.toggle("is-active", language !== "off");
        markMenuSelection(captionMenu, language);
        if (persist !== false) { savePreference(subtitleStorageKey, language); }
        if (transcriptLanguage && transcriptTracks.some(function (track) { return track.language === language; })) {
            transcriptLanguage.value = language;
            searchTranscript();
        }
    }

    function installTranscript() {
        // Read embedded subtitle data, so search also works offline and with CC off.
        if (!transcriptSearch || !transcriptLanguage || !transcriptList) { return; }
        transcriptTracks = (Array.isArray(subtitleData.tracks) ? subtitleData.tracks : []).map(function (track) {
            var cues = (Array.isArray(track.cues) ? track.cues : []).filter(function (cue) {
                return Number.isFinite(Number(cue.start)) && Number(cue.start) >= 0 &&
                    Number.isFinite(Number(cue.end)) && Number(cue.end) > Number(cue.start);
            }).map(function (cue) {
                var text = String(cue.text || "");
                return { start: Number(cue.start), end: Number(cue.end), text: text, searchable: text.toLowerCase() };
            });
            return { language: track.language || "und", label: getLanguageLabel(track), cues: cues };
        });
        transcriptTracks.forEach(function (track) {
            var option = document.createElement("option");
            option.value = track.language;
            option.textContent = track.label;
            transcriptLanguage.appendChild(option);
        });
        if (transcriptTracks.length === 0) {
            var unavailableOption = document.createElement("option");
            unavailableOption.value = "";
            unavailableOption.textContent = "沒有可用字幕";
            transcriptLanguage.appendChild(unavailableOption);
        }
        if (transcriptTracks.some(function (track) { return track.language === activeSubtitleLanguage; })) {
            transcriptLanguage.value = activeSubtitleLanguage;
        }
        var unavailable = !transcriptTracks.some(function (track) { return track.cues.length > 0; });
        transcriptSearch.disabled = unavailable;
        transcriptLanguage.disabled = unavailable;
        document.getElementById("transcript-clear").disabled = unavailable;
        if (transcriptFollow) {
            transcriptFollow.disabled = unavailable;
            transcriptFollow.addEventListener("change", function () {
                syncTranscriptFollowHint();
                if (transcriptPrevious) {
                    transcriptPrevious.hidden = transcriptVisibleStart === 0 || transcriptFollow.checked;
                }
                updateTranscriptPosition(true);
            });
        }
        if (transcriptPrevious) {
            transcriptPrevious.addEventListener("click", function () {
                transcriptVisibleStart = Math.max(0, transcriptVisibleStart - 100);
                transcriptVisibleCount = 100;
                transcriptList.scrollTop = 0;
                renderTranscript();
            });
        }
        transcriptSearch.addEventListener("input", function (event) {
            syncTranscriptFollowHint();
            if (!event.isComposing) { searchTranscript(); }
        });
        transcriptSearch.addEventListener("compositionend", searchTranscript);
        transcriptLanguage.addEventListener("change", searchTranscript);
        document.getElementById("transcript-clear").addEventListener("click", function () {
            transcriptSearch.value = "";
            searchTranscript();
            transcriptSearch.focus();
        });
        transcriptMore.addEventListener("click", function () {
            var previousCount = transcriptVisibleCount;
            transcriptVisibleCount += 100;
            renderTranscript();
            if (transcriptMore.hidden && transcriptRows[previousCount]) {
                transcriptRows[previousCount].button.focus();
            }
        });
        searchTranscript();
    }

    function activateReadingTab(name) {
        if (!chaptersTab || !transcriptTab) { return; }
        var transcript = name === "transcript";
        chaptersPanel.hidden = transcript || standalone;
        transcriptPanel.hidden = !transcript;
        chaptersTab.setAttribute("aria-selected", String(!transcript));
        transcriptTab.setAttribute("aria-selected", String(transcript));
        chaptersTab.tabIndex = transcript ? -1 : 0;
        transcriptTab.tabIndex = transcript ? 0 : -1;
        syncChapterHeight();
        if (transcript) { updateTranscriptPosition(true); }
        else { window.requestAnimationFrame(updateChapterTitleOverflow); }
    }

    function installReadingTabs() {
        if (!chaptersTab || !transcriptTab) { return; }
        chaptersTab.hidden = standalone;
        chaptersTab.addEventListener("click", function () { activateReadingTab("chapters"); });
        transcriptTab.addEventListener("click", function () { activateReadingTab("transcript"); });
        [chaptersTab, transcriptTab].forEach(function (tab) {
            tab.addEventListener("keydown", function (event) {
                var tabs = [chaptersTab, transcriptTab].filter(function (item) { return !item.hidden; });
                var index = tabs.indexOf(tab);
                if (event.key === "ArrowRight") { index = (index + 1) % tabs.length; }
                else if (event.key === "ArrowLeft") { index = (index + tabs.length - 1) % tabs.length; }
                else if (event.key === "Home") { index = 0; }
                else if (event.key === "End") { index = tabs.length - 1; }
                else { return; }
                event.preventDefault();
                activateReadingTab(tabs[index] === transcriptTab ? "transcript" : "chapters");
                tabs[index].focus();
            });
        });
        activateReadingTab(standalone ? "transcript" : "chapters");
    }

    function searchTranscript() {
        var track = transcriptTracks.find(function (item) { return item.language === transcriptLanguage.value; });
        var query = transcriptSearch.value.trim().toLowerCase();
        transcriptMatches = track ? track.cues.filter(function (cue) {
            return !query || cue.searchable.indexOf(query) !== -1;
        }) : [];
        transcriptVisibleCount = 100;
        transcriptVisibleStart = 0;
        transcriptList.scrollTop = 0;
        syncTranscriptFollowHint();
        syncTranscriptDownloads();
        renderTranscript();
    }

    function syncTranscriptFollowHint() {
        if (transcriptFollowHint) {
            transcriptFollowHint.hidden = !(transcriptFollow && transcriptFollow.checked && transcriptSearch.value.trim());
        }
    }

    function appendTranscriptText(element, text, query) {
        // Literal matching and text nodes: subtitle contents never become HTML.
        var offset = 0;
        var lower = text.toLowerCase();
        var index = query ? lower.indexOf(query) : -1;
        while (index !== -1) {
            element.appendChild(document.createTextNode(text.slice(offset, index)));
            var mark = document.createElement("mark");
            mark.textContent = text.slice(index, index + query.length);
            element.appendChild(mark);
            offset = index + query.length;
            index = lower.indexOf(query, offset);
        }
        element.appendChild(document.createTextNode(text.slice(offset)));
    }

    function renderTranscript(skipPositionUpdate) {
        transcriptList.textContent = "";
        transcriptRows = [];
        transcriptLastFollowCue = null;
        var fragment = document.createDocumentFragment();
        var query = transcriptSearch.value.trim().toLowerCase();
        transcriptMatches.slice(transcriptVisibleStart, transcriptVisibleStart + transcriptVisibleCount).forEach(function (cue) {
            var item = document.createElement("li");
            var button = document.createElement("button");
            var time = document.createElement("span");
            var text = document.createElement("span");
            button.type = "button";
            button.className = "transcript-item";
            time.className = "transcript-time";
            time.textContent = formatTime(cue.start);
            text.className = "transcript-text";
            appendTranscriptText(text, cue.text, query);
            button.appendChild(time);
            button.appendChild(text);
            button.addEventListener("click", function () {
                video.currentTime = cue.start;
                updateTimeline();
                playVideo();
            });
            item.appendChild(button);
            fragment.appendChild(item);
            transcriptRows.push({ button: button, cue: cue });
        });
        transcriptList.appendChild(fragment);
        transcriptMore.hidden = transcriptVisibleStart + transcriptVisibleCount >= transcriptMatches.length;
        if (transcriptPrevious) {
            transcriptPrevious.hidden = transcriptVisibleStart === 0 || Boolean(transcriptFollow && transcriptFollow.checked);
        }
        if (transcriptSearch.disabled) {
            transcriptStatus.textContent = "尚未加入字幕，無法顯示逐字稿。";
        } else if (!transcriptMatches.length) {
            transcriptStatus.textContent = query ? "找不到符合的字幕，請換個關鍵字。" : "此語言沒有可用的字幕內容。";
        } else {
            transcriptStatus.textContent = (query ? "找到 " : "共 ") + transcriptMatches.length +
                " 段字幕，" + (transcriptVisibleStart === 0 ? "已顯示 " + transcriptRows.length + " 段。" :
                    "顯示第 " + (transcriptVisibleStart + 1) + "～" + (transcriptVisibleStart + transcriptRows.length) + " 段。");
        }
        if (!skipPositionUpdate) { updateTranscriptPosition(true); }
    }

    function updateTranscriptPosition(forceFollow) {
        var following = transcriptFollow && transcriptFollow.checked && !transcriptFollow.disabled &&
            !transcriptSearch.value.trim() && !transcriptPanel.hidden && !chapterCard.hidden;
        if (following) {
            var activeIndex = transcriptMatches.findIndex(function (cue) {
                return video.currentTime >= cue.start && video.currentTime < cue.end;
            });
            if (activeIndex !== -1 && (activeIndex < transcriptVisibleStart ||
                    activeIndex >= transcriptVisibleStart + transcriptVisibleCount)) {
                var focusedRow = transcriptRows.find(function (row) { return row.button === document.activeElement; });
                // Keep automatic seeking bounded, rather than rendering all
                // earlier cues in a many-hour transcript. Manual paging remains.
                transcriptVisibleStart = Math.min(Math.max(0, activeIndex - 25), Math.max(0, transcriptMatches.length - 100));
                transcriptVisibleCount = 100;
                transcriptList.scrollTop = 0;
                renderTranscript(true);
                if (focusedRow) {
                    var retainedRow = transcriptRows.find(function (row) { return row.cue === focusedRow.cue; });
                    // Keep a retained keyboard target; if it left this page,
                    // leave focus on the persistent follow control, not BODY.
                    (retainedRow ? retainedRow.button : transcriptFollow).focus({ preventScroll: true });
                }
            }
        }
        var activeRow = null;
        transcriptRows.forEach(function (row) {
            var active = video.currentTime >= row.cue.start && video.currentTime < row.cue.end;
            if (active) {
                row.button.setAttribute("aria-current", "true");
                if (!activeRow) { activeRow = row; }
            }
            else { row.button.removeAttribute("aria-current"); }
        });
        if (!following || !activeRow) { transcriptLastFollowCue = null; return; }
        if (!forceFollow && transcriptLastFollowCue === activeRow.cue) { return; }
        transcriptLastFollowCue = activeRow.cue;
        var viewport = transcriptList.getBoundingClientRect();
        var rowBounds = activeRow.button.getBoundingClientRect();
        if (transcriptList.clientHeight > 0 && (rowBounds.top < viewport.top || rowBounds.bottom > viewport.bottom)) {
            // Scroll this list only: scrollIntoView would also move the page
            // and can push the playing video off screen on mobile.
            transcriptList.scrollTop = Math.max(0, transcriptList.scrollTop + rowBounds.top - viewport.top -
                Math.max(0, (transcriptList.clientHeight - rowBounds.height) / 2));
        }
    }

    function installSpeedMenu() {
        speedOptions.forEach(function (speed) {
            createMenuItem(speedMenu, speed === 1 ? "正常" : speed + "×", speed, setPlaybackSpeed);
        });
        setPlaybackSpeed(1);
    }

    function supportsStandardPictureInPicture() {
        return Boolean(
            document.pictureInPictureEnabled &&
            typeof video.requestPictureInPicture === "function"
        );
    }

    function supportsWebKitPictureInPicture() {
        return Boolean(
            typeof video.webkitSupportsPresentationMode === "function" &&
            video.webkitSupportsPresentationMode("picture-in-picture") &&
            typeof video.webkitSetPresentationMode === "function"
        );
    }

    function installPictureInPicture() {
        pipToggle.hidden = !(supportsStandardPictureInPicture() || supportsWebKitPictureInPicture());
    }

    function setPlaybackSpeed(speed) {
        video.playbackRate = Number(speed) || 1;
        speedButton.textContent = video.playbackRate + "×";
        markMenuSelection(speedMenu, video.playbackRate);
    }

    function playVideo() {
        var promise = video.play();
        if (promise && typeof promise.catch === "function") {
            promise.catch(function () {
                showControls();
            });
        }
    }

    function togglePlayback() {
        if (video.paused || video.ended) {
            playVideo();
        } else {
            video.pause();
        }
    }

    function updatePlayState() {
        var isPlaying = !video.paused && !video.ended;
        if (isPlaying && document.activeElement === bigPlay) { playToggle.focus({ preventScroll: true }); }
        bigPlay.hidden = isPlaying;
        videoStage.classList.toggle("is-playing", isPlaying);
        playToggle.setAttribute("aria-label", isPlaying ? "暫停" : "播放");
        bigPlay.setAttribute("aria-label", isPlaying ? "暫停影片" : "播放影片");
        showControls();
    }

    function updateTimeline() {
        var duration = Number.isFinite(video.duration) ? video.duration : Number(courseConfig.duration) || 0;
        var ratio = duration > 0 ? Math.min(1, video.currentTime / duration) : 0;
        seekSlider.value = String(Math.round(ratio * 1000));
        seekSlider.style.setProperty("--progress", (ratio * 100) + "%");
        currentTimeLabel.textContent = formatTime(video.currentTime);
        seekSlider.setAttribute("aria-valuetext", formatTime(video.currentTime) + "／" + formatTime(duration));
        totalTimeLabel.textContent = formatTime(duration);
        if (chapters.length > 0) {
            setActiveChapter(findActiveChapter(video.currentTime));
        }
        updateCaptionOverlay();
        updateTranscriptPosition();
    }

    function updateVolume() {
        var value = video.muted ? 0 : video.volume;
        volumeSlider.value = String(value);
        volumeSlider.style.setProperty("--progress", (value * 100) + "%");
        muteToggle.classList.toggle("is-muted", value === 0);
        muteToggle.classList.toggle("is-low", value > 0 && value <= 0.5);
        muteToggle.setAttribute("aria-label", value === 0 ? "開啟聲音" : "靜音");
        volumeSlider.setAttribute("aria-valuetext", String(Math.round(value * 100)) + "%");
    }

    function toggleMenu(menu, button) {
        var willOpen = menu.hidden;
        closeMenus();
        if (willOpen) {
            menu.hidden = false;
            button.setAttribute("aria-expanded", "true");
            fitMenuToVideo(menu, button);
            var selected = menu.querySelector('[aria-checked="true"]');
            (selected || menu.querySelector(".menu-item")).focus();
        }
        showControls();
    }

    function fitMenuToVideo(menu, button) {
        var stageBounds = videoStage.getBoundingClientRect();
        var buttonBounds = button.getBoundingClientRect();
        var availableHeight = Math.floor(buttonBounds.top - stageBounds.top - 8);
        menu.style.setProperty("--player-menu-max-height", Math.max(80, availableHeight) + "px");
    }

    function fitOpenMenus() {
        if (!captionMenu.hidden) {
            fitMenuToVideo(captionMenu, captionButton);
        }
        if (!speedMenu.hidden) {
            fitMenuToVideo(speedMenu, speedButton);
        }
    }

    function closeMenus(restoreFocus) {
        var opener = !captionMenu.hidden ? captionButton : (!speedMenu.hidden ? speedButton : null);
        captionMenu.hidden = true;
        speedMenu.hidden = true;
        if (captionLanguageView && captionStyleView) {
            captionLanguageView.hidden = false;
            captionStyleView.hidden = true;
        }
        captionButton.setAttribute("aria-expanded", "false");
        speedButton.setAttribute("aria-expanded", "false");
        if (restoreFocus && opener) { opener.focus(); }
    }

    function menusAreOpen() {
        return !captionMenu.hidden || !speedMenu.hidden;
    }

    function showControls() {
        window.clearTimeout(controlsTimer);
        videoStage.classList.remove("controls-hidden");
        if (!video.paused && !video.ended && !menusAreOpen()) {
            controlsTimer = window.setTimeout(function () {
                if (!document.getElementById("video-controls").contains(document.activeElement) && !videoStage.matches(":focus-visible")) {
                    videoStage.classList.add("controls-hidden");
                }
            }, 2500);
        }
    }

    function frameFullscreenIsActive() {
        return videoStage.classList.contains("is-frame-fullscreen");
    }

    function enterFrameFullscreen() {
        videoStage.classList.add("is-frame-fullscreen");
        document.body.classList.add("frame-fullscreen-active");
        updateFullscreenState();
        fitOpenMenus();
    }

    function exitFrameFullscreen() {
        videoStage.classList.remove("is-frame-fullscreen");
        document.body.classList.remove("frame-fullscreen-active");
        updateFullscreenState();
        syncChapterHeight();
    }

    function handleFullscreenFailure() {
        if (!document.fullscreenElement && !document.webkitFullscreenElement) {
            enterFrameFullscreen();
        }
    }

    function toggleFullscreen() {
        var operation;

        if (frameFullscreenIsActive()) {
            exitFrameFullscreen();
            return;
        }
        if (document.fullscreenElement || document.webkitFullscreenElement) {
            operation = (document.exitFullscreen || document.webkitExitFullscreen).call(document);
            if (operation && typeof operation.catch === "function") {
                operation.catch(showControls);
            }
            return;
        }

        try {
            if (videoStage.requestFullscreen) {
                operation = videoStage.requestFullscreen();
            } else if (videoStage.webkitRequestFullscreen) {
                operation = videoStage.webkitRequestFullscreen();
            } else if (video.webkitEnterFullscreen && window.top === window.self) {
                video.webkitEnterFullscreen();
            } else {
                enterFrameFullscreen();
                return;
            }
        } catch (error) {
            handleFullscreenFailure();
            return;
        }

        if (operation && typeof operation.catch === "function") {
            operation.catch(handleFullscreenFailure);
        }
    }

    function togglePictureInPicture() {
        var operation;

        if (supportsStandardPictureInPicture()) {
            if (document.pictureInPictureElement === video) {
                operation = document.exitPictureInPicture();
            } else {
                // Chromium snapshots the active text track while creating the PiP window.
                // Enable the native subtitle track before requesting PiP so captions are included.
                preparingPictureInPicture = true;
                syncSubtitleTrackModes();
                operation = video.requestPictureInPicture();
            }
        } else if (supportsWebKitPictureInPicture()) {
            if (video.webkitPresentationMode !== "picture-in-picture") {
                preparingPictureInPicture = true;
                syncSubtitleTrackModes();
            }
            video.webkitSetPresentationMode(
                video.webkitPresentationMode === "picture-in-picture"
                    ? "inline"
                    : "picture-in-picture"
            );
            preparingPictureInPicture = false;
            syncSubtitleTrackModes();
        }

        if (operation && typeof operation.then === "function") {
            operation.then(function () {
                preparingPictureInPicture = false;
                syncSubtitleTrackModes();
            }).catch(function () {
                preparingPictureInPicture = false;
                syncSubtitleTrackModes();
                showControls();
            });
        }
    }

    function updatePictureInPictureState() {
        var isActive = document.pictureInPictureElement === video ||
            video.webkitPresentationMode === "picture-in-picture";
        preparingPictureInPicture = false;
        pipToggle.classList.toggle("is-active", isActive);
        pipToggle.setAttribute("aria-label", isActive ? "離開子母畫面" : "子母畫面");
        pipToggle.title = isActive ? "離開子母畫面" : "子母畫面";
        syncSubtitleTrackModes();
    }

    function updateFullscreenState() {
        var isNativeFullscreen = Boolean(document.fullscreenElement || document.webkitFullscreenElement);
        var isFrameFullscreen = frameFullscreenIsActive();
        var isFullscreen = isNativeFullscreen || isFrameFullscreen;
        if (isNativeFullscreen && isFrameFullscreen) {
            exitFrameFullscreen();
            return;
        }
        fullscreenToggle.setAttribute("aria-label", isFullscreen ? "離開全螢幕" : "全螢幕");
        fullscreenToggle.title = isFrameFullscreen ? "離開框架內全螢幕" : (isFullscreen ? "離開全螢幕" : "全螢幕");
        fullscreenToggle.classList.toggle("is-active", isFullscreen);
        showControls();
    }

    function isTypingTarget(target) {
        return Boolean(target.closest("input, textarea, select, summary, a, [contenteditable], [role='menu'], [role='dialog']"));
    }

    function bindEvents() {
        bigPlay.addEventListener("click", togglePlayback);
        playToggle.addEventListener("click", togglePlayback);
        video.addEventListener("click", function () {
            videoStage.focus({ preventScroll: true });
            togglePlayback();
        });
        video.addEventListener("play", updatePlayState);
        video.addEventListener("pause", updatePlayState);
        video.addEventListener("ended", updatePlayState);
        video.addEventListener("timeupdate", updateTimeline);
        video.addEventListener("seeked", function () { updateTranscriptPosition(true); });
        video.addEventListener("durationchange", updateTimeline);
        video.addEventListener("loadedmetadata", function () {
            updateTimeline();
            setCourseDurationMetadata(video.duration);
            installPictureInPicture();
        });
        video.addEventListener("volumechange", updateVolume);
        video.addEventListener("waiting", function () { loadingSpinner.hidden = false; });
        video.addEventListener("playing", function () { loadingSpinner.hidden = true; });
        video.addEventListener("canplay", function () { loadingSpinner.hidden = true; });

        seekSlider.addEventListener("input", function () {
            var duration = Number.isFinite(video.duration) ? video.duration : Number(courseConfig.duration) || 0;
            if (duration > 0) {
                video.currentTime = (Number(seekSlider.value) / 1000) * duration;
                updateTimeline();
            }
        });

        muteToggle.addEventListener("click", function () {
            video.muted = !video.muted;
        });
        volumeSlider.addEventListener("input", function () {
            video.muted = false;
            video.volume = Number(volumeSlider.value);
        });

        captionButton.addEventListener("click", function () {
            toggleMenu(captionMenu, captionButton);
        });
        speedButton.addEventListener("click", function () {
            toggleMenu(speedMenu, speedButton);
        });
        pipToggle.addEventListener("click", togglePictureInPicture);
        fullscreenToggle.addEventListener("click", toggleFullscreen);

        videoStage.addEventListener("mousemove", showControls);
        videoStage.addEventListener("touchstart", showControls, { passive: true });
        videoStage.addEventListener("mouseleave", showControls);
        videoStage.addEventListener("focusin", showControls);
        [captionMenu, speedMenu].forEach(function (menu) {
            menu.addEventListener("focusout", function (event) {
                if (event.relatedTarget && !menu.parentElement.contains(event.relatedTarget)) { closeMenus(); }
            });
        });
        window.addEventListener("resize", function () {
            fitOpenMenus();
            syncChapterHeight();
            updateChapterTitleOverflow();
            updateTranscriptPosition(true);
        });
        window.addEventListener("orientationchange", function () {
            fitOpenMenus();
            syncChapterHeight();
            updateChapterTitleOverflow();
            updateTranscriptPosition(true);
        });
        document.addEventListener("fullscreenchange", updateFullscreenState);
        document.addEventListener("webkitfullscreenchange", updateFullscreenState);
        document.addEventListener("fullscreenerror", handleFullscreenFailure);
        document.addEventListener("webkitfullscreenerror", handleFullscreenFailure);
        video.addEventListener("enterpictureinpicture", updatePictureInPictureState);
        video.addEventListener("leavepictureinpicture", updatePictureInPictureState);
        video.addEventListener("webkitpresentationmodechanged", updatePictureInPictureState);

        document.addEventListener("click", function (event) {
            if (!event.target.closest(".menu-wrap")) {
                closeMenus();
            }
        });

        document.addEventListener("keydown", function (event) {
            if (event.defaultPrevented || event.isComposing || event.keyCode === 229) { return; }
            if (event.key === "Escape") {
                if (readingSettings && readingSettings.open && readingSettings.contains(event.target)) {
                    readingSettings.open = false;
                    readingSettings.querySelector("summary").focus();
                } else if (menusAreOpen()) { closeMenus(true); }
                else if (event.target.closest("#player-help") && document.getElementById("player-help").open) {
                    var help = document.getElementById("player-help");
                    help.open = false;
                    help.querySelector("summary").focus();
                }
                else if (frameFullscreenIsActive()) { exitFrameFullscreen(); }
                else { return; }
                event.preventDefault(); showControls(); return;
            }
            var menu = event.target.closest('[role="menu"]');
            if (menu && ["ArrowDown", "ArrowUp", "Home", "End"].indexOf(event.key) !== -1) {
                var items = Array.from(menu.querySelectorAll('button:not(:disabled)'));
                var index = items.indexOf(document.activeElement);
                if (event.key === "Home") { index = 0; }
                else if (event.key === "End") { index = items.length - 1; }
                else { index = (index + (event.key === "ArrowDown" ? 1 : -1) + items.length) % items.length; }
                if (items[index]) { items[index].focus(); event.preventDefault(); }
                return;
            }
            if (event.ctrlKey || event.metaKey || event.altKey || !videoStage.contains(event.target)) { return; }
            if ((event.target === captionButton || event.target === speedButton) && event.key === "ArrowDown") {
                event.preventDefault();
                if ((event.target === captionButton ? captionMenu : speedMenu).hidden) { event.target.click(); }
                return;
            }
            if (isTypingTarget(event.target)) {
                return;
            }
            // Space/Enter keep native button activation; arrows on a form or
            // menu keep that control's behavior. Letters are scoped to the
            // player group, including its ordinary control buttons.
            var onButton = event.target.closest("button");
            if (event.code === "Space") {
                if (onButton) { return; }
                event.preventDefault();
                togglePlayback();
            } else if (event.key === "ArrowLeft") {
                if (onButton) { return; }
                event.preventDefault();
                video.currentTime = Math.max(0, video.currentTime - 10);
            } else if (event.key === "ArrowRight") {
                if (onButton) { return; }
                event.preventDefault();
                video.currentTime = Math.min(video.duration || Number(courseConfig.duration) || Infinity, video.currentTime + 10);
            } else if (event.key.toLowerCase() === "m") {
                if (event.repeat) { return; }
                event.preventDefault();
                video.muted = !video.muted;
            } else if (event.key.toLowerCase() === "f") {
                if (event.repeat) { return; }
                event.preventDefault();
                toggleFullscreen();
            } else if (event.key === "Escape") {
                if (frameFullscreenIsActive()) {
                    exitFrameFullscreen();
                }
                closeMenus();
            }
            showControls();
        });
    }

    setCourseMetadata();
    renderChapters();
    installSubtitles();
    installTranscript();
    installReadingTabs();
    installReadingSettings();
    installPlayerNavigation();
    installSpeedMenu();
    installPictureInPicture();
    bindEvents();
    syncChapterHeight();
    updateVolume();
    updateTimeline();
}());
