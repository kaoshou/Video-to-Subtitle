"""Private local MCP policy and durable records; importing this module does no I/O.

Only the local GUI/admin calls ``configure``. Tool handlers must never expose it,
or accept ``admitted_generation`` from a client: that keyword is an internal
capability for jobs admitted before a finish-mode disable.
"""
import contextlib
import errno
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys
import time

from safe_files import SafeDirectory, _retry_sharing_violation

MAX_POLICY_BYTES = 1024 * 1024
MAX_RECORD_BYTES = 8 * 1024 * 1024
MAX_RECORDS = 4096
KINDS = frozenset(('assets', 'jobs', 'sources', 'drafts', 'tracks', 'requests',
                   'connections', 'backups'))
_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z')
_OPTIONS = frozenset(('model', 'device', 'cache', 'cache_dir', 'model_cache_dir',
                      'stop_mode', 'backend_command'))
_RESERVED = re.compile(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?\Z', re.I)


class MCPError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = {'disabled': 'MCP_DISABLED', 'root_revoked': 'ROOT_NOT_ALLOWED'}.get(code, code.upper())


def default_state_dir() -> Path:
    """Compute a user-local location without creating, inspecting or migrating it."""
    if sys.platform == 'win32':
        local = Path(os.environ.get('LOCALAPPDATA', ''))
        if not local.is_absolute():
            local = Path.home() / 'AppData' / 'Local'
        return local / 'VideoToSubtitle' / 'mcp'
    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Application Support' / 'VideoToSubtitle' / 'mcp'
    local = Path(os.environ.get('XDG_STATE_HOME', ''))
    if not local.is_absolute():
        local = Path.home() / '.local' / 'state'
    return local / 'video-to-subtitle' / 'mcp'


def _id(value):
    if not isinstance(value, str) or not _ID.fullmatch(value) or _RESERVED.fullmatch(value):
        raise MCPError('invalid_id', 'Expected a bounded opaque identifier.')
    return value


def _kind(value):
    if not isinstance(value, str) or value not in KINDS:
        raise MCPError('invalid_kind', 'Unknown record namespace.')
    return value


def _relative(value, *, empty=True):
    if not isinstance(value, str) or len(value) > 4096:
        raise MCPError('unsafe_path', 'Invalid relative path.')
    if value == '' and empty:
        return []
    parts = value.split('/')
    if len(parts) > 128 or any(not p or p in ('.', '..') or p[-1:] in (' ', '.') or
                               any(c in p for c in '\\:\x00') or
                               any(ord(c) < 32 for c in p) or _RESERVED.fullmatch(p)
                               for p in parts):
        raise MCPError('unsafe_path', 'Unsafe relative path.')
    return parts


@contextlib.contextmanager
def _errors(code='unsafe_path'):
    try:
        yield
    except MCPError:
        raise
    except (OSError, ValueError, UnicodeError, RecursionError, TypeError) as error:
        raise MCPError(code, 'Local MCP storage or path validation failed.') from error


@contextlib.contextmanager
def _absolute_directory(path):
    """Pin every component, including root ancestors; never resolve a new link."""
    path = Path(os.path.abspath(path))
    with contextlib.ExitStack() as stack:
        directory = stack.enter_context(SafeDirectory(path.anchor))
        for component in path.parts[1:]:
            directory = stack.enter_context(directory.child(component))
        yield directory


def _windows_private(path, *, create=False):
    """Check current-user ownership and a user-only DACL; fail on API errors.

    New directories receive a protected, inheritable DACL at creation. No owner
    is changed and no process/shell is launched.
    """
    import ctypes
    from ctypes import wintypes as w
    adv = ctypes.WinDLL('advapi32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    pointer = ctypes.c_void_p
    kernel.GetCurrentProcess.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.LocalFree.argtypes = [pointer]
    adv.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE)]
    adv.GetTokenInformation.argtypes = [w.HANDLE, ctypes.c_int, pointer, w.DWORD, ctypes.POINTER(w.DWORD)]
    adv.GetNamedSecurityInfoW.argtypes = [w.LPWSTR, ctypes.c_int, w.DWORD,
                                         ctypes.POINTER(pointer), pointer,
                                         ctypes.POINTER(pointer), pointer,
                                         ctypes.POINTER(pointer)]
    adv.GetNamedSecurityInfoW.restype = w.DWORD
    adv.EqualSid.argtypes = [pointer, pointer]
    adv.GetAce.argtypes = [pointer, w.DWORD, ctypes.POINTER(pointer)]
    adv.ConvertSidToStringSidW.argtypes = [pointer, ctypes.POINTER(w.LPWSTR)]
    adv.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [w.LPCWSTR, w.DWORD, ctypes.POINTER(pointer), pointer]
    def checked(result):
        if not result:
            raise ctypes.WinError(ctypes.get_last_error())
    token = w.HANDLE()
    checked(adv.OpenProcessToken(kernel.GetCurrentProcess(), 0x8, ctypes.byref(token)))
    try:
        size = w.DWORD()
        adv.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
        buffer = ctypes.create_string_buffer(size.value)
        checked(adv.GetTokenInformation(token, 1, buffer, size.value, ctypes.byref(size)))
        current_sid = pointer.from_buffer(buffer).value
        if create:
            class SecurityAttributes(ctypes.Structure):
                _fields_ = [('length', w.DWORD), ('descriptor', pointer), ('inherit', w.BOOL)]
            kernel.CreateDirectoryW.argtypes = [w.LPCWSTR, ctypes.POINTER(SecurityAttributes)]
            sid_text, private_sd = w.LPWSTR(), pointer()
            checked(adv.ConvertSidToStringSidW(current_sid, ctypes.byref(sid_text)))
            try:
                checked(adv.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                    f'D:P(A;OICI;FA;;;{sid_text.value})', 1, ctypes.byref(private_sd), None))
                try:
                    attributes = SecurityAttributes(ctypes.sizeof(SecurityAttributes), private_sd, False)
                    checked(kernel.CreateDirectoryW(str(path), ctypes.byref(attributes)))
                finally:
                    kernel.LocalFree(private_sd)
            finally:
                kernel.LocalFree(ctypes.cast(sid_text, pointer))
        owner, dacl, descriptor = pointer(), pointer(), pointer()
        result = adv.GetNamedSecurityInfoW(str(path), 1, 0x5, ctypes.byref(owner), None,
                                           ctypes.byref(dacl), None, ctypes.byref(descriptor))
        if result:
            raise ctypes.WinError(result)
        try:
            if not adv.EqualSid(owner, current_sid):
                raise MCPError('private_storage', 'Private storage must belong to the current user.')
            if not dacl:
                raise MCPError('private_storage', 'Private storage has an unrestricted ACL.')
            # ACL header: revision, reserved, size, ACE count, reserved.
            count = ctypes.c_ushort.from_address(dacl.value + 4).value
            user_allowed = False
            for index in range(count):
                ace = pointer()
                checked(adv.GetAce(dacl, index, ctypes.byref(ace)))
                ace_type = ctypes.c_ubyte.from_address(ace.value).value
                if ace_type == 1:  # ACCESS_DENIED_ACE cannot grant other users access.
                    continue
                if ace_type != 0 or not adv.EqualSid(ace.value + 8, current_sid):
                    raise MCPError('private_storage', 'Private storage grants access to another identity.')
                user_allowed = True
            if not user_allowed:
                raise MCPError('private_storage', 'Private storage has no current-user access.')
        finally:
            kernel.LocalFree(descriptor)
    finally:
        kernel.CloseHandle(token)


