import importlib
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from mcp_state import MCPError, State, ProcessLock
from test_web_export_inputs import make_video


SRT = '1\n00:00:00,123 --> 00:00:00,456\nFirst\n\n2\n00:00:00,400 --> 00:00:00,987\nSecond\n'


class ServiceFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.media = self.root / 'media'
        self.media.mkdir()
        make_video(self.media / 'lesson.mp4')
        (self.media / 'lesson.srt').write_text(SRT, encoding='utf-8')
        (self.media / 'secret.txt').write_text('not media')
        self.state = State(self.root / 'state')
        self.root_id = self.state.configure(True, [self.media])['roots'][0]['id']
        self.api = importlib.import_module('mcp_service')
        self.service = self.api.Service(self.state)
        self.addCleanup(lambda: self.service.close())

    def assets(self):
        listed = self.service.call('list_media', {'root_id': self.root_id})
        return {a['name']: a['asset_id'] for a in listed['items']}

    def imported(self):
        assets = self.assets()
        return self.service.call('import_subtitle', {
            'media_id': assets['lesson.mp4'], 'subtitle_id': assets['lesson.srt'],
            'language': 'en', 'request_id': 'import-one'})

    def wait_job(self, id):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            job = self.service.call('get_job', {'job_id': id})
            if job['state'] in ('succeeded', 'failed', 'cancelled', 'interrupted'):
                return job
            time.sleep(.01)
        self.fail('Job did not settle')


