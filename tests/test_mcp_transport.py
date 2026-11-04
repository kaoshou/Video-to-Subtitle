"""Real broker/bridge contracts; no models, user state or host configuration."""
import importlib.util
import contextlib
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from mcp_state import State

ROOT = Path(__file__).resolve().parents[1]
SDK = importlib.util.find_spec('mcp') is not None


class _NativePipeContract:
    """Windows API boundary model: first-instance exclusivity and hard capacity.

    Runs the real descriptor/creation/listener code; only OS calls and the native
    Connection wrapper are replaced. Handles remain live until explicitly closed.
    """
    ERROR_NO_DATA, ERROR_BROKEN_PIPE = 232, 109

    def __init__(self):
        from types import SimpleNamespace
        self.live, self.pending = set(), {}
        self.next_id, self.last_error = 100, 0
        self.connect_error = None
        self.namespace_gaps = 0
        self.limit = None
        self.sids = []
        self.kernel = SimpleNamespace()
        self.adv = SimpleNamespace()
        # Plain functions accept the ctypes signature attributes production sets.
        def bind(target, name, function):
            setattr(target, name, lambda *args: function(*args))
        bind(self.kernel, 'GetCurrentProcess', lambda: 1)
        bind(self.kernel, 'CloseHandle', self.CloseHandle)
        bind(self.kernel, 'LocalFree', lambda pointer: None)
        bind(self.kernel, 'CreateNamedPipeW', self.create_pipe)
        bind(self.adv, 'OpenProcessToken', self.open_token)
        bind(self.adv, 'GetTokenInformation', self.token_information)
        bind(self.adv, 'ConvertSidToStringSidW', self.sid_string)
        bind(self.adv, 'ConvertStringSecurityDescriptorToSecurityDescriptorW', self.descriptor)

    def open_token(self, process, access, output):
        import ctypes
        from ctypes import wintypes as w
        ctypes.cast(output, ctypes.POINTER(w.HANDLE))[0] = 99
        return True

    def token_information(self, token, kind, buffer, count, size):
        import ctypes
        from ctypes import wintypes as w
        ctypes.cast(size, ctypes.POINTER(w.DWORD))[0] = ctypes.sizeof(ctypes.c_void_p)
        if buffer is not None:
            ctypes.c_void_p.from_buffer(buffer).value = 1
        return buffer is not None

    def sid_string(self, sid, output):
        import ctypes
        value = ctypes.c_wchar_p('S-1-5-21-1000')
        self.sids.append(value)
        ctypes.cast(output, ctypes.POINTER(ctypes.c_wchar_p))[0] = value
        return True

    def descriptor(self, text, revision, output, size):
        import ctypes
        ctypes.cast(output, ctypes.POINTER(ctypes.c_void_p))[0] = 2
        return True

    def create_pipe(self, address, flags, mode, limit, *args):
        import ctypes
        self.limit = limit
        if flags & 0x00080000 and self.live:
            self.last_error = 5  # FIRST_PIPE_INSTANCE cannot coexist with earlier handles
            return ctypes.c_void_p(-1).value
        if len(self.live) >= limit:
            self.last_error = 231  # every instance slot is in use
            return ctypes.c_void_p(-1).value
        self.next_id += 1
        self.live.add(self.next_id)
        return self.next_id

    def CloseHandle(self, handle):
        handle = getattr(handle, 'value', handle)
        if handle in self.live:
            self.live.remove(handle)
            if not self.live:
                self.namespace_gaps += 1
        return True

    def ConnectNamedPipe(self, handle, *, overlapped):
        from types import SimpleNamespace
        if self.connect_error is not None:
            code, self.connect_error = self.connect_error, None
            raise self.WinError(code)
        pending = SimpleNamespace(event=handle, error=0)
        pending.cancel = lambda: None
        pending.GetOverlappedResult = lambda wait: (0, pending.error)
        self.pending[handle] = pending
        return pending

    def WaitForMultipleObjects(self, events, wait_all, timeout):
        return 0

    def WinError(self, code):
        error = OSError(code, 'modeled native pipe error')
        error.winerror = code
        return error

    def connection(self, handle):
        from types import SimpleNamespace
        return SimpleNamespace(close=lambda: self.CloseHandle(handle), fileno=lambda: handle)

    @contextlib.contextmanager
    def installed(self):
        import ctypes
        import multiprocessing.connection
        with mock.patch.dict(sys.modules, {'_winapi': self}), \
                mock.patch.object(ctypes, 'WinDLL', side_effect=lambda name, **kwargs:
                                  self.kernel if name == 'kernel32' else self.adv, create=True), \
                mock.patch.object(ctypes, 'get_last_error', side_effect=lambda: self.last_error, create=True), \
                mock.patch.object(ctypes, 'WinError', side_effect=self.WinError, create=True), \
                mock.patch.object(multiprocessing.connection, 'PipeConnection', side_effect=self.connection, create=True):
            yield


