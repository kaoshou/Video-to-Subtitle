"""Local file operations that never truncate a caller-supplied directory entry.

POSIX operations are anchored to directory descriptors. On Windows, directory
handles deny delete sharing so ancestors cannot be exchanged for junctions while
an operation is in progress. The explicitly selected parent is resolved once;
descendant links/reparse points are rejected.
"""
import contextlib
import os
import secrets
import stat
import sys
import time
from pathlib import Path


class UnsafePathError(OSError):
    pass


def _retry_sharing_violation(operation):
    """Only retry Windows sharing/lock violations; never relax file safety.

    Newly closed files can briefly be held by another reader. Keep the owning
    directory handles pinned while waiting, and bound the total delay to 4.55s.
    Access denied, existing destinations and unsafe paths are not transient.
    """
    delays = iter((0.05, 0.1, 0.2, 0.4, 0.8, 1.0, 1.0, 1.0))
    while True:
        try:
            return operation()
        except OSError as error:
            if getattr(error, 'winerror', None) not in (32, 33):
                raise
            delay = next(delays, None)
            if delay is None:
                if hasattr(error, 'add_note'):
                    error.add_note('檔案持續被占用；已有限次重試，未略過安全檢查。')
                raise
            time.sleep(delay)


def _publish_exclusive(source_fd, destination_fd, name):
    # macOS RENAME_EXCL also works on volumes without hard links (e.g. exFAT).
    # Never use a check-then-overwriting rename for the original-page backup.
    if sys.platform == 'darwin':
        import ctypes
        libc = ctypes.CDLL(None, use_errno=True)
        rename = libc.renameatx_np
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                           ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        if rename(source_fd, b'content', destination_fd, os.fsencode(name), 0x4):
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error), name)
    else:
        os.link('content', name, src_dir_fd=source_fd, dst_dir_fd=destination_fd,
                follow_symlinks=False)


def _regular(info, path, directory=False):
    if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
        raise UnsafePathError(f"拒絕符號連結或重新解析點：{path}")
    if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
        raise UnsafePathError(f"非一般{'資料夾' if directory else '檔案'}：{path}")


