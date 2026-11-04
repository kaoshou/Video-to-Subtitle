import os
from pathlib import Path
import tempfile
import time
import types
import unittest
import subprocess
import sys
from unittest.mock import patch

from mcp_state import MCPError, ProcessLock, State


class FakeEngine:
    def __init__(self, *args, **kwargs):
        self.loaded = False

    def load_model(self, log_callback=None, progress_callback=None, cancel_check_callback=None):
        self.loaded = True
        log_callback('loaded')
        progress_callback(.5, {'percent': 50})

    def run(self, path, **kwargs):
        if not self.loaded:
            raise RuntimeError('model must load before reuse')
        if path == 'cancel':
            while not kwargs['cancel_check_callback']():
                time.sleep(.01)
            raise InterruptedError('cancelled cooperatively')
        kwargs['stage_callback']('transcription', 'running')
        kwargs['review_callback'](path, {'warnings': []})
        kwargs['progress_callback'](.75)
        return (os.getpid(), path, kwargs['batch_size'])


class ContractEngine:
    def __init__(self, *args, **kwargs):
        pass

    def run(self, path, **options):
        self.last_batch_decision = {'requested_mode':'auto', 'effective_size':8, 'reason':'automatic',
                                   'rationale':'Conservative cuda memory/core estimate: 8; not benchmarked'}
        options['log_callback'](path)
        return {key: value for key, value in options.items() if not key.endswith('_callback')}


class AccessErrorEngine:
    def __init__(self, *args, **kwargs):
        pass

    def load_model(self, **kwargs):
        from transcriber import ModelCacheAccessError
        raise ModelCacheAccessError('fixture access denied', 'small', '/fixture/cache')


class OrphanEngine:
    def __init__(self, *args, **kwargs): pass
    def run(self, path, **kwargs):
        root = Path(path)
        (root / 'child-alive').touch()
        while not (root / 'release').exists():
            time.sleep(.01)
        (root / 'child-done').touch()
        return True


class BrokerOrphanEngine:
    def __init__(self, **kwargs): pass
    def load_model(self, **kwargs): pass
    def run(self, path, **kwargs):
        root = Path(path).parent
        (root / 'child-alive').touch()
        while not (root / 'release').exists(): time.sleep(.01)
        output = Path(path).with_suffix('.srt')
        output.write_text('1\n00:00:00,000 --> 00:00:01,000\nsynthetic\n')
        (root / 'child-done').touch()
        return str(output)


def broker_orphan_child(root, connection, cancelled):
    # Only the native engine/cache readiness dependency is synthetic. Execute
    # the real production child target and its residency acquisition.
    import mcp_service
    from unittest.mock import patch
    fake = types.ModuleType('transcriber')
    fake.SubtitleTranscriber = BrokerOrphanEngine
    fake.inspect_model_cache = lambda *a: types.SimpleNamespace(state='ready', path=str(root))
    with patch.dict(sys.modules, {'transcriber': fake}):
        mcp_service._inference_child({'model': 'small', 'device': 'cpu'}, str(Path(root) / 'input.mp4'),
                                    connection, cancelled, str(Path(root) / 'state'))


class InferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = State(Path(self.temp.name) / 'state')
        self.owner = types.SimpleNamespace(transcriber=None)

    def test_orphan_broker_child_retains_residency_until_exit(self):
        script = '''import os, sys, time, multiprocessing
from pathlib import Path
from mcp_state import ProcessLock
from test_mcp_inference import broker_orphan_child
root = Path(sys.argv[1]); context = multiprocessing.get_context('spawn')
lock = ProcessLock(root / 'state' / 'locks', 'inference'); assert lock.acquire()
reader, writer = context.Pipe(duplex=False); cancelled = context.Event()
child = context.Process(target=broker_orphan_child, args=(str(root), writer, cancelled))
child.start(); writer.close()
deadline = time.monotonic() + 5
while not (root / 'child-alive').exists():
 if not child.is_alive() or time.monotonic() > deadline: sys.exit(2)
 time.sleep(.01)
os._exit(27)
'''
        env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(Path(__file__).resolve().parent), str(Path.cwd())]))
        process = subprocess.Popen([sys.executable, '-c', script, self.temp.name], env=env,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        contender = ProcessLock(self.state.path / 'locks', 'model-residency')
        try:
            self.assertEqual(process.wait(timeout=10), 27)
            self.assertFalse(contender.acquire())
            from mcp_inference import InferenceBatch
            with self.assertRaises(MCPError):
                InferenceBatch(self.owner, state=self.state)
            from app_entry import _mcp_admin
            import io
            with patch('sys.stderr', new_callable=io.StringIO):
                self.assertEqual(_mcp_admin(['--mcp-maintenance', '--state-dir', str(self.state.path)]), 3)
        finally:
            contender.release()
            (Path(self.temp.name) / 'release').touch()
            _, diagnostics = process.communicate(timeout=10)
        self.assertTrue((Path(self.temp.name) / 'child-done').exists())
        self.assertTrue(contender.acquire())
        contender.release()

    def test_proxy_residency_wait_cancels_before_engine_construction(self):
        from mcp_inference import ProcessTranscriber
        with ProcessLock(self.state.path / 'locks', 'model-residency'):
            proxy = ProcessTranscriber(engine_factory=OrphanEngine, state_path=self.state.path)
            proxy._start()
            proxy._connection.send(('run', (self.temp.name,), {}))
            time.sleep(.15)
            self.assertFalse((Path(self.temp.name) / 'child-alive').exists())
            proxy.close()
            self.assertFalse(proxy._process.is_alive())

    def test_orphan_proxy_retains_residency_until_child_exits(self):
        script = '''import os, threading, time, sys
from pathlib import Path
from mcp_inference import ProcessTranscriber, InferenceBatch
from mcp_state import State
from types import SimpleNamespace
from test_mcp_inference import OrphanEngine
root = Path(sys.argv[1]); state = State(root / 'state')
state.configure(True, [root]); owner = SimpleNamespace(transcriber=None)
batch = InferenceBatch(owner, state=state)
proxy = ProcessTranscriber(engine_factory=OrphanEngine, state_path=state.path)
owner.transcriber = proxy
threading.Thread(target=lambda: proxy.run(str(root)), daemon=True).start()
while not (root / 'child-alive').exists(): time.sleep(.01)
os._exit(27)
'''
        env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(Path(__file__).resolve().parent), str(Path.cwd())]))
        process = subprocess.Popen([sys.executable, '-c', script, self.temp.name], env=env,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        contender = ProcessLock(self.state.path / 'locks', 'model-residency')
        try:
            self.assertEqual(process.wait(timeout=10), 27)
            self.assertTrue((Path(self.temp.name) / 'child-alive').exists())
            self.assertFalse(contender.acquire(), 'orphaned engine lost residency')
            from mcp_runtime import enable
            self.state.disable()
            with self.assertRaises(MCPError):
                enable(self.state, [Path(self.temp.name)])
        finally:
            contender.release()
            (Path(self.temp.name) / 'release').touch()
            # communicate waits for the inherited pipe to close on child exit.
            _, diagnostics = process.communicate(timeout=10)
        self.assertTrue((Path(self.temp.name) / 'child-done').exists())
        self.assertTrue(contender.acquire())
        contender.release()

    def test_process_lifetime_lock_survives_object_collection_and_teardown(self):
        script = '''import atexit, gc, sys, time
from pathlib import Path
from mcp_state import ProcessLock
root = Path(sys.argv[1])
lock = ProcessLock(root / 'state' / 'locks', 'model-residency', process_lifetime=True)
assert lock.acquire()
del lock; gc.collect()
def teardown():
 (root / 'teardown').touch()
 while not (root / 'release').exists(): time.sleep(.01)
atexit.register(teardown)
'''
        process = subprocess.Popen([sys.executable, '-c', script, self.temp.name], stderr=subprocess.PIPE)
        root = Path(self.temp.name)
        contender = ProcessLock(self.state.path / 'locks', 'model-residency')
        try:
            deadline = time.monotonic() + 5
            while not (root / 'teardown').exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertTrue((root / 'teardown').exists())
            self.assertFalse(contender.acquire())
        finally:
            contender.release()
            (root / 'release').touch()
            _, errors = process.communicate(timeout=5)
        self.assertEqual(process.returncode, 0, errors)
        self.assertTrue(contender.acquire())
        contender.release()

    def test_direct_batch_retains_ownership_even_if_engine_reference_cleared(self):
        from mcp_inference import InferenceBatch
        from mcp_runtime import enable
        batch = InferenceBatch(self.owner, state=self.state)
        self.assertFalse(batch.use_proxy)
        batch.retain_direct()
        self.addCleanup(batch.lock.release)
        self.addCleanup(batch.residency.release)
        batch.close()
        self.owner.transcriber = None
        with self.assertRaises(MCPError):
            enable(self.state, [Path(self.temp.name)], owner=self.owner)
        second = InferenceBatch(self.owner, state=self.state)
        self.assertIs(second.lock, batch.lock)
        second.close()
        contender = ProcessLock(self.state.path / 'locks', 'inference')
        self.assertFalse(contender.acquire())

    def test_final_policy_read_is_under_shared_inference_lock(self):
        from mcp_inference import InferenceBatch
        from unittest.mock import patch
        policy = self.state.policy
        def guarded():
            contender = ProcessLock(self.state.path / 'locks', 'inference')
            self.assertFalse(contender.acquire())
            return policy()
        with patch.object(self.state, 'policy', side_effect=guarded):
            batch = InferenceBatch(self.owner, state=self.state)
        batch.close()
        contender = ProcessLock(self.state.path / 'locks', 'inference')
        self.assertTrue(contender.acquire())
        contender.release()

    def test_proxy_reuses_child_delivers_callbacks_and_exits_before_lock_release(self):
        from mcp_inference import InferenceBatch, ProcessTranscriber
        self.state.configure(True, [Path(self.temp.name)])
        batch = InferenceBatch(self.owner, state=self.state)
        self.assertTrue(batch.use_proxy)
        proxy = ProcessTranscriber('small', 'cpu', 'int8', cpu_threads=8, engine_factory=FakeEngine, state_path=self.state.path)
        self.owner.transcriber = proxy
        logs, progress, stages, reviews = [], [], [], []
        proxy.load_model(logs.append, lambda *args: progress.append(args), lambda: False)
        first = proxy.run('one', batch_size=4, progress_callback=progress.append,
                          stage_callback=lambda *a: stages.append(a), review_callback=lambda *a: reviews.append(a))
        second = proxy.run('two', batch_size=8)
        self.assertNotEqual(first[0], os.getpid())
        self.assertEqual(first[0], second[0])
        self.assertEqual(first[1:], ('one', 4))
        self.assertEqual(second[1:], ('two', 8))
        self.assertEqual(logs, ['loaded'])
        self.assertEqual(stages, [('transcription', 'running')])
        self.assertEqual(reviews, [('one', {'warnings': []})])
        self.assertIn(.75, progress)
        self.assertEqual(proxy.cpu_threads, 8)
        process = proxy._process
        batch.close()
        self.assertFalse(process.is_alive())
        contender = ProcessLock(self.state.path / 'locks', 'inference')
        self.assertTrue(contender.acquire())
        contender.release()

    def test_proxy_cancellation_is_cooperative(self):
        from mcp_inference import ProcessTranscriber
        proxy = ProcessTranscriber(engine_factory=FakeEngine, state_path=self.state.path)
        self.addCleanup(proxy.close)
        proxy.load_model()
        deadline = time.monotonic() + .15
        with self.assertRaises(InterruptedError):
            proxy.run('cancel', cancel_check_callback=lambda: time.monotonic() > deadline)
        process = proxy._process
        proxy.close()
        self.assertFalse(process.is_alive())

    def test_run_preserves_positional_callbacks_and_default_options(self):
        from mcp_inference import ProcessTranscriber
        proxy = ProcessTranscriber(engine_factory=ContractEngine, state_path=self.state.path)
        self.addCleanup(proxy.close)
        logs = []
        result = proxy.run('lesson', logs.append, None, None, 'vtt')
        self.assertEqual(logs, ['lesson'])
        self.assertEqual(result['output_format'], 'vtt')
        self.assertEqual(result['batch_size'], 4)
        self.assertEqual(result['word_timestamps'], True)
        self.assertEqual(result['task'], 'transcribe')
        self.assertIsNone(result['hotwords'])

    def test_preexisting_direct_engine_cannot_be_reused_under_enabled_policy(self):
        from mcp_inference import InferenceBatch
        self.owner.transcriber = FakeEngine()
        self.state.configure(True, [Path(self.temp.name)])
        with self.assertRaises(MCPError):
            InferenceBatch(self.owner, state=self.state)
        contender = ProcessLock(self.state.path / 'locks', 'inference')
        self.assertTrue(contender.acquire())
        contender.release()

    def test_proxy_preserves_model_access_error_type_metadata_and_message(self):
        from mcp_inference import ProcessTranscriber
        from transcriber import ModelCacheAccessError
        proxy = ProcessTranscriber(engine_factory=AccessErrorEngine, state_path=self.state.path)
        self.addCleanup(proxy.close)
        with self.assertRaises(ModelCacheAccessError) as raised:
            proxy.load_model()
        error = raised.exception
        self.assertEqual(error.model_size, 'small')
        self.assertEqual(error.cache_dir, '/fixture/cache')
        self.assertEqual(str(error).count('技術資訊'), 1)

    def test_proxy_transports_batch_option_without_coercion(self):
        from mcp_inference import ProcessTranscriber
        proxy = ProcessTranscriber(engine_factory=ContractEngine, state_path=self.state.path)
        self.addCleanup(proxy.close)
        self.assertEqual(proxy.run('lesson', batch_size='auto')['batch_size'], 'auto')
        self.assertEqual(proxy.last_batch_decision, {'requested_mode':'auto', 'effective_size':8, 'reason':'automatic',
            'rationale':'Conservative cuda memory/core estimate: 8; not benchmarked'})


if __name__ == '__main__':
    unittest.main()
