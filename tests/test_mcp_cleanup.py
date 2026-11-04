from pathlib import Path
import tempfile
import unittest
import threading
from unittest.mock import patch

from mcp_state import MCPError, ProcessLock, State


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = State(self.root / 'state')
        self.state.configure(True, [self.root])
        self.state.put('jobs', 'old-job', {'id': 'old-job', 'state': 'running'})
        for kind in ('assets', 'sources', 'drafts', 'tracks', 'requests'):
            self.state.put(kind, 'old', {'id': 'old', 'text': 'unfinished private work'})
        for kind in ('connections', 'backups'):
            self.state.put(kind, 'keep', {'id': 'keep', 'secret': 'preserve'})
        (self.root / 'original.mp4').write_bytes(b'original')
        (self.root / 'published').mkdir()
        (self.root / 'published' / 'index.html').write_text('published')
        (self.root / 'models').mkdir()
        (self.root / 'models' / 'model').write_text('model')
        self.state.disable()

    def test_cleanup_removes_complete_work_graph_preserving_outside_and_backups(self):
        from mcp_cleanup import preview_cleanup, apply_cleanup
        plan = preview_cleanup(self.state)
        self.assertEqual(plan['location'], str(self.state.path))
        self.assertGreater(plan['bytes'], 0)
        self.assertIn('drafts', plan['scope'])
        with self.assertRaises(MCPError):
            apply_cleanup(self.state, plan, consent=False)
        apply_cleanup(self.state, plan, consent=True)
        for kind in ('jobs', 'assets', 'sources', 'drafts', 'tracks', 'requests'):
            self.assertEqual(self.state.records(kind), [])
            self.state.put(kind, 'new', {'id': 'new'})  # Quota namespace usable again.
        self.assertEqual(self.state.get('backups', 'keep')['secret'], 'preserve')
        self.assertEqual(self.state.get('connections', 'keep')['secret'], 'preserve')
        self.assertEqual((self.root / 'original.mp4').read_bytes(), b'original')
        self.assertEqual((self.root / 'published' / 'index.html').read_text(), 'published')
        self.assertEqual((self.root / 'models' / 'model').read_text(), 'model')
        self.assertFalse(self.state.policy()['enabled'])

    def test_cleanup_refuses_live_owner_and_unsafe_link(self):
        from mcp_cleanup import preview_cleanup, apply_cleanup
        plan = preview_cleanup(self.state)
        for name in ('broker', 'service-owner', 'inference', 'model-residency'):
            with ProcessLock(self.state.path / 'locks', name):
                with self.assertRaises(MCPError) as error:
                    apply_cleanup(self.state, plan, consent=True)
                self.assertEqual(error.exception.code, 'WORK_ACTIVE')
        (self.state.path / 'drafts' / 'unsafe').symlink_to(self.root / 'models', target_is_directory=True)
        with self.assertRaises(MCPError):
            preview_cleanup(self.state)
        self.assertTrue((self.root / 'models' / 'model').exists())

    def test_interrupted_cleanup_blocks_activation_and_resumes(self):
        import mcp_cleanup
        plan = mcp_cleanup.preview_cleanup(self.state)
        original = mcp_cleanup._remove_tree
        count = 0
        def interrupted(parent, name):
            nonlocal count
            count += 1
            if count == 2:
                raise OSError('synthetic interruption')
            return original(parent, name)
        with patch.object(mcp_cleanup, '_remove_tree', side_effect=interrupted):
            with self.assertRaises(OSError):
                mcp_cleanup.apply_cleanup(self.state, plan, consent=True)
        with self.assertRaises(MCPError) as error:
            self.state.configure(True, [self.root])
        self.assertEqual(error.exception.code, 'CLEANUP_PENDING')
        resumed = mcp_cleanup.preview_cleanup(self.state)
        self.assertTrue(resumed['resume'])
        mcp_cleanup.apply_cleanup(self.state, resumed, consent=True)
        self.assertEqual(self.state.records('drafts'), [])
        self.assertTrue(self.state.configure(True, [self.root])['enabled'])

    def test_changed_preview_requires_fresh_consent(self):
        from mcp_cleanup import preview_cleanup, apply_cleanup
        plan = preview_cleanup(self.state)
        self.state.put('drafts', 'another', {'id': 'another'})
        with self.assertRaises(MCPError) as error:
            apply_cleanup(self.state, plan, consent=True)
        self.assertEqual(error.exception.code, 'CLEANUP_CHANGED')
        self.assertTrue(self.state.get('drafts', 'another'))

    def test_cleanup_cannot_race_offline_cancel_record_commit(self):
        from mcp_cleanup import preview_cleanup, apply_cleanup
        from mcp_transport import BrokerClient
        plan = preview_cleanup(self.state)
        entered, release = threading.Event(), threading.Event()
        original, failures = self.state._put, []
        def paused(kind, key, data):
            if kind == 'jobs':
                entered.set()
                release.wait(5)
            return original(kind, key, data)
        def cancel():
            try:
                BrokerClient(self.state).call('cancel_job', {'job_id': 'old-job'})
            except Exception as error:
                failures.append(error)
        with patch.object(self.state, '_put', side_effect=paused):
            worker = threading.Thread(target=cancel)
            worker.start()
            try:
                self.assertTrue(entered.wait(3))
                with self.assertRaises(MCPError) as error:
                    apply_cleanup(self.state, plan, consent=True)
                self.assertEqual(error.exception.code, 'WORK_ACTIVE')
            finally:
                release.set()
                worker.join(5)
        self.assertFalse(failures, failures)
        apply_cleanup(self.state, preview_cleanup(self.state), consent=True)
        self.assertEqual(self.state.records('jobs'), [])