def _win_open(path, directory=False, rename_access=False):
    """Open the entry itself, not its reparse target; hold it against renames."""
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                       wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    # No FILE_SHARE_DELETE: prevents replacing the opened directory/file.
    handle = create(path, 0x80000000 | (0x10000 if rename_access else 0), 3 if directory else 1, None, 3,
                    0x00200000 | (0x02000000 if directory else 0), None)
    if handle == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    class TagInfo(ctypes.Structure):
        _fields_ = [('attributes', wintypes.DWORD), ('tag', wintypes.DWORD)]
    get_info = kernel.GetFileInformationByHandleEx
    get_info.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    get_info.restype = wintypes.BOOL
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    info = TagInfo()
    try:
        if not get_info(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        if info.attributes & 0x400 or bool(info.attributes & 0x10) != directory:
            raise UnsafePathError(f"拒絕連結或非預期檔案類型：{path}")
    except BaseException:
        close(handle)
        raise
    return handle, close


class SafeDirectory:
    def __init__(self, path):
        path = os.path.abspath(path)
        _regular(os.lstat(path), path, directory=True)
        # Resolve platform aliases in the explicitly selected parent (/var,
        # /tmp on macOS), but NEVER resolve the checked leaf again: it could
        # have been exchanged for a link since lstat. __enter__ opens that
        # same leaf without following links.
        self.path = os.path.join(os.path.realpath(os.path.dirname(path)), os.path.basename(path))
        self.fd = None
        self.handles = []

    def __enter__(self):
        try:
            if os.name == 'nt':
                # Pin all ancestors, including the course root, on Windows.
                chain = []
                current = self.path
                while True:
                    chain.append(current)
                    parent = os.path.dirname(current)
                    if parent == current:
                        break
                    current = parent
                for path in reversed(chain):
                    self.handles.append(_win_open(path, directory=True))
            else:
                self.fd = os.open(self.path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *args):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        for handle, close in reversed(self.handles):
            close(handle)
        self.handles.clear()

    @staticmethod
    def _name(name):
        if not name or name in ('.', '..') or any(c in name for c in '/\\\x00:'):
            raise UnsafePathError(f"不安全的檔名：{name!r}")
        return name

    def _path(self, name):
        return os.path.join(self.path, self._name(name))

    def info(self, name):
        self._name(name)
        try:
            return os.stat(name, dir_fd=self.fd, follow_symlinks=False) if self.fd is not None else os.lstat(self._path(name))
        except FileNotFoundError:
            return None

    def check_file(self, name):
        info = self.info(name)
        if info is not None:
            _regular(info, name)
        return info

    def names(self):
        return os.listdir(self.fd if self.fd is not None else self.path)

    @contextlib.contextmanager
    def child(self, name, create=False):
        self._name(name)
        if create:
            try:
                if self.fd is not None:
                    os.mkdir(name, 0o755, dir_fd=self.fd)
                else:
                    os.mkdir(self._path(name))
            except FileExistsError:
                pass
        info = self.info(name)
        if info is None:
            raise FileNotFoundError(name)
        _regular(info, name, directory=True)
        child = object.__new__(SafeDirectory)
        child.path, child.fd, child.handles = self._path(name), None, []
        try:
            if self.fd is not None:
                child.fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=self.fd)
            else:
                child.handles.append(_win_open(child.path, directory=True))
            yield child
        finally:
            child.__exit__(None, None, None)

    @contextlib.contextmanager
    def open_read(self, name):
        """Yield a pinned, seekable regular file without following its leaf."""
        self.check_file(name)
        if self.fd is not None:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self.fd)
        else:
            import msvcrt
            handle, close = _win_open(self._path(name))
            try:
                fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
            except BaseException:
                close(handle)
                raise
        with os.fdopen(fd, 'rb') as stream:
            _regular(os.fstat(stream.fileno()), name)
            yield stream

    def read_bytes(self, name):
        with self.open_read(name) as stream:
            return stream.read()

    def write_bytes(self, name, data, exclusive=False):
        old = self.check_file(name)
        if exclusive and old is not None:
            raise FileExistsError(name)
        # Private staging directory avoids reopening an attacker-controlled temp
        # name and isolates the staged file from other directory collaborators.
        staging = '.vts-' + secrets.token_hex(16)
        if self.fd is not None:
            os.mkdir(staging, 0o700, dir_fd=self.fd)
        else:
            os.mkdir(self._path(staging), 0o700)
        failure = None
        try:
            with self.child(staging) as stage:
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
                fd = os.open('content', flags, 0o666, dir_fd=stage.fd) if stage.fd is not None else os.open(stage._path('content'), flags | os.O_BINARY, 0o666)
                try:
                    with os.fdopen(fd, 'wb') as stream:
                        stream.write(data)
                        stream.flush()
                        os.fsync(stream.fileno())
                        if old is not None and os.name != 'nt':
                            os.fchmod(stream.fileno(), stat.S_IMODE(old.st_mode) & 0o777)
                    def publish_content():
                        # Recheck the destination on every attempt. The rename
                        # itself still enforces exclusive publication atomically.
                        self.check_file(name)
                        if self.fd is not None:
                            if exclusive:
                                _publish_exclusive(stage.fd, self.fd, name)
                            else:
                                os.replace('content', name, src_dir_fd=stage.fd, dst_dir_fd=self.fd)
                        elif exclusive:
                            os.rename(stage._path('content'), self._path(name))
                        else:
                            os.replace(stage._path('content'), self._path(name))
                    _retry_sharing_violation(publish_content)
                except BaseException as error:
                    failure = error
                    raise
                finally:
                    try:
                        if stage.fd is not None:
                            _retry_sharing_violation(lambda: os.unlink('content', dir_fd=stage.fd))
                        else:
                            _retry_sharing_violation(lambda: os.unlink(stage._path('content')))
                    except FileNotFoundError:
                        pass
                    except OSError:
                        if failure is None:
                            raise
                        failure.staging_path = Path(stage.path)
        except BaseException as error:
            failure = error
            raise
        finally:
            try:
                if self.fd is not None:
                    _retry_sharing_violation(lambda: os.rmdir(staging, dir_fd=self.fd))
                else:
                    _retry_sharing_violation(lambda: os.rmdir(self._path(staging)))
            except OSError as cleanup_error:
                retained_error = failure if failure is not None else cleanup_error
                retained_error.staging_path = Path(self._path(staging))
                if hasattr(retained_error, 'add_note'):
                    retained_error.add_note(f'未清理暫存：{retained_error.staging_path}（{cleanup_error}）')
                if failure is None:
                    raise