def _check_private(directory):
    if os.name == 'nt':
        _windows_private(directory.path)
    else:
        info = os.fstat(directory.fd)
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise MCPError('private_storage', 'Private storage requires current-user ownership and mode 0700.')


@contextlib.contextmanager
def _private_directory(path, *, create=False):
    """Create missing components privately while retaining every parent pin."""
    path = Path(os.path.abspath(path))
    # Normalize fixed macOS OS aliases lexically, never resolve arbitrary links.
    if sys.platform == 'darwin' and path.parts[1:2] in (('var',), ('tmp',)):
        path = Path('/private') / path.relative_to('/')
    missing = []
    parent = path
    while not parent.exists() and not parent.is_symlink():
        missing.append(parent.name)
        parent = parent.parent
    if missing and not create:
        raise FileNotFoundError(path)
    with contextlib.ExitStack() as stack:
        directory = stack.enter_context(_absolute_directory(parent))
        if not missing:
            _check_private(directory)
        for name in reversed(missing):
            try:
                if directory.fd is not None:
                    os.mkdir(name, 0o700, dir_fd=directory.fd)
                else:
                    _windows_private(directory._path(name), create=True)
            except FileExistsError:
                pass
            directory = stack.enter_context(directory.child(name))
            _check_private(directory)
        yield directory


