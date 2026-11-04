import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import types
from unittest.mock import patch

from mcp_state import MCPError, ProcessLock, State


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = State(self.root / 'state')

    def runtime(self):
        import mcp_runtime
        return mcp_runtime

    def test_source_command_is_absolute_full_stdio_without_creating_state(self):
        runtime = self.runtime()
        command = runtime.connection_command(self.state)
        self.assertEqual(command[-3:], ['--mcp', '--state-dir', str(self.state.path)])
        self.assertEqual(Path(command[1]).name, 'app_entry.py')
        self.assertTrue(all(Path(value).is_absolute() for value in command[:2]))
        self.assertEqual(runtime.backend_command(), command[:2])
        self.assertFalse(self.state.path.exists())

    def test_disable_absent_preserves_absence_and_finish_preserves_admission(self):
        runtime = self.runtime()
        runtime.disable(self.state)
        self.assertFalse(self.state.path.exists())
        enabled = self.state.configure(True, [self.root])
        disabled = runtime.disable(self.state, stop_mode='finish')
        self.assertFalse(disabled['enabled'])
        self.assertEqual(disabled['roots'], enabled['roots'])
        self.assertEqual(disabled['drain_generation'], enabled['generation'])
        with self.assertRaises(MCPError):
            self.state.require_enabled()
        runtime.disable(self.state, stop_mode='cancel')
        with self.assertRaises(MCPError):
            self.state.require_enabled(admitted_generation=enabled['generation'])

    def test_disable_missing_saved_root_revokes_remaining_root_in_both_modes(self):
        runtime = self.runtime()
        available = self.root / 'available'
        available.mkdir()
        (available / 'lesson.srt').write_text('existing result')
        unavailable = self.root / 'disconnected'
        for mode in ('cancel', 'finish'):
            with self.subTest(stop_mode=mode):
                unavailable.mkdir()
                enabled = self.state.configure(True, [unavailable, available], model='small', device='cpu')
                session = State(self.state.path)
                available_id = enabled['roots'][1]['id']
                with session.file(available_id, 'lesson.srt') as stream:
                    self.assertEqual(stream.read(), b'existing result')
                unavailable.rmdir()
                disabled = runtime.disable(self.state, stop_mode=mode)
                self.assertFalse(disabled['enabled'])
                self.assertEqual(disabled['roots'], enabled['roots'])
                self.assertEqual(disabled['generation'], enabled['generation'] + 1)
                self.assertEqual(disabled['options'], {**enabled['options'], 'stop_mode': mode})
                with self.assertRaises(MCPError) as denied:
                    with session.file(available_id, 'lesson.srt'):
                        self.fail('new tool access survived disable')
                self.assertEqual(denied.exception.code, 'MCP_DISABLED')
                if mode == 'finish':
                    self.assertEqual(disabled['drain_generation'], enabled['generation'])
                    with session.file(available_id, 'lesson.srt', admitted_generation=enabled['generation']) as stream:
                        self.assertEqual(stream.read(), b'existing result')
                else:
                    self.assertNotIn('drain_generation', disabled)
                    with self.assertRaises(MCPError):
                        session.require_enabled(admitted_generation=enabled['generation'])
                self.assertEqual((available / 'lesson.srt').read_text(), 'existing result')

    def test_enable_conflict_is_refused_before_policy_changes(self):
        runtime = self.runtime()
        lock = ProcessLock(self.state.path / 'locks', 'inference')
        self.assertTrue(lock.acquire())
        try:
            with self.assertRaisesRegex(MCPError, '關閉|restart|Restart'):
                runtime.enable(self.state, [self.root])
            self.assertFalse(self.state.policy()['enabled'])
        finally:
            lock.release()

    def test_enable_keeps_inference_lock_during_configure(self):
        runtime = self.runtime()
        configure = self.state.configure
        def guarded(*args, **kwargs):
            contender = ProcessLock(self.state.path / 'locks', 'inference')
            self.assertFalse(contender.acquire())
            return configure(*args, **kwargs)
        with patch.object(self.state, 'configure', side_effect=guarded):
            policy = runtime.enable(self.state, [self.root])
        self.assertTrue(policy['enabled'])
        self.assertEqual(policy['options']['backend_command'], runtime.backend_command())

    def test_enable_rejects_busy_or_preexisting_gui_without_creating_policy(self):
        runtime = self.runtime()
        for owner in (types.SimpleNamespace(is_running=True),
                      types.SimpleNamespace(current_downloading_model='small'),
                      types.SimpleNamespace(_storage_current_target='small'),
                      types.SimpleNamespace(transcriber=object()),
                      types.SimpleNamespace(_mcp_direct_model_used=True, transcriber=None)):
            with self.subTest(owner=owner), self.assertRaises(MCPError):
                runtime.enable(self.state, [self.root], owner=owner)
        self.assertFalse(self.state.path.exists())

    def test_frozen_command_hashing_works_without_python311_file_digest(self):
        runtime = self.runtime()
        bundle = self.root / 'bundle'
        bundle.mkdir()
        name = 'VideoToSubtitleMCP.exe' if sys.platform == 'win32' else 'VideoToSubtitleMCP'
        payload = b'inert supported-python fixture'
        (bundle / name).write_bytes(payload)
        (bundle / 'vts-mcp-payload.json').write_text(json.dumps({
            'launcher': name, 'sha256': hashlib.sha256(payload).hexdigest(), 'platform': sys.platform}))
        with patch.object(sys, 'frozen', True, create=True), patch.object(sys, '_MEIPASS', str(bundle), create=True), \
                patch.object(hashlib, 'file_digest', None, create=True):
            command = runtime.connection_command(self.state)
            self.assertEqual(Path(command[0]).read_bytes(), payload)

    def test_frozen_missing_payload_refuses_and_verified_activation_is_stable(self):
        runtime = self.runtime()
        bundle = self.root / 'bundle'
        bundle.mkdir()
        with patch.object(sys, 'frozen', True, create=True), patch.object(sys, '_MEIPASS', str(bundle), create=True):
            with self.assertRaises(MCPError):
                runtime.connection_command(self.state)
            self.assertFalse(self.state.path.exists())
            name = 'VideoToSubtitleMCP.exe' if sys.platform == 'win32' else 'VideoToSubtitleMCP'
            payload = b'inert packaged launcher fixture'
            (bundle / name).write_bytes(payload)
            (bundle / 'vts-mcp-payload.json').write_text(json.dumps({
                'launcher': name, 'sha256': hashlib.sha256(payload).hexdigest(), 'platform': sys.platform}))
            command = runtime.connection_command(self.state)
            launcher = Path(command[0])
            self.assertNotIn(str(bundle), command[0])
            self.assertEqual(launcher.read_bytes(), payload)
            self.assertEqual(runtime.connection_command(self.state), command)
            launcher.write_bytes(b'changed')
            with self.assertRaises(MCPError):
                runtime.connection_command(self.state)
            self.assertEqual(runtime.connection_command(self.state, repair=True), command)
            self.assertEqual(launcher.read_bytes(), payload)


if __name__ == '__main__':
    unittest.main()
