"""Standalone video package inputs and export. Imported packages are data, never code."""
from contextlib import contextmanager
from dataclasses import dataclass
from io import BytesIO
import json
import math
import os
from pathlib import Path
import re
import html
import shutil
import sys
from uuid import uuid4

from safe_files import SafeDirectory, StagedDirectory, ExportCancelled
from web_export_model import (ExportRequest, Metadata, SubtitleSource, ValidationIssue,
                              canonical_language, validate_request)


@dataclass
class LoadedPackage:
    request: ExportRequest
    issues: list[ValidationIssue]


@contextmanager
def open_source(path):
    path = Path(path).absolute()
    with SafeDirectory(path.parent) as parent, parent.open_read(path.name) as stream:
        yield stream


def read_bounded(path, limit):
    with open_source(path) as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f'{Path(path).name}：檔案超過大小限制')
    return data


def parse_subtitles(text, extension, filename):
    """Strict standalone parser, deliberately separate from EverCam's lenient parser."""
    text = text.lstrip('\ufeff').replace('\r\n', '\n').replace('\r', '\n')
    lines = text.split('\n')
    vtt = extension.lower() == '.vtt'
    if extension.lower() not in ('.srt', '.vtt'):
        raise ValueError(f'{filename}：只接受 SRT／VTT')
    if vtt and (not lines or not re.fullmatch(r'WEBVTT(?:[ \t].*)?', lines[0])):
        raise ValueError(f'{filename}:1：缺少 WEBVTT 標頭')
    index = 1 if vtt else 0
    # WebVTT header metadata lasts until the first empty line.
    if vtt:
        while index < len(lines) and lines[index].strip(): index += 1
    cues = []

    def timestamp(token):
        pattern = r'(?:(\d{2,}):)?(\d{2}):(\d{2})\.(\d{3})' if vtt else r'(\d{2,}):(\d{2}):(\d{2}),(\d{3})'
        match = re.fullmatch(pattern, token)
        if not match:
            raise ValueError('無效的字幕時間')
        hours, minutes, seconds, milliseconds = match.groups()
        if int(minutes) > 59 or int(seconds) > 59:
            raise ValueError('分鐘或秒數超出範圍')
        value = int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds) + int(milliseconds) / 1000
        if not math.isfinite(value): raise ValueError('時間必須為有限數字')
        return value

    while index < len(lines):
        if not lines[index].strip():
            index += 1
            continue
        start_line = index + 1
        block = []
        while index < len(lines) and lines[index].strip():
            block.append(lines[index]); index += 1
        if vtt and (re.match(r'^NOTE(?:[ \t]|$)', block[0]) or block[0] in ('STYLE', 'REGION')):
            continue
        try:
            timing_index = 0 if '-->' in block[0] else 1
            if not vtt and timing_index == 1 and not block[0].isdigit():
                raise ValueError('無效的字幕序號')
            timing = block[timing_index]
            match = re.fullmatch(r'(\S+)\s+-->\s+(\S+)(?:[ \t]+(.+))?', timing)
            if not match or (not vtt and match[3]): raise ValueError('無效的字幕時間區塊')
            start, end = timestamp(match[1]), timestamp(match[2])
            body = '\n'.join(block[timing_index + 1:])
            if end <= start: raise ValueError('結束時間必須晚於開始時間')
            if not body.strip(): raise ValueError('字幕內容不可空白')
            cues.append({'start': start, 'end': end, 'text': body})
        except (ValueError, IndexError, OverflowError) as error:
            raise ValueError(f'{filename}:{start_line}：{error}') from error
    if not cues:
        raise ValueError(f'{filename}:1：沒有有效字幕')
    return cues


def read_subtitle(path):
    # Bound text inputs as well as the manifest. 32 MiB exceeds typical courses.
    text = read_bounded(path, 32 * 1024 * 1024).decode('utf-8-sig')
    return text, parse_subtitles(text, path.suffix, path.name)


def probe_video(path):
    with open_source(path) as source:
        return probe_video_stream(source, Path(path).name)


