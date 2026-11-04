import os
from pathlib import Path
import tempfile
import time
import types
import unittest

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


class InferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = State(Path(self.temp.name) / 'state')
        self.owner = types.SimpleNamespace(transcriber=None)

    def test_direct_batch_retains_ownership_even_if_engine_reference_cleared(self):
        from mcp_inference import InferenceBatch
        from mcp_runtime import enable
        batch = InferenceBatch(self.owner, state=self.state)
        self.assertFalse(batch.use_proxy)
        batch.retain_direct()
        self.addCleanup(batch.lock.release)
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
        proxy = ProcessTranscriber('small', 'cpu', 'int8', cpu_threads=8, engine_factory=FakeEngine)
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
        proxy = ProcessTranscriber(engine_factory=FakeEngine)
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
        proxy = ProcessTranscriber(engine_factory=ContractEngine)
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
        proxy = ProcessTranscriber(engine_factory=AccessErrorEngine)
        self.addCleanup(proxy.close)
        with self.assertRaises(ModelCacheAccessError) as raised:
            proxy.load_model()
        error = raised.exception
        self.assertEqual(error.model_size, 'small')
        self.assertEqual(error.cache_dir, '/fixture/cache')
        self.assertEqual(str(error).count('技術資訊'), 1)

    def test_proxy_transports_batch_option_without_coercion(self):
        from mcp_inference import ProcessTranscriber
        proxy = ProcessTranscriber(engine_factory=ContractEngine)
        self.addCleanup(proxy.close)
        self.assertEqual(proxy.run('lesson', batch_size='auto')['batch_size'], 'auto')
        self.assertEqual(proxy.last_batch_decision, {'requested_mode':'auto', 'effective_size':8, 'reason':'automatic',
            'rationale':'Conservative cuda memory/core estimate: 8; not benchmarked'})


if __name__ == '__main__':
    unittest.main()
