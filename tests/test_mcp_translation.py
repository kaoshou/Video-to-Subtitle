import json
from pathlib import Path
import time
import unittest
from unittest.mock import patch

from mcp_state import MCPError
from test_mcp_service import ServiceFixture


class TranslationTests(ServiceFixture):
    def prepare(self, source, language='fr', request='prepare-fr'):
        return self.service.call('prepare_translation', {
            'source_id': source['source_id'], 'revision': source['revision'],
            'language': language, 'request_id': request})

    def submit(self, draft, request='submit-fr', entries=None, **extra):
        batch = self.service.call('get_translation_batch', {
            'draft_id': draft['draft_id'], 'batch_id': draft['batches'][0]['batch_id']})
        return self.service.call('submit_translation_batch', {
            'draft_id': draft['draft_id'], 'batch_id': batch['batch_id'],
            'revision': draft['revision'], 'request_id': request,
            'translations': entries if entries is not None else [
                {'cue_id': c['cue_id'], 'text': 'Translated ' + c['text']} for c in batch['cues']],
            **extra})

    def test_real_import_two_language_finalize_and_player_export_preserve_timing(self):
        source = self.imported()
        tracks = [source['track_id']]
        for language in ('fr', 'ja'):
            draft = self.prepare(source, language, 'prepare-' + language)
            self.submit(draft, 'submit-' + language)
            result = self.service.call('finalize_translation', {
                'draft_id': draft['draft_id'], 'request_id': 'final-' + language})
            tracks.append(result['track_id'])
        args = {'asset_id': self.assets()['lesson.mp4'], 'track_ids': tracks,
                'request_id': 'export-once', 'default_subtitle': 'fr'}
        accepted = self.service.call('export_player', args)
        job = self.wait_job(accepted['job_id'])
        self.assertEqual(job['state'], 'succeeded', job)
        output = Path(job['result']['folder'])
        self.assertTrue((output / 'index.html').is_file())
        expected = ['00:00:00,123 --> 00:00:00,456', '00:00:00,400 --> 00:00:00,987']
        for language in ('fr', 'ja'):
            text = (output / ('media.' + language + '.srt')).read_text()
            self.assertEqual([line for line in text.splitlines() if '-->' in line], expected)
        self.assertEqual(self.service.call('export_player', args), accepted)
        self.assertEqual(len(list(self.media.glob('lesson-web*'))), 1)
        config = json.loads((output / 'web-export.json').read_text())
        self.assertEqual([t['language'] for t in config['subtitles']], ['en', 'fr', 'ja'])

    def test_batch_missing_duplicate_foreign_or_timing_input_fails_atomically(self):
        source = self.imported()
        draft = self.prepare(source)
        batch = self.service.call('get_translation_batch', {
            'draft_id': draft['draft_id'], 'batch_id': draft['batches'][0]['batch_id']})
        valid = [{'cue_id': c['cue_id'], 'text': 'Bonjour'} for c in batch['cues']]
        invalid = [valid[:1], [valid[0], valid[0]],
                   [valid[0], {'cue_id': 'foreign', 'text': 'Bonjour'}],
                   [dict(valid[0], start=0), valid[1]]]
        for i, entries in enumerate(invalid):
            with self.subTest(i=i), self.assertRaises(MCPError):
                self.submit(draft, 'bad-' + str(i), entries)
            stored = self.state.get('drafts', draft['draft_id'])
            self.assertEqual(stored['translations'], {})
        with self.assertRaises(MCPError) as raised:
            self.service.call('finalize_translation', {'draft_id': draft['draft_id'], 'request_id': 'incomplete'})
        self.assertEqual(raised.exception.code, 'TRANSLATION_INCOMPLETE')
        self.submit(draft)
        self.assertEqual(self.submit(draft), {'accepted': True, 'batch_id': batch['batch_id']})

    def test_source_changed_or_wrong_revision_blocks_translation(self):
        source = self.imported()
        with self.assertRaises(MCPError) as raised:
            self.prepare(dict(source, revision='wrong'))
        self.assertEqual(raised.exception.code, 'REVISION_CONFLICT')
        draft = self.prepare(source, request='prepare-valid')
        (self.media / 'lesson.srt').write_text('changed')
        with self.assertRaises(MCPError) as raised:
            self.submit(draft)
        self.assertEqual(raised.exception.code, 'SOURCE_CHANGED')

    def test_revocation_during_final_render_blocks_track_publication(self):
        source = self.imported()
        draft = self.prepare(source)
        self.submit(draft)
        original = self.api.render_srt
        def revoke_during_render(*args, **kwargs):
            result = original(*args, **kwargs)
            self.state.configure(True, [])
            return result
        with patch.object(self.api, 'render_srt', revoke_during_render):
            with self.assertRaises(MCPError) as raised:
                self.service.call('finalize_translation', {
                    'draft_id': draft['draft_id'], 'request_id': 'revoke-finalize'})
        self.assertEqual(raised.exception.code, 'ROOT_NOT_ALLOWED')
        self.assertEqual([track['id'] for track in self.state.records('tracks')], [source['track_id']])
        self.assertNotIn('track_id', self.state.get('drafts', draft['draft_id']))

    def test_final_authorization_and_track_write_share_policy_lock(self):
        source = self.imported()
        draft = self.prepare(source)
        self.submit(draft)
        original = self.state.put
        def assert_guarded_publication(kind, id, data):
            if kind == 'tracks':
                from mcp_state import ProcessLock
                contender = ProcessLock(self.state.path / 'locks', 'policy')
                acquired = contender.acquire()
                if acquired:
                    contender.release()
                self.assertFalse(acquired, 'Policy changes can race final authorized track publication')
            return original(kind, id, data)
        with patch.object(self.state, 'put', assert_guarded_publication):
            result = self.service.call('finalize_translation', {
                'draft_id': draft['draft_id'], 'request_id': 'guarded-finalize'})
        self.assertTrue(result['complete'])

    def test_batches_bound_cues_and_characters_and_reject_one_oversize_cue(self):
        text = '\n\n'.join(f'{i}\n00:00:00,123 --> 00:00:00,987\n' + 'x' * 200 for i in range(1, 52))
        (self.media / 'lesson.srt').write_text(text)
        source = self.imported()
        draft = self.prepare(source)
        counts = [b['cue_count'] for b in draft['batches']]
        self.assertEqual(counts, [40, 11])
        (self.media / 'lesson.srt').write_text('1\n00:00:00,123 --> 00:00:00,987\n' + 'x' * 8001)
        assets = self.assets()
        source = self.service.call('import_subtitle', {'media_id': assets['lesson.mp4'],
            'subtitle_id': assets['lesson.srt'], 'request_id': 'large-import'})
        with self.assertRaises(MCPError): self.prepare(source, request='large-prepare')

    def test_incomplete_or_foreign_tracks_never_enter_export_queue(self):
        source = self.imported()
        draft = self.prepare(source)
        self.state.put('tracks', 'incomplete', {'id': 'incomplete', 'complete': False})
        with self.assertRaises(MCPError) as raised:
            self.service.call('export_player', {'asset_id': self.assets()['lesson.mp4'],
                'track_ids': [source['track_id'], 'incomplete'], 'request_id': 'incomplete-export'})
        self.assertEqual(raised.exception.code, 'TRANSLATION_INCOMPLETE')
        self.assertEqual(self.state.records('jobs'), [])

    def test_source_media_changed_during_export_blocks_publication(self):
        source = self.imported()
        original = self.api.export_package
        def changed_after_build(*args, **kwargs):
            result = original(*args, **kwargs)
            with (self.media / 'lesson.mp4').open('ab') as output:
                output.write(b'changed')
            return result
        with patch.object(self.api, 'export_package', changed_after_build):
            accepted = self.service.call('export_player', {'asset_id': self.assets()['lesson.mp4'],
                'track_ids': [source['track_id']], 'request_id': 'changed-export'})
            job = self.wait_job(accepted['job_id'])
        self.assertEqual(job['state'], 'failed', job)
        self.assertEqual(job['error']['code'], 'SOURCE_CHANGED')
        self.assertEqual(list(self.media.glob('lesson-web*')), [])

    def test_cancel_or_root_revocation_during_export_prevents_publication(self):
        source = self.imported()
        original = self.api.export_package
        def revoked_after_build(*args, **kwargs):
            result = original(*args, **kwargs)
            self.state.configure(True, [])
            return result
        with patch.object(self.api, 'export_package', revoked_after_build):
            accepted = self.service.call('export_player', {'asset_id': self.assets()['lesson.mp4'],
                'track_ids': [source['track_id']], 'request_id': 'revoked-export'})
            deadline = time.monotonic() + 5
            while self.service.busy and time.monotonic() < deadline:
                time.sleep(.01)
        job = self.state.get('jobs', accepted['job_id'])
        self.assertEqual(job['state'], 'failed')
        self.assertEqual(job['error']['code'], 'ROOT_NOT_ALLOWED')
        self.assertEqual(list(self.media.glob('lesson-web*')), [])

    def test_cancel_during_final_stream_copy_preserves_cancelled_state(self):
        source = self.imported()
        original = self.api.StagedDirectory.copy_from
        def cancel_after_copy(stage, *args, **kwargs):
            result = original(stage, *args, **kwargs)
            if Path(stage.parent.path) == self.media:
                job = self.state.records('jobs')[0]
                self.service.call('cancel_job', {'job_id': job['id']})
            return result
        with patch.object(self.api.StagedDirectory, 'copy_from', cancel_after_copy):
            accepted = self.service.call('export_player', {'asset_id': self.assets()['lesson.mp4'],
                'track_ids': [source['track_id']], 'request_id': 'cancel-copy'})
            job = self.wait_job(accepted['job_id'])
        self.assertEqual(job['state'], 'cancelled', job)
        self.assertEqual(list(self.media.glob('lesson-web*')), [])

    def test_cancel_after_exclusive_publish_preserves_success_and_artifact(self):
        import threading
        source = self.imported()
        original = self.api.StagedDirectory.publish
        cancellers = []
        def cancel_after_publish(stage, name):
            result = original(stage, name)
            if Path(stage.parent.path) == self.media:
                job = self.state.records('jobs')[0]
                worker = threading.Thread(target=lambda: self.service.call('cancel_job', {'job_id': job['id']}))
                cancellers.append(worker)
                worker.start()
            return result
        with patch.object(self.api.StagedDirectory, 'publish', cancel_after_publish):
            accepted = self.service.call('export_player', {'asset_id': self.assets()['lesson.mp4'],
                'track_ids': [source['track_id']], 'request_id': 'cancel-published'})
            job = self.wait_job(accepted['job_id'])
        for worker in cancellers:
            worker.join(3)
            self.assertFalse(worker.is_alive())
        self.assertEqual(job['state'], 'succeeded', job)
        self.assertTrue(Path(job['result']['index_path']).is_file())


if __name__ == '__main__': unittest.main()
