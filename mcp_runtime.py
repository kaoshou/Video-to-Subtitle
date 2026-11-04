"""Explicit local administration and trusted launcher activation; no import I/O."""
import hashlib
import os
from pathlib import Path
import sys

from mcp_state import MCPError, ProcessLock, _absolute_directory, _private_directory, _write_json


def backend_command():
    """Pure absolute GUI backend prefix, never the thin STDIO launcher."""
    executable = os.path.abspath(sys.executable)
    return ([executable] if getattr(sys, 'frozen', False) else
            [executable, str(Path(__file__).resolve().with_name('app_entry.py'))])


def connection_command(state, *, repair=False):
    """Activate only build-attested payloads, then return complete STDIO argv."""
    if not getattr(sys, 'frozen', False):
        return backend_command() + ['--mcp', '--state-dir', str(state.path)]
    from mcp_clients import bundled_mcp_payload, _file_digest
    payload = bundled_mcp_payload()
    if payload is None:
        raise MCPError('PACKAGED_BINARY_REQUIRED', '此版本未包含 MCP 啟動檔；請安裝包含 MCP 的正式版本。')
    # Version by full digest: application upgrades never overwrite an old
    # version's running launcher, and no persisted path points into _MEIPASS.
    destination = state.path / 'launchers' / payload.sha256
    with ProcessLock(state.path / 'locks', 'activation'):
        with _private_directory(destination, create=True) as directory:
            name = payload.launcher.name
            existing = directory.info(name)
            if existing is not None:
                with directory.open_read(name) as stream:
                    good = _file_digest(stream) == payload.sha256
                if not good and not repair:
                    raise MCPError('PAYLOAD_CHANGED', 'MCP 啟動檔已變更；請使用「修復啟動檔」重新驗證並修復。')
            else:
                good = False
            if not good:
                with _absolute_directory(payload.launcher.parent) as source:
                    with source.open_read(name) as stream:
                        binary = stream.read()
                if hashlib.sha256(binary).hexdigest() != payload.sha256:
                    raise MCPError('PAYLOAD_CHANGED', '內附 MCP 啟動檔驗證失敗；請重新安裝。')
                # The existing private atomic publisher accepts bytes; its
                # safety is independent of the JSON used by State records.
                _write_json(directory, name, binary)
            if directory.fd is not None:
                os.chmod(name, 0o700, dir_fd=directory.fd, follow_symlinks=False)
            with directory.open_read(name) as stream:
                if _file_digest(stream) != payload.sha256:
                    raise MCPError('PAYLOAD_CHANGED', 'MCP 啟動檔驗證失敗。')
    return [str(destination / name), '--mcp', '--state-dir', str(state.path)]


def enable(state, roots, *, owner=None, **options):
    """Serialize permission changes against the GUI's final engine decision."""
    if owner is not None:
        if (getattr(owner, 'is_running', False) or getattr(owner, 'current_downloading_model', None)
                or getattr(owner, '_storage_current_target', None)):
            raise MCPError('GUI_BUSY', '請等待 GUI 轉錄或模型下載結束後再變更權限。')
        if getattr(owner, '_mcp_direct_model_used', False):
            raise MCPError('RESTART_REQUIRED', '此視窗已載入本機模型；請正常關閉並重新啟動程式後啟用 MCP。')
        engine = getattr(owner, 'transcriber', None)
        if engine is not None:
            from mcp_inference import ProcessTranscriber
            if not isinstance(engine, ProcessTranscriber):
                raise MCPError('RESTART_REQUIRED', '此視窗已有本機模型；請正常關閉並重新啟動程式後啟用 MCP。')
    lock = ProcessLock(state.path / 'locks', 'inference')
    if not lock.acquire():
        raise MCPError('INFERENCE_BUSY', '模型正在使用中；請等待工作結束，或正常關閉保留模型的 GUI 後再試。')
    try:
        connection_command(state)
        return state.configure(True, list(roots), **{**options, 'backend_command': backend_command()})
    finally:
        lock.release()


def disable(state, stop_mode='cancel'):
    """Immediately revoke tool access; let the service cooperatively drain."""
    return state.disable(stop_mode=stop_mode)
