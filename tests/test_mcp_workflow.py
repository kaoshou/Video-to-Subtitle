"""End-user workflow tests with real private state and synthetic media."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from test_mcp_service import ServiceFixture, SRT
from mcp_state import MCPError


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
