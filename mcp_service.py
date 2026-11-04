"""Local MCP business tools, private translation drafts and a single job queue.

Importing this module does not import inference engines, start workers or create
storage. A broker owns one Service. A lifetime process lock prevents a second
worker owner from marking a live owner's jobs interrupted.
"""
import contextlib
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import queue
import secrets
import shutil
import stat
import threading

from mcp_state import MCPError, ProcessLock, State, _private_directory, file_version, directory_identity
from mcp_translation import batches, render_srt, validate_batch
from mcp_projects import inspect_project, project_for_asset, build_project
from safe_files import SafeDirectory, StagedDirectory
from web_export import export_package, parse_subtitles
from web_export_model import ExportRequest, Metadata, SubtitleSource, canonical_language, validate_folder_name


from mcp_contracts import (TOOL_SCHEMAS, _validate, _schema, _ID, _REQUEST, _SETTINGS, _MEDIA,
                           _SUBTITLES, _TERMINAL, _MUTATING)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False, separators=(',', ':')).encode()).hexdigest()


def _stream_hash(stream):
    before, digest, count = os.fstat(stream.fileno()), hashlib.sha256(), 0
    while True:
        chunk = stream.read(4 * 1024 * 1024)
        if not chunk:
            break
        count += len(chunk)
        if count > before.st_size:
            raise MCPError('SOURCE_CHANGED', 'Source changed during reading.')
        digest.update(chunk)
    after = os.fstat(stream.fileno())
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or count != before.st_size:
        raise MCPError('SOURCE_CHANGED', 'Source changed during reading.')
    return digest.hexdigest()


def _ready(settings):
    from transcriber import inspect_model_cache
    status = inspect_model_cache(settings['model'], settings.get('cache_dir'), settings['device'])
    if status.state != 'ready':
        code = 'MODEL_ACCESS_ERROR' if status.state == 'unavailable' else 'MODEL_DOWNLOAD_REQUIRED'
        raise MCPError(code, 'Selected local model is unavailable; use the local model manager.')
    return status.path


def _local_model_path(model_size, download_root=None, device='cpu', **kwargs):
    """Child-only loader guard: the real download function is never called."""
    return _ready({'model': model_size, 'device': device, 'cache_dir': download_root})


def _inference_child(settings, media_path, connection, cancelled, state_path):
    """One model lifetime per process; only bounded primitive IPC is emitted."""
    # Engine diagnostics must never escape into the broker's protocol stream.
    with open(os.devnull, 'w') as quiet, contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        from mcp_inference import child_residency
        residency = child_residency(state_path, cancelled)
        if residency is None:
            connection.close()
            return
        _child_run(settings, media_path, connection, cancelled)


def _child_run(settings, media_path, connection, cancelled):
    try:
        os.environ['HF_HUB_OFFLINE'] = '1'
        os.environ['TRANSFORMERS_OFFLINE'] = '1'
        import transcriber
        transcriber.download_model_with_progress = _local_model_path
        _ready(settings)
        engine = transcriber.SubtitleTranscriber(**_engine_settings(settings))
        result = _run_engine(engine, settings, media_path, cancelled.is_set)
        # The output path is fixed server-side, never accepted from IPC.
        if result:
            output = Path(media_path).with_suffix('.srt')
            if Path(result) != output:
                raise MCPError('INVALID_SUBTITLE', 'Unexpected transcription output.')
        from batch_policy import decision_summary
        connection.send_bytes(json.dumps({'ok': bool(result),
            'batch_decision': decision_summary(getattr(engine, 'last_batch_decision', None))}).encode('utf-8'))
    except MCPError as error:
        connection.send_bytes(json.dumps({'error': error.code}).encode('utf-8'))
    except Exception:
        connection.send_bytes(b'{"error":"TRANSCRIPTION_FAILED"}')
    finally:
        connection.close()


def _engine_settings(settings):
    return {'model_size': settings['model'], 'device': settings['device'],
            'download_root': settings.get('cache_dir'),
            'compute_type': 'float16' if settings['device'] == 'cuda' else 'int8'}


def _run_engine(engine, settings, media_path, cancelled):
    engine.load_model(cancel_check_callback=cancelled)
    if cancelled():
        return None
    options = {key: value for key, value in settings.items()
               if key in _SETTINGS and key not in ('model', 'device', 'language', 'batch_mode')}
    if settings.get('batch_mode') == 'auto':
        options['batch_size'] = 'auto'
    return engine.run(str(media_path), output_format='srt', cancel_check_callback=cancelled, **options)