def _read_json(directory, name, limit):
    with directory.open_read(name) as stream:
        if os.name == 'nt':
            _windows_private(directory._path(name))
        else:
            info = os.fstat(stream.fileno())
            if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
                raise MCPError('private_storage', 'Stored file permissions are not private.')
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise MCPError('invalid_state', 'Stored JSON exceeds its size limit.')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = value
        return result
    def invalid_constant(value):
        raise ValueError('Nonfinite JSON number')
    result = json.loads(data.decode('utf-8'), object_pairs_hook=unique, parse_constant=invalid_constant)
    if not isinstance(result, dict):
        raise MCPError('invalid_state', 'Stored JSON must be an object.')
    return result


def _encode(data, limit):
    if not isinstance(data, dict):
        raise MCPError('invalid_record', 'A record must be a JSON object.')
    with _errors('invalid_record'):
        encoded = json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
    if len(encoded) > limit:
        raise MCPError('invalid_record', 'JSON exceeds its size limit.')
    return encoded


def _write_json(directory, name, data):
    """Publish an already-private file; never briefly publish a 0666 inode."""
    directory.check_file(name)
    staging = '.mcp-' + secrets.token_hex(16)
    if directory.fd is not None:
        os.mkdir(staging, 0o700, dir_fd=directory.fd)
    else:
        _windows_private(directory._path(staging), create=True)
    try:
        with directory.child(staging) as stage:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
            fd = (os.open('content', flags, 0o600, dir_fd=stage.fd) if stage.fd is not None else
                  os.open(stage._path('content'), flags | os.O_BINARY, 0o600))
            try:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                def publish():
                    directory.check_file(name)
                    if directory.fd is not None:
                        os.replace('content', name, src_dir_fd=stage.fd, dst_dir_fd=directory.fd)
                    else:
                        _windows_private(stage._path('content'))
                        os.replace(stage._path('content'), directory._path(name))
                _retry_sharing_violation(publish)
                if directory.fd is not None:
                    os.fsync(directory.fd)
            finally:
                try:
                    if stage.fd is not None:
                        os.unlink('content', dir_fd=stage.fd)
                    else:
                        _retry_sharing_violation(lambda: os.unlink(stage._path('content')))
                except FileNotFoundError:
                    pass
    finally:
        if directory.fd is not None:
            os.rmdir(staging, dir_fd=directory.fd)
        else:
            _retry_sharing_violation(lambda: os.rmdir(directory._path(staging)))


def _validate_options(options):
    if not isinstance(options, dict) or set(options) - _OPTIONS:
        raise MCPError('invalid_policy', 'Unknown or secret-bearing policy option.')
    if options.get('stop_mode', 'cancel') not in ('finish', 'cancel'):
        raise MCPError('invalid_policy', 'Invalid stop mode.')
    for key, value in options.items():
        if key == 'backend_command':
            if (not isinstance(value, list) or not 1 <= len(value) <= 64 or
                    any(not isinstance(arg, str) or not arg or '\x00' in arg or len(arg) > 4096 for arg in value) or
                    not Path(value[0]).is_absolute()):
                raise MCPError('invalid_policy', 'Backend command requires an absolute executable and argv list.')
        elif not isinstance(value, str) or len(value) > 4096 or '\x00' in value:
            raise MCPError('invalid_policy', 'Invalid policy option.')
    return options