def probe_video_stream(source, filename):
    import av
    # The demuxer also accepts QuickTime; require ISO BMFF ftyp and MP4 brand.
    header = source.read(4096)
    if len(header) < 16 or header[4:8] != b'ftyp' or header[8:12] == b'qt  ':
        raise ValueError(f'{filename}：不是支援的 MP4 容器')
    source.seek(0)
    with av.open(source, mode='r') as container:
        if not container.streams.video:
            raise ValueError(f'{filename}：找不到影片軌')
        video = container.streams.video[0]
        duration = float(container.duration / av.time_base) if container.duration else None
        codec = video.codec_context.name
        # Verify at least one frame can be decoded, without claiming browser support.
        if next(container.decode(video), None) is None:
            raise ValueError(f'{filename}：沒有可讀取的影片影格')
        return {'duration': duration if duration and math.isfinite(duration) and duration > 0 else None,
                'codec': codec, 'size': os.fstat(source.fileno()).st_size}


def prepare_poster(path):
    from PIL import Image
    if Path(path).suffix.lower() not in ('.png', '.jpg', '.jpeg'):
        raise ValueError('封面只接受 PNG／JPEG')
    raw = read_bounded(path, 20 * 1024 * 1024)
    with Image.open(BytesIO(raw)) as image:
        if image.format not in ('PNG', 'JPEG') or image.width * image.height > 25_000_000:
            raise ValueError('封面格式無效或超過 2,500 萬像素')
        image.load()
        # A fresh RGB image strips EXIF, comments, ICC and other source metadata.
        clean = Image.new('RGB', image.size)
        clean.paste(image.convert('RGB'))
        output = BytesIO()
        clean.save(output, format='PNG')
        return output.getvalue()


def inspect_inputs(request):
    issues = validate_request(request)
    info = None
    try:
        info = probe_video(request.video)
        if info['codec'] != 'h264':
            issues.append(ValidationIssue('video', f"影片編碼 {info['codec']} 的瀏覽器支援可能不同；本工具不重新編碼", 'warning'))
    except (OSError, ValueError) as error:
        issues.append(ValidationIssue('video', str(error)))
    for track in request.subtitles:
        try:
            _, cues = read_subtitle(track.path)
            if info and info['duration'] and max(c['end'] for c in cues) > info['duration']:
                issues.append(ValidationIssue('subtitles', f'{track.path.name}：字幕超出影片長度，仍要保留完整時間軸嗎？', 'warning'))
        except (OSError, ValueError) as error:
            issues.append(ValidationIssue('subtitles', str(error)))
    if request.poster:
        try: prepare_poster(request.poster)
        except (OSError, ValueError) as error: issues.append(ValidationIssue('poster', str(error)))
    return issues


def load_package(folder):
    folder = Path(folder).absolute()
    with SafeDirectory(folder) as directory:
        with directory.open_read('web-export.json') as stream:
            raw = stream.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError('設定清單超過 1 MiB')
        try:
            data = json.loads(raw.decode('utf-8'), parse_constant=lambda v: (_ for _ in ()).throw(ValueError(v)))
            if (not isinstance(data, dict) or type(data.get('schemaVersion')) is not int or
                    data['schemaVersion'] != 1 or data.get('kind') != 'video-to-subtitle-web'):
                raise ValueError('不支援的設定版本或類型')
            if not isinstance(data['appVersion'], str): raise ValueError('無效的版本資訊')
            if not isinstance(data['packageId'], str): raise ValueError('缺少資料包識別碼')
            metadata = Metadata(**data['metadata'])
            video = data['video']
            if video['path'] != 'media.mp4': raise ValueError('無效的影片路徑')
            if 'duration' in video and (type(video['duration']) not in (int, float) or
                                      not math.isfinite(video['duration']) or video['duration'] <= 0):
                raise ValueError('無效的影片長度')
            poster = data['poster']
            if poster not in (None, 'poster.png', 'poster.jpg'): raise ValueError('無效的封面路徑')
            tracks = []
            for track in data['subtitles']:
                language = canonical_language(track['language'])
                if track['language'] != language or track['path'] not in (f'media.{language}.srt', f'media.{language}.vtt'):
                    raise ValueError('無效的字幕路徑或語言')
                tracks.append(SubtitleSource(folder / track['path'], language))
            request = ExportRequest(folder / 'media.mp4', tuple(tracks), metadata, folder.parent,
                                    folder.name + '-2', data['defaultSubtitle'],
                                    folder / poster if poster else None, data['packageId'])
            issues = validate_request(request)
            if issues: raise ValueError('\n'.join(i.message for i in issues))
        except (KeyError, TypeError, AttributeError) as error:
            raise ValueError('設定欄位缺失或型別無效') from error
        missing = []
        for path in [request.video] + [t.path for t in tracks] + ([request.poster] if request.poster else []):
            try:
                with directory.open_read(path.name): pass
            except FileNotFoundError:
                missing.append(ValidationIssue('file', f'缺少 {path.name}，請重新選擇'))
        return LoadedPackage(request, missing)


