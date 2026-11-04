"""GUI batch ownership and cooperative private child-process inference.

The pipe connects only an owned spawned child, never an external MCP client.
Direct native engines retain their OS lock for the lifetime of this process:
dropping a Python engine reference does not prove that MLX caches were freed.
"""
import multiprocessing

from mcp_state import MCPError, ProcessLock, State

_DIRECT_LOCKS = []
_CALLBACKS = ('log_callback', 'progress_callback', 'stage_callback', 'review_callback')


def child_residency(state_path, cancelled):
    """Children take residency only; parents take inference before residency.

    This raw-FD lease deliberately lasts through Python/native teardown to OS
    exit. No parent lock handoff, cache unload, PID probing or forced kill.
    """
    def stopped():
        parent = multiprocessing.parent_process()
        return cancelled.is_set() or (parent is not None and not parent.is_alive())
    lock = ProcessLock(State(state_path).path / 'locks', 'model-residency', process_lifetime=True)
    if not lock.acquire(blocking=True, cancelled=stopped):
        return None
    if stopped():
        lock.release()  # No engine was constructed.
        return None
    return lock


class InferenceBatch:
    def __init__(self, owner, *, state=None):
        self.owner = owner
        self.state = state if state is not None else State()
        self.retained = getattr(owner, '_mcp_direct_model_used', False)
        self.lock = getattr(owner, '_mcp_direct_lock', None) or ProcessLock(self.state.path / 'locks', 'inference')
        self.residency = getattr(owner, '_mcp_direct_residency', None)
        if not self.lock.acquire():
            raise MCPError('INFERENCE_BUSY', '其他 GUI 或 MCP 工作正在使用模型；請等待工作結束或正常關閉該 GUI。')
        try:
            self.use_proxy = self.state.policy()['enabled']
            if not self.use_proxy and self.residency is None:
                self.residency = ProcessLock(self.state.path / 'locks', 'model-residency', process_lifetime=True)
                if not self.residency.acquire():
                    raise MCPError('INFERENCE_BUSY', '背景模型仍在使用中；請等待模型程序正常結束。')
            existing = getattr(owner, 'transcriber', None)
            if self.use_proxy and (self.retained or (existing is not None and not isinstance(existing, ProcessTranscriber))):
                raise MCPError('RESTART_REQUIRED', '本視窗保留本機模型；請正常關閉並重新啟動程式。')
        except BaseException:
            if not self.retained:
                if self.residency is not None:
                    self.residency.release()
                self.lock.release()
            raise

    def retain_direct(self):
        if not self.retained:
            self.retained = True
            self.owner._mcp_direct_model_used = True
            self.owner._mcp_direct_lock = self.lock
            self.owner._mcp_direct_residency = self.residency
            _DIRECT_LOCKS.append(self.lock)
            _DIRECT_LOCKS.append(self.residency)

    def close(self):
        if self.use_proxy:
            engine = getattr(self.owner, 'transcriber', None)
            if isinstance(engine, ProcessTranscriber):
                engine.close()  # join must complete BEFORE shared lock release
                self.owner.transcriber = None
        if not self.retained:
            if self.residency is not None:
                self.residency.release()
            self.lock.release()


def _engine_child(connection, cancelled, args, kwargs, engine_factory, state_path):
    try:
        residency = child_residency(state_path, cancelled)
        if residency is None:
            return
        if engine_factory is None:
            from transcriber import SubtitleTranscriber
            engine_factory = SubtitleTranscriber
        engine = engine_factory(*args, **kwargs)
        while True:
            request = connection.recv()
            if request is None:
                return
            method, positional, options = request
            for name in _CALLBACKS:
                if method == 'run' or name in ('log_callback', 'progress_callback'):
                    options[name] = lambda *values, event=name: connection.send(('callback', event, values))
            options['cancel_check_callback'] = cancelled.is_set
            try:
                result = getattr(engine, method)(*positional, **options)
                from batch_policy import decision_summary
                connection.send(('result', result, decision_summary(getattr(engine, 'last_batch_decision', None))))
            except Exception as error:
                connection.send(('error', type(error).__name__, str(error),
                                 {name: getattr(error, name, None) for name in ('model_size', 'cache_dir')}))
    except (EOFError, BrokenPipeError):
        pass
    except Exception as error:
        try:
            connection.send(('error', type(error).__name__, str(error), {}))
        except (EOFError, BrokenPipeError, OSError):
            pass
    finally:
        connection.close()