class State:
    def __init__(self, path: Path | None = None):
        self.path = Path(os.path.abspath(path if path is not None else default_state_dir()))
        self.state_dir = self.path

    def policy(self) -> dict:
        with _errors('invalid_policy'):
            try:
                with _private_directory(self.path) as directory:
                    policy = _read_json(directory, 'policy.json', MAX_POLICY_BYTES)
            except FileNotFoundError:
                return {'enabled': False, 'roots': [], 'generation': 0}
            if (type(policy.get('enabled')) is not bool or type(policy.get('generation')) is not int or
                    policy['generation'] < 0 or not isinstance(policy.get('roots'), list) or len(policy['roots']) > 128):
                raise MCPError('invalid_policy', 'Malformed MCP policy.')
            ids, paths = set(), set()
            for root in policy['roots']:
                if (not isinstance(root, dict) or set(root) != {'id', 'path', 'label'} or
                        not isinstance(root.get('path'), str) or len(root['path']) > 4096 or
                        not Path(root['path']).is_absolute() or '\x00' in root['path'] or
                        not isinstance(root.get('label'), str) or len(root['label']) > 1024):
                    raise MCPError('invalid_policy', 'Malformed root policy.')
                _id(root.get('id'))
                if root['id'] in ids or root['path'] in paths:
                    raise MCPError('invalid_policy', 'Duplicate root policy.')
                ids.add(root['id'])
                paths.add(root['path'])
            _validate_options(policy.get('options', {}))
            drain = policy.get('drain_generation')
            if drain is not None and (type(drain) is not int or drain <= 0 or
                                      drain >= policy['generation'] or policy['enabled']):
                raise MCPError('invalid_policy', 'Malformed drain admission.')
            return policy

    def configure(self, enabled: bool, roots: list[Path], **options) -> dict:
        """Local admin only. Never register this method as an MCP tool."""
        if type(enabled) is not bool or not isinstance(roots, list) or len(roots) > 128:
            raise MCPError('invalid_policy', 'Invalid local policy.')
        _validate_options(options)
        with _errors('invalid_policy'), ProcessLock(self.path / 'locks', 'policy'):
            old = self.policy()
            old_ids = {root['path']: root['id'] for root in old['roots']}
            selected = []
            for root in roots:
                resolved = str(Path(root).resolve(strict=True))
                with _absolute_directory(resolved):
                    pass
                if resolved not in {entry['path'] for entry in selected}:
                    selected.append({'id': old_ids.get(resolved, secrets.token_hex(16)),
                                     'path': resolved, 'label': Path(resolved).name or resolved})
            policy = {'enabled': enabled, 'roots': selected, 'generation': old['generation'] + 1,
                      'options': {**old.get('options', {}), **options}}
            if (not enabled and policy['options'].get('stop_mode') == 'finish' and
                    old['roots'] == selected):
                admission = old['generation'] if old['enabled'] else old.get('drain_generation')
                if admission is not None:
                    policy['drain_generation'] = admission
            with _private_directory(self.path, create=True) as directory:
                _write_json(directory, 'policy.json', _encode(policy, MAX_POLICY_BYTES))
            return policy

    def require_enabled(self, *, admitted_generation=None) -> dict:
        policy = self.policy()
        if not policy['enabled'] and not (type(admitted_generation) is int and
                                         admitted_generation == policy.get('drain_generation')):
            raise MCPError('disabled', 'Local MCP access is disabled.')
        return policy

    @contextlib.contextmanager
    def directory(self, root_id, relative='', *, admitted_generation=None):
        _id(root_id)
        parts = _relative(relative)
        with _errors(), contextlib.ExitStack() as stack:
            policy = self.require_enabled(admitted_generation=admitted_generation)
            root = next((root for root in policy['roots'] if root['id'] == root_id), None)
            if root is None:
                raise MCPError('root_revoked', 'The selected root is not authorized.')
            directory = stack.enter_context(_absolute_directory(root['path']))
            for part in parts:
                directory = stack.enter_context(directory.child(part))
            current = self.require_enabled(admitted_generation=admitted_generation)
            if root not in current['roots']:
                raise MCPError('root_revoked', 'The selected root is no longer authorized.')
            yield directory

    @contextlib.contextmanager
    def file(self, root_id, relative, *, admitted_generation=None):
        parts = _relative(relative, empty=False)
        with _errors(), self.directory(root_id, '/'.join(parts[:-1]), admitted_generation=admitted_generation) as directory:
            with directory.open_read(parts[-1]) as stream:
                current = self.require_enabled(admitted_generation=admitted_generation)
                if not any(root['id'] == root_id for root in current['roots']):
                    raise MCPError('root_revoked', 'The selected root is no longer authorized.')
                yield stream

    def get(self, kind, id) -> dict:
        _kind(kind)
        _id(id)
        with _errors('invalid_state'):
            try:
                with _private_directory(self.path) as directory, directory.child(kind) as records:
                    _check_private(records)
                    return _read_json(records, id + '.json', MAX_RECORD_BYTES)
            except FileNotFoundError as error:
                raise MCPError('not_found', 'The local record does not exist.') from error

    def _put(self, kind, id, data):
        encoded = _encode(data, MAX_RECORD_BYTES)
        with ProcessLock(self.path / 'locks', kind + '-index'):
            with _private_directory(self.path, create=True) as directory:
                try:
                    if directory.fd is not None:
                        os.mkdir(kind, 0o700, dir_fd=directory.fd)
                    else:
                        _windows_private(directory._path(kind), create=True)
                except FileExistsError:
                    pass
                with directory.child(kind) as records:
                    _check_private(records)
                    if records.info(id + '.json') is None and len(records.names()) >= MAX_RECORDS:
                        raise MCPError('storage_limit', 'The record namespace is full.')
                    _write_json(records, id + '.json', encoded)

    def put(self, kind, id, data):
        _kind(kind)
        _id(id)
        _encode(data, MAX_RECORD_BYTES)
        with _errors('invalid_state'), ProcessLock(self.path / 'locks', kind + '-' + id):
            self._put(kind, id, data)

    @contextlib.contextmanager
    def mutation(self, kind, id):
        """Serialize a whole read-modify-write; exception exits publish nothing."""
        _kind(kind)
        _id(id)
        with _errors('invalid_state'), ProcessLock(self.path / 'locks', kind + '-' + id):
            try:
                data = self.get(kind, id)
            except MCPError as error:
                if error.code != 'NOT_FOUND':
                    raise
                data = {}
            yield data
            self._put(kind, id, data)

    def records(self, kind) -> list[dict]:
        _kind(kind)
        with _errors('invalid_state'):
            try:
                with _private_directory(self.path) as directory, directory.child(kind) as records:
                    _check_private(records)
                    names = records.names()
                    if len(names) > MAX_RECORDS:
                        raise MCPError('storage_limit', 'The record namespace is too large.')
                    result = []
                    total = 0
                    for name in sorted(names):
                        if not name.endswith('.json'):
                            raise MCPError('invalid_state', 'Unexpected record entry.')
                        _id(name[:-5])
                        value = _read_json(records, name, MAX_RECORD_BYTES)
                        total += len(_encode(value, MAX_RECORD_BYTES))
                        if total > 32 * 1024 * 1024:
                            raise MCPError('storage_limit', 'Record listing exceeds its size limit.')
                        result.append(value)
                    return result
            except FileNotFoundError:
                return []


