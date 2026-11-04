"""Local-admin client setup. No client processes, settings I/O or discovery on import.

Schema support means a documented file format, never a live client connection.
Only explicit preview/apply/remove calls read selected configuration contents.
"""
import contextlib
from dataclasses import dataclass
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import re
import secrets
import stat
import sys
import zipfile

from mcp_state import MCPError, ProcessLock, State, _absolute_directory

SERVER_KEY = 'video-to-subtitle'
MAX_CONFIG_BYTES = 1024 * 1024
_COMPATIBILITY = '支援設定格式／客戶端版本未實測；尚未驗證實際連線。'
_CLIENTS = {
    'codex': ('Codex', 'mcp_servers', 'toml'),
    'claude-code': ('Claude Code', 'mcpServers', 'json'),
    'claude-desktop': ('Claude Desktop', None, 'mcpb'),
    'gemini-cli': ('Gemini CLI', 'mcpServers', 'json'),
    'antigravity': ('Antigravity', 'mcpServers', 'json'),
    'cursor': ('Cursor', 'mcpServers', 'json'),
    'vscode': ('VS Code / GitHub Copilot', 'servers', 'json'),
    'copilot': ('GitHub Copilot portable', 'mcpServers', 'json'),
    'windsurf': ('Windsurf', 'mcpServers', 'json'),
    'opencode': ('OpenCode', 'mcp', 'json'),
    'generic': ('Other MCP client', 'mcpServers', 'json'),
}
_MAC_APPS = {'codex': 'Codex.app', 'claude-desktop': 'Claude.app', 'cursor': 'Cursor.app',
             'vscode': 'Visual Studio Code.app', 'windsurf': 'Windsurf.app',
             'antigravity': 'Antigravity.app'}
_CLI_NAMES = {'codex': 'codex', 'claude-code': 'claude', 'gemini-cli': 'gemini',
              'cursor': 'cursor', 'vscode': 'code', 'windsurf': 'windsurf',
              'antigravity': 'antigravity', 'opencode': 'opencode', 'copilot': 'copilot'}
_WINDOWS_APPS = {
    'codex': ('Codex/Codex.exe', 'OpenAI/Codex/Codex.exe'),
    'antigravity': ('Antigravity/Antigravity.exe',),
    'vscode': ('Microsoft VS Code/Code.exe',),
    'cursor': ('cursor/Cursor.exe',),
    'windsurf': ('Windsurf/Windsurf.exe',),
    'claude-desktop': ('Claude/Claude.exe',),
}


def _windows_package_names(family, query=None):
    """Current-user package metadata, without PowerShell or WindowsApps scanning.

    GetPackagesByPackageFamily is a read-only Win32 API. Bound both allocations
    and retries: an update racing discovery simply yields no evidence this time.
    """
    import ctypes
    from ctypes import wintypes
    if query is None:
        if os.name != 'nt':
            return []
        try:
            query = ctypes.WinDLL('kernel32', use_last_error=True).GetPackagesByPackageFamily
            query.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.UINT),
                              ctypes.POINTER(wintypes.LPWSTR), ctypes.POINTER(wintypes.UINT),
                              wintypes.LPWSTR]
            query.restype = wintypes.LONG
        except (OSError, AttributeError):
            return []
    count, length = wintypes.UINT(), wintypes.UINT()
    result = query(family, ctypes.byref(count), None, ctypes.byref(length), None)
    if result != 122 or not 0 < count.value <= 64 or not 0 < length.value <= 32768:
        return []
    capacity = count.value
    names = (wintypes.LPWSTR * capacity)()
    buffer = ctypes.create_unicode_buffer(length.value)
    result = query(family, ctypes.byref(count), names, ctypes.byref(length), buffer)
    if result != 0 or count.value > capacity:
        return []
    return [names[index] for index in range(count.value) if names[index]]


def _client(client_id):
    if not isinstance(client_id, str) or client_id not in _CLIENTS:
        raise MCPError('manual_only', 'Unknown client. Use a manual stdio configuration.')
    return _CLIENTS[client_id]


