"""Pure input contracts for standalone video packages; no GUI/media imports."""
from dataclasses import dataclass
from pathlib import Path
import re
from uuid import UUID


@dataclass(frozen=True)
class Metadata:
    title: str
    author: str = ''
    organization: str = ''
    description: str = ''


@dataclass(frozen=True)
class SubtitleSource:
    path: Path
    language: str


@dataclass(frozen=True)
class ExportRequest:
    video: Path
    subtitles: tuple[SubtitleSource, ...]
    metadata: Metadata
    output_parent: Path
    folder_name: str
    default_subtitle: str
    poster: Path | None = None
    package_id: str | None = None


@dataclass(frozen=True)
class ValidationIssue:
    field: str
    message: str
    severity: str = 'error'


def canonical_language(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z]{2,3}(?:-[A-Za-z]{4})?(?:-(?:[A-Za-z]{2}|[0-9]{3}))?', value):
        raise ValueError('請選擇有效的字幕語言碼，例如 zh-TW 或 en')
    parts = value.split('-')
    return '-'.join([parts[0].lower()] + [p.title() if len(p) == 4 else p.upper() for p in parts[1:]])


def validate_folder_name(value: str) -> str:
    if (not isinstance(value, str) or not value or value in ('.', '..') or
            value.endswith((' ', '.')) or any(ord(c) < 32 or c in '<>:"/\\|?*' for c in value) or
            re.match(r'^(CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\.|$)', value, re.I)):
        raise ValueError('輸出資料夾名稱不符合跨平台檔名規則')
    return value


def validate_request(request: ExportRequest) -> list[ValidationIssue]:
    issues = []
    for field, limit in [('title', 200), ('author', 100), ('organization', 200), ('description', 5000)]:
        value = getattr(request.metadata, field)
        if not isinstance(value, str) or len(value.strip()) > limit or (field == 'title' and not value.strip()):
            issues.append(ValidationIssue(field, f'{field} 必須為文字且最多 {limit} 字元' + ('，不可空白' if field == 'title' else '')))
    try:
        validate_folder_name(request.folder_name)
    except ValueError as error:
        issues.append(ValidationIssue('folder_name', str(error)))
    if request.video.suffix.lower() != '.mp4':
        issues.append(ValidationIssue('video', '請選擇 MP4 影片'))
    if not request.subtitles:
        issues.append(ValidationIssue('subtitles', '至少需要一軌字幕'))
    languages = set()
    for track in request.subtitles:
        try:
            language = canonical_language(track.language)
            if language in languages:
                raise ValueError(f'字幕語言重複：{language}')
            languages.add(language)
        except ValueError as error:
            issues.append(ValidationIssue('subtitles', str(error)))
        if track.path.suffix.lower() not in ('.srt', '.vtt'):
            issues.append(ValidationIssue('subtitles', f'{track.path.name}：只接受 SRT／VTT'))
    try:
        default = 'off' if request.default_subtitle == 'off' else canonical_language(request.default_subtitle)
        if default != 'off' and default not in languages:
            raise ValueError('預設字幕已不存在，請重新選擇')
    except ValueError as error:
        issues.append(ValidationIssue('default_subtitle', str(error)))
    if request.poster and request.poster.suffix.lower() not in ('.png', '.jpg', '.jpeg'):
        issues.append(ValidationIssue('poster', '封面只接受本機 PNG／JPEG'))
    if request.package_id is not None:
        try:
            if str(UUID(request.package_id)) != request.package_id:
                raise ValueError('非標準 UUID')
        except (ValueError, TypeError, AttributeError):
            issues.append(ValidationIssue('package_id', '資料包識別碼無效'))
    return issues


class TitleState:
    def __init__(self):
        self.value = ''
        self.dirty = False
        self._video = None

    def select_video(self, path: Path):
        self._video = path
        if not self.dirty:
            self.value = path.stem

    def edit(self, text: str):
        self.value, self.dirty = text, True

    def use_filename(self):
        self.dirty = False
        self.value = self._video.stem if self._video else ''