def atomic_write_text(path, text):
    path = os.path.abspath(path)
    with SafeDirectory(os.path.dirname(path)) as directory:
        directory.write_bytes(os.path.basename(path), text.encode('utf-8'))


class ExportCancelled(InterruptedError):
    pass


def _identity(info):
    return (info.st_dev, info.st_ino) if info is not None else None


def _win_rename_directory(handle, destination):
    """Rename the open object, never replace an existing destination."""
    import ctypes
    from ctypes import wintypes
    class RenameInfo(ctypes.Structure):
        _fields_ = [('ReplaceIfExists', wintypes.BOOLEAN),
                    ('RootDirectory', wintypes.HANDLE),
                    ('FileNameLength', wintypes.DWORD),
                    ('FileName', wintypes.WCHAR * 1)]
    encoded = os.path.abspath(destination).encode('utf-16-le')
    # SetFileInformationByHandle expects a NUL-terminated WCHAR path even
    # though FileNameLength excludes that terminator. Without spare zeroed
    # storage Windows can rename to trailing heap garbage instead of the path.
    size = max(ctypes.sizeof(RenameInfo), RenameInfo.FileName.offset + len(encoded) + ctypes.sizeof(wintypes.WCHAR))
    buffer = ctypes.create_string_buffer(size)
    info = RenameInfo.from_buffer(buffer)
    info.ReplaceIfExists = False
    info.FileNameLength = len(encoded)
    ctypes.memmove(ctypes.addressof(buffer) + RenameInfo.FileName.offset, encoded, len(encoded))
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    setter = kernel.SetFileInformationByHandle
    setter.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    setter.restype = wintypes.BOOL
    if not setter(handle, 3, buffer, size):
        raise ctypes.WinError(ctypes.get_last_error())


