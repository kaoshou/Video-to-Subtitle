"""Real broker/bridge contracts; no models, user state or host configuration."""
import importlib.util
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

from mcp_state import State

ROOT = Path(__file__).resolve().parents[1]
SDK = importlib.util.find_spec('mcp') is not None


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='vts-ipc-', dir='/private/tmp' if sys.platform == 'darwin' else None)
        self.addCleanup(self.temp.cleanup)
        self.state = State(Path(self.temp.name) / 'state')
        self.stop = threading.Event()

    def broker(self, **kwargs):
        from mcp_transport import Broker, BrokerClient
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
                client.call('get_status', {})
                return broker, client
            except Exception:
                if time.monotonic() > deadline:
                    raise
                time.sleep(.02)

    def test_disabled_status_and_structured_denial(self):
        from mcp_state import MCPError
        broker, client = self.broker()
        self.assertFalse(client.call('get_status', {})['enabled'])
        with self.assertRaises(MCPError) as caught:
            client.call('list_media', {'root_id': 'missing'})
        self.assertEqual(caught.exception.code, 'MCP_DISABLED')
        with self.assertRaises(MCPError) as caught:
            client.call('configure', {'enabled': True})
        self.assertEqual(caught.exception.code, 'UNKNOWN_TOOL')
        self.assertFalse(self.state.policy()['enabled'])

    def test_default_disabled_status_does_not_create_runtime_or_launch(self):
        from mcp_transport import BrokerClient
        client = BrokerClient(self.state, command=['/not/an/executable'])
        self.assertEqual(client.call('get_status', {}),
                         {'version': 1, 'enabled': False, 'roots': [], 'jobs': []})
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
        self.assertTrue(entered.wait(4))
        second = BrokerClient(self.state, autostart=False)
        jobs = second.call('get_status', {})['jobs']
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
        self.assertFalse(client.call('get_status', {})['enabled'])

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
        self.assertFalse(client.call('get_status', {})['enabled'])

    def test_independent_client_cancels_persistent_job(self):
        from mcp_transport import BrokerClient
        self.state.put('jobs', 'existing', {'id': 'existing', 'state': 'queued', 'kind': 'transcription'})
        broker, client = self.broker()
        # Startup interrupts previously unowned work. Cancellation remains metadata-only while off.
        result = BrokerClient(self.state, autostart=False).call('cancel_job', {'job_id': 'existing'})
        self.assertIn(result['state'], ('interrupted', 'cancelled'))
        self.assertNotIn('result', client.call('get_job', {'job_id': 'existing'}))

    def test_idle_exit_and_restart_release_endpoint(self):
        from mcp_transport import Broker, BrokerClient
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
            assert 'configure' not in names and 'get_status' in names and len(names)==12
            status=await s.call_tool('get_status',{})
            assert status.structuredContent['enabled'] is False and not status.isError
            denied=await s.call_tool('list_media',{'root_id':'missing'})
            assert denied.isError and denied.structuredContent['error']['code']=='MCP_DISABLED'
            bad=await s.call_tool('get_status',{'secret':'not-allowed'})
            assert bad.isError and bad.structuredContent['error']['code']=='INVALID_ARGUMENT'
            print(json.dumps({'protocol':initial.protocolVersion,'tools':names}))
asyncio.run(check())
'''
        for _ in range(2):
            result = subprocess.run([sys.executable, '-c', script, str(ROOT / 'app_entry.py'), str(self.state.path)],
                                    capture_output=True, text=True, timeout=25, cwd=self.temp.name)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(len(json.loads(result.stdout)['tools']), 12)
            self.assertEqual(client.handshake()['broker_id'], broker.identity)

    def test_bootstrap_headless_and_self_test_preserve_off_policy(self):
        broker, client = self.broker()
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
        broker, client = self.broker()
        result = subprocess.run([sys.executable, str(ROOT / 'mcp_entry.py'), '--state-dir', str(self.state.path)],
                                input=b'{bad\n', capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        for line in result.stdout.splitlines():
            self.assertEqual(json.loads(line)['jsonrpc'], '2.0')
        self.assertFalse(client.call('get_status', {})['enabled'])

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
