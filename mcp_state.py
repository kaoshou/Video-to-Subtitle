"""Private local MCP policy and durable records; importing this module does no I/O.

Only the local GUI/admin calls ``configure`` or ``disable``. Tool handlers must never expose them,
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
                   'connections', 'backups', 'locations'))
_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z')
_OPTIONS = frozenset(('model', 'device', 'cache', 'cache_dir', 'model_cache_dir',
                      'stop_mode', 'backend_command', 'access_mode'))
_RESERVED = re.compile(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?\Z', re.I)
_STAGING = re.compile(r'\.mcp-[0-9a-f]{32}\Z')


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


def directory_identity(directory):
    # Windows SafeDirectory pins the directory and ancestors against rename;
    # POSIX uses the opened descriptor, never a second pathname lookup.
    info = os.fstat(directory.fd) if directory.fd is not None else os.stat(directory.path, follow_symlinks=False)
    return [info.st_dev, info.st_ino]


def file_version(stream):
    info = os.fstat(stream.fileno())
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns]


@contextlib.contextmanager
def _windows_creation_security():
    """Explicit TokenUser owner and user-only DACL, before object visibility.

    TokenOwner can be the Administrators group in an elevated process. Never
    depend on that default, or change the process token / an existing owner.
    """
    import ctypes
    from ctypes import wintypes as w
    pointer = ctypes.c_void_p
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    adv = ctypes.WinDLL('advapi32', use_last_error=True)
    class SecurityAttributes(ctypes.Structure):
        _fields_ = [('length', w.DWORD), ('descriptor', pointer), ('inherit', w.BOOL)]
    kernel.GetCurrentProcess.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.LocalFree.argtypes, kernel.LocalFree.restype = [pointer], pointer
    adv.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE)]
    adv.GetTokenInformation.argtypes = [w.HANDLE, ctypes.c_int, pointer, w.DWORD, ctypes.POINTER(w.DWORD)]
    adv.ConvertSidToStringSidW.argtypes = [pointer, ctypes.POINTER(w.LPWSTR)]
    adv.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [w.LPCWSTR, w.DWORD, ctypes.POINTER(pointer), pointer]
    def checked(result):
        if not result:
            raise ctypes.WinError(ctypes.get_last_error())
    token, sid_text, descriptor = w.HANDLE(), w.LPWSTR(), pointer()
    checked(adv.OpenProcessToken(kernel.GetCurrentProcess(), 8, ctypes.byref(token)))
    try:
        size = w.DWORD()
        adv.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
        buffer = ctypes.create_string_buffer(size.value)
        checked(adv.GetTokenInformation(token, 1, buffer, size.value, ctypes.byref(size)))
        checked(adv.ConvertSidToStringSidW(pointer.from_buffer(buffer).value, ctypes.byref(sid_text)))
        checked(adv.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            f'O:{sid_text.value}D:P(A;OICI;FA;;;{sid_text.value})', 1,
            ctypes.byref(descriptor), None))
        yield SecurityAttributes(ctypes.sizeof(SecurityAttributes), descriptor, False)
    finally:
        if descriptor:
            kernel.LocalFree(descriptor)
        if sid_text:
            kernel.LocalFree(ctypes.cast(sid_text, pointer))
        kernel.CloseHandle(token)


def _windows_private_file(path, *, exclusive=False):
    """Return a non-delete-shared FD; creation never uses TokenOwner defaults."""
    import ctypes
    import msvcrt
    from ctypes import wintypes as w
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, ctypes.c_void_p,
                       w.DWORD, w.DWORD, w.HANDLE]
    create.restype = w.HANDLE
    with _windows_creation_security() as attributes:
        handle = create(str(path), 0xC0000000, 3, ctypes.byref(attributes),
                        1 if exclusive else 4, 0x00200000, None)
        if handle == w.HANDLE(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
    try:
        return msvcrt.open_osfhandle(handle, os.O_RDWR | os.O_BINARY)
    except BaseException:
        kernel.CloseHandle.argtypes = [w.HANDLE]
        kernel.CloseHandle(handle)
        raise


def _windows_private(path, *, create=False):
    """Check current-user ownership and a user-only DACL; fail on API errors.

    New directories receive an explicit user owner and protected, inheritable
    DACL at creation. Existing ownership is never changed.
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
            kernel.CreateDirectoryW.argtypes = [w.LPCWSTR, pointer]
            with _windows_creation_security() as attributes:
                checked(kernel.CreateDirectoryW(str(path), ctypes.byref(attributes)))
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
                  _windows_private_file(stage._path('content'), exclusive=True))
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