def _path(value):
    path = Path(value)
    if not path.is_absolute() or '..' in path.parts or '\x00' in str(path):
        raise MCPError('unsafe_path', 'Select an absolute path without traversal.')
    # Only fixed operating-system aliases; never resolve a user-created link.
    if sys.platform == 'darwin' and path.parts[1:2] in (('tmp',), ('var',)):
        path = Path('/private') / path.relative_to('/')
    return path


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _file_digest(stream):
    digest = hashlib.sha256()
    for block in iter(lambda: stream.read(1024 * 1024), b''):
        digest.update(block)
    return digest.hexdigest()


def _owner_id(client_id, path):
    return 'owner_' + _digest((client_id + '\0' + str(path)).encode())


def _config_lock(path):
    return 'config_' + _digest(str(path).encode())


def _optional_record(state, kind, record_id):
    try:
        return state.get(kind, record_id)
    except MCPError as error:
        if error.code != 'NOT_FOUND':
            raise
        return {}


def _effective_owner(record, current, raw):
    if record.get('status') == 'pending':
        if (raw is not None and record.get('expected_hash') == _digest(raw) and
                current == record.get('entry')):
            return {key: value for key, value in record.items() if key not in ('previous', 'expected_hash')} | {'status': 'managed'}
        return record.get('previous', {})
    return record


def _discovery_roots(roots):
    """Bounded explicit roots; never expand PATH or enumerate their contents."""
    roots = list(roots)
    if len(roots) > 32:
        raise MCPError('invalid_discovery', 'Select at most 32 discovery directories.')
    result = []
    for value in roots:
        _path(value)
        path = Path(value)
        if path not in result:
            result.append(path)
    return result


def _installation_evidence(client_id, app_roots, executable_roots, system):
    candidates = []
    if system == 'Darwin' and client_id in _MAC_APPS:
        candidates.extend((root / _MAC_APPS[client_id], 'app-bundle', True)
                          for root in app_roots)
    elif system == 'Windows':
        candidates.extend((root / relative, 'application-file', False)
                          for root in app_roots for relative in _WINDOWS_APPS.get(client_id, ()))
    if client_id in _CLI_NAMES:
        name = _CLI_NAMES[client_id]
        names = (name + '.exe', name + '.cmd') if system == 'Windows' else (name,)
        candidates.extend((root / name, 'command-file', False)
                          for root in executable_roots for name in names)
    evidence = []
    for path, kind, directory in candidates:
        try:
            info = path.lstat()
            linked = stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & 0x400)
            if linked:
                # Resolve metadata only, so a broken npm/bin link is not an
                # installation signal. Never read or invoke the target.
                info = path.stat()
            if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
                continue
            if kind == 'command-file' and system != 'Windows' and not info.st_mode & 0o111:
                continue
            evidence.append({'kind': kind + '-link' if linked else kind, 'path': str(path)})
        except OSError:
            continue
    return evidence


