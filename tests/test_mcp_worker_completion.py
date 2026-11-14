import json
import multiprocessing
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from mcp_service import Service
from mcp_progress import ProgressEmitter
from mcp_state import MCPError


def completed_child(settings, media, writer, cancel, state_path):
    writer.send_bytes(json.dumps({'event':'progress', 'stage':'output', 'fraction':1.0}).encode())
    writer.send_bytes(json.dumps({'ok':True, 'transcription':{'model':'large-v3-turbo',
        'device':'cuda', 'backend':'faster-whisper'}, 'output_language':'zh-TW'}).encode())
    writer.close()


class WorkerCompletionTests(unittest.TestCase):
    def test_real_spawned_child_completion_and_exit(self):
        service = Service.__new__(Service)
        service._factory = None
        service.state = SimpleNamespace(path=Path('/fixture'))
        service._checkpoint = Mock()
        service._job_progress = lambda job: ProgressEmitter(lambda event: None)
        context = multiprocessing.get_context('spawn')
        wrapper = SimpleNamespace(Pipe=context.Pipe, Event=context.Event,
            Process=lambda target, args: context.Process(target=completed_child, args=args))
        with patch('mcp_service.multiprocessing.get_context', return_value=wrapper):
            result = service._transcribe({'id':'job', 'arguments':{'settings':{}}}, Path('/fixture/media.mp4'))
        self.assertEqual(result['output_language'], 'zh-TW')

    def run_worker(self, events, alive):
        service = Service.__new__(Service)
        service._factory = None
        service.state = SimpleNamespace(path=Path('/fixture'))
        service._checkpoint = Mock()
        service._update_job = Mock()
        service._job_progress = lambda job: ProgressEmitter(lambda event: None)
        reader, writer, process, cancel = Mock(), Mock(), Mock(), Mock()
        pending = list(events)
        def poll(*args):
            if not pending:
                error = BrokenPipeError('pipe writer has closed')
                error.winerror = 109
                raise error
            return True
        reader.poll.side_effect = poll
        reader.recv_bytes.side_effect = lambda size: json.dumps(pending.pop(0)).encode()
        process.is_alive.side_effect = list(alive)
        context = SimpleNamespace(Pipe=lambda **kw: (reader, writer), Event=lambda: cancel,
                                  Process=lambda **kw: process)
        with patch('mcp_service.multiprocessing.get_context', return_value=context):
            return service._transcribe({'id': 'job', 'arguments': {'settings': {}}}, Path('/fixture/media.mp4'))

    def success(self):
        return {'ok': True, 'transcription': {'model':'large-v3-turbo', 'device':'cuda',
                 'backend':'faster-whisper'}, 'output_language':'zh-TW'}

    def test_received_success_is_not_polled_again_after_child_exit(self):
        result = self.run_worker([self.success()], [True, False, False])
        self.assertEqual(result['transcription']['model'], 'large-v3-turbo')

    def test_exited_child_buffer_is_drained_only_until_final_result(self):
        result = self.run_worker([{'event':'progress', 'stage':'output', 'fraction':1.0},
                                  self.success()], [False, False])
        self.assertEqual(result['output_language'], 'zh-TW')

    def test_disconnected_worker_without_success_is_failure(self):
        with self.assertRaises(MCPError) as raised:
            self.run_worker([], [False, False])
        self.assertEqual(raised.exception.code, 'TRANSCRIPTION_FAILED')
