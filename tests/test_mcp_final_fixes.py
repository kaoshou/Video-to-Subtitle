import os
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

from mcp_state import MCPError, ProcessLock
from test_mcp_service import ServiceFixture, SRT


class AuthorizationFixTests(ServiceFixture):
    def test_export_attests_pinned_stage_without_reopening_delete_leased_folder(self):
        # Windows refuses a new non-delete-shared open while the exclusive
        # publisher still holds its DELETE-capable handle. Keep that lease.
        source = self.imported()
        original = self.api.SafeDirectory.child
        def no_reopen(directory, name, *args, **kwargs):
            if Path(directory.path) == self.media and name == 'lesson-web':
                raise PermissionError(13, 'published folder still has a delete-capable lease')
            return original(directory, name, *args, **kwargs)
        with patch.object(self.api.SafeDirectory, 'child', no_reopen):
            accepted = self.service.call('export_player', {'asset_id': self.assets()['lesson.mp4'],
                'track_ids': [source['track_id']], 'request_id': 'leased-export'})
            self.service._queue.join()
        job = self.state.get('jobs', accepted['job_id'])
        self.assertEqual(job['state'], 'succeeded', job)
        opened = []
        from mcp_runtime import open_job_result
        open_job_result(self.state, accepted['job_id'], opener=opened.append)
        self.assertTrue(opened[0].endswith('/lesson-web/index.html'))

    def test_local_open_result_revalidates_root_and_published_identity(self):
        import mcp_runtime
        source = self.imported()
        accepted = self.service.call('export_player', {'asset_id': self.assets()['lesson.mp4'],
            'track_ids': [source['track_id']], 'request_id': 'open-result'})
        job = self.wait_job(accepted['job_id'])
        opened = []
        mcp_runtime.open_job_result(self.state, accepted['job_id'], opener=opened.append)
        self.assertTrue(opened[0].endswith('/lesson-web/index.html'))
        (self.media / 'lesson-web' / 'index.html').write_text('replacement')
        with self.assertRaises(MCPError):
            mcp_runtime.open_job_result(self.state, accepted['job_id'], opener=opened.append)
        self.state.configure(True, [])
        with self.assertRaises(MCPError):
            mcp_runtime.open_job_result(self.state, accepted['job_id'], opener=opened.append)
        self.assertEqual(len(opened), 1)

    def test_disabled_offline_job_controls_are_metadata_only(self):
        from mcp_transport import BrokerClient
        self.state.put('jobs', 'offline', {'id': 'offline', 'state': 'succeeded', 'stage': 'complete',
            'asset_id': 'missing', 'result': {'index_path': '/private/result'}, 'text': 'subtitle-secret'})
        self.state.disable()
        client = BrokerClient(self.state)
        result = client.call('get_job', {'job_id': 'offline'})
        self.assertEqual(result, {'job_id': 'offline', 'state': 'succeeded', 'stage': 'complete'})
        self.assertEqual(client.call('cancel_job', {'job_id': 'offline'})['state'], 'succeeded')

    def test_export_commit_serializes_revoke_and_cancel_at_real_publish(self):
        source = self.imported()
        original = self.api.StagedDirectory.publish
        attempted, finished = threading.Event(), threading.Event()
        revokers = []
        def publish(stage, name):
            if name == 'lesson-web':
                def revoke():
                    attempted.set()
                    self.state.disable('cancel')
                    finished.set()
                worker = threading.Thread(target=revoke)
                revokers.append(worker)
                worker.start()
                self.assertTrue(attempted.wait(2))
                self.assertFalse(finished.wait(.08), 'revocation completed inside publication commit')
            return original(stage, name)
        with patch.object(self.api.StagedDirectory, 'publish', publish):
            accepted = self.service.call('export_player', {'asset_id': self.assets()['lesson.mp4'],
                'track_ids': [source['track_id']], 'request_id': 'commit-export'})
            self.service._queue.join()
        for worker in revokers:
            worker.join(3)
        saved = self.state.get('jobs', accepted['job_id'])
        self.assertEqual(saved['state'], 'succeeded', saved)
        self.assertTrue((self.media / 'lesson-web' / 'index.html').is_file())
        self.assertTrue(finished.is_set())

    def test_transcription_commit_serializes_cancel_at_real_source_write(self):
        class Fake:
            def __init__(self, **kwargs): pass
            def load_model(self, **kwargs): pass
            def run(self, path, **kwargs):
                output = Path(path).with_suffix('.srt')
                output.write_text(SRT)
                return str(output)
        self.service.close()
        self.service = self.api.Service(self.state, transcribe_factory=Fake)
        original = self.state.put
        attempted, finished = threading.Event(), threading.Event()
        cancellers = []
        def put(kind, key, data):
            if kind == 'sources':
                job = self.state.records('jobs')[0]
                def cancel():
                    attempted.set()
                    self.service._cancel_job(job['id'])
                    finished.set()
                worker = threading.Thread(target=cancel)
                cancellers.append(worker)
                worker.start()
                self.assertTrue(attempted.wait(2))
                self.assertFalse(finished.wait(.08), 'cancel completed inside source commit')
            return original(kind, key, data)
        with patch.object(self.state, 'put', side_effect=put):
            accepted = self.service.call('start_transcription', {'asset_id': self.assets()['lesson.mp4'],
                'request_id': 'commit-transcription'})
            self.service._queue.join()
        for worker in cancellers:
            worker.join(3)
        self.assertEqual(self.state.get('jobs', accepted['job_id'])['state'], 'succeeded')
        self.assertTrue(finished.is_set())

    def test_replacement_real_root_needs_new_authorization(self):
        old = self.media.with_name('old-media')
        self.media.rename(old)
        self.media.mkdir()
        (self.media / 'lesson.srt').write_text('replacement')
        with self.assertRaises(MCPError) as error:
            with self.state.file(self.root_id, 'lesson.srt'):
                pass
        self.assertEqual(error.exception.code, 'ROOT_NOT_ALLOWED')
        new = self.state.configure(True, [self.media])['roots'][0]['id']
        self.assertNotEqual(new, self.root_id)

    def test_legacy_grant_without_identity_fails_closed_with_reauthorization(self):
        policy = self.state.policy()
        policy['roots'][0].pop('identity', None)
        import json
        (self.state.path / 'policy.json').write_text(json.dumps(policy))
        with self.assertRaisesRegex(MCPError, 'reauthoriz'):
            with self.state.file(self.root_id, 'lesson.srt'):
                pass

    def test_unchanged_policy_keeps_finish_admission(self):
        first = self.state.policy()['generation']
        self.state.configure(True, [self.media])
        self.state.disable('finish')
        with self.state.file(self.root_id, 'lesson.srt', admitted_generation=first) as stream:
            self.assertIn(b'First', stream.read())
        self.state.disable('cancel')
        with self.assertRaises(MCPError):
            self.state.require_enabled(admitted_generation=first)

    def test_cancel_then_reenable_does_not_restore_old_job_admission(self):
        generation = self.state.policy()['generation']
        self.state.disable('cancel')
        self.state.configure(True, [self.media])
        with self.assertRaises(MCPError) as error:
            self.state.require_enabled(admitted_generation=generation)
        self.assertEqual(error.exception.code, 'MCP_DISABLED')

    def test_root_reduction_works_during_inference_with_unavailable_kept_root(self):
        from mcp_runtime import enable
        unavailable = self.root / 'unavailable'
        unavailable.mkdir()
        before = self.state.configure(True, [self.media, unavailable], model='small')
        unavailable.rmdir()
        lock = ProcessLock(self.state.path / 'locks', 'inference')
        self.assertTrue(lock.acquire())
        try:
            result = enable(self.state, [unavailable], model='small')
        finally:
            lock.release()
        self.assertEqual(result['roots'], [before['roots'][1]])
        self.assertEqual(result['options'], before['options'])

    def test_queued_input_change_never_enters_inference(self):
        ran = threading.Event()
        class Fake:
            def __init__(self, **kwargs): ran.set()
            def load_model(self, **kwargs): pass
            def run(self, path, **kwargs):
                output = Path(path).with_suffix('.srt')
                output.write_text(SRT)
                return str(output)
        self.service.close()
        self.service = self.api.Service(self.state, transcribe_factory=Fake)
        asset = self.assets()['lesson.mp4']
        lock = ProcessLock(self.state.path / 'locks', 'inference')
        self.assertTrue(lock.acquire())
        try:
            job = self.service.call('start_transcription', {'asset_id': asset, 'request_id': 'queued-version'})
            with (self.media / 'lesson.mp4').open('ab') as stream:
                stream.write(b'changed after admission')
        finally:
            lock.release()
        # Changed assets deliberately disallow content-bearing get_job.
        self.service._queue.join()
        saved = self.state.get('jobs', job['job_id'])
        self.assertEqual(saved['state'], 'failed')
        self.assertEqual(saved['error']['code'], 'SOURCE_CHANGED')
        self.assertFalse(ran.is_set())

    def test_queued_real_root_replacement_never_enters_inference(self):
        ran = threading.Event()
        class Fake:
            def __init__(self, **kwargs): ran.set()
        self.service.close()
        self.service = self.api.Service(self.state, transcribe_factory=Fake)
        asset = self.assets()['lesson.mp4']
        replaced = threading.Event()
        checkpoint = self.service._checkpoint
        def after_replacement(job):
            self.assertTrue(replaced.wait(5), 'replacement did not complete')
            return checkpoint(job)
        # Pause before the worker's first check, not merely its inference lock:
        # this fixture tests a complete real-directory replacement rather than
        # the equally fail-closed but differently classified rename gap.
        with patch.object(self.service, '_checkpoint', side_effect=after_replacement):
            try:
                job = self.service.call('start_transcription', {'asset_id': asset, 'request_id': 'queued-root'})
                old = self.media.with_name('original-root')
                self.media.rename(old)
                self.media.mkdir()
                (self.media / 'lesson.mp4').write_bytes((old / 'lesson.mp4').read_bytes())
            finally:
                replaced.set()
            self.service._queue.join()
        saved = self.state.get('jobs', job['job_id'])
        self.assertEqual(saved['state'], 'failed')
        self.assertEqual(saved['error']['code'], 'ROOT_NOT_ALLOWED')
        self.assertFalse(ran.is_set())
        self.assertEqual(self.state.records('sources'), [])

    def test_read_after_hash_revocation_does_not_return_cached_text(self):
        for tool in ('read_transcript', 'get_translation_batch'):
            self.root_id = self.state.configure(True, [self.media])['roots'][0]['id']
            assets = self.assets()
            source = self.service.call('import_subtitle', {'media_id': assets['lesson.mp4'],
                'subtitle_id': assets['lesson.srt'], 'request_id': 'import-' + tool})
            draft = self.service.call('prepare_translation', {
                'source_id': source['source_id'], 'revision': source['revision'],
                'language': 'fr', 'request_id': 'draft-' + tool})
            arguments = ({'source_id': source['source_id']} if tool == 'read_transcript' else
                         {'draft_id': draft['draft_id'], 'batch_id': draft['batches'][0]['batch_id']})
            original = self.api._stream_hash
            def revoke(stream):
                value = original(stream)
                self.state.configure(True, [])
                return value
            with patch.object(self.api, '_stream_hash', side_effect=revoke):
                with self.assertRaises(MCPError) as error:
                    self.service.call(tool, arguments)
                self.assertEqual(error.exception.code, 'ROOT_NOT_ALLOWED')

    def test_new_service_discovers_and_resumes_partial_draft_without_request_id(self):
        source = self.imported()
        draft = self.service.call('prepare_translation', {'source_id': source['source_id'],
            'revision': source['revision'], 'language': 'fr', 'request_id': 'lost-request'})
        batch = self.service.call('get_translation_batch', {'draft_id': draft['draft_id'],
            'batch_id': draft['batches'][0]['batch_id']})
        self.service.call('submit_translation_batch', {'draft_id': draft['draft_id'],
            'batch_id': batch['batch_id'], 'revision': source['revision'], 'request_id': 'saved-batch',
            'translations': [{'cue_id': c['cue_id'], 'text': 'Traduction'} for c in batch['cues']]})
        self.service.close()
        self.service = self.api.Service(self.state)
        found = self.service.call('list_translation_drafts', {'source_id': source['source_id'], 'language': 'fr'})
        self.assertEqual(len(found['items']), 1)
        recovered = found['items'][0]
        self.assertEqual(recovered['draft_id'], draft['draft_id'])
        self.assertEqual(recovered['completed_batches'], [batch['batch_id']])
        self.assertEqual(recovered['missing_batches'], [])
        track = self.service.call('finalize_translation', {'draft_id': recovered['draft_id'], 'request_id': 'new-client'})
        found = self.service.call('list_translation_drafts', {'source_id': source['source_id'], 'language': 'fr'})
        self.assertEqual(found['items'][0]['track_id'], track['track_id'])

    def test_translation_context_is_bounded_and_cannot_be_submitted(self):
        (self.media / 'lesson.srt').write_text('\n\n'.join(
            f'{i+1}\n00:00:00,123 --> 00:00:00,456\nCue {i+1}' for i in range(101)))
        source = self.imported()
        draft = self.service.call('prepare_translation', {'source_id': source['source_id'],
            'revision': source['revision'], 'language': 'fr', 'request_id': 'context'})
        for index, summary in enumerate(draft['batches']):
            batch = self.service.call('get_translation_batch', {'draft_id': draft['draft_id'], 'batch_id': summary['batch_id']})
            self.assertEqual([c['text'] for c in batch['context_before']],
                             [[], ['Cue 49', 'Cue 50'], ['Cue 99', 'Cue 100']][index])
            self.assertEqual([c['text'] for c in batch['context_after']],
                             [['Cue 51', 'Cue 52'], ['Cue 101'], []][index])
            self.assertEqual(batch['context_role'], 'read_only_not_for_translation')
            if batch['context_after']:
                with self.assertRaises(MCPError):
                    self.service.call('submit_translation_batch', {'draft_id': draft['draft_id'],
                        'batch_id': summary['batch_id'], 'revision': source['revision'], 'request_id': f'bad-{index}',
                        'translations': [{'cue_id': c['cue_id'], 'text': 'Wrong'} for c in batch['context_after']]})


if __name__ == '__main__':
    unittest.main()