def discover_clients(*, home=None, environ=None, system=None,
                     application_roots=None, executable_roots=None):
    """Inspect path metadata only. Evidence is not an installed/live/version badge.

    ``detected`` combines separate installation/configuration metadata flags;
    a config file alone is never installation evidence. Optional root lists
    replace the bounded OS defaults; pass empty tuples for isolated fixtures.
    ``can_apply`` describes the adapter and unambiguous target, not current file
    writability or a successful preview. The GUI must still preview and consent.
    """
    # Explicit fixture/custom roots never inspect the current user's registry.
    native_packages = home is None and environ is None and application_roots is None
    home = _path(Path.home() if home is None else home)
    env = dict(os.environ if environ is None else environ)
    system = platform.system() if system is None else system

    def override(name, fallback):
        value = env.get(name)
        if value:
            candidate = Path(value)
            if candidate.is_absolute():
                return candidate
        return fallback

    if application_roots is None:
        if system == 'Darwin':
            application_roots = (Path('/Applications'), home / 'Applications')
        elif system == 'Windows':
            local = override('LOCALAPPDATA', home / 'AppData' / 'Local')
            application_roots = [local / 'Programs', local]
            application_roots.extend(Path(env[key]) for key in ('ProgramFiles', 'ProgramFiles(x86)')
                                     if env.get(key) and Path(env[key]).is_absolute())
        else:
            application_roots = ()
    if executable_roots is None:
        executable_roots = [home / '.local' / 'bin', home / '.opencode' / 'bin']
        if system == 'Windows':
            executable_roots.append(override('APPDATA', home / 'AppData' / 'Roaming') / 'npm')
        else:
            executable_roots.extend((Path('/usr/local/bin'), Path('/usr/bin')))
            if system == 'Darwin':
                executable_roots.append(Path('/opt/homebrew/bin'))
        prefix = env.get('NPM_CONFIG_PREFIX') or env.get('npm_config_prefix')
        if prefix and Path(prefix).is_absolute():
            executable_roots.append(Path(prefix) if system == 'Windows' else Path(prefix) / 'bin')
    app_roots = _discovery_roots(application_roots)
    executable_roots = _discovery_roots(executable_roots)

    paths = {
        'codex': override('CODEX_HOME', home / '.codex') / 'config.toml',
        'claude-code': home / '.claude.json',
        'claude-desktop': None,
        'gemini-cli': home / '.gemini' / 'settings.json',
        'antigravity': home / '.gemini' / 'config' / 'mcp_config.json',
        'cursor': home / '.cursor' / 'mcp.json',
        'vscode': None,
        'copilot': override('COPILOT_HOME', home / '.copilot') / 'mcp-config.json',
        'windsurf': home / '.codeium' / 'windsurf' / 'mcp_config.json',
        'opencode': override('OPENCODE_CONFIG', override('XDG_CONFIG_HOME', home / '.config') /
                             'opencode' / 'opencode.json'),
        'generic': None,
    }
    rows = []
    for client_id, (name, section, format_name) in _CLIENTS.items():
        path = paths[client_id]
        configuration_evidence = []
        if path is not None:
            try:
                info = path.lstat()
                if stat.S_ISREG(info.st_mode) and not getattr(info, 'st_file_attributes', 0) & 0x400:
                    configuration_evidence.append({'kind': 'config-file', 'path': str(path)})
            except OSError:
                pass
        installation_evidence = _installation_evidence(client_id, app_roots, executable_roots, system)
        if system == 'Windows' and native_packages and client_id == 'codex':
            for family in ('OpenAI.Codex_2p2nqsd0c76g0', 'OpenAI.Codex_8wekyb3d8bbwe'):
                installation_evidence.extend({'kind': 'registered-package', 'path': name}
                                             for name in _windows_package_names(family))
        evidence = installation_evidence + configuration_evidence
        reason = ''
        if client_id == 'windsurf':
            reason = 'Current official Windsurf format could not be verified; legacy snippet only.'
        elif client_id == 'vscode':
            reason = 'Select the MCP user-profile file shown by VS Code; profile location is not inferred.'
        elif client_id == 'claude-desktop':
            reason = 'Export a packaged binary MCPB, then install it yourself in Claude Desktop.'
        elif client_id == 'generic':
            reason = 'Select a client and apply its stdio snippet manually.'
        elif path.suffix == '.jsonc':
            reason = 'JSONC preservation is not supported; use the manual snippet.'
        override_key = {'codex': 'CODEX_HOME', 'copilot': 'COPILOT_HOME',
                        'opencode': 'OPENCODE_CONFIG' if env.get('OPENCODE_CONFIG') else 'XDG_CONFIG_HOME'}.get(client_id)
        if override_key and env.get(override_key) and not Path(env[override_key]).is_absolute():
            reason = 'The configured environment override is relative; select the configuration file explicitly.'
        rows.append({'id': client_id, 'name': name, 'detected': bool(evidence),
                     'evidence': evidence, 'config_path': str(path) if path else None,
                     'installation_detected': bool(installation_evidence),
                     'configuration_detected': bool(configuration_evidence),
                     'installation_evidence': installation_evidence,
                     'configuration_evidence': configuration_evidence,
                     'publisher_verified': False,
                     'installation_note': '僅發現已知安裝位置或指令檔；未驗證發行者、版本或連線。',
                     'format': format_name, 'section': section,
                     'schema_supported': client_id not in ('windsurf', 'generic', 'claude-desktop'),
                     'can_apply': not reason, 'manual_reason': reason,
                     'client_version': None, 'version_verified': False, 'live_verified': False,
                     'compatibility_note': _COMPATIBILITY, 'system': system})
    return rows


