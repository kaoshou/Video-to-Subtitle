"""Pinned, bounded project discovery and private native player construction.

Project JavaScript is never evaluated by the service. OpenCam data is parsed
as JSON; EverCam config is carried to its browser player unchanged.
"""
import json
from pathlib import Path
import re

from mcp_state import MCPError, file_version
from safe_files import SafeDirectory, StagedDirectory
from web_export_model import SubtitleSource, canonical_language

MAX_RESOURCE = 32 * 1024 * 1024
MAX_RESOURCES = 64 * 1024 * 1024
SUBTITLE_NAME = re.compile(r'media(?:\.([A-Za-z0-9-]+))?\.(srt|vtt)', re.I)


def _resource(directory, name):
    with directory.open_read(name) as source:
        version = file_version(source)
        raw = source.read(MAX_RESOURCE + 1)
        if len(raw) > MAX_RESOURCE:
            raise MCPError('INVALID_PROJECT', 'Project resource exceeds 32 MiB.')
        if file_version(source) != version:
            raise MCPError('PROJECT_CHANGED', 'Project changed while reading; list media again.')
    return version, raw


def inspect_project(directory, media_name):
    """Only OpenCam's associated media qualifies; unrelated videos stay generic."""
    generic = {'type': 'mp4' if Path(media_name).suffix.lower() == '.mp4' else 'media', 'files': {}}
    if Path(media_name).suffix.lower() != '.mp4':
        return generic
    try:
        if media_name == 'media.mp4' and directory.info('opencam-player.js') is not None:
            from opencam_integration import _read_project
            # Bounded JSON parser also checks index/video and validates chapters.
            project = _read_project(directory)
            names = ['index.html', 'opencam-player.js']
            details = {'type': 'opencam', 'title': project.data['title'],
                       'chapter_count': len(project.data['chapters']),
                       'languages': [t['language'] for t in (project.data.get('subtitles') or {}).get('tracks', [])]}
        elif directory.info('opencam-player.js') is not None:
            return generic
        elif directory.info('config.js') is not None:
            names = ['config.js']
            if directory.info('index.html') is not None:
                names.append('index.html')
            entries = directory.names()
            if len(entries) > 4096:
                raise MCPError('LIST_LIMIT', 'Select a smaller project directory.')
            names += sorted(n for n in entries if SUBTITLE_NAME.fullmatch(n))
            details = {'type': 'evercam'}
        else:
            return generic
        files, total = {}, 0
        for name in names:
            version, raw = _resource(directory, name)
            total += len(raw)
            if total > MAX_RESOURCES:
                raise MCPError('INVALID_PROJECT', 'Project resources exceed 64 MiB.')
            if name == 'config.js' and not raw.strip():
                raise ValueError('Empty EverCam config')
            files[name] = version
        return dict(details, files=files)
    except (OSError, ValueError, UnicodeError, RecursionError) as error:
        raise MCPError('INVALID_PROJECT', 'Project is invalid, unsafe or unsupported; original files were not changed.') from error


def project_for_asset(state, asset, generation=None):
    parent = Path(asset['relative']).parent
    relative = '' if parent == Path('.') else parent.as_posix()
    with state.directory(asset['root_id'], relative, admitted_generation=generation) as directory:
        current = inspect_project(directory, Path(asset['relative']).name)
    expected = asset.get('project')
    if expected is not None and current != expected:
        raise MCPError('PROJECT_CHANGED', 'Project changed; list media and submit a new request.')
    return current


def build_project(state, asset, job, media, workspace, subtitles, cancelled):
    """Create a new native package privately; never modify the user's project."""
    arguments = job['arguments']
    project = project_for_asset(state, asset, job['generation'])
    kind = project['type']
    if kind != arguments['player_type']:
        raise MCPError('PROJECT_TYPE_MISMATCH', 'Project no longer matches requested player type.')
    selected = {s.language for s in subtitles}
    parent = Path(asset['relative']).parent
    relative = '' if parent == Path('.') else parent.as_posix()
    resources = {}
    with state.directory(asset['root_id'], relative, admitted_generation=job['generation']) as directory:
        for name, version in project['files'].items():
            if cancelled():
                raise MCPError('CANCELLED', 'Export cancelled.')
            current, raw = _resource(directory, name)
            if current != version:
                raise MCPError('PROJECT_CHANGED', 'Project resource changed during export.')
            match = SUBTITLE_NAME.fullmatch(name)
            if kind == 'evercam' and match:
                # A selected language replaces old VTT as well as old SRT.
                language = canonical_language(match[1] or 'zh-TW')
                if language in selected:
                    continue
            resources[name] = raw
    with StagedDirectory(workspace) as stage:
        with SafeDirectory(media.parent) as source, source.open_read(media.name) as stream:
            from web_export import probe_video_stream
            probe_video_stream(stream, media.name)
            stream.seek(0)
            stage.copy_from(stream, 'media.mp4', progress=lambda n: None, cancelled=cancelled)
        for name, raw in resources.items():
            stage.write_bytes(name, raw)
        for subtitle in subtitles:
            with SafeDirectory(subtitle.path.parent) as source:
                stage.write_bytes(subtitle.path.name, source.read_bytes(subtitle.path.name))
        folder = stage.publish('package')
    if kind == 'opencam':
        from opencam_integration import insert_subtitles, load_project
        local = tuple(SubtitleSource(folder / s.path.name, s.language) for s in subtitles)
        insert_subtitles(folder, local)
        data = load_project(folder).data
        if arguments['title']:
            data['title'] = arguments['title']
        default = arguments['default_subtitle']
        data['subtitles']['defaultTrackId'] = ('off' if default == 'off' else next(
            t['id'] for t in data['subtitles']['tracks'] if t['language'] == default))
        with SafeDirectory(folder) as directory:
            directory.write_bytes('opencam-player.js', ('window.OpenCamPlayerData = ' +
                json.dumps(data, ensure_ascii=True, allow_nan=False) + ';\n').encode('utf-8'))
    else:
        from evercam_integration import deploy_evercam_player
        ok, message, _ = deploy_evercam_player(str(folder))
        if not ok:
            raise MCPError('EXPORT_FAILED', message)
        with SafeDirectory(folder) as directory:
            config = directory.read_bytes('config.js')
            overrides = {'src': [{'src': 'media.mp4', 'type': 'video/mp4'}],
                         'defaultSubtitle': arguments['default_subtitle']}
            if arguments['title']:
                overrides['title'] = arguments['title']
            # The existing config runs only in the browser, exactly as in the
            # desktop EverCam converter. Preserve its chapters and course data.
            directory.write_bytes('config.js', config + b'\n;window.config = Object.assign('
                b'(typeof config === "object" ? config : window.config) || {}, ' +
                json.dumps(overrides, ensure_ascii=True).encode() + b');\n')
            raw = directory.read_bytes('subtitles-data.js').decode('utf-8')
            payload = json.loads(raw.split('window.EVERCAM_SUBTITLES = ', 1)[1].strip().removesuffix(';'))
            if len(payload['tracks']) > 32:
                raise MCPError('INVALID_PROJECT', 'Merged player exceeds 32 subtitle languages.')
            payload['defaultLanguage'] = arguments['default_subtitle']
            directory.write_bytes('subtitles-data.js', ('window.EVERCAM_SUBTITLES = ' +
                json.dumps(payload, ensure_ascii=True, allow_nan=False) + ';\n').encode('utf-8'))
    if cancelled():
        raise MCPError('CANCELLED', 'Export cancelled.')
    project_for_asset(state, asset, job['generation'])
    return folder
