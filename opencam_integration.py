"""Attach timed subtitles to OpenCam's existing schema-v1 player, not a conversion.

Imported JavaScript is strictly parsed as a JSON assignment, never executed.
Every publication uses the shared safe IO and has its own exclusive backup.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import threading
from uuid import uuid4
from weakref import WeakValueDictionary

from safe_files import SafeDirectory
from web_export import read_subtitle
from web_export_form import ExportFormState, find_subtitle_candidates
from web_export_model import canonical_language

DATA_FILE = 'opencam-player.js'
MAX_DATA = 32 * 1024 * 1024
_project_locks = WeakValueDictionary()
_project_locks_guard = threading.Lock()


def _project_lock(path):
    # SafeDirectory normalizes the explicitly selected parent's aliases. Keep
    # one transaction per actual project even across nonmodal UI windows.
    key = os.path.normcase(os.path.realpath(path))
    with _project_locks_guard:
        lock = _project_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _project_locks[key] = lock
        return lock


@dataclass(frozen=True)
class OpenCamProject:
    folder: Path
    data: dict
    raw: bytes

    @property
    def video(self):
        return self.folder / 'media.mp4'


@dataclass(frozen=True)
class InsertResult:
    index_path: Path
    backup_path: Path
    languages: tuple[str, ...]


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _invalid_constant(value):
    raise ValueError(f'OpenCam 資料含有無效數字：{value}')


def _validate_cues(cues):
    if not isinstance(cues, list) or not 0 < len(cues) <= 100000:
        raise ValueError('字幕段落數量必須為 1～100,000')
    for cue in cues:
        if (not isinstance(cue, dict) or not _finite(cue.get('start')) or
                not _finite(cue.get('end')) or cue['start'] < 0 or cue['end'] <= cue['start'] or
                not isinstance(cue.get('text'), str) or len(cue['text']) > 10000):
            raise ValueError('OpenCam 字幕格式或時間無效')


def _read_project(directory):
    for name in ('index.html', 'media.mp4'):
        if directory.check_file(name) is None:
            raise ValueError(f'OpenCam 專案缺少 {name}')
    with directory.open_read(DATA_FILE) as source:
        raw = source.read(MAX_DATA + 1)
    if len(raw) > MAX_DATA:
        raise ValueError('OpenCam 播放器資料超過 32 MiB 限制')
    match = re.fullmatch(r'\s*(?://[^\n]*\n\s*)*window\.OpenCamPlayerData\s*=\s*([\s\S]*?)\s*;\s*',
                         raw.decode('utf-8-sig'))
    if not match:
        raise ValueError('只支援 OpenCam 產生的 JSON 資料，不執行 JavaScript 程式碼')
    data = json.loads(match[1], parse_constant=_invalid_constant)
    if (not isinstance(data, dict) or data.get('format') != 'opencam.web-player' or
            type(data.get('schemaVersion')) is not int or data['schemaVersion'] != 1 or
            data.get('entry') != 'index.html' or data.get('media') != 'media.mp4' or
            not isinstance(data.get('title'), str) or not isinstance(data.get('chapters'), list)):
        raise ValueError('不是支援的 OpenCam 網頁播放器（schemaVersion 1）')
    for chapter in data['chapters']:
        if (not isinstance(chapter, dict) or not isinstance(chapter.get('title'), str) or
                not _finite(chapter.get('start')) or not _finite(chapter.get('end')) or
                chapter['start'] < 0 or chapter['end'] < chapter['start']):
            raise ValueError('OpenCam 章節資料無效；未修改原檔')
    subtitles = data.get('subtitles')
    if subtitles is not None:
        if not isinstance(subtitles, dict):
            raise ValueError('OpenCam 字幕資料無效')
        tracks = subtitles.get('tracks', [])
        if not isinstance(tracks, list) or len(tracks) > 32:
            raise ValueError('OpenCam 最多支援 32 軌字幕')
        ids = set()
        for track in tracks:
            if (not isinstance(track, dict) or not isinstance(track.get('id'), str) or
                    not 0 < len(track['id']) <= 128 or track['id'] == 'off' or track['id'] in ids or
                    not isinstance(track.get('label'), str) or not isinstance(track.get('language'), str)):
                raise ValueError('OpenCam 字幕軌資料無效')
            ids.add(track['id'])
            _validate_cues(track.get('cues'))
    return OpenCamProject(Path(directory.path), data, raw)


def load_project(folder):
    with SafeDirectory(folder) as directory:
        return _read_project(directory)


def detect_opencam_project(path):
    """Only the associated video/entry identifies a project, not a nearby MP4."""
    if not path:
        return False, None
    path = Path(path).absolute()
    try:
        if path.is_dir():
            folder = path
        elif path.name in ('media.mp4', 'index.html', DATA_FILE):
            folder = path.parent
        else:
            return False, None
        load_project(folder)
        return True, str(folder)
    except (OSError, ValueError, UnicodeError, RecursionError):
        return False, None


def completed_projects(files, sources):
    """Successful timed output must map explicitly to the OpenCam source media."""
    found = []
    for subtitle in files:
        if Path(subtitle).suffix.lower() not in ('.srt', '.vtt') or not Path(subtitle).is_file():
            continue
        source = sources.get(str(subtitle))
        if not source or Path(source).suffix.lower() != '.mp4':
            continue
        detected, folder = detect_opencam_project(source)
        if detected:
            found.append((folder, str(subtitle)))
    return found


def subtitle_candidates(folder):
    project = load_project(folder)
    form = ExportFormState()
    form.offer_candidates(find_subtitle_candidates(project.video))
    return tuple(form.tracks)


def insert_subtitles(folder, subtitles):
    """Merge one track per language; retain unrelated data and the default track.

    Validate the entire operation before creating a backup. If backup creation
    fails the original is untouched. A failed replacement still leaves a backup.
    """
    prepared = []
    languages = set()
    for source in subtitles:
        language = canonical_language(source.language)
        if language in languages:
            raise ValueError(f'字幕語言重複：{language}')
        languages.add(language)
        path = Path(source.path)
        _, cues = read_subtitle(path)
        _validate_cues(cues)
        prepared.append((language, path.name, cues))
    if not prepared:
        raise ValueError('請至少加入一個 SRT／VTT 字幕檔')
    directory = SafeDirectory(folder)
    with _project_lock(directory.path), directory:
        project = _read_project(directory)
        data = project.data
        payload = data.get('subtitles') or {}
        tracks = payload.get('tracks', [])
        by_language = {}
        for track in tracks:
            try:
                code = canonical_language(track['language'].replace('_', '-'))
            except ValueError:
                continue  # Preserve unknown existing language tags unchanged.
            if code in by_language:
                raise ValueError(f'原播放器的字幕語言重複：{code}；請先在 OpenCam 整理字幕軌')
            by_language[code] = track
        for language, name, cues in prepared:
            track = by_language.get(language)
            if track is None:
                track = {'id': str(uuid4())}
                tracks.append(track)
            track.update(language=language, label=f'{name} · {language}', cues=cues)
        if len(tracks) > 32:
            raise ValueError('OpenCam 最多支援 32 軌字幕；未修改原檔')
        default_id = payload.get('defaultTrackId')
        if default_id not in [t['id'] for t in tracks]:
            default_id = tracks[0]['id']
        payload.update(defaultTrackId=default_id, tracks=tracks)
        data['subtitles'] = payload
        updated = ('// Generated by OpenCam — https://github.com/kaoshou/OpenCam\n'
                   'window.OpenCamPlayerData = ' + json.dumps(data, ensure_ascii=True, indent=2,
                                                              allow_nan=False) + ';\n').encode('utf-8')
        if len(updated) > MAX_DATA:
            raise ValueError('置入後播放器資料超過 32 MiB；未修改原檔')
        stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
        backup = f'opencam-player.backup-{stamp}-{uuid4().hex}.js'
        directory.write_bytes(backup, project.raw, exclusive=True)
        # Do not knowingly overwrite a newer edit made while preparing backup.
        with directory.open_read(DATA_FILE) as source:
            if source.read(MAX_DATA + 1) != project.raw:
                raise OSError('OpenCam 播放器資料已被其他操作更新，未置入字幕；備份已保留')
        directory.write_bytes(DATA_FILE, updated)
        return InsertResult(Path(directory.path) / 'index.html', Path(directory.path) / backup,
                            tuple(code for code, _, _ in prepared))
