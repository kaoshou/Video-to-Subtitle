"""Packaging boundaries exercised without models, real configs or home state."""
import json
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


class PackagingTests(unittest.TestCase):
    def test_maintenance_drains_accepted_job_before_broker_exits(self):
        from mcp_state import State
        from mcp_service import Service
        from mcp_transport import Broker, BrokerClient
        entered, release, stop = threading.Event(), threading.Event(), threading.Event()
        class Engine:
            def __init__(self, **kwargs): pass
            def load_model(self, **kwargs): pass
            def run(self, path, **kwargs):
                entered.set()
                release.wait(12)
                output = Path(path).with_suffix('.srt')
                output.write_text('1\n00:00:00,000 --> 00:00:01,000\nfixture\n')
                return str(output)
        with tempfile.TemporaryDirectory() as tmp:
            media = Path(tmp) / 'media'
            media.mkdir()
            (media / 'clip.wav').write_bytes(b'synthetic snapshot')
            state = State(Path(tmp) / 'state')
            policy = state.configure(True, [media])
            with mock.patch('mcp_transport.Service', side_effect=lambda state: Service(state, transcribe_factory=Engine)):
                thread = threading.Thread(target=Broker(state).serve, args=(stop,))
                thread.start()
                client = BrokerClient(state, autostart=False)
                try:
                    deadline = time.monotonic() + 5
                    while True:
                        try:
                            client.handshake()
                            break
                        except (OSError, EOFError):
                            if time.monotonic() >= deadline:
                                raise
                            time.sleep(.02)
                    asset = client.call('list_media', {'root_id': policy['roots'][0]['id']})['items'][0]['asset_id']
                    job = client.call('start_transcription', {'asset_id': asset, 'request_id': 'drain'})
                    self.assertTrue(entered.wait(3))
                    result = subprocess.run([sys.executable, str(ROOT / 'app_entry.py'),
                        '--mcp-maintenance', '--state-dir', str(state.path)], capture_output=True, timeout=15)
                    self.assertEqual(result.returncode, 3, result.stderr)
                    self.assertTrue(thread.is_alive())
                    self.assertFalse(state.get('jobs', job['job_id']).get('cancel_requested'))
                    release.set()
                    thread.join(5)
                    self.assertFalse(thread.is_alive())
                    self.assertEqual(state.get('jobs', job['job_id'])['state'], 'succeeded')
                finally:
                    release.set()
                    stop.set()
                    thread.join(5)

    def test_maintenance_refuses_owned_inference_and_leaves_policy_disabled(self):
        from mcp_state import State, ProcessLock
        with tempfile.TemporaryDirectory() as tmp:
            state = State(Path(tmp) / 'state')
            state.configure(True, [Path(tmp)])
            with ProcessLock(state.path / 'locks', 'inference'):
                result = subprocess.run([sys.executable, str(ROOT / 'app_entry.py'),
                                         '--mcp-maintenance', '--state-dir', str(state.path)],
                                        capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 3, result.stderr)
                self.assertFalse(state.policy()['enabled'])

    def test_disabled_broker_quiesces_without_waiting_for_enabled_idle_timeout(self):
        from mcp_state import State
        from mcp_transport import Broker, BrokerClient
        with tempfile.TemporaryDirectory() as tmp:
            state = State(Path(tmp) / 'state')
            state.configure(True, [Path(tmp)])
            stop = threading.Event()
            thread = threading.Thread(target=Broker(state, idle_timeout=300).serve, args=(stop,))
            thread.start()
            try:
                client = BrokerClient(state, autostart=False)
                deadline = time.monotonic() + 5
                while True:
                    try:
                        client.handshake()
                        break
                    except (OSError, EOFError):
                        if time.monotonic() >= deadline:
                            raise
                        time.sleep(.02)
                state.disable('finish')
                thread.join(3)
                self.assertFalse(thread.is_alive(), 'An idle disabled broker must release maintenance locks promptly')
            finally:
                stop.set()
                thread.join(5)

    def test_thin_import_does_not_load_backend_media_gui_or_sdk(self):
        code = '''
import sys
import mcp_transport, mcp_entry, mcp_launcher, mcp_contracts
for name in ('mcp_service', 'transcriber', 'web_export', 'av', 'PIL',
             'tkinter', 'customtkinter', 'faster_whisper', 'torch', 'mlx', 'mcp'):
    assert name not in sys.modules, name
from mcp_state import MCPError
try:
    mcp_contracts._validate({'extra': True}, mcp_contracts.TOOL_SCHEMAS['get_status'])
except MCPError as error:
    assert error.code == 'INVALID_ARGUMENT'
else:
    raise AssertionError('contract validation missing')
'''
        result = subprocess.run([sys.executable, '-c', code], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_frozen_thin_requires_configured_backend_and_refuses_recursion(self):
        from mcp_state import State, MCPError
        from mcp_transport import backend_command
        with tempfile.TemporaryDirectory() as tmp:
            state = State(Path(tmp) / 'state')
            launcher = Path(tmp) / ('VideoToSubtitleMCP.exe' if os.name == 'nt' else 'VideoToSubtitleMCP')
            launcher.write_bytes(b'inert test payload')
            with mock.patch.object(sys, 'frozen', True, create=True), mock.patch.object(sys, 'executable', str(launcher)):
                for configured in (None, [str(launcher)], [str(Path(tmp) / 'missing-backend')]):
                    with mock.patch.object(state, 'policy', return_value={'options': {'backend_command': configured}}):
                        with self.assertRaises(MCPError) as caught:
                            backend_command(state)
                        self.assertEqual(caught.exception.code, 'BACKEND_REPAIR_REQUIRED')

    @unittest.skipUnless(importlib.util.find_spec('mcp'), 'optional official MCP SDK is unavailable')
    def test_source_stdio_smoke_imports_two_languages_and_exports_player(self):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/smoke_mcp.py')],
                                cwd=ROOT, capture_output=True, text=True, timeout=90)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report['languages'], ['en', 'ja'])
        self.assertTrue(report['disabled_denied'])
        self.assertTrue(report['protocol_only_stdout'])
        self.assertFalse(report['frozen'])

    def test_headless_disable_preserves_absence_and_revokes_missing_roots(self):
        from mcp_state import State
        with tempfile.TemporaryDirectory() as tmp:
            state = State(Path(tmp) / 'state')
            command = [sys.executable, str(ROOT / 'app_entry.py'), '--mcp-disable', '--state-dir', str(state.path)]
            result = subprocess.run(command, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(state.path.exists())
            root = Path(tmp) / 'media'
            root.mkdir()
            state.configure(True, [root])
            root.rmdir()
            result = subprocess.run(command, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(state.policy()['enabled'])
            self.assertEqual(state.policy()['options']['stop_mode'], 'finish')


if __name__ == '__main__':
    unittest.main()