def _command(command):
    if (not isinstance(command, list) or not 2 <= len(command) <= 6 or
            any(not isinstance(arg, str) or not arg or len(arg) > 4096 or
                any(ord(c) < 32 for c in arg) for arg in command)):
        raise MCPError('invalid_command', 'Use the fixed local MCP launcher and argument list.')
    executable = _path(command[0])
    source = str(Path(__file__).absolute().with_name('app_entry.py'))
    if len(command) >= 3 and command[1] == source:
        if str(executable) != str(_path(sys.executable)):
            raise MCPError('invalid_command', 'Use this application Python interpreter.')
        rest = command[2:]
    else:
        payload = bundled_mcp_payload()
        if payload is None or executable.name != payload.launcher.name:
            raise MCPError('invalid_command', 'Use the packaged application MCP launcher.')
        try:
            with _absolute_directory(executable.parent) as directory, directory.open_read(executable.name) as stream:
                if _file_digest(stream) != payload.sha256:
                    raise MCPError('invalid_command', 'The MCP launcher does not match this application release.')
        except OSError as error:
            raise MCPError('invalid_command', 'Select the verified application MCP launcher.') from error
        rest = command[1:]
    if rest != ['--mcp']:
        if len(rest) != 3 or rest[:2] != ['--mcp', '--state-dir']:
            raise MCPError('invalid_command', 'Only --mcp and an optional absolute --state-dir are supported.')
        _path(rest[2])
    return list(command)


def connection_entry(command, client_id):
    _client(client_id)
    command = _command(command)
    if client_id == 'opencode':
        return {'type': 'local', 'command': command, 'enabled': True}
    entry = {'command': command[0], 'args': command[1:]}
    if client_id == 'vscode':
        return {'type': 'stdio', **entry}
    return entry


def _tomlkit():
    try:
        import tomlkit
    except ImportError as error:
        raise MCPError('manual_only', 'Install the optional MCP dependency tomlkit to preserve TOML comments.') from error
    return tomlkit


def manual_configuration(client_id, command):
    """Return only our fixed entry; caller decides where to paste it."""
    _, section, format_name = _client(client_id)
    entry = connection_entry(command, client_id)
    if format_name == 'mcpb':
        return 'Claude Desktop requires a packaged binary MCPB. Export it, then install with your consent.'
    if format_name == 'toml':
        # JSON string quoting also produces valid TOML basic strings for the
        # supported bounded argv (no control characters).
        return ('[mcp_servers.video-to-subtitle]\ncommand = ' + json.dumps(entry['command'], ensure_ascii=False) +
                '\nargs = ' + json.dumps(entry['args'], ensure_ascii=False) + '\n')
    return json.dumps({section: {SERVER_KEY: entry}}, indent=2, ensure_ascii=False) + '\n'


@contextlib.contextmanager
def _config_directory(path):
    try:
        with _absolute_directory(path.parent) as directory:
            info = directory.info(path.name)
            if info is not None:
                directory.check_file(path.name)
                if info.st_size > MAX_CONFIG_BYTES:
                    raise MCPError('invalid_config', 'Configuration exceeds the 1 MiB limit.')
                if not info.st_mode & 0o200 or (os.name != 'nt' and info.st_uid != os.getuid()):
                    raise MCPError('manual_only', 'Configuration is read-only or managed by another owner.')
            parent_info = os.fstat(directory.fd) if directory.fd is not None else os.stat(directory.path)
            if os.name != 'nt' and (parent_info.st_uid != os.getuid() or not parent_info.st_mode & 0o200):
                raise MCPError('manual_only', 'Select a writable user configuration directory.')
            yield directory
    except MCPError:
        raise
    except OSError as error:
        raise MCPError('unsafe_config', 'Select an existing writable directory and a regular, non-link configuration file.') from error


def _read(directory, name):
    if directory.info(name) is None:
        return None
    with directory.open_read(name) as stream:
        data = stream.read(MAX_CONFIG_BYTES + 1)
    if len(data) > MAX_CONFIG_BYTES:
        raise MCPError('invalid_config', 'Configuration exceeds the 1 MiB limit.')
    return data


