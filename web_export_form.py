"""Pure quick-export form rules, independent of the desktop toolkit."""
from dataclasses import dataclass
import os
from pathlib import Path
import re

from web_export_model import SubtitleSource, TitleState, canonical_language, validate_folder_name

LANGUAGES = {'und': '預設字幕', 'zh-TW': '繁體中文', 'zh-CN': '簡體中文', 'en': '英文',
             'ja': '日文', 'ko': '韓文', 'fr': '法文', 'de': '德文', 'es': '西班牙文'}


def language_label(value):
    return LANGUAGES.get(value, value)


def language_code(value):
    value = {label: code for code, label in LANGUAGES.items()}.get(value, value)
    try:
        return canonical_language(value)
    except ValueError:
        return ''


@dataclass(frozen=True)
class ExportAction:
    enabled: bool
    label: str
    hint: str


def export_action_state(form, phase, media_ready):
    busy = {'reading': ('正在讀取…', '正在讀取影片與字幕，請稍候。'),
            'checking': ('正在檢查…', '正在檢查字幕、相容性與輸出設定。'),
            'exporting': ('正在建立…', '正在複製影片與建立網頁，原始檔案不會被修改。'),
            'cancelling': ('正在取消…', '正在停止工作；部分暫存檔案可能會保留。')}
    if phase in busy:
        return ExportAction(False, *busy[phase])
    hint = ''
    if not form.video:
        hint = '先選擇 MP4 影片，字幕會自動讀入。'
    elif not media_ready:
        hint = '影片尚未通過讀取檢查，請重新選擇可讀取的 MP4。'
    elif not form.tracks:
        hint = '找不到同名字幕；請放入影片旁，或從進階設定加入。'
    else:
        languages = [language_code(t.language) for t in form.tracks]
        if '' in languages or len(set(languages)) != len(languages):
            hint = '請在進階設定修正字幕語言：不可空白或重複。'
        elif form.default_language() not in ['off'] + languages:
            hint = '請在進階設定重新選擇預設字幕。'
        elif not form.title.value.strip() or not form.output_parent:
            hint = '請在進階設定填入標題與儲存位置。'
        else:
            try:
                validate_folder_name(form.folder_name)
            except ValueError as error:
                hint = str(error)
    return ExportAction(not hint, '建立網頁', hint or '已就緒，按「建立網頁」即可。')


def suggested_folder(parent, stem):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '-', stem).strip(' .')[:80] + '-web'
    try:
        validate_folder_name(name)
    except ValueError:
        name = 'video-web'
    candidate, index = name, 2
    while os.path.lexists(Path(parent) / candidate):
        candidate, index = f'{name}-{index}', index + 1
    return candidate


def find_subtitle_candidates(video):
    video = Path(video)
    found = []
    try:
        for path in sorted(video.parent.iterdir()):
            if path.suffix.lower() not in ('.srt', '.vtt') or path.is_symlink():
                continue
            if getattr(path.lstat(), 'st_file_attributes', 0) & 0x400 or not path.is_file():
                continue  # Windows reparse points are not automatic input candidates.
            language = 'und'
            if path.stem != video.stem:
                if not path.stem.startswith(video.stem + '.'):
                    continue
                language = language_code(path.stem[len(video.stem) + 1:])
                if not language:
                    continue
            found.append(SubtitleSource(path, language))
    except OSError:
        pass
    return found


@dataclass
class Track:
    path: Path
    language: str = ''
    automatic: bool = False


class ExportFormState:
    def __init__(self):
        self.video = None
        self.title = TitleState()
        self.tracks = []
        self.output_parent = None
        self.folder_name = ''
        self.parent_manual = self.folder_manual = False
        self.default_choice = 'auto'

    def select_video(self, video):
        video = Path(video)
        if video != self.video:
            for track in list(self.tracks):
                if track.automatic:
                    self.remove_track(track)
        self.video = video
        self.title.select_video(video)
        if not self.parent_manual:
            self.output_parent = video.parent
        self.refresh_output_name()

    def offer_candidates(self, candidates):
        # Manual choices win. For each remaining language choose one file,
        # preferring VTT to SRT. Keep untagged subtitles first without guessing.
        self.tracks = [track for track in self.tracks if not track.automatic]
        languages = {track.language for track in self.tracks}
        added = False
        for candidate in sorted(candidates, key=lambda c: (
                (c.language or 'und') != 'und', c.language or 'und',
                c.path.suffix.lower() != '.vtt', str(c.path))):
            language = candidate.language or 'und'
            if language in languages or any(t.path.absolute() == candidate.path.absolute() for t in self.tracks):
                continue
            self.add_track(candidate.path, language, automatic=True)
            languages.add(language)
            added = True
        if self.default_choice not in ('auto', 'off', '') and self.default_choice not in languages:
            self.default_choice = ''
        return added

    def add_track(self, path, language='', automatic=False):
        path = Path(path)
        if not any(t.path.absolute() == path.absolute() for t in self.tracks):
            self.tracks.append(Track(path, language or 'und', automatic))

    def set_track_language(self, track, label):
        old = track.language
        track.language = language_code(label)
        track.automatic = False
        if old and self.default_choice == old and old != track.language:
            self.default_choice = ''

    def remove_track(self, track):
        self.tracks.remove(track)
        if track.language and self.default_choice == track.language:
            self.default_choice = ''

    def set_output_parent(self, path):
        self.output_parent = Path(path)
        self.parent_manual = True
        self.refresh_output_name()

    def set_folder_name(self, value):
        self.folder_name = value
        self.folder_manual = True

    def refresh_output_name(self):
        if not self.folder_manual and self.video and self.output_parent:
            self.folder_name = suggested_folder(self.output_parent, self.video.stem)

    def default_language(self):
        if self.default_choice == 'auto':
            return next((t.language for t in self.tracks if t.language), '')
        return self.default_choice