class WindowsListenerContractTests(unittest.TestCase):
    def test_early_disconnect_recovery_preserves_existing_channels_and_namespace(self):
        from mcp_transport import _WindowsListener
        for stage in ('connect', 'overlapped'):
            with self.subTest(stage=stage):
                native = _NativePipeContract()
                with native.installed():
                    listener = _WindowsListener('controlled-native-pipe')
                    channels = []
                    try:
                        if stage == 'connect':
                            native.connect_error = native.ERROR_NO_DATA
                            channels.append(listener.accept())
                        else:
                            channels.append(listener.accept())
                            native.pending[listener.handle].error = native.ERROR_BROKEN_PIPE
                            with self.assertRaises(TimeoutError):
                                listener.accept()
                        channels.append(listener.accept())
                        self.assertTrue(all(c.connection.fileno() in native.live for c in channels))
                        self.assertEqual(native.namespace_gaps, 0)
                    finally:
                        for channel in channels:
                            channel.close()
                        listener.close()
                    self.assertEqual(native.live, set())

    def test_recovery_keeps_namespace_when_last_client_closes(self):
        from mcp_transport import _WindowsListener
        native = _NativePipeContract()
        with native.installed():
            listener = _WindowsListener('controlled-native-pipe')
            native.connect_error = native.ERROR_NO_DATA
            channel = listener.accept()
            try:
                channel.close()
                self.assertEqual(native.namespace_gaps, 0)
                replacement = listener.accept()
                replacement.close()
            finally:
                listener.close()
            self.assertEqual(native.live, set())

    def test_saturation_can_reject_extra_channel_without_losing_live_work(self):
        from mcp_transport import _WindowsListener, MAX_CLIENTS
        native = _NativePipeContract()
        with native.installed():
            listener = _WindowsListener('controlled-native-pipe')
            channels = []
            try:
                for _ in range(MAX_CLIENTS):
                    channels.append(listener.accept())
                overflow = listener.accept()  # broker rejects only after listener returns
                overflow.close()
                self.assertTrue(all(c.connection.fileno() in native.live for c in channels))
                self.assertIn(listener.handle, native.live)
                self.assertEqual(native.namespace_gaps, 0)
                channels.pop().close()
                channels.append(listener.accept())
            finally:
                for channel in channels:
                    channel.close()
                listener.close()
            self.assertEqual(native.live, set())

    def test_first_instance_ownership_failure_is_not_suppressed(self):
        from mcp_transport import _WindowsListener
        native = _NativePipeContract()
        with native.installed():
            first = _WindowsListener('controlled-native-pipe')
            try:
                with self.assertRaises(OSError) as caught:
                    _WindowsListener('controlled-native-pipe')
                self.assertEqual(caught.exception.winerror, 5)
                self.assertIn(first.handle, native.live)
            finally:
                first.close()


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='vts-ipc-', dir='/private/tmp' if sys.platform == 'darwin' else None)
        self.addCleanup(self.temp.cleanup)
        self.state = State(Path(self.temp.name) / 'state')
        self.stop = threading.Event()

    def broker(self, **kwargs):
        from mcp_transport import Broker, BrokerClient
        # Live-broker fixtures must grant a temporary policy: disabled idle
        # brokers now quiesce immediately so maintenance does not wait 5 min.
        if not self.state.policy()['enabled']:
            self.state.configure(True, [])
        broker = Broker(self.state, idle_timeout=30, **kwargs)
        thread = threading.Thread(target=broker.serve, args=(self.stop,), daemon=True)
        thread.start()
        def close():
            self.stop.set()
            thread.join(8)
            self.assertFalse(thread.is_alive(), 'Broker shutdown must join work and clients')
        self.addCleanup(close)
        client = BrokerClient(self.state, autostart=False)
        deadline = time.monotonic() + 5
        while True:
            try:
                # Probe transport readiness without coupling every broker test
                # to the host's model-cache state or native ML dependencies.
                client.handshake()
                return broker, client
            except Exception:
                if time.monotonic() > deadline:
                    raise
                time.sleep(.02)

    def test_disabled_status_and_structured_denial(self):
        from mcp_state import MCPError
        from mcp_transport import BrokerClient
        client = BrokerClient(self.state)
        self.assertFalse(client.call('get_status', {})['enabled'])
        with self.assertRaises(MCPError) as caught:
            client.call('list_media', {'root_id': 'missing'})
        self.assertEqual(caught.exception.code, 'MCP_DISABLED')
        with self.assertRaises(MCPError) as caught:
            client.call('configure', {'enabled': True})
        self.assertEqual(caught.exception.code, 'UNKNOWN_TOOL')
        self.assertFalse(self.state.policy()['enabled'])
        self.assertFalse(self.state.path.exists())

    def test_default_disabled_status_does_not_create_runtime_or_launch(self):
        from mcp_transport import BrokerClient
        client = BrokerClient(self.state, command=['/not/an/executable'])
        self.assertEqual(client.call('get_status', {}),
                         {'version': 1, 'enabled': False, 'roots': [], 'jobs': []})
        self.assertFalse(self.state.path.exists())

    def test_missing_sdk_entry_reports_actionable_install_without_state(self):
        import io
        import mcp_entry
        with mock.patch.dict(sys.modules, {'mcp': None}), mock.patch('sys.stderr', new_callable=io.StringIO) as errors:
            result = mcp_entry.main(['--state-dir', str(self.state.path)])
        self.assertEqual(result, 2)
        self.assertIn('mcp extra', errors.getvalue())
        self.assertFalse(self.state.path.exists())

    @unittest.skipUnless(SDK, 'optional official MCP SDK is unavailable')
    def test_probe_exercises_configured_stdio_and_disabled_is_protocol_success(self):
        from mcp_transport import probe_connection
        command = [sys.executable, str(ROOT / 'app_entry.py'), '--mcp']
        report = probe_connection(self.state.path, command)
        self.assertTrue(report['connected'], report)
        self.assertFalse(report['status']['enabled'])
        self.assertIn('protocol_version', report)
        self.assertFalse(self.state.path.exists())
        explicit = probe_connection(self.state.path, command + ['--state-dir', str(self.state.path)])
        self.assertTrue(explicit['connected'], explicit)
        # An IPC-only probe would incorrectly succeed despite an invalid launcher.
        broker, client = self.broker()
        report = probe_connection(self.state.path, ['/not/a/launcher'])
        self.assertFalse(report['connected'])
        self.assertEqual(report['error']['code'], 'INVALID_COMMAND')

    @unittest.skipUnless(SDK, 'optional official MCP SDK is unavailable')
    def test_probe_timeout_only_ends_its_thin_process(self):
        from mcp_transport import probe_connection
        from unittest.mock import patch
        broker, client = self.broker()
        script = Path(self.temp.name) / 'unresponsive.py'
        script.write_text('import time\ntime.sleep(60)\n')
        with patch('mcp_transport.PROBE_TIMEOUT', .2):
            before = time.monotonic()
            report = probe_connection(self.state.path, [sys.executable, str(script)])
        self.assertLess(time.monotonic() - before, 6)
        self.assertFalse(report['connected'])
        self.assertEqual(client.handshake()['broker_id'], broker.identity)

    def test_autostart_configured_backend_once_and_reuse_after_client_exit(self):
        from concurrent.futures import ThreadPoolExecutor
        from mcp_transport import BrokerClient
        self.state.configure(True, [])
        launcher = Path(self.temp.name) / 'backend.py'
        starts = Path(self.temp.name) / 'starts'
        launcher.write_text(
            'import sys\nfrom pathlib import Path\n'
            f'sys.path.insert(0,{str(ROOT)!r})\n'
            'from mcp_transport import Broker\nfrom mcp_state import State\n'
            f'with open({str(starts)!r},"a") as log: log.write("started\\n")\n'
            'state=State(sys.argv[sys.argv.index("--state-dir")+1])\n'
            'Broker(state,idle_timeout=.5).serve()\n')
        command = [sys.executable, str(launcher)]
        def connect(_):
            client = BrokerClient(self.state, command)
            client._ensure()
            return client.handshake()['broker_id']
        with ThreadPoolExecutor(max_workers=3) as pool:
            ids = list(pool.map(connect, range(3)))
        self.assertEqual(len(set(ids)), 1)
        self.assertEqual(starts.read_text(), 'started\n')
        self.assertEqual(BrokerClient(self.state, command).handshake()['broker_id'], ids[0])
        # Wait for the real detached broker's idle shutdown before deleting state.
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                BrokerClient(self.state, autostart=False).handshake()
            except (OSError, EOFError):
                break
            time.sleep(.7)
        else:
            self.fail('Detached broker did not exit when idle')

    def test_accepted_job_survives_client_eof_and_independent_client_cancels(self):
        from unittest.mock import patch
        from mcp_service import Service
        from mcp_transport import BrokerClient, _runtime, _connect, _bytes
        entered, release = threading.Event(), threading.Event()
        media = Path(self.temp.name) / 'media'
        media.mkdir()
        (media / 'clip.wav').write_bytes(b'controlled snapshot bytes')
        root_id = self.state.configure(True, [media])['roots'][0]['id']
        class Engine:
            def __init__(self, **kwargs): pass
            def load_model(self, **kwargs): pass
            def run(self, path, **kwargs):
                entered.set()
                release.wait(8)
                output = Path(path).with_suffix('.srt')
                output.write_text('1\n00:00:00,000 --> 00:00:01,000\nfixture\n')
                return str(output)
        with patch('mcp_transport.Service', side_effect=lambda state: Service(state, transcribe_factory=Engine)):
            broker, client = self.broker()
        self.addCleanup(release.set)
        asset = client.call('list_media', {'root_id': root_id})['items'][0]['asset_id']
        token, address = _runtime(self.state)
        raw = _connect(address)
        raw.send_bytes(_bytes({'token': token, 'op': 'call', 'name': 'start_transcription',
                               'arguments': {'asset_id': asset, 'request_id': 'lost-client'}}))
        raw.close()  # disconnect without reading admission acknowledgement
        # A freshly provisioned Windows runner may briefly delay the first
        # worker thread while Defender scans imported native dependencies.
        # The contract is eventual admission after the client disconnects,
        # not a four-second performance deadline.
        self.assertTrue(entered.wait(12))
        second = BrokerClient(self.state, autostart=False)
        # Inspect the durable admission record directly; get_status also probes
        # the local model cache and is outside this disconnect/cancellation
        # transport contract.
        jobs = [{'job_id': job['id'], 'state': job['state']}
                for job in self.state.records('jobs')]
        self.assertEqual(len(jobs), 1)
        job_id = jobs[0]['job_id']
        self.assertEqual(second.call('get_job', {'job_id': job_id})['state'], 'running')
        second.call('cancel_job', {'job_id': job_id})
        release.set()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            job = second.call('get_job', {'job_id': job_id})
            if job['state'] == 'cancelled':
                break
            time.sleep(.02)
        self.assertEqual(job['state'], 'cancelled')
        self.assertEqual(self.state.records('sources'), [])

    def test_legacy_entry_preserves_arguments_and_freezes_before_gui(self):
        stub = Path(self.temp.name) / 'SubtitleTranscriber.py'
        stub.write_text('import multiprocessing,sys,json\n'
                        'assert multiprocessing.freeze_observed\n'
                        'print(json.dumps(sys.argv[1:]))\n')
        driver = '''import sys,multiprocessing
sys.path[:0]=[sys.argv[1],sys.argv[2]]
import app_entry
multiprocessing.freeze_support=lambda: setattr(multiprocessing,'freeze_observed',True)
raise SystemExit(app_entry.main(sys.argv[3:]))
'''
        flags = ['--from-installer', '--test-open-page', '/temporary/index.html', '--test-report',
                 '/temporary/report.json', '--test-web-export', '--test-traditional-chinese', '--test-import-mlx']
        result = subprocess.run([sys.executable, '-c', driver, self.temp.name, str(ROOT), *flags],
                                capture_output=True, text=True, timeout=10, cwd=self.temp.name)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), flags)

    def test_relative_state_and_backend_script_are_rejected(self):
        from mcp_transport import backend_command
        from mcp_state import MCPError
        with self.assertRaises(MCPError):
            backend_command(self.state, [sys.executable, '-u', 'relative.py'])
        result = subprocess.run([sys.executable, str(ROOT / 'mcp_entry.py'), '--state-dir', 'relative', '--self-test'],
                                capture_output=True, timeout=10, cwd=self.temp.name)
        self.assertEqual(result.returncode, 2)
        self.assertFalse((Path(self.temp.name) / 'relative').exists())

    def test_launch_lock_contention_has_bounded_wait_without_spawning(self):
        from unittest.mock import patch
        from mcp_state import ProcessLock, MCPError
        from mcp_transport import BrokerClient
        self.state.configure(True, [])
        marker = Path(self.temp.name) / 'unexpected-launch'
        launcher = Path(self.temp.name) / 'exit.py'
        launcher.write_text(f'from pathlib import Path\nPath({str(marker)!r}).touch()\n')
        lock = ProcessLock(self.state.path / 'locks', 'broker-launch')
        lock.acquire()
        timer = threading.Timer(.8, lock.release)
        timer.start()
        try:
            before = time.monotonic()
            with patch('mcp_transport.START_TIMEOUT', .1), self.assertRaises(MCPError) as caught:
                BrokerClient(self.state, [sys.executable, str(launcher)]).call('get_status', {})
            self.assertEqual(caught.exception.code, 'BROKER_UNAVAILABLE')
            self.assertLess(time.monotonic() - before, .5)
            self.assertFalse(marker.exists())
        finally:
            timer.join(2)
            lock.release()

    @unittest.skipUnless(os.name == 'nt', 'native Windows pipe ACL/lifecycle gate')
    def test_windows_pipe_has_private_acl_and_rejects_bad_auth(self):
        import ctypes
        import secrets
        import _winapi
        from ctypes import wintypes as w
        from mcp_transport import _private_pipe_handle, _connect
        address = r'\\.\pipe\vts-acl-test-' + secrets.token_hex(16)
        handle = _private_pipe_handle(address, True)
        try:
            adv = ctypes.WinDLL('advapi32', use_last_error=True)
            pointer = ctypes.c_void_p
            adv.GetKernelObjectSecurity.argtypes = [w.HANDLE, w.DWORD, pointer, w.DWORD, ctypes.POINTER(w.DWORD)]
            adv.GetKernelObjectSecurity.restype = w.BOOL
            adv.GetSecurityDescriptorDacl.argtypes = [pointer, ctypes.POINTER(w.BOOL), ctypes.POINTER(pointer), ctypes.POINTER(w.BOOL)]
            adv.GetSecurityDescriptorDacl.restype = w.BOOL
            adv.GetAce.argtypes = [pointer, w.DWORD, ctypes.POINTER(pointer)]
            adv.GetAce.restype = w.BOOL
            adv.GetSecurityDescriptorOwner.argtypes = [pointer, ctypes.POINTER(pointer), ctypes.POINTER(w.BOOL)]
            adv.GetSecurityDescriptorOwner.restype = w.BOOL
            adv.EqualSid.argtypes, adv.EqualSid.restype = [pointer, pointer], w.BOOL
            size = w.DWORD()
            adv.GetKernelObjectSecurity(handle, 5, None, 0, ctypes.byref(size))
            descriptor = ctypes.create_string_buffer(size.value)
            self.assertTrue(adv.GetKernelObjectSecurity(handle, 5, descriptor, size.value, ctypes.byref(size)))
            present, defaulted, dacl, owner = w.BOOL(), w.BOOL(), pointer(), pointer()
            self.assertTrue(adv.GetSecurityDescriptorDacl(descriptor, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted)))
            self.assertTrue(present.value and dacl.value)
            self.assertEqual(ctypes.c_ushort.from_address(dacl.value + 4).value, 1)
            self.assertTrue(adv.GetSecurityDescriptorOwner(descriptor, ctypes.byref(owner), ctypes.byref(defaulted)))
            ace = pointer()
            self.assertTrue(adv.GetAce(dacl, 0, ctypes.byref(ace)))
            self.assertEqual(ctypes.c_ubyte.from_address(ace.value).value, 0)
            self.assertTrue(adv.EqualSid(ace.value + 8, owner))
        finally:
            _winapi.CloseHandle(handle)
        broker, client = self.broker()
        raw = _connect(client.address)
        try:
            raw.send_bytes(b'{"token":"wrong","op":"hello"}')
            with self.assertRaises((OSError, EOFError)):
                raw.recv_bytes()
        finally:
            raw.close()
        for _ in range(3):
            raw = _connect(client.address)
            raw.close()
        self.assertTrue(client.call('get_status', {})['enabled'])

    @unittest.skipUnless(os.name == 'nt', 'native Windows live-instance saturation gate')
    def test_windows_listener_saturation_and_disconnect_keep_open_channel_usable(self):
        import secrets
        from mcp_transport import _WindowsListener, _connect, MAX_CLIENTS
        address = r'\\.\pipe\vts-capacity-test-' + secrets.token_hex(16)
        listener = _WindowsListener(address)
        peers, accepted = [], []
        try:
            for _ in range(MAX_CLIENTS):
                peers.append(_connect(address))
                accepted.append(listener.accept())
            overflow_peer = _connect(address)
            try:
                overflow = listener.accept()
                overflow.close()  # same immediate overflow rejection as Broker
            finally:
                overflow_peer.close()
            disconnected = _connect(address)
            disconnected.close()
            try:
                early = listener.accept()
            except TimeoutError:
                pass  # native completion can report the early disconnect here
            else:
                early.close()
            # Recovery is exercised while the first sixteen channels stay open.
            from concurrent.futures import ThreadPoolExecutor
            def accept_recovered():
                deadline = time.monotonic() + 5
                while True:
                    try:
                        return listener.accept()
                    except TimeoutError:
                        if time.monotonic() >= deadline:
                            raise
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(accept_recovered)
                peers.append(_connect(address))
                accepted.append(future.result(timeout=6))
            peers[0].send_bytes(b'still-running')
            self.assertEqual(accepted[0].recv_bytes(), b'still-running')
            accepted.pop().close()
            peers.pop().close()
        finally:
            for channel in accepted + peers:
                channel.close()
            listener.close()

    def test_second_broker_does_not_create_service_owner(self):
        from mcp_transport import Broker
        broker, client = self.broker()
        second = Broker(self.state)
        self.assertFalse(second.serve(threading.Event()))
        self.assertEqual(client.handshake()['broker_id'], broker.identity)

    @unittest.skipIf(os.name == 'nt', 'AF_UNIX frame-specific check')
    def test_bad_auth_json_oversize_and_partial_frame_do_not_poison_broker(self):
        from mcp_transport import BrokerClient, MAX_FRAME, FRAME_TIMEOUT
        broker, client = self.broker()
        for payload in (b'{bad', b'{"token":"wrong","op":"hello"}',
                        b'{"token":"x","token":"x","op":"hello"}'):
            with socket.socket(socket.AF_UNIX) as raw:
                raw.settimeout(5)
                raw.connect(client.address)
                raw.sendall(struct.pack('!I', len(payload)) + payload)
                self.assertEqual(raw.recv(1), b'')
        with socket.socket(socket.AF_UNIX) as raw:
            raw.settimeout(FRAME_TIMEOUT + 3)
            raw.connect(client.address)
            raw.sendall(struct.pack('!I', MAX_FRAME + 1))
            self.assertEqual(raw.recv(1), b'')
        with socket.socket(socket.AF_UNIX) as raw:
            raw.settimeout(FRAME_TIMEOUT + 3)
            raw.connect(client.address)
            raw.sendall(b'\x00')
            self.assertEqual(raw.recv(1), b'')
        self.assertTrue(client.call('get_status', {})['enabled'])

    def test_independent_client_cancels_persistent_job(self):
        from mcp_transport import BrokerClient
        media = Path(self.temp.name) / 'clip.wav'
        media.write_bytes(b'synthetic media')
        policy = self.state.configure(True, [Path(self.temp.name)])
        self.state.put('assets', 'asset', {'id': 'asset', 'root_id': policy['roots'][0]['id'],
                                         'relative': media.name, 'kind': 'media'})
        self.state.put('jobs', 'existing', {'id': 'existing', 'state': 'queued', 'kind': 'transcription',
                                          'asset_id': 'asset'})
        broker, client = self.broker()
        # Startup interrupts previously unowned work; no fabricated result appears.
        result = BrokerClient(self.state, autostart=False).call('cancel_job', {'job_id': 'existing'})
        self.assertIn(result['state'], ('interrupted', 'cancelled'))
        self.assertNotIn('result', client.call('get_job', {'job_id': 'existing'}))

    def test_idle_exit_and_restart_release_endpoint(self):
        from mcp_transport import Broker, BrokerClient
        self.state.configure(True, [])
        broker = Broker(self.state, idle_timeout=.15)
        thread = threading.Thread(target=broker.serve)
        thread.start()
        thread.join(5)
        self.assertFalse(thread.is_alive())
        restarted, client = self.broker()
        self.assertNotEqual(broker.identity, client.handshake()['broker_id'])

    @unittest.skipUnless(SDK, 'optional official MCP SDK is unavailable')
    def test_official_client_subprocess_handshake_list_call_and_shared_broker(self):
        broker, client = self.broker()
        script = r'''
import asyncio,json,sys
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client
async def check():
    p=StdioServerParameters(command=sys.executable,args=[sys.argv[1],'--mcp','--state-dir',sys.argv[2]])
    async with stdio_client(p) as (r,w):
        async with ClientSession(r,w) as s:
            initial=await s.initialize()
            await s.send_ping()
            names=[t.name for t in (await s.list_tools()).tools]
            assert 'configure' not in names and 'get_status' in names and 'list_translation_drafts' in names and len(names)==13
            status=await s.call_tool('get_status',{})
            assert status.structuredContent['enabled'] is True and not status.isError
            denied=await s.call_tool('list_media',{'root_id':'missing'})
            assert denied.isError and denied.structuredContent['error']['code']=='ROOT_NOT_ALLOWED'
            bad=await s.call_tool('get_status',{'secret':'not-allowed'})
            assert bad.isError and bad.structuredContent['error']['code']=='INVALID_ARGUMENT'
            print(json.dumps({'protocol':initial.protocolVersion,'tools':names}))
asyncio.run(check())
'''
        for _ in range(2):
            result = subprocess.run([sys.executable, '-c', script, str(ROOT / 'app_entry.py'), str(self.state.path)],
                                    capture_output=True, text=True, timeout=25, cwd=self.temp.name)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(len(json.loads(result.stdout)['tools']), 13)
            self.assertEqual(client.handshake()['broker_id'], broker.identity)

    @unittest.skipUnless(SDK, 'optional official MCP SDK is unavailable')
    def test_bootstrap_headless_and_self_test_preserve_off_policy(self):
        script = '''import runpy,sys
class NoGUI:
 def find_spec(self, fullname, path=None, target=None):
  if fullname.split('.')[0] in ('tkinter','customtkinter','SubtitleTranscriber'):
   raise RuntimeError('GUI imported in headless mode')
sys.meta_path.insert(0,NoGUI())
from pathlib import Path
sys.path.insert(0,str(Path(sys.argv[1]).parent))
sys.argv=[sys.argv[1],'--mcp','--self-test','--state-dir',sys.argv[2]]
runpy.run_path(sys.argv[0],run_name='__main__')
'''
        result = subprocess.run([sys.executable, '-c', script, str(ROOT / 'app_entry.py'), str(self.state.path)],
                                capture_output=True, text=True, timeout=15, cwd=self.temp.name)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = json.loads(result.stdout)
        self.assertTrue(result['connected'])
        self.assertFalse(result['status']['enabled'])
        self.assertFalse(self.state.policy()['enabled'])

    @unittest.skipUnless(SDK, 'optional official MCP SDK is unavailable')
    def test_stdio_eof_and_bad_json_never_emit_debug(self):
        result = subprocess.run([sys.executable, str(ROOT / 'mcp_entry.py'), '--state-dir', str(self.state.path)],
                                input=b'{bad\n', capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        for line in result.stdout.splitlines():
            self.assertEqual(json.loads(line)['jsonrpc'], '2.0')
        self.assertFalse(self.state.policy()['enabled'])
        self.assertFalse(self.state.path.exists())

    @unittest.skipUnless(SDK, 'optional official MCP SDK is unavailable')
    def test_stdio_oversize_and_invalid_utf8_close_bridge(self):
        from mcp_transport import MAX_FRAME
        for data in (b'x' * (MAX_FRAME + 1) + b'\n', b'\xff\n'):
            result = subprocess.run([sys.executable, str(ROOT / 'mcp_entry.py'), '--state-dir', str(self.state.path)],
                                    input=data, capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, b'')


if __name__ == '__main__':
    unittest.main()