def _record_names(directory):
    """Return only published names; retain private stages for local recovery.

    Staging can be active or left by a process death. Never open its contents,
    follow its links, or delete it from a reader. A concurrent publisher may
    remove an observed staging directory before its metadata is inspected.
    """
    names = []
    for name in directory.names():
        if _STAGING.fullmatch(name):
            info = directory.info(name)
            if info is None:
                continue
            if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode) or
                    getattr(info, 'st_file_attributes', 0) & 0x400):
                raise MCPError('invalid_state', 'Unsafe record staging entry.')
            if os.name != 'nt' and (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077):
                raise MCPError('private_storage', 'Record staging permissions are not private.')
            continue
        if not name.endswith('.json'):
            raise MCPError('invalid_state', 'Unexpected record entry.')
        _id(name[:-5])
        names.append(name)
        if len(names) > MAX_RECORDS:
            raise MCPError('storage_limit', 'The record namespace is too large.')
    return names


def _validate_options(options):
    if not isinstance(options, dict) or set(options) - _OPTIONS:
        raise MCPError('invalid_policy', 'Unknown or secret-bearing policy option.')
    if options.get('stop_mode', 'cancel') not in ('finish', 'cancel'):
        raise MCPError('invalid_policy', 'Invalid stop mode.')
    if options.get('access_mode', 'restricted') not in ('general', 'restricted'):
        raise MCPError('invalid_policy', 'Invalid access mode.')
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

    def require_no_cleanup(self):
        try:
            with _private_directory(self.path) as directory:
                if directory.info('cleanup.json') is not None:
                    raise MCPError('CLEANUP_PENDING', 'Private cleanup was interrupted; resume it in local AI connection settings before enabling access.')
        except FileNotFoundError:
            pass

    def cancel_job(self, job_id):
        """Metadata-only control shared by broker, offline bridge and local GUI.

        Reset/control -> job record -> namespace. A reset holds the same guard
        across inventory and deletion, so a paused cancellation cannot recreate
        a deleted job or invalidate the confirmed cleanup inventory.
        """
        self.require_no_cleanup()
        guard = ProcessLock(self.path / 'locks', 'cleanup-control')
        if not guard.acquire():
            raise MCPError('WORK_ACTIVE', 'Private cleanup/control is active; retry after it finishes.')
        try:
            self.require_no_cleanup()
            with self.mutation('jobs', job_id) as job:
                if not job:
                    raise MCPError('NOT_FOUND', 'Unknown local job.')
                if job['state'] not in ('succeeded', 'failed', 'cancelled', 'interrupted'):
                    job.update(cancel_requested=True, state='cancelling')
            return {'job_id': job_id, 'state': job['state']}
        finally:
            guard.release()

    def policy(self) -> dict:
        with _errors('invalid_policy'):
            try:
                with _private_directory(self.path) as directory:
                    if directory.info('policy.json') is None:
                        return {'enabled': False, 'roots': [], 'generation': 0}
                    with ProcessLock(self.path / 'locks', 'json-policy'):
                        policy = _read_json(directory, 'policy.json', MAX_POLICY_BYTES)
            except FileNotFoundError:
                return {'enabled': False, 'roots': [], 'generation': 0}
            if (type(policy.get('enabled')) is not bool or type(policy.get('generation')) is not int or
                    policy['generation'] < 0 or not isinstance(policy.get('roots'), list) or len(policy['roots']) > 128):
                raise MCPError('invalid_policy', 'Malformed MCP policy.')
            ids, paths = set(), set()
            for root in policy['roots']:
                if (not isinstance(root, dict) or set(root) not in ({'id', 'path', 'label'}, {'id', 'path', 'label', 'identity'}) or
                        not isinstance(root.get('path'), str) or len(root['path']) > 4096 or
                        not Path(root['path']).is_absolute() or '\x00' in root['path'] or
                        not isinstance(root.get('label'), str) or len(root['label']) > 1024):
                    raise MCPError('invalid_policy', 'Malformed root policy.')
                _id(root.get('id'))
                identity = root.get('identity')
                if identity is not None and (not isinstance(identity, list) or len(identity) != 2 or
                                             any(type(n) is not int or n < 0 for n in identity)):
                    raise MCPError('invalid_policy', 'Malformed root identity.')
                if root['id'] in ids or root['path'] in paths:
                    raise MCPError('invalid_policy', 'Duplicate root policy.')
                ids.add(root['id'])
                paths.add(root['path'])
            _validate_options(policy.get('options', {}))
            floor = policy.get('admission_floor', policy['generation'])
            if type(floor) is not int or not 0 <= floor <= policy['generation']:
                raise MCPError('invalid_policy', 'Malformed admission range.')
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
            if enabled:
                self.require_no_cleanup()
            old = self.policy()
            old_roots = {root['path']: root for root in old['roots']}
            selected = []
            for root in roots:
                resolved = str(Path(root).resolve(strict=True))
                with _absolute_directory(resolved) as directory:
                    identity = directory_identity(directory)
                previous = old_roots.get(resolved, {})
                if resolved not in {entry['path'] for entry in selected}:
                    selected.append({'id': previous['id'] if previous.get('identity') == identity else secrets.token_hex(16),
                                     'path': resolved, 'label': Path(resolved).name or resolved, 'identity': identity})
            policy = {'enabled': enabled, 'roots': selected, 'generation': old['generation'] + 1,
                      'options': {**old.get('options', {}), **options}}
            policy['admission_floor'] = old.get('admission_floor', old['generation']) if old['enabled'] else policy['generation']
            if old.get('options', {}).get('access_mode', 'restricted') != policy['options'].get('access_mode', 'restricted'):
                policy['admission_floor'] = policy['generation']
            if (not enabled and policy['options'].get('stop_mode') == 'finish' and
                    old['roots'] == selected):
                admission = old['generation'] if old['enabled'] else old.get('drain_generation')
                if admission is not None:
                    policy['drain_generation'] = admission
                    policy['admission_floor'] = old.get('admission_floor', admission)
            with ProcessLock(self.path / 'locks', 'json-policy'), _private_directory(self.path, create=True) as directory:
                _write_json(directory, 'policy.json', _encode(policy, MAX_POLICY_BYTES))
            return policy

    def reduce_roots(self, roots, **options):
        """Try a pure reduction against the latest policy, without filesystem I/O.

        None means a new grant, identity refresh, activation or option change
        needs the normal inference-guarded enable path. No stale GUI policy is
        written back, and missing disks do not prevent revocation.
        """
        paths = {os.path.abspath(root) for root in roots}
        with ProcessLock(self.path / 'locks', 'policy'):
            old = self.policy()
            if (not old['enabled'] or not paths < {r['path'] for r in old['roots']} or
                    any(old.get('options', {}).get(k) != v for k, v in options.items())):
                return None
            policy = {**old, 'roots': [r for r in old['roots'] if r['path'] in paths],
                      'generation': old['generation'] + 1,
                      'admission_floor': old.get('admission_floor', old['generation'])}
            with ProcessLock(self.path / 'locks', 'json-policy'), _private_directory(self.path) as directory:
                _write_json(directory, 'policy.json', _encode(policy, MAX_POLICY_BYTES))
            return policy

    def disable(self, stop_mode='cancel') -> dict:
        """Local admin revocation without resolving/opening any approved root.

        Preserve the latest saved roots verbatim, including unavailable ones.
        New grants still go through configure's full filesystem validation.
        """
        _validate_options({'stop_mode': stop_mode})
        old = self.policy()
        if old['generation'] == 0:
            return old  # No policy means no lock or storage creation either.
        with _errors('invalid_policy'), ProcessLock(self.path / 'locks', 'policy'):
            old = self.policy()  # An intervening configure must not be lost.
            if old['generation'] == 0:
                return old
            policy = {'enabled': False, 'roots': old['roots'], 'generation': old['generation'] + 1,
                      'options': {**old.get('options', {}), 'stop_mode': stop_mode}}
            if stop_mode == 'finish':
                admission = old['generation'] if old['enabled'] else old.get('drain_generation')
                if admission is not None:
                    policy['drain_generation'] = admission
                    policy['admission_floor'] = old.get('admission_floor', admission)
            with ProcessLock(self.path / 'locks', 'json-policy'), _private_directory(self.path, create=True) as directory:
                _write_json(directory, 'policy.json', _encode(policy, MAX_POLICY_BYTES))
            return policy

    def require_enabled(self, *, admitted_generation=None) -> dict:
        self.require_no_cleanup()
        policy = self.policy()
        if type(admitted_generation) is int and admitted_generation < policy.get('admission_floor', 0):
            raise MCPError('disabled', 'This job admission was revoked; submit a new job.')
        if not policy['enabled'] and not (type(admitted_generation) is int and
                policy.get('admission_floor', policy.get('drain_generation', 0)) <= admitted_generation <=
                policy.get('drain_generation', -1)):
            raise MCPError('disabled', 'Local MCP access is disabled.')
        return policy

    def path_location(self, path):
        """Pin a requested directory; never expand the configured allowlist."""
        if not isinstance(path, str) or not Path(path).is_absolute() or len(path) > 4096 or '\x00' in path or '..' in Path(path).parts:
            raise MCPError('UNSAFE_PATH', 'Use an absolute local path without parent traversal.')
        with _errors(), ProcessLock(self.path / 'locks', 'policy'):
            policy = self.require_enabled()
            if policy.get('options', {}).get('access_mode', 'restricted') != 'general':
                for root in policy['roots']:
                    try:
                        relative = Path(path).relative_to(root['path']).as_posix()
                    except ValueError:
                        continue
                    return root['id'], '' if relative == '.' else relative
                raise MCPError('ROOT_NOT_ALLOWED', 'Select a path within the configured folders.')
            with _absolute_directory(path) as directory:
                identity = directory_identity(directory)
            import hashlib
            floor = policy.get('admission_floor', policy['generation'])
            record = {'path': str(Path(path)), 'identity': identity, 'floor': floor}
            identifier = hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()
            self.put('locations', identifier, record)
            return identifier, ''

    def _authorized_root(self, policy, root_id):
        root = next((root for root in policy['roots'] if root['id'] == root_id), None)
        if root is not None:
            return root
        if policy.get('options', {}).get('access_mode', 'restricted') == 'general':
            try:
                location = self.get('locations', root_id)
            except MCPError as error:
                if error.code != 'NOT_FOUND':
                    raise
            else:
                if location.get('floor') == policy.get('admission_floor', policy['generation']):
                    return location
        raise MCPError('ROOT_NOT_ALLOWED', 'The selected location is no longer authorized.')

    @contextlib.contextmanager
    def directory(self, root_id, relative='', *, admitted_generation=None):
        _id(root_id)
        parts = _relative(relative)
        with _errors(), contextlib.ExitStack() as stack:
            policy = self.require_enabled(admitted_generation=admitted_generation)
            root = self._authorized_root(policy, root_id)
            if 'identity' not in root:
                raise MCPError('root_revoked', 'Legacy root grant requires local reauthorization: remove and add the folder again.')
            directory = stack.enter_context(_absolute_directory(root['path']))
            if directory_identity(directory) != root['identity']:
                raise MCPError('root_revoked', 'Root directory was replaced; locally reauthorize the new directory.')
            for part in parts:
                directory = stack.enter_context(directory.child(part))
            current = self.require_enabled(admitted_generation=admitted_generation)
            if root != self._authorized_root(current, root_id):
                raise MCPError('root_revoked', 'The selected root is no longer authorized.')
            yield directory

    @contextlib.contextmanager
    def file(self, root_id, relative, *, admitted_generation=None):
        parts = _relative(relative, empty=False)
        with _errors(), self.directory(root_id, '/'.join(parts[:-1]), admitted_generation=admitted_generation) as directory:
            with directory.open_read(parts[-1]) as stream:
                current = self.require_enabled(admitted_generation=admitted_generation)
                self._authorized_root(current, root_id)
                yield stream

    def get(self, kind, id) -> dict:
        _kind(kind)
        _id(id)
        with _errors('invalid_state'):
            try:
                with _private_directory(self.path) as directory, directory.child(kind) as records:
                    _check_private(records)
                    if records.info(id + '.json') is None:
                        raise FileNotFoundError(id + '.json')
                    # Leaf I/O leases are separate from mutation locks, so a
                    # mutation may read its own record without reentrant locks.
                    # Keep Windows readers closed before atomic replacement.
                    with ProcessLock(self.path / 'locks', 'json-' + kind + '-' + id):
                        return _read_json(records, id + '.json', MAX_RECORD_BYTES)
            except FileNotFoundError as error:
                raise MCPError('not_found', 'The local record does not exist.') from error

    def _put(self, kind, id, data):
        encoded = _encode(data, MAX_RECORD_BYTES)
        with ProcessLock(self.path / 'locks', 'namespace-' + kind):
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
                    if records.info(id + '.json') is None and len(_record_names(records)) >= MAX_RECORDS:
                        raise MCPError('storage_limit', 'The record namespace is full.')
                    with ProcessLock(self.path / 'locks', 'json-' + kind + '-' + id):
                        _write_json(records, id + '.json', encoded)

    def put(self, kind, id, data):
        _kind(kind)
        _id(id)
        _encode(data, MAX_RECORD_BYTES)
        with _errors('invalid_state'), ProcessLock(self.path / 'locks', 'record-' + kind + '-' + id):
            self._put(kind, id, data)

    @contextlib.contextmanager
    def mutation(self, kind, id):
        """Serialize a whole read-modify-write; exception exits publish nothing."""
        _kind(kind)
        _id(id)
        with _errors('invalid_state'), ProcessLock(self.path / 'locks', 'record-' + kind + '-' + id):
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
                    names = _record_names(records)
                    result = []
                    total = 0
                    for name in sorted(names):
                        with ProcessLock(self.path / 'locks', 'json-' + kind + '-' + name[:-5]):
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
    def __init__(self, directory: Path, name='inference', *, process_lifetime=False):
        self.directory = Path(directory)
        # Record mutation names are two individually bounded identifiers.
        if (not isinstance(name, str) or len(name) > 256 or _RESERVED.fullmatch(name) or
                not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', name)):
            raise MCPError('invalid_id', 'Invalid lock name.')
        self.name = name + '.lock'
        self._stream = None
        self._stack = None
        self._process_lifetime = process_lifetime
        self._raw_fd = None

    def acquire(self, blocking=False, cancelled=None) -> bool:
        if self._stream is not None:
            return True
        stack = contextlib.ExitStack()
        raw_fd = None
        def close_failed():
            stack.close()
            if raw_fd is not None:
                os.close(raw_fd)
        with _errors('lock_failed'):
            try:
                directory = stack.enter_context(_private_directory(self.directory, create=True))
                directory.check_file(self.name)
                flags = os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
                if directory.fd is not None:
                    try:
                        fd = os.open(self.name, flags, 0o600, dir_fd=directory.fd)
                    except FileNotFoundError:
                        # Some POSIX filesystems return ENOENT to concurrent
                        # first creators even after a peer has created the leaf.
                        # Retry exactly once only for that now-safe existing
                        # file, retaining the pinned parent and nofollow flags.
                        _check_private(directory)
                        parent = os.fstat(directory.fd)
                        named = os.stat(directory.path, follow_symlinks=False)
                        leaf = directory.info(self.name)
                        if (not parent.st_nlink or (parent.st_dev, parent.st_ino) !=
                                (named.st_dev, named.st_ino) or leaf is None or
                                not stat.S_ISREG(leaf.st_mode) or leaf.st_nlink != 1 or
                                leaf.st_uid != os.getuid() or stat.S_IMODE(leaf.st_mode) & 0o077):
                            raise
                        fd = os.open(self.name, flags, 0o600, dir_fd=directory.fd)
                else:
                    # Open the leaf itself and deny delete sharing, so the lock
                    # inode cannot be exchanged for a reparse point/new lock.
                    fd = _windows_private_file(directory._path(self.name))
                if self._process_lifetime:
                    raw_fd = fd
                # A native engine may survive Python object destruction and
                # atexit callbacks. Lifetime leases use a raw non-inherited FD:
                # FileIO/GC cannot close it; only explicit release or OS exit.
                os.set_inheritable(fd, False)
                stream = stack.enter_context(os.fdopen(fd, 'r+b', buffering=0,
                                                       closefd=not self._process_lifetime))
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
                        close_failed()
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
                        self._raw_fd = raw_fd
                        return True
                    except OSError as error:
                        if error.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                            raise
                        if not blocking:
                            close_failed()
                            return False
                        time.sleep(0.05)
            except BaseException:
                close_failed()
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
            if self._raw_fd is not None:
                os.close(self._raw_fd)
                self._raw_fd = None
            self._stream = self._stack = None

    def __enter__(self):
        self.acquire(blocking=True)
        return self

    def __exit__(self, *args):
        self.release()
