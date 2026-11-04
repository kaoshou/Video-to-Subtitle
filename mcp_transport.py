"""Owner-private, bounded JSON IPC between thin MCP bridges and one job owner.

No pickle, network listener, GUI, SDK or inference backend is imported here.
Each connection carries one authenticated request; disconnecting cannot cancel
an admitted job. Only local launchers supply backend argv, never tool clients.
"""
import contextlib
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import socket
import stat
import struct
import subprocess
import sys
import threading
import time

from mcp_state import (MCPError, ProcessLock, State, _private_directory,
                       _read_json, _write_json, _encode)
from mcp_contracts import TOOL_SCHEMAS, _validate

MAX_FRAME = 1024 * 1024
FRAME_TIMEOUT = 2.0
CALL_TIMEOUT = 60.0
START_TIMEOUT = 12.0
PROBE_TIMEOUT = 20.0
MAX_CLIENTS = 16


def Service(*args, **kwargs):
    """Compatibility factory; backend imports occur only when a broker serves."""
    from mcp_service import Service as BackendService
    return BackendService(*args, **kwargs)


def _json(data):
    if not isinstance(data, bytes) or len(data) > MAX_FRAME:
        raise MCPError('INVALID_FRAME', 'IPC frame exceeds its limit.')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate key')
            result[key] = value
        return result
    def nonfinite(value):
        raise ValueError('nonfinite number')
    try:
        value = json.loads(data.decode('utf-8'), object_pairs_hook=unique, parse_constant=nonfinite)
        if not isinstance(value, dict):
            raise ValueError('object required')
        return value
    except (ValueError, UnicodeError, RecursionError) as error:
        raise MCPError('INVALID_FRAME', 'Invalid IPC JSON object.') from error


def _bytes(value):
    try:
        data = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
        if len(data) > MAX_FRAME:
            raise ValueError('oversize')
        return data
    except (ValueError, TypeError, RecursionError) as error:
        raise MCPError('INVALID_FRAME', 'IPC JSON exceeds its limits.') from error


def _runtime(state, create=False):
    """State-pinned secret; short private POSIX address avoids sun_path limits."""
    with _private_directory(state.path / 'runtime', create=create) as directory:
        try:
            value = _read_json(directory, 'secret.json', 512)
        except FileNotFoundError:
            if not create:
                raise
            value = {'token': secrets.token_hex(32)}
            _write_json(directory, 'secret.json', _encode(value, 512))
    token = value.get('token')
    if not isinstance(token, str) or len(token) != 64 or any(c not in '0123456789abcdef' for c in token):
        raise MCPError('PRIVATE_STORAGE', 'Invalid runtime authentication record.')
    key = hashlib.sha256((str(state.path) + token).encode()).hexdigest()[:32]
    if os.name == 'nt':
        return token, r'\\.\pipe\VideoToSubtitle-' + key
    parent = Path('/private/tmp' if sys.platform == 'darwin' else '/tmp') / ('vts-mcp-' + str(os.getuid()))
    with _private_directory(parent, create=create):
        pass
    return token, str(parent / (key + '.sock'))


class _SocketChannel:
    def __init__(self, sock):
        self.socket = sock
        sock.settimeout(FRAME_TIMEOUT)

    def send_bytes(self, data):
        if len(data) > MAX_FRAME:
            raise ValueError('oversize frame')
        self.socket.sendall(struct.pack('!I', len(data)) + data)

    def recv_bytes(self, maximum=MAX_FRAME, timeout=FRAME_TIMEOUT):
        deadline = time.monotonic() + timeout
        def exact(count):
            data = bytearray()
            while len(data) < count:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('frame deadline')
                self.socket.settimeout(remaining)
                chunk = self.socket.recv(count - len(data))
                if not chunk:
                    raise EOFError('closed frame')
                data.extend(chunk)
            return bytes(data)
        length, = struct.unpack('!I', exact(4))
        if length > maximum:
            raise ValueError('oversize frame')
        return exact(length)

    def close(self):
        self.socket.close()


