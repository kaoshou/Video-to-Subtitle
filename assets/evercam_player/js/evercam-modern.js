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

    var courseConfig = window.config || {};
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
    var chapterButtons = [];
    var nativeTracks = [];
    var activeSubtitleLanguage = "off";
    var preparingPictureInPicture = false;
    var activeChapterIndex = -1;
    var controlsTimer = null;
    var subtitleStorageKey = "evercam.subtitle." + String(courseConfig.title || "course");
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

    function setCourseMetadata() {
        var title = courseConfig.title || "未命名課程";
        var author = "";
        var duration = Number(courseConfig.duration) || 0;
        document.title = title;
        document.getElementById("course-title").textContent = title;

        if (typeof courseConfig.author === "string") {
            author = courseConfig.author.trim();
        } else if (courseConfig.author && typeof courseConfig.author.name === "string") {
            author = courseConfig.author.name.trim();
        }

        courseAuthor.hidden = !author;
        courseAuthor.textContent = author ? "作者：" + author : "";
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
        courseMeta.hidden = courseAuthor.hidden && courseDuration.hidden;
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
        return track.label || languageLabels[track.language] || track.language || "字幕";
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
            closeMenus();
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
        captionStyleView = document.createElement("div");
        captionStyleView.className = "caption-menu-view";
        captionStyleView.hidden = true;
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
        var defaultLanguage = preferred && languages.indexOf(preferred) !== -1
            ? preferred
            : subtitleData.defaultLanguage;

        if (!defaultLanguage || languages.indexOf(defaultLanguage) === -1) {
            defaultLanguage = languages.indexOf("zh-TW") !== -1 ? "zh-TW" : languages[0];
        }
        setSubtitleLanguage(defaultLanguage || "off");
        applyCaptionAppearance();
    }

    function setSubtitleLanguage(language) {
        activeSubtitleLanguage = language;
        syncSubtitleTrackModes();
        captionButton.classList.toggle("is-active", language !== "off");
        markMenuSelection(captionMenu, language);
        savePreference(subtitleStorageKey, language);
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
        totalTimeLabel.textContent = formatTime(duration);
        if (chapters.length > 0) {
            setActiveChapter(findActiveChapter(video.currentTime));
        }
        updateCaptionOverlay();
    }

    function updateVolume() {
        var value = video.muted ? 0 : video.volume;
        volumeSlider.value = String(value);
        volumeSlider.style.setProperty("--progress", (value * 100) + "%");
        muteToggle.classList.toggle("is-muted", value === 0);
        muteToggle.classList.toggle("is-low", value > 0 && value <= 0.5);
        muteToggle.setAttribute("aria-label", value === 0 ? "開啟聲音" : "靜音");
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

    function closeMenus() {
        captionMenu.hidden = true;
        speedMenu.hidden = true;
        if (captionLanguageView && captionStyleView) {
            captionLanguageView.hidden = false;
            captionStyleView.hidden = true;
        }
        captionButton.setAttribute("aria-expanded", "false");
        speedButton.setAttribute("aria-expanded", "false");
    }

    function menusAreOpen() {
        return !captionMenu.hidden || !speedMenu.hidden;
    }

    function showControls() {
        window.clearTimeout(controlsTimer);
        videoStage.classList.remove("controls-hidden");
        if (!video.paused && !video.ended && !menusAreOpen()) {
            controlsTimer = window.setTimeout(function () {
                if (!document.getElementById("video-controls").contains(document.activeElement)) {
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
        return target.matches("input, textarea, select, button, [contenteditable='true']");
    }

    function bindEvents() {
        bigPlay.addEventListener("click", togglePlayback);
        playToggle.addEventListener("click", togglePlayback);
        video.addEventListener("click", togglePlayback);
        video.addEventListener("play", updatePlayState);
        video.addEventListener("pause", updatePlayState);
        video.addEventListener("ended", updatePlayState);
        video.addEventListener("timeupdate", updateTimeline);
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
        window.addEventListener("resize", function () {
            fitOpenMenus();
            syncChapterHeight();
            updateChapterTitleOverflow();
        });
        window.addEventListener("orientationchange", function () {
            fitOpenMenus();
            syncChapterHeight();
            updateChapterTitleOverflow();
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
            if (isTypingTarget(event.target)) {
                return;
            }
            if (event.code === "Space") {
                event.preventDefault();
                togglePlayback();
            } else if (event.key === "ArrowLeft") {
                video.currentTime = Math.max(0, video.currentTime - 10);
            } else if (event.key === "ArrowRight") {
                video.currentTime = Math.min(video.duration || Infinity, video.currentTime + 10);
            } else if (event.key.toLowerCase() === "m") {
                video.muted = !video.muted;
            } else if (event.key.toLowerCase() === "f") {
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
    installSpeedMenu();
    installPictureInPicture();
    bindEvents();
    syncChapterHeight();
    updateVolume();
    updateTimeline();
}());