class ServiceTests(ServiceFixture):
    def test_listing_is_supported_bounded_relative_and_schema_rejects_internal_capability(self):
        self.assertEqual(set(self.assets()), {'lesson.mp4', 'lesson.srt'})
        with self.assertRaises(MCPError):
            self.service.call('list_media', {'root_id': self.root_id, 'admitted_generation': 1})
        self.assertNotIn(str(self.root), json.dumps(self.service.call('get_status', {})))
        with self.assertRaises(TypeError):
            self.api.TOOL_SCHEMAS['invented'] = {}

    def test_import_is_snapshot_paged_and_request_is_persistent(self):
        result = self.imported()
        self.assertIn('track_id', result)
        page = self.service.call('read_transcript', {'source_id': result['source_id'], 'limit': 1})
        self.assertEqual([(c['start'], c['end'], c['text']) for c in page['cues']],
                         [(.123, .456, 'First')])
        self.assertIsNotNone(page['next_cursor'])
        self.service.close()
        self.service = self.api.Service(self.state)
        self.assertEqual(self.imported(), result)
        with self.assertRaises(MCPError) as raised:
            self.service.call('import_subtitle', dict(media_id=self.assets()['lesson.mp4'],
                subtitle_id=self.assets()['lesson.srt'], language='fr', request_id='import-one'))
        self.assertEqual(raised.exception.code, 'REQUEST_CONFLICT')

    def test_concurrent_identical_imports_publish_one_source(self):
        from concurrent.futures import ThreadPoolExecutor
        assets = self.assets()
        arguments = {'media_id': assets['lesson.mp4'], 'subtitle_id': assets['lesson.srt'],
                     'request_id': 'concurrent-import'}
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.service.call('import_subtitle', arguments), range(8)))
        self.assertTrue(all(result == results[0] for result in results))
        self.assertEqual(len(self.state.records('sources')), 1)
        self.assertEqual(len(self.state.records('tracks')), 1)

    def test_live_service_owner_prevents_false_interruption_by_second_service(self):
        entered, release = threading.Event(), threading.Event()
        class Fake:
            def __init__(fake, **kwargs): pass
            def load_model(fake, **kwargs): pass
            def run(fake, path, **kwargs):
                entered.set()
                release.wait(5)
                return None
        self.service.close()
        self.service = self.api.Service(self.state, transcribe_factory=Fake)
        accepted = self.service.call('start_transcription', {'asset_id': self.assets()['lesson.mp4'],
                                                            'request_id': 'owner-job'})
        try:
            self.assertTrue(entered.wait(3))
            with self.assertRaises(MCPError) as raised:
                self.api.Service(self.state)
            self.assertEqual(raised.exception.code, 'SERVICE_BUSY')
            self.assertEqual(self.service.call('get_job', accepted)['state'], 'running')
        finally:
            release.set()
        self.wait_job(accepted['job_id'])

    def test_disabled_blocks_existing_content_and_revocation_blocks_sources(self):
        source = self.imported()
        self.state.configure(False, [self.media])
        for name, args in [('list_media', {'root_id': self.root_id}),
                           ('read_transcript', {'source_id': source['source_id']})]:
            with self.subTest(name=name), self.assertRaises(MCPError) as raised:
                self.service.call(name, args)
            self.assertEqual(raised.exception.code, 'MCP_DISABLED')
        self.state.configure(True, [])
        with self.assertRaises(MCPError) as raised:
            self.service.call('read_transcript', {'source_id': source['source_id']})
        self.assertEqual(raised.exception.code, 'ROOT_NOT_ALLOWED')

    def test_missing_model_fails_admission_without_queue_or_download(self):
        self.state.configure(True, [self.media], cache_dir=str(self.root / 'absent-model'))
        with self.assertRaises(MCPError) as raised:
            self.service.call('start_transcription', {'asset_id': self.assets()['lesson.mp4'],
                                                       'request_id': 'missing-model'})
        self.assertEqual(raised.exception.code, 'MODEL_DOWNLOAD_REQUIRED')
        self.assertEqual(self.state.records('jobs'), [])

    def test_injected_transcriber_snapshot_queue_cancel_and_off_metadata(self):
        entered, release = threading.Event(), threading.Event()
        original = (self.media / 'lesson.mp4').read_bytes()
        class Fake:
            def __init__(fake, **kwargs): pass
            def load_model(fake, **kwargs): pass
            def run(fake, path, **kwargs):
                self.assertNotEqual(Path(path).parent, self.media)
                self.assertEqual(Path(path).read_bytes(), original)
                entered.set()
                release.wait(5)
                output = Path(path).with_suffix('.srt')
                output.write_text(SRT)
                return str(output)
        self.service.close()
        self.service = self.api.Service(self.state, transcribe_factory=Fake)
        self.addCleanup(release.set)
        first = self.service.call('start_transcription', {'asset_id': self.assets()['lesson.mp4'],
                                                        'request_id': 'fake-first'})
        self.assertTrue(entered.wait(3))
        self.assertTrue(self.service.busy)
        second = self.service.call('start_transcription', {'asset_id': self.assets()['lesson.mp4'],
                                                         'request_id': 'fake-second'})
        self.service.call('cancel_job', {'job_id': second['job_id']})
        self.service.call('cancel_job', {'job_id': first['job_id']})
        self.state.configure(False, [self.media])
        self.assertEqual(self.service.call('get_job', first)['state'], 'cancelling')
        release.set()
        self.assertEqual(self.wait_job(first['job_id'])['state'], 'cancelled')
        self.assertEqual(self.wait_job(second['job_id'])['state'], 'cancelled')
        self.assertFalse(self.service.busy)
        self.assertEqual(self.state.records('sources'), [])

    def test_restart_marks_old_nonterminal_jobs_interrupted(self):
        self.state.put('jobs', 'abandoned', {'id': 'abandoned', 'state': 'running',
                       'kind': 'transcription', 'asset_id': self.assets()['lesson.mp4']})
        self.service.close()
        self.service = self.api.Service(self.state)
        result = self.service.call('get_job', {'job_id': 'abandoned'})
        self.assertEqual(result['state'], 'interrupted')
        self.assertEqual(result['error']['code'], 'JOB_INTERRUPTED')

    def test_durable_cancellation_from_other_idle_service_prevents_publication(self):
        entered, release = threading.Event(), threading.Event()
        class Fake:
            def __init__(fake, **kwargs): pass
            def load_model(fake, **kwargs): pass
            def run(fake, path, **kwargs):
                entered.set()
                release.wait(5)
                output = Path(path).with_suffix('.srt')
                output.write_text(SRT)
                return str(output)
        self.service.close()
        self.service = self.api.Service(self.state, transcribe_factory=Fake)
        other = self.api.Service(self.state)
        self.addCleanup(other.close)
        accepted = self.service.call('start_transcription', {'asset_id': self.assets()['lesson.mp4'],
                                                            'request_id': 'durable-cancel'})
        try:
            self.assertTrue(entered.wait(3))
            self.assertEqual(other.call('cancel_job', accepted)['state'], 'cancelling')
        finally:
            release.set()
        job = self.wait_job(accepted['job_id'])
        self.assertEqual(job['state'], 'cancelled', job)
        self.assertEqual(self.state.records('sources'), [])
        self.assertEqual(self.state.records('tracks'), [])

    def test_child_local_only_guard_sends_bounded_json_when_model_is_missing(self):
        import multiprocessing
        context = multiprocessing.get_context('spawn')
        read, write = context.Pipe(duplex=False)
        cancelled = context.Event()
        process = context.Process(target=self.api._inference_child,
            args=({'model': 'small', 'device': 'cpu', 'cache_dir': str(self.root / 'absent')},
                  str(self.root / 'unused.mp4'), write, cancelled))
        process.start()
        write.close()
        try:
            self.assertTrue(read.poll(5))
            message = json.loads(read.recv_bytes(4096).decode('utf-8'))
            self.assertEqual(message, {'error': 'MODEL_DOWNLOAD_REQUIRED'})
        finally:
            process.join(5)
            self.assertFalse(process.is_alive())
            read.close()
            process.close()
        self.assertFalse((self.root / 'absent').exists())

    def test_local_loader_refuses_missing_cache_without_invoking_downloader(self):
        import transcriber
        with patch.object(transcriber, 'download_model_with_progress', side_effect=AssertionError('download called')):
            with self.assertRaises(MCPError) as raised:
                self.api._local_model_path('small', download_root=str(self.root / 'absent'))
        self.assertEqual(raised.exception.code, 'MODEL_DOWNLOAD_REQUIRED')

    def test_waiting_inference_lock_can_be_cancelled_without_releasing_gui_lock(self):
        class Fake:
            def __init__(fake, **kwargs): raise AssertionError('Inference must not start')
        self.service.close()
        self.service = self.api.Service(self.state, transcribe_factory=Fake)
        lock = ProcessLock(self.state.path / 'locks', 'inference')
        self.assertTrue(lock.acquire())
        try:
            accepted = self.service.call('start_transcription', {'asset_id': self.assets()['lesson.mp4'],
                                                                'request_id': 'wait-lock'})
            deadline = time.monotonic() + 3
            while self.service.call('get_job', accepted)['state'] == 'queued' and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertEqual(self.service.call('get_job', accepted)['state'], 'preparing')
            time.sleep(.1)
            self.service.call('cancel_job', accepted)
            job = self.wait_job(accepted['job_id'])
            self.assertEqual(job['state'], 'cancelled')
            contender = ProcessLock(self.state.path / 'locks', 'inference')
            self.assertFalse(contender.acquire())
        finally:
            lock.release()

    def test_finish_disable_allows_admitted_work_but_root_removal_prevents_publication(self):
        for remove_root in (False, True):
            with self.subTest(remove_root=remove_root):
                entered, release = threading.Event(), threading.Event()
                class Fake:
                    def __init__(fake, **kwargs): pass
                    def load_model(fake, **kwargs): pass
                    def run(fake, path, **kwargs):
                        entered.set()
                        release.wait(5)
                        output = Path(path).with_suffix('.srt')
                        output.write_text(SRT)
                        return str(output)
                self.service.close()
                self.state.configure(True, [self.media])
                self.service = self.api.Service(self.state, transcribe_factory=Fake)
                accepted = self.service.call('start_transcription', {'asset_id': self.assets()['lesson.mp4'],
                    'request_id': 'finish-' + str(remove_root)})
                try:
                    self.assertTrue(entered.wait(3))
                    self.state.configure(False, [] if remove_root else [self.media], stop_mode='finish')
                finally:
                    release.set()
                job = self.wait_job(accepted['job_id'])
                self.assertEqual(job['state'], 'failed' if remove_root else 'succeeded', job)
                self.assertNotIn('result', job)
                if not remove_root:
                    self.state.configure(True, [self.media])
                    self.assertIn('source_id', self.service.call('get_job', accepted)['result'])


if __name__ == '__main__': unittest.main()