def _private_pipe_handle(address, first):
    """Create a local-only overlapped pipe with explicit current-user DACL.

    Native descriptor is supplied to CreateNamedPipeW, before visibility.
    Handles are owned by PipeConnection after accept, otherwise by listener.
    """
    import ctypes
    from ctypes import wintypes as w
    pointer = ctypes.c_void_p
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    adv = ctypes.WinDLL('advapi32', use_last_error=True)
    class SA(ctypes.Structure):
        _fields_ = [('length', w.DWORD), ('descriptor', pointer), ('inherit', w.BOOL)]
    kernel.GetCurrentProcess.argtypes = []
    kernel.GetCurrentProcess.restype = w.HANDLE
    kernel.CloseHandle.argtypes, kernel.CloseHandle.restype = [w.HANDLE], w.BOOL
    kernel.LocalFree.argtypes, kernel.LocalFree.restype = [pointer], pointer
    kernel.CreateNamedPipeW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, w.DWORD,
                                        w.DWORD, w.DWORD, w.DWORD, ctypes.POINTER(SA)]
    kernel.CreateNamedPipeW.restype = w.HANDLE
    adv.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE)]
    adv.OpenProcessToken.restype = w.BOOL
    adv.GetTokenInformation.argtypes = [w.HANDLE, ctypes.c_int, pointer, w.DWORD, ctypes.POINTER(w.DWORD)]
    adv.GetTokenInformation.restype = w.BOOL
    adv.ConvertSidToStringSidW.argtypes = [pointer, ctypes.POINTER(w.LPWSTR)]
    adv.ConvertSidToStringSidW.restype = w.BOOL
    adv.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [w.LPCWSTR, w.DWORD, ctypes.POINTER(pointer), pointer]
    adv.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = w.BOOL
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
            f'D:P(A;;GA;;;{sid_text.value})', 1, ctypes.byref(descriptor), None))
        attributes = SA(ctypes.sizeof(SA), descriptor, False)
        flags = 3 | 0x40000000 | (0x00080000 if first else 0)  # DUPLEX, OVERLAPPED, FIRST
        # At saturation: active handlers + overflow awaiting broker rejection +
        # replacement listener. Recovery also briefly holds old/new listeners.
        handle = kernel.CreateNamedPipeW(address, flags, 4 | 2 | 8,  # MESSAGE, READMODE, REJECT_REMOTE
                                         MAX_CLIENTS + 2, 65536, 65536, 0, ctypes.byref(attributes))
        if handle == w.HANDLE(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        return handle
    finally:
        if descriptor:
            kernel.LocalFree(descriptor)
        if sid_text:
            kernel.LocalFree(ctypes.cast(sid_text, pointer))
        kernel.CloseHandle(token)


class _PipeChannel:
    def __init__(self, connection):
        self.connection = connection

    @contextlib.contextmanager
    def _deadline(self, timeout):
        import ctypes
        from ctypes import wintypes as w
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CancelIoEx.argtypes = [w.HANDLE, ctypes.c_void_p]
        kernel.CancelIoEx.restype = w.BOOL
        done = threading.Event()
        handle = self.connection.fileno()
        def cancel_late_io():
            if done.wait(timeout):
                return
            # Repeat after expiry to cover poll/read and write-scheduling races.
            while not done.is_set():
                kernel.CancelIoEx(handle, None)
                done.wait(.01)
        timer = threading.Thread(target=cancel_late_io, daemon=True)
        timer.start()
        try:
            yield
        finally:
            done.set()
            timer.join()

    def send_bytes(self, data):
        if len(data) > MAX_FRAME:
            raise ValueError('oversize frame')
        with self._deadline(FRAME_TIMEOUT):
            self.connection.send_bytes(data)

    def recv_bytes(self, maximum=MAX_FRAME, timeout=FRAME_TIMEOUT):
        with self._deadline(timeout):
            if not self.connection.poll(timeout):
                raise TimeoutError('frame deadline')
            return self.connection.recv_bytes(maxlength=maximum)

    def close(self):
        self.connection.close()


class _WindowsListener:
    def __init__(self, address):
        self.address, self.handle, self.pending = address, None, None
        self._next(True)

    def _next(self, first=False):
        import _winapi
        handle = _private_pipe_handle(self.address, first)
        try:
            pending = _winapi.ConnectNamedPipe(handle, overlapped=True)
        except OSError as error:
            if error.winerror != _winapi.ERROR_NO_DATA:
                _winapi.CloseHandle(handle)
                raise
            # A client may disconnect between creation and ConnectNamedPipe.
            # Retain this instance as namespace owner until its replacement is
            # created, even if every previously accepted client also closes.
            pending = None
        except BaseException:
            _winapi.CloseHandle(handle)
            raise
        previous = self.handle
        self.handle, self.pending = handle, pending
        if previous is not None:
            _winapi.CloseHandle(previous)

    def accept(self):
        import _winapi
        from multiprocessing.connection import PipeConnection
        if self.pending is None:
            self._next()
            if self.pending is None:
                raise TimeoutError()
        if _winapi.WaitForMultipleObjects([self.pending.event], False, 100) == 258:
            raise TimeoutError()
        _, error = self.pending.GetOverlappedResult(True)
        if error in (_winapi.ERROR_NO_DATA, _winapi.ERROR_BROKEN_PIPE):
            self.pending = None  # keep namespace ownership during replacement
            raise TimeoutError()
        if error:
            raise OSError(error, 'Pipe connection failed')
        connection = PipeConnection(self.handle)
        self.handle, self.pending = None, None
        try:
            self._next()
        except BaseException:
            connection.close()
            raise
        return _PipeChannel(connection)

    def close(self):
        import _winapi
        if self.handle is not None:
            try:
                if self.pending is not None:
                    self.pending.cancel()
                    self.pending.GetOverlappedResult(True)
            finally:
                _winapi.CloseHandle(self.handle)
                self.handle, self.pending = None, None


def _connect(address):
    if os.name == 'nt':
        import _winapi
        from multiprocessing.connection import PipeConnection
        _winapi.WaitNamedPipe(address, int(FRAME_TIMEOUT * 1000))
        handle = _winapi.CreateFile(address, _winapi.GENERIC_READ | _winapi.GENERIC_WRITE,
                                    0, 0, _winapi.OPEN_EXISTING, _winapi.FILE_FLAG_OVERLAPPED, 0)
        try:
            _winapi.SetNamedPipeHandleState(handle, _winapi.PIPE_READMODE_MESSAGE, None, None)
            return _PipeChannel(PipeConnection(handle))
        except BaseException:
            _winapi.CloseHandle(handle)
            raise
    sock = socket.socket(socket.AF_UNIX)
    sock.settimeout(FRAME_TIMEOUT)
    try:
        sock.connect(address)
        return _SocketChannel(sock)
    except BaseException:
        sock.close()
        raise


class Broker:
    def __init__(self, state, *, idle_timeout=300):
        self.state = state
        self.idle_timeout = idle_timeout
        self.identity = secrets.token_hex(16)

    def serve(self, stop_event=None):
        """Return False when another broker owns the process lock; join on stop."""
        stop_event = stop_event or threading.Event()
        lock = ProcessLock(self.state.path / 'locks', 'broker')
        if not lock.acquire():
            return False
        listener = service = None
        clients, guard = set(), threading.Lock()
        last_activity = [time.monotonic()]
        address = None
        try:
            token, address = _runtime(self.state, create=True)
            service = Service(self.state)
            if os.name == 'nt':
                listener = _WindowsListener(address)
            else:
                # Only the broker-lock holder removes a stale socket, never an arbitrary leaf.
                try:
                    info = os.lstat(address)
                except FileNotFoundError:
                    pass
                else:
                    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
                        raise MCPError('PRIVATE_STORAGE', 'Unsafe IPC endpoint.')
                    os.unlink(address)
                listener = socket.socket(socket.AF_UNIX)
                listener.bind(address)
                os.chmod(address, 0o600)
                listener.listen(MAX_CLIENTS)
                listener.settimeout(.1)

            def handle(channel):
                try:
                    request = _json(channel.recv_bytes())
                    supplied = request.pop('token', None)
                    if (not isinstance(supplied, str) or not supplied.isascii()
                            or not hmac.compare_digest(supplied, token)):
                        return
                    if request == {'op': 'hello'}:
                        response = {'ok': True, 'result': {'version': 1, 'broker_id': self.identity}}
                    elif (set(request) == {'op', 'name', 'arguments'} and request['op'] == 'call'
                          and isinstance(request['name'], str) and isinstance(request['arguments'], dict)):
                        try:
                            response = {'ok': True, 'result': service.call(request['name'], request['arguments'])}
                        except MCPError as error:
                            response = {'ok': False, 'error': {'code': error.code, 'message': str(error)[:512]}}
                        except Exception:
                            response = {'ok': False, 'error': {'code': 'SERVICE_ERROR', 'message': 'Local operation failed.'}}
                    else:
                        return
                    channel.send_bytes(_bytes(response))
                except (OSError, EOFError, ValueError, MCPError):
                    pass
                finally:
                    channel.close()
                    with guard:
                        clients.discard(threading.current_thread())
                        last_activity[0] = time.monotonic()

            while not stop_event.is_set():
                with guard:
                    quiescent = not clients
                    idle = quiescent and time.monotonic() - last_activity[0] >= self.idle_timeout
                if quiescent and not service.busy and (idle or not self.state.policy()['enabled']):
                    break
                try:
                    if os.name == 'nt':
                        channel = listener.accept()
                    else:
                        sock, _ = listener.accept()
                        channel = _SocketChannel(sock)
                except TimeoutError:
                    continue
                with guard:
                    if len(clients) >= MAX_CLIENTS:
                        channel.close()
                        continue
                    thread = threading.Thread(target=handle, args=(channel,), daemon=True)
                    clients.add(thread)
                    thread.start()
            return True
        finally:
            if listener is not None:
                listener.close()
            with guard:
                running = list(clients)
            for thread in running:
                thread.join()  # accepted calls finish before closing their Service
            if service is not None:
                service.close()  # joins inference children before releasing locks
            if address is not None and os.name != 'nt' and listener is not None:
                with contextlib.suppress(FileNotFoundError):
                    os.unlink(address)
            lock.release()


def backend_command(state, command=None):
    """Absolute local-admin argv prefix, followed by --mcp-broker at spawn."""
    from_policy = command is None
    if command is None:
        command = state.policy().get('options', {}).get('backend_command')
    if from_policy and getattr(sys, 'frozen', False):
        # A standalone bridge has no backend of its own. Never recursively
        # launch it, or discover a replacement through PATH/cwd.
        if (command is None or not isinstance(command, (list, tuple)) or not command
                or not isinstance(command[0], str) or not Path(command[0]).is_file()
                or Path(command[0]).name in ('VideoToSubtitleMCP', 'VideoToSubtitleMCP.exe')):
            raise MCPError('BACKEND_REPAIR_REQUIRED',
                           'Open Video to Subtitle and repair/re-enable MCP; the configured backend is missing.')
    if command is None:
        command = ([sys.executable] if getattr(sys, 'frozen', False) else
                   [sys.executable, str(Path(__file__).resolve().with_name('app_entry.py'))])
    if (not isinstance(command, (list, tuple)) or not 1 <= len(command) <= 64
            or any(not isinstance(arg, str) or not arg or '\x00' in arg or len(arg) > 4096 for arg in command)
            or not Path(command[0]).is_absolute() or not Path(command[0]).is_file()):
        raise MCPError('INVALID_COMMAND', 'A valid absolute backend executable is required.')
    if any(arg in ('--state-dir', '--broker', '--mcp-broker', '--self-test') for arg in command):
        raise MCPError('INVALID_COMMAND', 'Backend command must be an executable prefix.')
    # Python launchers must use an absolute script; never search cwd or PYTHONPATH.
    if any((arg.endswith('.py') and not Path(arg).is_absolute()) or arg in ('-c', '-m')
           for arg in command[1:]):
        raise MCPError('INVALID_COMMAND', 'Backend Python entry must be an absolute script.')
    return list(command)


@contextlib.contextmanager
def _launch_guard(state, deadline):
    lock = ProcessLock(state.path / 'locks', 'broker-launch')
    try:
        while not lock.acquire():
            if time.monotonic() >= deadline:
                raise MCPError('BROKER_UNAVAILABLE', 'Timed out waiting for local broker startup.')
            time.sleep(.05)
        if time.monotonic() >= deadline:
            raise MCPError('BROKER_UNAVAILABLE', 'Local broker startup deadline expired.')
        yield
    finally:
        lock.release()


class BrokerClient:
    def __init__(self, state, command=None, *, autostart=True):
        self.state, self.command, self.autostart = state, command, autostart
        self.address = None

    def _exchange(self, request, timeout=CALL_TIMEOUT):
        token, self.address = _runtime(self.state)
        with contextlib.closing(_connect(self.address)) as channel:
            channel.send_bytes(_bytes(dict(request, token=token)))
            reply = _json(channel.recv_bytes(timeout=timeout))
        if reply.get('ok') is True and set(reply) == {'ok', 'result'} and isinstance(reply['result'], dict):
            return reply['result']
        if reply.get('ok') is False and set(reply) == {'ok', 'error'}:
            error = reply['error']
            if isinstance(error, dict) and isinstance(error.get('code'), str) and isinstance(error.get('message'), str):
                raise MCPError(error['code'][:64], error['message'][:512])
        raise MCPError('INVALID_FRAME', 'Invalid broker response.')

    def handshake(self):
        return self._exchange({'op': 'hello'}, timeout=FRAME_TIMEOUT)

    def _ensure(self):
        deadline = time.monotonic() + START_TIMEOUT
        try:
            self.handshake()
            return
        except (OSError, EOFError):
            if not self.autostart:
                raise
        if not self.state.policy()['enabled']:
            raise MCPError('MCP_DISABLED', 'Local MCP access is disabled.')
        command = backend_command(self.state, self.command)
        with _launch_guard(self.state, deadline):
            try:
                self.handshake()
                return
            except (OSError, EOFError):
                pass
            if not self.state.policy()['enabled']:
                raise MCPError('MCP_DISABLED', 'Local MCP access is disabled.')
            options = {'stdin': subprocess.DEVNULL, 'stdout': subprocess.DEVNULL,
                       'stderr': subprocess.DEVNULL, 'cwd': str(Path(command[0]).parent), 'close_fds': True}
            if os.name == 'nt':
                options['creationflags'] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
            else:
                options['start_new_session'] = True
            process = subprocess.Popen(command + ['--mcp-broker', '--state-dir', str(self.state.path)], **options)
            threading.Thread(target=process.wait, daemon=True).start()
            while time.monotonic() < deadline:
                try:
                    self.handshake()
                    return
                except (OSError, EOFError):
                    if process.poll() is not None:
                        break
                    time.sleep(.05)
            raise MCPError('BROKER_UNAVAILABLE', 'Local broker did not become ready.')

    def call(self, name, arguments):
        if not isinstance(name, str) or name not in TOOL_SCHEMAS:
            raise MCPError('UNKNOWN_TOOL', 'Unknown local tool.')
        _validate(arguments, TOOL_SCHEMAS[name])
        try:
            self._ensure()
        except MCPError as error:
            if error.code == 'MCP_DISABLED' and name in ('get_job', 'cancel_job'):
                key = arguments['job_id']
                if name == 'cancel_job':
                    return self.state.cancel_job(key)
                job = self.state.get('jobs', key)
                # Never expose result paths/subtitle content from offline control.
                return {'job_id': key, **{k: job[k] for k in ('state', 'stage', 'error') if k in job}}
            if error.code == 'MCP_DISABLED' and name == 'get_status':
                policy = self.state.policy()
                return {'version': 1, 'enabled': False,
                        'roots': [{'id': root['id'], 'label': root['label']} for root in policy['roots']],
                        'jobs': [{'job_id': job['id'], 'state': job['state']} for job in self.state.records('jobs')]}
            raise
        # Never retry a call after bytes may have reached the broker.
        try:
            return self._exchange({'op': 'call', 'name': name, 'arguments': arguments})
        except (OSError, EOFError) as error:
            raise MCPError('BROKER_UNAVAILABLE', 'Connection lost; poll or reuse the same request ID.') from error


def probe_connection(state_path, command=None):
    """Probe full STDIO argv through SDK ClientSession, without changing policy.

    ``command`` is the complete STDIO entry prefix (normally app_entry --mcp),
    unlike BrokerClient's backend prefix. This synchronous helper belongs on a
    GUI worker thread. Success does not claim a named external AI is connected.
    """
    import asyncio
    try:
        if not Path(state_path).is_absolute():
            raise MCPError('INVALID_COMMAND', 'State directory must be absolute.')
        state = State(state_path)
        if command is None:
            command = backend_command(state) + ['--mcp']
        else:
            if isinstance(command, (list, tuple)) and '--state-dir' in command:
                command = list(command)
                index = command.index('--state-dir')
                if (command.count('--state-dir') != 1 or index + 1 >= len(command)
                        or command[index + 1] != str(state.path)):
                    raise MCPError('INVALID_COMMAND', 'Probe state directory does not match launcher.')
                del command[index:index + 2]
            # Validate argv without invoking policy's backend-command selection.
            command = backend_command(state, command)
        return asyncio.run(_probe_stdio(state.path, command))
    except MCPError as error:
        return {'connected': False, 'error': {'code': error.code, 'message': str(error)[:512]}}
    except ImportError:
        return {'connected': False, 'error': {'code': 'MCP_UNAVAILABLE', 'message': 'Optional MCP dependency unavailable.'}}
    except Exception:
        return {'connected': False, 'error': {'code': 'PROBE_FAILED', 'message': 'STDIO protocol probe failed or timed out.'}}


async def _probe_stdio(state_path, command):
    """SDK session over bounded streams; cleanup targets only our thin process.

    We intentionally own the subprocess lifecycle: the SDK stdio convenience
    transport can terminate a Windows process tree, which could include the
    detached broker. Never terminate that broker or an inference child here.
    """
    import asyncio
    import anyio
    from mcp import ClientSession
    from mcp.types import JSONRPCMessage
    from mcp.shared.message import SessionMessage
    process = await asyncio.create_subprocess_exec(
        *command, '--state-dir', str(state_path), stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        cwd=str(Path(command[0]).parent), limit=2 * MAX_FRAME + 65536)
    incoming, read = anyio.create_memory_object_stream(0)
    write, outgoing = anyio.create_memory_object_stream(0)
    async def receive():
        async with incoming:
            while line := await process.stdout.readline():
                await incoming.send(SessionMessage(JSONRPCMessage.model_validate_json(line)))
    async def send():
        async with outgoing:
            async for message in outgoing:
                process.stdin.write((message.message.model_dump_json(by_alias=True, exclude_none=True) + '\n').encode())
                await process.stdin.drain()
    try:
        with anyio.fail_after(PROBE_TIMEOUT):
            async with anyio.create_task_group() as group:
                group.start_soon(receive)
                group.start_soon(send)
                async with ClientSession(read, write) as session:
                    initialized = await session.initialize()
                    await session.send_ping()
                    tools = await session.list_tools()
                    if {tool.name for tool in tools.tools} != set(TOOL_SCHEMAS):
                        raise MCPError('PROBE_FAILED', 'Unexpected MCP tool contract.')
                    result = await session.call_tool('get_status', {})
                    if result.isError or not isinstance(result.structuredContent, dict):
                        raise MCPError('PROBE_FAILED', 'MCP status failed.')
                    report = {'connected': True, 'protocol_version': initialized.protocolVersion,
                              'status': result.structuredContent}
                group.cancel_scope.cancel()
            return report
    finally:
        process.stdin.close()
        try:
            await asyncio.wait_for(process.wait(), .5)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                process.terminate()  # one exact probe process, never process group/tree
            try:
                await asyncio.wait_for(process.wait(), .5)
            except TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    process.kill()
                await process.wait()
        await read.aclose()
        await write.aclose()