class ProcessTranscriber:
    """Existing engine contract with one reusable child per GUI batch."""
    def __init__(self, model_size='small', device='cpu', compute_type='int8', download_root=None,
                 cpu_threads=4, *, engine_factory=None, state_path=None):
        self.model_size = model_size.split()[0].strip()
        self.device, self.compute_type = device, compute_type
        self.download_root, self.cpu_threads = download_root, cpu_threads
        self.model = None
        self.last_batch_decision = None
        self._factory = engine_factory
        self._state_path = str(State(state_path).path)
        self._process = self._connection = self._cancelled = None

    def _start(self):
        if self._process is not None:
            return
        context = multiprocessing.get_context('spawn')
        parent, child = context.Pipe()
        self._cancelled = context.Event()
        process = context.Process(target=_engine_child, args=(child, self._cancelled,
            (self.model_size, self.device, self.compute_type),
            {'download_root': self.download_root, 'cpu_threads': self.cpu_threads}, self._factory, self._state_path))
        try:
            process.start()
        except BaseException:
            parent.close()
            child.close()
            raise
        child.close()
        self._process, self._connection = process, parent

    def _call(self, method, args, options):
        self._start()
        callbacks = {name: options.pop(name, None) for name in _CALLBACKS}
        cancelled = options.pop('cancel_check_callback', None)
        self._cancelled.clear()
        self._connection.send((method, args, options))
        callback_error = None
        while True:
            if cancelled and cancelled():
                self._cancelled.set()
            if not self._connection.poll(.05):
                if not self._process.is_alive():
                    raise RuntimeError('GUI inference child exited before returning a result.')
                continue
            try:
                message = self._connection.recv()
            except EOFError as error:
                raise RuntimeError('GUI inference child exited unexpectedly.') from error
            if message[0] == 'callback':
                callback = callbacks.get(message[1])
                if callback and callback_error is None:
                    try:
                        callback(*message[2])
                    except Exception as error:
                        callback_error = error
                        self._cancelled.set()
                continue
            if callback_error is not None:
                raise callback_error
            if message[0] == 'result':
                from batch_policy import decision_summary
                self.last_batch_decision = decision_summary(message[2])
                return message[1]
            _, kind, text, attributes = message
            if kind == 'InterruptedError':
                raise InterruptedError(text)
            if kind in ('CorruptedModelError', 'ModelCacheAccessError', 'TraditionalChineseConversionError'):
                import transcriber
                error_type = getattr(transcriber, kind)
                if kind == 'TraditionalChineseConversionError':
                    raise error_type(text)
                # Constructors may decorate their message. The child already
                # did that; preserve the exact message and public metadata.
                error = error_type.__new__(error_type)
                RuntimeError.__init__(error, text)
                error.model_size, error.cache_dir = attributes['model_size'], attributes['cache_dir']
                raise error
            raise RuntimeError(text)

    def load_model(self, log_callback=None, progress_callback=None, cancel_check_callback=None):
        return self._call('load_model', (), dict(log_callback=log_callback,
            progress_callback=progress_callback, cancel_check_callback=cancel_check_callback))

    def run(self, file_path, log_callback=None, progress_callback=None, cancel_check_callback=None,
            output_format='srt', initial_prompt=None, task='transcribe', force_zh_tw=False,
            max_chars=35, hotwords=None, clean_punctuation='space', word_timestamps=True,
            spacing=True, case_correction=True, vad_filter=True, batch_acceleration=False,
            batch_size=4, review_callback=None, stage_callback=None):
        options = dict(log_callback=log_callback, progress_callback=progress_callback,
            cancel_check_callback=cancel_check_callback, output_format=output_format,
            initial_prompt=initial_prompt, task=task, force_zh_tw=force_zh_tw, max_chars=max_chars,
            hotwords=hotwords, clean_punctuation=clean_punctuation, word_timestamps=word_timestamps,
            spacing=spacing, case_correction=case_correction, vad_filter=vad_filter,
            batch_acceleration=batch_acceleration, batch_size=batch_size,
            review_callback=review_callback, stage_callback=stage_callback)
        return self._call('run', (file_path,), options)

    def close(self):
        if self._process is None:
            return
        self._cancelled.set()
        try:
            if self._process.is_alive():
                try:
                    self._connection.send(None)
                except (BrokenPipeError, EOFError, OSError):
                    pass
            self._process.join()  # Never force-kill CTranslate2 or Metal.
        finally:
            self._connection.close()