class StagedDirectory:
    """One private export transaction. Nonempty failed staging is retained safely.

    Caller retains the open parent until exit. No crashed/previous transaction is
    recovered implicitly. Successful publication is irreversible by this object.
    """
    def __init__(self, parent):
        self.parent = parent
        self.name = '.vts-export-' + secrets.token_hex(16)
        self.directory = None
        self._owned = {}
        self._directories = {}
        self._published = False

    def __enter__(self):
        parent = self.parent
        if parent.fd is not None:
            os.mkdir(self.name, 0o700, dir_fd=parent.fd)
        else:
            os.mkdir(parent._path(self.name), 0o700)
        self._root_identity = _identity(parent.info(self.name))
        directory = object.__new__(SafeDirectory)
        directory.path = parent._path(self.name)
        directory.fd, directory.handles = None, []
        try:
            if parent.fd is not None:
                directory.fd = os.open(self.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                       dir_fd=parent.fd)
                if _identity(os.fstat(directory.fd)) != self._root_identity:
                    raise UnsafePathError('暫存資料夾已變更')
            else:
                directory.handles.append(_win_open(directory.path, directory=True, rename_access=True))
            self.directory = directory
            self._check_root()
            return self
        except BaseException as error:
            directory.__exit__(None, None, None)
            error.staging_path = Path(directory.path)
            raise

    def _check_root(self):
        info = self.parent.info(self.name)
        if _identity(info) != self._root_identity:
            raise UnsafePathError('暫存資料夾已變更')
        _regular(info, self.name, directory=True)

    def copy_from(self, source, name, *, progress, cancelled):
        if self._published:
            raise RuntimeError('資料包已發布')
        directory = self.directory
        directory._name(name)
        before = os.fstat(source.fileno())
        _regular(before, name)
        if cancelled():
            raise ExportCancelled('已取消匯出')
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
        fd = (os.open(name, flags, 0o600, dir_fd=directory.fd) if directory.fd is not None
              else os.open(directory._path(name), flags | os.O_BINARY, 0o600))
        self._owned[name] = _identity(os.fstat(fd))
        count = 0
        with os.fdopen(fd, 'wb') as output:
            while True:
                if cancelled():
                    raise ExportCancelled('已取消匯出')
                chunk = source.read(4 * 1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                count += len(chunk)
                progress(count)
                # Bound a concurrently growing source instead of reading forever.
                if count > before.st_size:
                    raise OSError('來源檔案在複製期間變更')
            output.flush()
            os.fsync(output.fileno())
        after = os.fstat(source.fileno())
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or count != before.st_size:
            raise OSError('來源檔案在複製期間變更')
        return count

    @contextlib.contextmanager
    def _relative_parent(self, name, create=False):
        parts = name.split('/')
        for part in parts:
            self.directory._name(part)
        with contextlib.ExitStack() as stack:
            current = self.directory
            for index, part in enumerate(parts[:-1]):
                key = '/'.join(parts[:index + 1])
                if create and key not in self._directories:
                    if current.fd is not None:
                        os.mkdir(part, 0o700, dir_fd=current.fd)
                    else:
                        os.mkdir(current._path(part), 0o700)
                    self._directories[key] = _identity(current.info(part))
                if key not in self._directories or _identity(current.info(part)) != self._directories[key]:
                    raise UnsafePathError('暫存子資料夾已变更')
                current = stack.enter_context(current.child(part))
            yield current, parts[-1]

    def write_bytes(self, name, data):
        if self._published:
            raise RuntimeError('資料包已發布')
        with self._relative_parent(name, create=True) as (parent, leaf):
            parent.write_bytes(leaf, data, exclusive=True)
            self._owned[name] = _identity(parent.info(leaf))

    def publish(self, name):
        if self._published:
            raise RuntimeError('資料包已發布')
        self.parent._name(name)
        self._check_root()
        if self.parent.fd is None:
            _win_rename_directory(self.directory.handles[0][0], self.parent._path(name))
        else:
            import ctypes
            libc = ctypes.CDLL(None, use_errno=True)
            if sys.platform == 'darwin':
                rename, flag = libc.renameatx_np, 4
            elif sys.platform.startswith('linux') and hasattr(libc, 'renameat2'):
                rename, flag = libc.renameat2, 1
            else:
                raise OSError('此平台不支援安全排他發布')
            rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                               ctypes.c_char_p, ctypes.c_uint]
            rename.restype = ctypes.c_int
            if rename(self.parent.fd, os.fsencode(self.name), self.parent.fd, os.fsencode(name), flag):
                error = ctypes.get_errno()
                raise OSError(error, os.strerror(error), name)
        self._published = True
        return Path(self.parent._path(name))

    def __exit__(self, kind, error, traceback):
        try:
            if not self._published:
                self._check_root()
                # No portable unlink-by-open-handle primitive proves the identity
                # through deletion on every supported OS. A same-user actor can
                # exchange a checked name immediately before unlink. Fail closed:
                # retain nonempty failed packages and report their exact location.
                # rmdir below can only remove an empty directory, never its contents.
                if self._owned or self._directories or self.directory.names():
                    raise UnsafePathError('無法原子確認刪除對象，已保留未完成資料包')
                self.directory.__exit__(None, None, None)
                self._check_root()
                if self.parent.fd is not None:
                    os.rmdir(self.name, dir_fd=self.parent.fd)
                else:
                    os.rmdir(self.parent._path(self.name))
        except OSError as cleanup_error:
            failure = error if error is not None else cleanup_error
            failure.staging_path = Path(self.parent._path(self.name))
            failure.add_note(f'未清理暫存：{failure.staging_path}（{cleanup_error}）')
            if error is None:
                raise
        finally:
            if self.directory is not None:
                self.directory.__exit__(None, None, None)