@dataclass(frozen=True)
class ExportResult:
    folder: Path
    index_path: Path
    package_id: str


def export_package(request, *, app_version, progress, cancelled, accept_warnings=False):
    if cancelled(): raise ExportCancelled('已取消匯出')
    issues = inspect_inputs(request)
    blocking = [i for i in issues if i.severity == 'error' or not accept_warnings]
    if blocking: raise ValueError('\n'.join(i.message for i in blocking))
    metadata = {key: value.strip() for key, value in vars(request.metadata).items()}
    package_id = request.package_id or str(uuid4())
    base = Path(getattr(sys, '_MEIPASS', Path(__file__).parent)) / 'assets'
    # Only explicitly trusted built-in assets, never JS/HTML from an imported package.
    resources = {name: (base / 'evercam_player' / name).read_bytes()
                 for name in ('css/evercam-modern.css', 'js/evercam-modern.js')}
    template = (base / 'standalone_player/index.html').read_text(encoding='utf-8')
    resources['index.html'] = template.replace('{{TITLE}}', html.escape(metadata['title'])).encode('utf-8')
    tracks, manifest_tracks = [], []
    for source in request.subtitles:
        text, cues = read_subtitle(source.path)
        language = canonical_language(source.language)
        name = f'media.{language}{source.path.suffix.lower()}'
        resources[name] = text.encode('utf-8')
        manifest_tracks.append({'language': language, 'path': name})
        tracks.append({'language': language, 'label': '預設字幕' if language == 'und' else language, 'cues': cues})
    poster = 'poster.png' if request.poster else None
    if poster: resources[poster] = prepare_poster(request.poster)
    default = 'off' if request.default_subtitle == 'off' else canonical_language(request.default_subtitle)
    with SafeDirectory(request.output_parent) as parent:
        if parent.info(request.folder_name) is not None: raise FileExistsError(request.folder_name)
        with open_source(request.video) as source:
            size = os.fstat(source.fileno()).st_size
            estimated = size + sum(map(len, resources.values())) + 1024 * 1024
            if shutil.disk_usage(parent.path).free < estimated + max(64 * 1024 * 1024, estimated // 20):
                raise OSError('磁碟可用空間不足，請選擇其他輸出位置')
            with StagedDirectory(parent) as stage:
                stage.copy_from(source, 'media.mp4', progress=lambda n: progress(n, size), cancelled=cancelled)
                # Probe the actual copied bytes, not an earlier path-based snapshot.
                with stage.directory.open_read('media.mp4') as copied:
                    info = probe_video_stream(copied, 'media.mp4')
                manifest_video = {'path': 'media.mp4'}
                if info['duration']: manifest_video['duration'] = info['duration']
                manifest = {'schemaVersion': 1, 'kind': 'video-to-subtitle-web', 'packageId': package_id,
                            'appVersion': app_version, 'metadata': metadata, 'video': manifest_video,
                            'poster': poster, 'subtitles': manifest_tracks, 'defaultSubtitle': default}
                config = dict(metadata, mode='standalone', packageId=package_id, defaultSubtitle=default,
                              index=[], src=[{'src': 'media.mp4', 'type': 'video/mp4'}])
                if info['duration']: config['duration'] = info['duration']
                if poster: config['poster'] = poster
                resources['web-export.json'] = json.dumps(manifest, ensure_ascii=False, indent=2).encode('utf-8')
                resources['player-config.js'] = ('window.VTS_PLAYER_CONFIG = ' + json.dumps(config) + ';\n').encode('utf-8')
                resources['subtitles-data.js'] = ('window.EVERCAM_SUBTITLES = ' + json.dumps({'tracks': tracks}) + ';\n').encode('utf-8')
                for name, data in resources.items():
                    if cancelled(): raise ExportCancelled('已取消匯出')
                    stage.write_bytes(name, data)
                if cancelled(): raise ExportCancelled('已取消匯出')
                folder = stage.publish(request.folder_name)
    return ExportResult(folder, folder / 'index.html', package_id)
