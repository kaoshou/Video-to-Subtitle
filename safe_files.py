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


class UnsafePathError(OSError):
    pass


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


def _win_open(path, directory=False):
    """Open the entry itself, not its reparse target; hold it against renames."""
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                       wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    # No FILE_SHARE_DELETE: prevents replacing the opened directory/file.
    handle = create(path, 0x80000000, 3 if directory else 1, None, 3,
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

    def read_bytes(self, name):
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
                finally:
                    try:
                        if stage.fd is not None:
                            os.unlink('content', dir_fd=stage.fd)
                        else:
                            os.unlink(stage._path('content'))
                    except FileNotFoundError:
                        pass
        finally:
            if self.fd is not None:
                os.rmdir(staging, dir_fd=self.fd)
            else:
                os.rmdir(self._path(staging))


def atomic_write_text(path, text):
    path = os.path.abspath(path)
    with SafeDirectory(os.path.dirname(path)) as directory:
        directory.write_bytes(os.path.basename(path), text.encode('utf-8'))