class Service:
    def __init__(self, state: State, *, transcribe_factory=None):
        state.require_no_cleanup()
        self.state, self._factory = state, transcribe_factory
        self._guard, self._queue = threading.RLock(), queue.Queue()
        self._closed, self._stop = False, threading.Event()
        self._events, self._thread = {}, None
        self._owner = None
        # Read-only construction remains lazy when no old jobs exist.
        if any(j.get('state') not in _TERMINAL for j in state.records('jobs')):
            self._own_worker()

    def _own_worker(self):
        if self._owner is not None:
            return
        owner = ProcessLock(self.state.path / 'locks', 'service-owner')
        if not owner.acquire():
            raise MCPError('SERVICE_BUSY', 'Another local service owns the job queue.')
        self._owner = owner
        try:
            for old in self.state.records('jobs'):
                if old.get('state') not in _TERMINAL:
                    with self.state.mutation('jobs', old['id']) as job:
                        job.update(state='interrupted', error={'code': 'JOB_INTERRUPTED',
                                                             'message': 'Previous service stopped before completion.'})
        except BaseException:
            owner.release()
            self._owner = None
            raise

    @property
    def busy(self):
        with self._guard:
            return bool(self._events)

    def close(self):
        with self._guard:
            self._closed = True
            self._stop.set()
            for event in self._events.values():
                event.set()
            thread = self._thread
        if thread is not None:
            thread.join()  # Cooperative: never terminate native inference.
        if self._owner is not None:
            self._owner.release()
            self._owner = None

    def call(self, name: str, arguments: dict) -> dict:
        if name not in TOOL_SCHEMAS:
            raise MCPError('UNKNOWN_TOOL', 'Unknown local tool.')
        _validate(arguments, TOOL_SCHEMAS[name])
        with self._guard:
            if self._closed:
                raise MCPError('SERVICE_CLOSED', 'The local service has closed.')
            if name not in ('get_status', 'get_job', 'cancel_job'):
                self.state.require_enabled()
            if name in _MUTATING:
                return self._idempotent(name, arguments)
            return getattr(self, '_' + name)(**arguments)

    def _idempotent(self, name, arguments):
        key = _digest([name, arguments['request_id']])
        digest = _digest(arguments)
        # Separate guard from State's nonreentrant record lock. Pending is
        # durable before side effects; crash retries never execute them twice.
        with ProcessLock(self.state.path / 'locks', 'request-' + key):
            try:
                previous = self.state.get('requests', key)
            except MCPError as error:
                if error.code != 'NOT_FOUND':
                    raise
                previous = None
            if previous:
                if previous['digest'] != digest:
                    raise MCPError('REQUEST_CONFLICT', 'Request ID was already used for different arguments.')
                if previous.get('status') == 'done':
                    self._authorize_result(name, arguments)
                    return previous['result']
                if previous.get('error'):
                    raise MCPError(previous['error'], 'The original request failed; use a new request ID to retry.')
                raise MCPError('JOB_INTERRUPTED', 'The original request was interrupted; it will not be repeated automatically.')
            pending = {'id': key, 'tool': name, 'digest': digest, 'status': 'pending'}
            self.state.put('requests', key, pending)
            try:
                result = getattr(self, '_' + name)(**{k: v for k, v in arguments.items() if k != 'request_id'})
            except MCPError as error:
                self.state.put('requests', key, dict(pending, status='failed', error=error.code))
                raise
            self.state.put('requests', key, dict(pending, status='done', result=result))
            return result

    def _authorize_result(self, name, args):
        if name == 'import_subtitle':
            self._asset(args['media_id'])
            self._asset(args['subtitle_id'])
        elif 'asset_id' in args:
            self._asset(args['asset_id'])
        elif 'source_id' in args:
            self._source(args['source_id'])
        elif 'draft_id' in args:
            self._draft(args['draft_id'])

    def _asset(self, id, generation=None):
        asset = self.state.get('assets', id)
        with self.state.file(asset['root_id'], asset['relative'], admitted_generation=generation) as stream:
            if asset.get('version') != file_version(stream):
                raise MCPError('SOURCE_CHANGED', 'Asset changed; list and import the current file again.')
        return asset

    def _asset_hash(self, asset, generation=None):
        with self.state.file(asset['root_id'], asset['relative'], admitted_generation=generation) as stream:
            return _stream_hash(stream)

    def _source(self, id, generation=None):
        source = self.state.get('sources', id)
        self._asset(source['media_id'], generation)
        origin = self._asset(source['origin_id'], generation)
        if self._asset_hash(origin, generation) != source['origin_hash']:
            raise MCPError('SOURCE_CHANGED', 'Source changed; import or transcribe a new revision.')
        self._source_authorized(source, generation)
        return source

    def _source_authorized(self, source, generation=None):
        self._asset(source['media_id'], generation)
        self._asset(source['origin_id'], generation)

    def _draft(self, id):
        draft = self.state.get('drafts', id)
        return draft, self._source(draft['source_id'])

    def _get_status(self):
        policy = self.state.policy()
        result = {'version': 1, 'enabled': policy['enabled'],
                  'access_mode': policy.get('options', {}).get('access_mode', 'restricted'),
                  'roots': [{'id': r['id'], 'label': r['label']} for r in policy['roots']],
                  'jobs': [{'job_id': j['id'], 'state': j['state']} for j in self.state.records('jobs')]}
        if policy['enabled']:
            try:
                _ready(self._settings({}))
                result['model_ready'] = True
            except MCPError as error:
                result.update(model_ready=False, model_error=error.code)
        return result

    def _list_media(self, root_id=None, relative='', cursor=0, limit=100, path=None):
        if (root_id is None) == (path is None) or (path is not None and relative):
            raise MCPError('INVALID_ARGUMENT', 'Supply either path or root_id (with optional relative).')
        selected_name = None
        if path is not None:
            if not Path(path).is_absolute() or '..' in Path(path).parts:
                raise MCPError('UNSAFE_PATH', 'Use an absolute local path without parent traversal.')
            try:
                info = os.lstat(path)
            except OSError as error:
                raise MCPError('NOT_FOUND', 'The requested path is unavailable.') from error
            if stat.S_ISDIR(info.st_mode):
                root_id, relative = self.state.path_location(path)
            elif stat.S_ISREG(info.st_mode) and Path(path).suffix.lower() in _MEDIA | _SUBTITLES:
                selected_name = Path(path).name
                root_id, relative = self.state.path_location(str(Path(path).parent))
            else:
                raise MCPError('UNSAFE_PATH', 'Expected a regular supported media/subtitle file or directory.')
        candidates = []
        with self.state.directory(root_id, relative) as directory:
            with os.scandir(directory.fd if directory.fd is not None else directory.path) as entries:
                for index, entry in enumerate(entries):
                    if index >= 4096:
                        raise MCPError('LIST_LIMIT', 'Select a smaller media directory.')
                    suffix = Path(entry.name).suffix.lower()
                    if (selected_name is None or entry.name == selected_name) and suffix in _MEDIA | _SUBTITLES and stat.S_ISREG(entry.stat(follow_symlinks=False).st_mode):
                        candidates.append(entry.name)
        candidates.sort()
        items = []
        for name in candidates[cursor:cursor + limit]:
            rel = relative + '/' + name if relative else name
            with self.state.file(root_id, rel) as stream:
                version = file_version(stream)
            with self.state.directory(root_id, relative) as directory:
                project = inspect_project(directory, name) if Path(name).suffix.lower() in _MEDIA else None
            id = _digest([root_id, rel, version, project])
            record = {'id': id, 'root_id': root_id, 'relative': rel,
                      'version': version,
                      'kind': 'subtitle' if Path(name).suffix.lower() in _SUBTITLES else 'media'}
            if project is not None:
                record['project'] = project
            with ProcessLock(self.state.path / 'locks', 'policy'):
                with self.state.file(root_id, rel) as stream:
                    if file_version(stream) != version:
                        raise MCPError('SOURCE_CHANGED', 'Media changed during listing; list again.')
                    self.state.put('assets', id, record)
            item = {'asset_id': id, 'name': name, 'relative': rel, 'kind': record['kind']}
            if project is not None:
                item['project_type'] = project['type']
                item['project'] = {k: v for k, v in project.items() if k != 'files'}
            items.append(item)
        with ProcessLock(self.state.path / 'locks', 'policy'):
            with self.state.directory(root_id, relative):
                return {'items': items, 'next_cursor': cursor + limit if cursor + limit < len(candidates) else None}

    def _read_subtitle(self, stream, suffix):
        raw = stream.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            raise MCPError('INVALID_SUBTITLE', 'Subtitle exceeds the 2 MiB input limit.')
        try:
            cues = parse_subtitles(raw.decode('utf-8-sig'), suffix, 'subtitle')
        except (ValueError, UnicodeError) as error:
            raise MCPError('INVALID_SUBTITLE', 'Invalid UTF-8 SRT/VTT source.') from error
        for cue in cues:
            cue['cue_id'] = secrets.token_hex(16)
        return raw, cues

    def _save_source(self, media_id, origin_id, origin_hash, cues, language, source_text):
        id, track_id = secrets.token_hex(16), secrets.token_hex(16)
        source = {'id': id, 'revision': origin_hash, 'media_id': media_id,
                  'origin_id': origin_id, 'origin_hash': origin_hash, 'cues': cues, 'language': language}
        self.state.put('sources', id, source)
        self.state.put('tracks', track_id, {'id': track_id, 'source_id': id, 'revision': origin_hash,
                                          'media_id': media_id, 'language': language, 'complete': True,
                                          'text': source_text, 'review_status': 'original'})
        return {'source_id': id, 'revision': origin_hash, 'track_id': track_id, 'cue_count': len(cues)}

    def _import_subtitle(self, media_id, subtitle_id, language='und'):
        language = self._language(language)
        media, subtitle = self._asset(media_id), self._asset(subtitle_id)
        if media['kind'] != 'media' or subtitle['kind'] != 'subtitle':
            raise MCPError('INVALID_ARGUMENT', 'Expected media and subtitle asset IDs.')
        with self.state.file(subtitle['root_id'], subtitle['relative']) as stream:
            raw, cues = self._read_subtitle(stream, Path(subtitle['relative']).suffix)
        version, text = hashlib.sha256(raw).hexdigest(), render_srt(cues)
        with ProcessLock(self.state.path / 'locks', 'policy'):
            self._asset(media_id)
            self._asset(subtitle_id)
            return self._save_source(media_id, subtitle_id, version, cues, language, text)

    @staticmethod
    def _language(value):
        try:
            return canonical_language(value)
        except ValueError as error:
            raise MCPError('INVALID_ARGUMENT', 'Invalid language code.') from error

    def _read_transcript(self, source_id, cursor=0, limit=50, search=''):
        source = self._source(source_id)
        cues, size, next_cursor = [], 0, None
        for index in range(cursor, len(source['cues'])):
            cue = source['cues'][index]
            if search and search.casefold() not in cue['text'].casefold():
                continue
            if len(cue['text']) > 8000:
                raise MCPError('INVALID_SUBTITLE', 'A cue exceeds the response limit; reduce the source cue size.')
            if len(cues) >= limit or size + len(cue['text']) > 8000:
                next_cursor = index
                break
            cues.append(cue)
            size += len(cue['text'])
        with ProcessLock(self.state.path / 'locks', 'policy'):
            self._source_authorized(source)
            return {'source_id': source_id, 'revision': source['revision'], 'cues': cues, 'next_cursor': next_cursor}

    def _prepare_translation(self, source_id, revision, language, glossary='', style=''):
        source, language = self._source(source_id), self._language(language)
        if revision != source['revision']:
            raise MCPError('REVISION_CONFLICT', 'Source revision does not match.')
        id = secrets.token_hex(16)
        draft = {'id': id, 'source_id': source_id, 'revision': revision, 'language': language,
                 'glossary': glossary, 'style': style, 'batches': batches(source['cues']), 'translations': {}}
        with ProcessLock(self.state.path / 'locks', 'policy'):
            self._source_authorized(source)
            self.state.put('drafts', id, draft)
        return {'draft_id': id, 'revision': revision, 'language': language,
                'batches': [{'batch_id': b['batch_id'], 'cue_count': len(b['cue_ids'])} for b in draft['batches']]}

    def _list_translation_drafts(self, source_id, language, cursor=0, limit=25):
        source, language = self._source(source_id), self._language(language)
        drafts = [d for d in self.state.records('drafts') if d['source_id'] == source_id and d['language'] == language]
        items, size = [], 0
        for draft in drafts[cursor:cursor + limit]:
            complete = [b['batch_id'] for b in draft['batches'] if all(c in draft['translations'] for c in b['cue_ids'])]
            item = {'draft_id': draft['id'], 'revision': draft['revision'], 'language': language,
                          'completed_batches': complete,
                          'missing_batches': [b['batch_id'] for b in draft['batches'] if b['batch_id'] not in complete],
                          'track_id': draft.get('track_id')}
            item_size = len(json.dumps(item).encode('utf-8'))
            if size + item_size > 128 * 1024:
                if not items:
                    raise MCPError('STORAGE_LIMIT', 'Draft batch metadata exceeds the response bound.')
                break
            items.append(item)
            size += item_size
        with ProcessLock(self.state.path / 'locks', 'policy'):
            self._source_authorized(source)
            next_index = cursor + len(items)
            return {'items': items, 'next_cursor': next_index if next_index < len(drafts) else None}

    @staticmethod
    def _batch(draft, batch_id):
        batch = next((b for b in draft['batches'] if b['batch_id'] == batch_id), None)
        if batch is None:
            raise MCPError('NOT_FOUND', 'Unknown translation batch.')
        return batch

    def _get_translation_batch(self, draft_id, batch_id):
        draft, source = self._draft(draft_id)
        batch = self._batch(draft, batch_id)
        cues = [cue for cue in source['cues'] if cue['cue_id'] in batch['cue_ids']]
        first = source['cues'].index(cues[0])
        last = source['cues'].index(cues[-1])
        def context(candidates):
            result, size = [], 0
            for cue in candidates:
                if size + len(cue['text']) > 2000:
                    break
                result.append({'cue_id': cue['cue_id'], 'text': cue['text']})
                size += len(cue['text'])
            return result
        result = {'draft_id': draft_id, 'batch_id': batch_id, 'revision': draft['revision'],
                'language': draft['language'], 'glossary': draft['glossary'], 'style': draft['style'],
                'cues': [{'cue_id': cue['cue_id'], 'text': cue['text']} for cue in cues],
                'context_before': context(source['cues'][max(0, first - 2):first]),
                'context_after': context(source['cues'][last + 1:last + 3]),
                'context_role': 'read_only_not_for_translation',
                'complete': all(c['cue_id'] in draft['translations'] for c in cues)}
        with ProcessLock(self.state.path / 'locks', 'policy'):
            self._source_authorized(source)
            return result

    def _submit_translation_batch(self, draft_id, batch_id, revision, translations):
        with ProcessLock(self.state.path / 'locks', 'record-drafts-' + draft_id):
            draft = self.state.get('drafts', draft_id)
            if not draft:
                raise MCPError('NOT_FOUND', 'Unknown translation draft.')
            source = self._source(draft['source_id'])
            if revision != draft['revision'] or revision != source['revision']:
                raise MCPError('REVISION_CONFLICT', 'Source revision does not match.')
            if draft.get('track_id'):
                raise MCPError('REVISION_CONFLICT', 'Finalized translation is immutable.')
            batch = self._batch(draft, batch_id)
            validated = validate_batch(batch, translations)
            with ProcessLock(self.state.path / 'locks', 'policy'):
                self._source_authorized(source)
                draft['translations'].update(validated)
                self.state._put('drafts', draft_id, draft)
        return {'accepted': True, 'batch_id': batch_id}

    def _finalize_translation(self, draft_id):
        with ProcessLock(self.state.path / 'locks', 'record-drafts-' + draft_id):
            draft = self.state.get('drafts', draft_id)
            if not draft:
                raise MCPError('NOT_FOUND', 'Unknown translation draft.')
            source = self._source(draft['source_id'])
            if draft.get('track_id'):
                with ProcessLock(self.state.path / 'locks', 'policy'):
                    self._source_authorized(source)
                    return {'track_id': draft['track_id'], 'language': draft['language'], 'complete': True,
                            'review_status': 'ai_translation_needs_review'}
            text = render_srt(source['cues'], draft['translations'])
            track_id = secrets.token_hex(16)
            self._source(source['id'])
            # configure() uses this same lock. Keep the final root checks and
            # content publication in one policy transaction; hashing stays
            # outside so a large source cannot delay local policy changes.
            with ProcessLock(self.state.path / 'locks', 'policy'):
                self._asset(source['media_id'])
                self._asset(source['origin_id'])
                self.state.put('tracks', track_id, {'id': track_id, 'source_id': source['id'],
                               'revision': source['revision'], 'media_id': source['media_id'],
                               'language': draft['language'], 'complete': True, 'text': text,
                               'review_status': 'ai_translation_needs_review'})
                draft['track_id'] = track_id
                self.state._put('drafts', draft_id, draft)
        return {'track_id': track_id, 'language': draft['language'], 'complete': True,
                'review_status': 'ai_translation_needs_review'}

    def _settings(self, settings):
        policy = self.state.policy().get('options', {})
        result = {'model': policy.get('model', 'small'), 'device': policy.get('device', 'cpu'), **settings}
        result.setdefault('batch_acceleration', True)
        _validate({k: v for k, v in result.items() if k in _SETTINGS}, _schema(_SETTINGS))
        result.setdefault('batch_mode', 'manual' if 'batch_size' in result else 'auto')
        if result['batch_mode'] == 'auto' and 'batch_size' in result:
            raise MCPError('INVALID_ARGUMENT', 'batch_mode auto cannot include batch_size; omit batch_size or choose manual.')
        if result['batch_mode'] == 'manual':
            result.setdefault('batch_size', 4)
        cache = policy.get('cache_dir') or policy.get('model_cache_dir') or policy.get('cache')
        if cache:
            result['cache_dir'] = cache
        result['language'] = self._language(result.get('language', 'und'))
        if result['device'] in ('mlx', 'mps'):
            result['batch_acceleration'] = False
        return result

    def _admit(self, kind, asset_id, arguments):
        self._own_worker()
        if len(self._events) >= 16:
            raise MCPError('QUEUE_FULL', 'At most 16 accepted jobs may be pending.')
        asset = self._asset(asset_id)
        relative_parent = Path(asset['relative']).parent
        relative = '' if relative_parent == Path('.') else relative_parent.as_posix()
        with self.state.directory(asset['root_id'], relative) as parent:
            if shutil.disk_usage(parent.path).free < 64 * 1024 * 1024:
                raise MCPError('DISK_FULL', 'Insufficient free space beside the media.')
        id = secrets.token_hex(16)
        with ProcessLock(self.state.path / 'locks', 'policy'):
            policy = self.state.require_enabled()
            self._asset(asset_id)
            job = {'id': id, 'kind': kind, 'asset_id': asset_id, 'state': 'queued',
                   'generation': policy['generation'], 'arguments': arguments, 'input_version': asset['version']}
            self.state.put('jobs', id, job)
        self._events[id] = threading.Event()
        self._queue.put(id)
        if self._thread is None:
            self._thread = threading.Thread(target=self._worker, name='mcp-jobs', daemon=True)
            self._thread.start()
        return {'job_id': id}

    def _start_transcription(self, asset_id, settings=None):
        asset = self._asset(asset_id)
        if asset['kind'] != 'media':
            raise MCPError('INVALID_ARGUMENT', 'Expected a media asset.')
        settings = self._settings(settings or {})
        if self._factory is None:
            _ready(settings)
        return self._admit('transcription', asset_id, {'settings': settings})

    def _tracks(self, asset_id, track_ids, generation=None):
        if len(set(track_ids)) != len(track_ids):
            raise MCPError('INVALID_ARGUMENT', 'Track IDs must be unique.')
        tracks, languages = [], set()
        for id in track_ids:
            track = self.state.get('tracks', id)
            if not track.get('complete'):
                raise MCPError('TRANSLATION_INCOMPLETE', 'Requested track is incomplete.')
            if track['media_id'] != asset_id or track['language'] in languages:
                raise MCPError('INVALID_ARGUMENT', 'Tracks must belong to this media and have unique languages.')
            self._source(track['source_id'], generation)
            languages.add(track['language'])
            tracks.append(track)
        return tracks

    def _export_player(self, asset_id, track_ids, title=None, default_subtitle=None, player_type='auto'):
        asset = self._asset(asset_id)
        if Path(asset['relative']).suffix.lower() != '.mp4':
            raise MCPError('INVALID_ARGUMENT', 'Player export requires an MP4 asset.')
        project = project_for_asset(self.state, asset)
        selected = project['type'] if player_type == 'auto' else player_type
        if selected != 'mp4' and selected != project['type']:
            raise MCPError('PROJECT_TYPE_MISMATCH', 'Requested player type does not match the detected project.')
        tracks = self._tracks(asset_id, track_ids)
        default = default_subtitle or tracks[0]['language']
        if default != 'off' and self._language(default) not in {t['language'] for t in tracks}:
            raise MCPError('TRANSLATION_INCOMPLETE', 'Requested default language is not a complete selected track.')
        return self._admit('export', asset_id, {'track_ids': track_ids, 'title': title,
                                               'default_subtitle': default, 'player_type': selected})

    def _get_job(self, job_id):
        job = self.state.get('jobs', job_id)
        result = {k: job[k] for k in ('state', 'stage', 'error') if k in job}
        result['job_id'] = job_id
        with ProcessLock(self.state.path / 'locks', 'policy'):
            if self.state.policy()['enabled'] and 'result' in job:
                try:
                    self._asset(job['asset_id'])
                except MCPError as error:
                    if error.code not in ('ROOT_NOT_ALLOWED', 'SOURCE_CHANGED', 'UNSAFE_PATH', 'MCP_DISABLED'):
                        raise
                else:
                    result['result'] = job['result']
        return result

    def _cancel_job(self, job_id):
        result = self.state.cancel_job(job_id)
        if result['state'] == 'cancelling' and job_id in self._events:
            self._events[job_id].set()
        return result

    def _checkpoint(self, job):
        current = self.state.get('jobs', job['id'])
        if (self._stop.is_set() or self._events[job['id']].is_set() or
                current.get('cancel_requested')):
            raise MCPError('CANCELLED', 'Job cancellation was requested.')
        asset = self._asset(job['asset_id'], job['generation'])
        if job.get('input_version') != asset.get('version'):
            raise MCPError('SOURCE_CHANGED', 'Admitted input changed; submit a new job.')
        return asset

    def _update_job(self, id, **values):
        with self.state.mutation('jobs', id) as record:
            if record.get('cancel_requested') and values.get('state') not in _TERMINAL:
                values['state'] = 'cancelling'
            record.update(values)

    @contextlib.contextmanager
    def _job_commit(self, job):
        """Lock order: request/service guard -> job/draft record -> policy ->
        leaf source/track records -> namespace. Cancellation takes job record;
        policy changes take policy only. No hash/copy/inference under policy.
        Publish and terminal success are one serializable transaction.
        """
        with ProcessLock(self.state.path / 'locks', 'record-jobs-' + job['id']):
            with ProcessLock(self.state.path / 'locks', 'policy'):
                self._checkpoint(job)
                current = self.state.get('jobs', job['id'])
                yield current
                self.state._put('jobs', job['id'], current)

    def _worker(self):
        while True:
            try:
                id = self._queue.get(timeout=.05)
            except queue.Empty:
                if self._stop.is_set():
                    return
                continue
            try:
                job = self.state.get('jobs', id)
                self._checkpoint(job)
                self._update_job(id, state='preparing', stage='snapshot')
                lock = ProcessLock(self.state.path / 'locks', 'inference')
                try:
                    if not lock.acquire(blocking=True, cancelled=lambda: self._cancelled(job)):
                        raise MCPError('CANCELLED', 'Job cancelled while waiting for inference.')
                    self._checkpoint(job)
                    self._execute(job)
                finally:
                    lock.release()
            except MCPError as error:
                self._update_job(id, state='cancelled' if error.code == 'CANCELLED' else 'failed',
                                 error={'code': error.code, 'message': str(error)})
            except Exception:
                self._update_job(id, state='failed', error={'code': 'JOB_FAILED',
                                                          'message': 'Local job failed; inspect local diagnostics.'})
            finally:
                with self._guard:
                    self._events.pop(id, None)
                self._queue.task_done()

    @contextlib.contextmanager
    def _workspace(self, id):
        with _private_directory(self.state.path / 'workspaces' / id, create=True) as directory:
            yield directory

    def _execute(self, job):
        asset = self._checkpoint(job)
        with self._workspace(job['id']) as workspace:
            suffix = Path(asset['relative']).suffix.lower()
            with StagedDirectory(workspace) as snapshot:
                with self.state.file(asset['root_id'], asset['relative'], admitted_generation=job['generation']) as source:
                    snapshot.copy_from(source, 'media' + suffix, progress=lambda n: None,
                                       cancelled=lambda: self._cancelled(job))
                folder = snapshot.publish('input')
            media = folder / ('media' + suffix)
            with SafeDirectory(folder) as directory, directory.open_read(media.name) as stream:
                version = _stream_hash(stream)
            self._checkpoint(job)
            self._update_job(job['id'], state='running', stage=job['kind'])
            if job['kind'] == 'transcription':
                batch_decision = self._transcribe(job, media)
                self._checkpoint(job)
                if self._asset_hash(asset, job['generation']) != version:
                    raise MCPError('SOURCE_CHANGED', 'Media changed during transcription.')
                self._update_job(job['id'], state='validating', stage='subtitle')
                with SafeDirectory(folder) as directory, directory.open_read(media.with_suffix('.srt').name) as stream:
                    _, cues = self._read_subtitle(stream, '.srt')
                text = render_srt(cues)
                self._checkpoint(job)
                self._update_job(job['id'], state='publishing')
                with self._job_commit(job) as current:
                    result = self._save_source(job['asset_id'], job['asset_id'], version, cues,
                                               job['arguments']['settings']['language'], text)
                    if batch_decision is not None:
                        result['batch_decision'] = batch_decision
                    current.update(state='succeeded', stage='complete', result=result)
            else:
                self._export(job, asset, media, workspace, version)

    def _cancelled(self, job):
        self._checkpoint(job)
        return False

    def _transcribe(self, job, media):
        settings = job['arguments']['settings']
        from batch_policy import decision_summary
        if self._factory is not None:
            engine = self._factory(**_engine_settings(settings))
            result = _run_engine(engine, settings, media,
                                 lambda: self._cancelled(job))
            if not result:
                raise MCPError('CANCELLED', 'Transcription cancelled.')
            if Path(result) != media.with_suffix('.srt'):
                raise MCPError('INVALID_SUBTITLE', 'Unexpected transcription output.')
            return decision_summary(getattr(engine, 'last_batch_decision', None))
        context = multiprocessing.get_context('spawn')
        read, write = context.Pipe(duplex=False)
        cancel = context.Event()
        process = context.Process(target=_inference_child, args=(settings, str(media), write, cancel, str(self.state.path)))
        process.start()
        write.close()
        message, failure = None, None
        try:
            while process.is_alive():
                try:
                    self._checkpoint(job)
                except MCPError as error:
                    failure = error
                    cancel.set()
                if message is None and read.poll(.05):
                    try:
                        message = json.loads(read.recv_bytes(4096).decode())
                    except (ValueError, OSError, EOFError):
                        failure = MCPError('TRANSCRIPTION_FAILED', 'Invalid worker response.')
                process.join(.05)
            process.join()  # MUST exit before releasing the shared inference lock.
            if message is None and read.poll():
                message = json.loads(read.recv_bytes(4096).decode())
            if failure:
                raise failure
            if not isinstance(message, dict) or not message.get('ok'):
                raise MCPError((message or {}).get('error', 'TRANSCRIPTION_FAILED'), 'Transcription did not complete.')
            return decision_summary(message.get('batch_decision'))
        finally:
            if process.is_alive():
                cancel.set()
                process.join()
            read.close()
            process.close()

    def _export(self, job, asset, media, workspace, version):
        arguments = job['arguments']
        tracks = self._tracks(job['asset_id'], arguments['track_ids'], job['generation'])
        subtitles = []
        for track in tracks:
            name = 'media.' + track['language'] + '.srt'
            workspace.write_bytes(name, track['text'].encode('utf-8'), exclusive=True)
            subtitles.append(SubtitleSource(Path(workspace.path) / name, track['language']))
        request = ExportRequest(media, tuple(subtitles),
                                Metadata(arguments['title'] or Path(asset['relative']).stem),
                                Path(workspace.path), 'package', arguments['default_subtitle'])
        player_type = arguments.get('player_type', 'mp4')
        if player_type in ('opencam', 'evercam'):
            from types import SimpleNamespace
            built = SimpleNamespace(folder=build_project(self.state, asset, job, media, workspace,
                tuple(subtitles), lambda: self._cancelled(job)))
        else:
            built = export_package(request, app_version='mcp-1', progress=lambda done, total: None,
                                   cancelled=lambda: self._cancelled(job))
        self._checkpoint(job)
        if self._asset_hash(asset, job['generation']) != version:
            raise MCPError('SOURCE_CHANGED', 'Media changed during export.')
        self._update_job(job['id'], state='validating', stage='package')
        relative_parent = Path(asset['relative']).parent
        relative = '' if relative_parent == Path('.') else relative_parent.as_posix()
        # Export core reopens its output path. Build privately, then publish
        # through the pinned authorized parent so replaced ancestors cannot
        # redirect the final package outside policy roots.
        with self.state.directory(asset['root_id'], relative, admitted_generation=job['generation']) as parent:
            with StagedDirectory(parent) as output, SafeDirectory(built.folder) as package:
                for path in sorted(built.folder.rglob('*')):
                    if path.is_dir():
                        continue
                    name = path.relative_to(built.folder).as_posix()
                    if name == 'media.mp4':
                        with package.open_read(name) as source:
                            output.copy_from(source, name, progress=lambda n: None,
                                             cancelled=lambda: self._cancelled(job))
                    else:
                        with contextlib.ExitStack() as stack:
                            current = package
                            for part in Path(name).parts[:-1]:
                                current = stack.enter_context(current.child(part))
                            resource_limit = (32 if player_type in ('opencam', 'evercam') else 8) * 1024 * 1024
                            with current.open_read(Path(name).name) as source:
                                raw = source.read(resource_limit + 1)
                            if len(raw) > resource_limit:
                                raise MCPError('STORAGE_LIMIT', 'Package resource exceeds its size limit.')
                            output.write_bytes(name, raw)
                self._tracks(job['asset_id'], arguments['track_ids'], job['generation'])
                self._checkpoint(job)
                if self._asset_hash(asset, job['generation']) != version:
                    raise MCPError('SOURCE_CHANGED', 'Media changed during export publication.')
                self._update_job(job['id'], state='publishing', stage='package')
                base = Path(asset['relative']).stem + '-web'
                validate_folder_name(base)
                with self._job_commit(job) as current:
                    project_for_asset(self.state, asset, job['generation'])
                    for track in tracks:
                        self._source_authorized(self.state.get('sources', track['source_id']), job['generation'])
                    # Attest the pinned package before its exclusive rename.
                    # On Windows the publisher retains DELETE access; reopening
                    # without delete sharing would conflict with our own lease.
                    # The rename preserves these object identities, and later
                    # local opening still revalidates them under current policy.
                    with output.directory.open_read('index.html') as index:
                        validation = {'directory': directory_identity(output.directory),
                                      'index': file_version(index)}
                    for collision in range(1, 10001):
                        name = base if collision == 1 else base + '-' + str(collision)
                        try:
                            folder = output.publish(name)
                            break
                        except FileExistsError:
                            continue
                    else:
                        raise MCPError('OUTPUT_EXISTS', 'No fresh export name is available.')
                    current.update(state='succeeded', stage='complete', result={
                        'folder': str(folder), 'index_path': str(folder / 'index.html'),
                        'player_type': player_type,
                        'source_path': str(Path(parent.path) / Path(asset['relative']).name)})
                    current['result_validation'] = validation