class ProcessLock:
    """Crash-released OS lock. Lock files stay in place to preserve inode identity."""
    def __init__(self, directory: Path, name='inference'):
        self.directory = Path(directory)
        # Record mutation names are two individually bounded identifiers.
        if (not isinstance(name, str) or len(name) > 256 or _RESERVED.fullmatch(name) or
                not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', name)):
            raise MCPError('invalid_id', 'Invalid lock name.')
        self.name = name + '.lock'
        self._stream = None
        self._stack = None

    def acquire(self, blocking=False, cancelled=None) -> bool:
        if self._stream is not None:
            return True
        stack = contextlib.ExitStack()
        with _errors('lock_failed'):
            try:
                directory = stack.enter_context(_private_directory(self.directory, create=True))
                directory.check_file(self.name)
                flags = os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
                if directory.fd is not None:
                    fd = os.open(self.name, flags, 0o600, dir_fd=directory.fd)
                else:
                    # Open the leaf itself and deny delete sharing, so the lock
                    # inode cannot be exchanged for a reparse point/new lock.
                    import ctypes
                    import msvcrt
                    from ctypes import wintypes as w
                    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
                    create = kernel.CreateFileW
                    create.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, ctypes.c_void_p,
                                       w.DWORD, w.DWORD, w.HANDLE]
                    create.restype = w.HANDLE
                    handle = create(directory._path(self.name), 0xC0000000, 3, None, 4, 0x00200000, None)
                    if handle == w.HANDLE(-1).value:
                        raise ctypes.WinError(ctypes.get_last_error())
                    try:
                        fd = msvcrt.open_osfhandle(handle, os.O_RDWR | os.O_BINARY)
                    except BaseException:
                        kernel.CloseHandle.argtypes = [w.HANDLE]
                        kernel.CloseHandle(handle)
                        raise
                stream = stack.enter_context(os.fdopen(fd, 'r+b', buffering=0))
                info = os.fstat(stream.fileno())
                if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
                        getattr(info, 'st_file_attributes', 0) & 0x400):
                    raise MCPError('lock_failed', 'Lock file is not a private regular file.')
                if os.name == 'nt':
                    _windows_private(directory._path(self.name))
                elif info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
                    raise MCPError('private_storage', 'Lock permissions are not private.')
                while True:
                    if cancelled and cancelled():
                        stack.close()
                        return False
                    try:
                        if os.name == 'nt':
                            import msvcrt
                            stream.seek(0)
                            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                        else:
                            import fcntl
                            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        self._stream, self._stack = stream, stack
                        return True
                    except OSError as error:
                        if error.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                            raise
                        if not blocking:
                            stack.close()
                            return False
                        time.sleep(0.05)
            except BaseException:
                stack.close()
                raise

    def release(self):
        if self._stream is None:
            return
        try:
            if os.name == 'nt':
                import msvcrt
                self._stream.seek(0)
                msvcrt.locking(self._stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._stream.fileno(), fcntl.LOCK_UN)
        finally:
            self._stack.close()
            self._stream = self._stack = None

    def __enter__(self):
        self.acquire(blocking=True)
        return self

    def __exit__(self, *args):
        self.release()
