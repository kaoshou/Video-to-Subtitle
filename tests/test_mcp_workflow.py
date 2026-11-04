"""End-user workflow tests with real private state and synthetic media."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from test_mcp_service import ServiceFixture, SRT
from mcp_state import MCPError
import json
import sys
import threading
import time


class PreviewTests(ServiceFixture):
    def test_preview_discloses_resolved_settings_without_queue_or_model_load(self):
        asset = self.assets()['lesson.mp4']
        with patch('transcriber.inspect_model_cache', return_value=SimpleNamespace(state='ready', path='/private/cache')), \
                patch('transcriber.SubtitleTranscriber.load_model', side_effect=AssertionError('preview loaded model')):
            result = self.service.call('preview_transcription', {'asset_id': asset,
                'settings': {'model': 'medium', 'device': 'cpu'}})
        self.assertTrue(result['can_start'])
        self.assertEqual(result['settings']['model'], 'medium')
        self.assertEqual(result['settings']['batch_mode'], 'auto')
        self.assertEqual(result['source_name'], 'lesson.mp4')
        self.assertEqual(result['output_parent'], str(self.media))
        self.assertEqual(result['project_type'], 'mp4')
        self.assertNotIn('cache_dir', result['settings'])
        self.assertNotIn('/private/cache', str(result))
        self.assertEqual(self.state.records('jobs'), [])
        self.assertEqual(self.state.records('requests'), [])

    def test_missing_model_blocks_and_preview_does_not_replace_execution_check(self):
        asset = self.assets()['lesson.mp4']
        with patch('transcriber.inspect_model_cache', return_value=SimpleNamespace(state='ready', path='/cache')):
            self.assertTrue(self.service.call('preview_transcription', {'asset_id': asset})['can_start'])
        with patch('transcriber.inspect_model_cache', return_value=SimpleNamespace(state='missing', path=None)):
            result = self.service.call('preview_transcription', {'asset_id': asset})
            self.assertFalse(result['can_start'])
            self.assertEqual(result['blockers'], ['MODEL_DOWNLOAD_REQUIRED'])
            self.assertEqual(result['settings']['model'], 'large-v3-turbo')
            with self.assertRaises(MCPError) as error:
                self.service.call('start_transcription', {'asset_id': asset, 'request_id': 'missing'})
            self.assertEqual(error.exception.code, 'MODEL_DOWNLOAD_REQUIRED')
        self.assertEqual(self.state.records('jobs'), [])

    def test_preview_rejects_revoked_asset_and_changed_source(self):
        asset = self.assets()['lesson.mp4']
        (self.media / 'lesson.mp4').write_bytes(b'changed')
        with self.assertRaises(MCPError) as error:
            self.service.call('preview_transcription', {'asset_id': asset})
        self.assertEqual(error.exception.code, 'SOURCE_CHANGED')
        self.state.disable()
        with self.assertRaises(MCPError):
            self.service.call('preview_transcription', {'asset_id': asset})


class ProgressTests(ServiceFixture):
    def test_live_progress_is_real_and_terminal_timing_excludes_queue(self):
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        class Engine:
            def __init__(self, **kwargs): pass
            def load_model(self, **kwargs): pass
            def run(self, path, **kwargs):
                kwargs['stage_callback']('recognition', 'no raw transcript')
                kwargs['progress_callback'](.5)
                entered.set()
                release.wait(3)
                output = Path(path).with_suffix('.srt'); output.write_text(SRT)
                return str(output)
        self.service.close()
        self.service = self.api.Service(self.state, transcribe_factory=Engine)
        asset = self.assets()['lesson.mp4']
        first = self.service.call('start_transcription', {'asset_id': asset, 'request_id': 'first'})
        self.assertTrue(entered.wait(2))
        live = self.service.call('get_job', first)
        self.assertEqual(live['progress'], {'stage': 'recognition', 'fraction': .5})
        self.assertIn('started_at', live)
        second = self.service.call('start_transcription', {'asset_id': asset, 'request_id': 'second'})
        self.assertNotIn('started_at', self.service.call('get_job', second))
        release.set()
        finished = self.wait_job(first['job_id'])
        self.assertGreaterEqual(finished['elapsed_seconds'], 0)
        self.assertGreaterEqual(finished['finished_at'], finished['started_at'])
        self.assertEqual(finished['progress'], {'stage': 'complete', 'fraction': 1.0})
        self.wait_job(second['job_id'])

    def test_emitter_ignores_invalid_progress_and_bounds_repeated_events(self):
        from mcp_progress import ProgressEmitter
        received = []
        emitter = ProgressEmitter(lambda event: received.append(event))
        emitter.stage('recognition')
        for value in (float('nan'), True, -1, 1.01, '0.5'):
            emitter.progress(value)
        emitter.progress(.5)
        for _ in range(1000):
            emitter.progress(.5)
        self.assertEqual(received, [{'stage': 'recognition', 'fraction': None},
                                    {'stage': 'recognition', 'fraction': .5}])
        emitter.stage('audio', 'private text')
        self.assertEqual(received[-1], {'stage': 'audio', 'fraction': None})

    def test_child_progress_messages_do_not_replace_terminal_report(self):
        class Engine:
            def __init__(self, **kwargs): pass
            def load_model(self, **kwargs): pass
            def run(self, path, **kwargs):
                kwargs['stage_callback']('recognition', 'private text')
                kwargs['progress_callback'](.5)
                return str(Path(path).with_suffix('.srt'))
        sent = []
        connection = SimpleNamespace(send_bytes=sent.append, close=lambda: None)
        module = SimpleNamespace(SubtitleTranscriber=Engine)
        with patch.dict(sys.modules, {'transcriber': module}), patch.object(self.api, '_ready'):
            self.api._child_run({'model': 'medium', 'device': 'cpu'}, str(self.media / 'lesson.mp4'),
                                connection, threading.Event())
        messages = [json.loads(raw) for raw in sent]
        self.assertTrue(messages[-1]['ok'])
        self.assertEqual(messages[-1]['transcription']['model'], 'medium')
        self.assertIn({'event': 'progress', 'stage': 'recognition', 'fraction': .5}, messages[:-1])
        self.assertNotIn('private text', str(messages))

    def test_cards_show_phase_progress_without_fabricating_old_timings(self):
        from mcp_jobs import job_card
        active = job_card({'id': 'one', 'kind': 'transcription', 'state': 'running',
                          'stage': 'recognition', 'progress': {'stage': 'recognition', 'fraction': .5}})
        self.assertIn('50%', active['progress_text'])
        unknown = job_card({'id': 'two', 'state': 'running', 'stage': 'model',
                           'progress': {'stage': 'model', 'fraction': None}})
        self.assertNotIn('%', unknown['progress_text'])
        old = job_card({'id': 'old', 'state': 'succeeded', 'stage': 'complete'})
        self.assertEqual(old['timing_text'], '')
        done = job_card({'id': 'done', 'state': 'succeeded', 'stage': 'complete', 'elapsed_seconds': 71.9})
        self.assertIn('1 分 12 秒', done['timing_text'])


class RecoveryTests(ServiceFixture):
    def test_new_conversation_discovers_source_and_only_missing_translation_batches(self):
        (self.media / 'lesson.srt').write_text(''.join(
            f'{i+1}\n00:00:{i % 60:02},000 --> 00:01:{i % 60:02},000\nSentence {i}\n\n' for i in range(51)))
        source = self.imported()
        draft = self.service.call('prepare_translation', {'source_id': source['source_id'],
            'revision': source['revision'], 'language': 'ja', 'request_id': 'draft'})
        batch = self.service.call('get_translation_batch', {'draft_id': draft['draft_id'],
            'batch_id': draft['batches'][0]['batch_id']})
        args = {'draft_id': draft['draft_id'], 'batch_id': batch['batch_id'], 'revision': source['revision'],
            'translations': [{'cue_id': cue['cue_id'], 'text': '訳文'} for cue in batch['cues']], 'request_id': 'batch'}
        self.service.call('submit_translation_batch', args)
        self.service.close(); self.service = self.api.Service(self.state)
        asset = self.assets()['lesson.mp4']
        first = self.service.call('list_work', {'asset_id': asset, 'limit': 1})
        self.assertEqual(len(first['items']), 1)
        self.assertIsNotNone(first['next_cursor'])
        result = self.service.call('list_work', {'asset_id': asset})
        src = next(item for item in result['items'] if item['kind'] == 'source')
        self.assertEqual(src['source_id'], source['source_id'])
        self.assertIn(source['track_id'], src['track_ids'])
        self.assertTrue(src['revision_valid'])
        pending = next(item for item in result['items'] if item['kind'] == 'translation')
        self.assertEqual((pending['completed_batches'], pending['missing_batches']), (1, 1))
        self.assertEqual(pending['next_action'], 'resume_translation')
        self.assertNotIn('Sentence', str(result))
        # Replaying the same batch is safe and does not erase prior work.
        self.assertEqual(self.service.call('submit_translation_batch', args)['accepted'], True)

    def test_changed_subtitle_is_marked_stale_and_revoked_media_is_not_disclosed(self):
        self.imported()
        asset = self.assets()['lesson.mp4']
        (self.media / 'lesson.srt').write_text(SRT + '\n')
        result = self.service.call('list_work', {'asset_id': asset})
        source = next(i for i in result['items'] if i['kind'] == 'source')
        self.assertFalse(source['revision_valid'])
        self.assertEqual(source['next_action'], 'reimport_source')
        self.state.configure(True, [], access_mode='restricted')
        with self.assertRaises(MCPError):
            self.service.call('list_work', {'asset_id': asset})

    def test_interrupted_inference_explicitly_requires_restart_not_resume(self):
        asset = self.assets()['lesson.mp4']
        self.state.put('jobs', 'old', {'id': 'old', 'asset_id': asset, 'kind': 'transcription',
            'state': 'interrupted'})
        result = self.service.call('list_work', {'asset_id': asset})
        job = next(i for i in result['items'] if i['kind'] == 'job')
        self.assertEqual(job['next_action'], 'restart_with_new_request_id')