def _adapter(client_id, path):
    _, section, format_name = _client(client_id)
    if client_id in ('claude-desktop', 'windsurf', 'generic'):
        raise MCPError('manual_only', 'This client requires manual configuration or packaged MCPB export.')
    if path.suffix.lower() == '.jsonc':
        raise MCPError('manual_only', 'JSONC comment preservation is unsupported. Use manual configuration.')
    if client_id == 'antigravity' and not (
            path.parts[-3:] == ('.gemini', 'config', 'mcp_config.json') or
            path.parts[-2:] == ('.agents', 'mcp_config.json')):
        raise MCPError('manual_only', 'Select the current .gemini/config/mcp_config.json or workspace .agents/mcp_config.json explicitly.')
    if any(part.lower() in ('managed', 'managed-settings', 'managed-mcp') for part in path.parts):
        raise MCPError('manual_only', 'Managed configuration must be changed by its administrator.')
    return section, format_name


def _parse(raw, client_id, path):
    section, format_name = _adapter(client_id, path)
    text = ''
    try:
        text = raw.decode('utf-8') if raw is not None else ''
        if format_name == 'toml':
            document = _tomlkit().parse(text)
        else:
            def unique(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError('Duplicate key')
                    result[key] = value
                return result
            def invalid(value):
                raise ValueError('Nonfinite number')
            def finite(value):
                import math
                number = float(value)
                if not math.isfinite(number):
                    raise ValueError('Nonfinite number')
                return number
            document = json.loads(text or '{}', object_pairs_hook=unique, parse_constant=invalid, parse_float=finite)
        if not isinstance(document, dict):
            raise ValueError('Object required')
        if any(key in document for key in ('version', 'schema_version', 'configVersion')):
            raise MCPError('manual_only', 'Explicit configuration version is unsupported; use manual configuration.')
        if section in document and not isinstance(document[section], dict):
            raise ValueError('Server section must be an object')
        if section not in document and any(key in document for key in ('mcpServers', 'mcp_servers', 'servers', 'mcp')):
            raise MCPError('manual_only', 'This file uses a different client schema; select the intended client configuration.')
        return document, section, format_name
    except MCPError:
        raise
    except (ValueError, TypeError, RecursionError, UnicodeError) as error:
        if format_name == 'json' and ('//' in text or '/*' in text):
            raise MCPError('manual_only', 'Commented JSON cannot be edited safely; use the manual snippet.') from error
        raise MCPError('invalid_config', 'Malformed or unsupported configuration. Use manual configuration.') from error


def _unchanged(directory, name, expected_hash):
    current = _read(directory, name)
    if (_digest(current) if current is not None else None) != expected_hash:
        raise MCPError('config_changed', 'Configuration changed before publication; create a new preview.')
    return False


def _render(document, section, format_name, entry, *, remove=False, section_created=False):
    if section not in document:
        document[section] = {} if format_name == 'json' else _tomlkit().table()
    if remove:
        del document[section][SERVER_KEY]
        if section_created and not document[section]:
            del document[section]
    else:
        document[section][SERVER_KEY] = entry
    result = (_tomlkit().dumps(document) if format_name == 'toml' else
              json.dumps(document, indent=2, ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')
    if len(result) > MAX_CONFIG_BYTES:
        raise MCPError('invalid_config', 'Adding the entry would exceed the 1 MiB limit.')
    return result


def preview_connection(client_id, config_path, command, *, state_dir):
    """Create an opaque private plan; returned diff contains our entry only.

    There is no live-version assertion. Unknown explicit schema versions and
    unsupported file formats reject before an applicable preview is created.
    """
    path = _path(config_path)
    entry = connection_entry(command, client_id)
    state = State(state_dir)
    owner_id = _owner_id(client_id, path)
    with ProcessLock(state.path / 'locks', _config_lock(path)), _config_directory(path) as directory:
        raw = _read(directory, path.name)
        document, section, format_name = _parse(raw, client_id, path)
        current = document.get(section, {}).get(SERVER_KEY)
        owner = _effective_owner(_optional_record(state, 'connections', owner_id), current, raw)
        if SERVER_KEY in document.get(section, {}) and (owner.get('status') != 'managed' or current != owner.get('entry')):
            raise MCPError('entry_conflict', 'The existing video-to-subtitle entry is not unchanged application-owned data.')
        preview_id = 'preview_' + secrets.token_hex(16)
        public = {'preview_id': preview_id, 'client_id': client_id, 'config_path': str(path),
                  'original_hash': _digest(raw) if raw is not None else None,
                  'entry_before': current, 'entry_after': entry, 'server_key': SERVER_KEY,
                  'backup_plan': 'Private local backup before write; removal affects only the managed entry.',
                  'compatibility_note': _COMPATIBILITY, 'live_verified': False,
                  'version_verified': False}
        # A private stored plan prevents edited UI dictionaries from changing
        # the selected destination, argv, or expected hash on application.
        state.put('connections', preview_id, {'public': public, 'command': list(command),
                  'owner_id': owner_id})
        return json.loads(json.dumps(public))


def apply_connection(preview, *, state_dir):
    state = State(state_dir)
    if not isinstance(preview, dict) or not isinstance(preview.get('preview_id'), str):
        raise MCPError('invalid_preview', 'Create a new configuration preview.')
    plan = state.get('connections', preview['preview_id'])
    if plan.get('public') != preview:
        raise MCPError('invalid_preview', 'The preview changed. Create a new preview.')
    path = _path(preview['config_path'])
    client_id = preview['client_id']
    owner_id = _owner_id(client_id, path)
    entry = connection_entry(plan['command'], client_id)
    with ProcessLock(state.path / 'locks', _config_lock(path)), _config_directory(path) as directory:
        raw = _read(directory, path.name)
        if (_digest(raw) if raw is not None else None) != preview['original_hash']:
            raise MCPError('config_changed', 'Configuration changed after preview; create a new preview.')
        document, section, format_name = _parse(raw, client_id, path)
        current = document.get(section, {}).get(SERVER_KEY)
        owner = _effective_owner(_optional_record(state, 'connections', owner_id), current, raw)
        if SERVER_KEY in document.get(section, {}) and (owner.get('status') != 'managed' or current != owner.get('entry')):
            raise MCPError('entry_conflict', 'An unknown or edited entry must be resolved manually.')
        if current == entry:
            return {'status': 'unchanged', 'client_id': client_id, 'config_path': str(path)}
        section_created = section not in document
        encoded = _render(document, section, format_name, entry)
        backup_id = 'backup_' + secrets.token_hex(16)
        state.put('backups', backup_id, {'client_id': client_id, 'config_path': str(path),
                  'original_hash': preview['original_hash'],
                  'original_text': raw.decode('utf-8') if raw is not None else None})
        # Pending ownership is recognizable only by the exact published file
        # hash. A failed prepublication intent cannot adopt an external entry.
        managed = {'status': 'managed', 'entry': entry,
                  'client_id': client_id, 'config_path': str(path),
                  'section_created': owner.get('section_created', section_created),
                  'backup_id': backup_id}
        state.put('connections', owner_id, {**managed, 'status': 'pending',
                  'expected_hash': _digest(encoded), 'previous': owner})
        try:
            directory.write_bytes(path.name, encoded, exclusive=raw is None,
                                  cancel_check=lambda: _unchanged(directory, path.name, preview['original_hash']))
        except BaseException:
            state.put('connections', owner_id, owner)
            raise
        state.put('connections', owner_id, managed)
        return {'status': 'applied', 'client_id': client_id, 'config_path': str(path), 'backup_id': backup_id}


def remove_connection(client_id, config_path, *, state_dir):
    path = _path(config_path)
    state = State(state_dir)
    owner_id = _owner_id(client_id, path)
    with ProcessLock(state.path / 'locks', _config_lock(path)), _config_directory(path) as directory:
        raw = _read(directory, path.name)
        document, section, format_name = _parse(raw, client_id, path)
        current = document.get(section, {}).get(SERVER_KEY)
        owner = _effective_owner(_optional_record(state, 'connections', owner_id), current, raw)
        if SERVER_KEY not in document.get(section, {}):
            return {'status': 'unchanged', 'client_id': client_id, 'config_path': str(path)}
        if owner.get('status') != 'managed' or current != owner.get('entry'):
            raise MCPError('entry_changed', 'The entry is unowned or was edited; remove it manually.')
        encoded = _render(document, section, format_name, None, remove=True,
                          section_created=owner.get('section_created', False))
        backup_id = 'backup_' + secrets.token_hex(16)
        state.put('backups', backup_id, {'client_id': client_id, 'config_path': str(path),
                  'original_hash': _digest(raw), 'original_text': raw.decode('utf-8')})
        directory.write_bytes(path.name, encoded,
                              cancel_check=lambda: _unchanged(directory, path.name, _digest(raw)))
        state.put('connections', owner_id, {**owner, 'status': 'removed'})
        return {'status': 'removed', 'client_id': client_id, 'config_path': str(path), 'backup_id': backup_id}


@dataclass(frozen=True)
class FrozenMCPPayload:
    """Build-owned descriptor, returned only by bundled_mcp_payload()."""
    launcher: Path
    sha256: str
    platform: str


def bundled_mcp_payload():
    """Return only a fixed-name, hashed payload in this frozen distribution.

    Task6 packaging owns vts-mcp-payload.json and the self-contained launcher.
    No caller-provided executable or digest is accepted as proof of provenance.
    """
    if not getattr(sys, 'frozen', False):
        return None
    root = _path(Path(getattr(sys, '_MEIPASS', Path(sys.executable).parent)))
    descriptor_root = root
    if (sys.platform == 'darwin' and root.name == 'Frameworks'
            and root.parent.name == 'Contents' and root.parent.parent.suffix == '.app'):
        # Native macOS bundle roles: data is regular in Resources, executable
        # code is regular in Frameworks. Never follow the cross-role symlinks
        # PyInstaller exposes, and never search/fallback after a failed read.
        descriptor_root = root.parent / 'Resources'
    name = 'VideoToSubtitleMCP.exe' if sys.platform == 'win32' else 'VideoToSubtitleMCP'
    try:
        with _absolute_directory(descriptor_root) as directory:
            with directory.open_read('vts-mcp-payload.json') as stream:
                raw = stream.read(4097)
            if len(raw) > 4096:
                raise ValueError('Oversize payload descriptor')
            descriptor = json.loads(raw)
            if (set(descriptor) != {'launcher', 'sha256', 'platform'} or descriptor['launcher'] != name or
                    not re.fullmatch('[0-9a-f]{64}', descriptor['sha256']) or
                    descriptor['platform'] != sys.platform):
                raise ValueError('Invalid payload descriptor')
        with _absolute_directory(root) as directory:
            with directory.open_read(name) as stream:
                digest = _file_digest(stream)
            if digest != descriptor['sha256']:
                raise ValueError('Payload integrity mismatch')
        return FrozenMCPPayload(root / name, digest, sys.platform)
    except (OSError, ValueError, TypeError, KeyError) as error:
        raise MCPError('packaged_binary_required', 'Reinstall a release with the verified standalone MCP launcher payload.') from error


def export_mcpb(destination, command):
    """Write a new user-selected archive; never install or alter client settings."""
    payload = bundled_mcp_payload()
    if payload is None:
        raise MCPError('packaged_binary_required', 'MCPB export requires a packaged standalone MCP launcher; a source Python checkout cannot be bundled.')
    command = _command(command)
    if _path(command[0]).name != payload.launcher.name:
        raise MCPError('packaged_binary_required', 'MCPB export requires this release standalone MCP launcher.')
    destination = _path(destination)
    if destination.suffix.lower() != '.mcpb':
        raise MCPError('invalid_destination', 'Choose a new .mcpb output file.')
    launcher_name = payload.launcher.name
    relative = 'server/' + launcher_name
    manifest = {'manifest_version': '0.3', 'name': 'video-to-subtitle', 'version': '1.0.0',
                'description': 'Local Video to Subtitle MCP server', 'author': {'name': 'Video to Subtitle'},
                'compatibility': {'platforms': [payload.platform]},
                'server': {'type': 'binary', 'entry_point': relative,
                           'mcp_config': {'command': '${__dirname}/' + relative, 'args': command[1:]}}}
    with _absolute_directory(payload.launcher.parent) as source:
        binary = source.read_bytes(launcher_name)
    if _digest(binary) != payload.sha256:
        raise MCPError('packaged_binary_required', 'Bundled launcher changed; reinstall the application.')
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
        info = zipfile.ZipInfo(relative)
        info.external_attr = (stat.S_IFREG | 0o755) << 16
        archive.writestr(info, binary)
    with _config_directory(destination) as directory:
        directory.write_bytes(destination.name, buffer.getvalue(), exclusive=True)
    return {'status': 'exported', 'path': str(destination), 'manifest_version': '0.3',
            'payload_sha256': payload.sha256, 'live_verified': False,
            'next_step': 'Install this local MCPB in Claude Desktop yourself and review its permissions.'}
