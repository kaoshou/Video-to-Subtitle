import json
from pathlib import Path
from unittest.mock import patch

from mcp_state import MCPError
from test_mcp_service import ServiceFixture, SRT
from test_web_export_inputs import make_video


class ProjectPlayers(ServiceFixture):
    def project(self, kind, subtitles=None):
        make_video(self.media / 'media.mp4')
        (self.media / 'media.srt').write_text(SRT, encoding='utf-8')
        if kind == 'opencam':
            data = dict(format='opencam.web-player', schemaVersion=1, entry='index.html',
                        media='media.mp4', title='課程',
                        chapters=[dict(title='第一章', start=0, end=1)], subtitles=subtitles)
            (self.media / 'index.html').write_text('<script src="opencam-player.js"></script><video src="media.mp4"></video>', encoding='utf-8')
            (self.media / 'opencam-player.js').write_text('window.OpenCamPlayerData = ' + json.dumps(data) + ';', encoding='utf-8')
        else:
            (self.media / 'config.js').write_text('var config = {title:"課程",index:[{title:"第一章",time:0}],src:[{src:"media.mp4"}]};', encoding='utf-8')
            (self.media / 'index.html').write_text('original evercam', encoding='utf-8')
        listed = self.service.call('list_media', {'root_id': self.root_id})['items']
        item = next(i for i in listed if i['name'] == 'media.mp4')
        sub = next(i for i in listed if i['name'] == 'media.srt')
        imported = self.service.call('import_subtitle', dict(media_id=item['asset_id'],
            subtitle_id=sub['asset_id'], language='en', request_id='import-project'))
        return item, imported['track_id']

    def export(self, item, track, **options):
        accepted = self.service.call('export_player', dict(asset_id=item['asset_id'],
            track_ids=[track], request_id=options.pop('request_id', 'export-project'), **options))
        result = self.wait_job(accepted['job_id'])
        self.assertEqual(result['state'], 'succeeded', result)
        return Path(result['result']['folder']), result['result']

    def test_opencam_auto_export_preserves_chapters_existing_languages_and_source(self):
        other = dict(id='ja', language='ja', label='日本語', cues=[dict(start=0, end=.5, text='こんにちは')])
        item, track = self.project('opencam', dict(defaultTrackId='ja', tracks=[other]))
        self.assertEqual(item['project_type'], 'opencam')
        before = (self.media / 'opencam-player.js').read_bytes()
        folder, result = self.export(item, track)
        from opencam_integration import load_project
        data = load_project(folder).data
        self.assertEqual(result['player_type'], 'opencam')
        self.assertEqual(set(result['languages']), {'en', 'ja'})
        self.assertEqual(result['cue_counts']['ja'], 1)
        self.assertIn('ja', result['unchecked_languages'])
        self.assertEqual(data['chapters'][0]['title'], '第一章')
        self.assertEqual({t['language'] for t in data['subtitles']['tracks']}, {'en', 'ja'})
        self.assertEqual(data['subtitles']['tracks'][0], other)
        self.assertEqual((self.media / 'opencam-player.js').read_bytes(), before)
        self.assertTrue(list(folder.glob('opencam-player.backup-*.js')))
        self.assertNotEqual(self.export(item, track, request_id='export-again')[0], folder)

    def test_opencam_without_subtitles_and_explicit_mp4_override(self):
        item, track = self.project('opencam')
        folder, _ = self.export(item, track, title='新標題', default_subtitle='off')
        from opencam_integration import load_project
        data = load_project(folder).data
        self.assertEqual(data['title'], '新標題')
        self.assertEqual(data['subtitles']['defaultTrackId'], 'off')
        generic, result = self.export(item, track, request_id='generic', player_type='mp4')
        self.assertEqual(result['player_type'], 'mp4')
        self.assertTrue((generic / 'web-export.json').exists())

    def test_evercam_exports_native_chapters_and_multiple_languages(self):
        item, track = self.project('evercam')
        # Relist after adding a project resource, as required for a new revision.
        (self.media / 'media.ja.srt').write_text(SRT.replace('First', '日本語'), encoding='utf-8')
        item = next(i for i in self.service.call('list_media', {'root_id': self.root_id})['items'] if i['name'] == 'media.mp4')
        imported = self.service.call('import_subtitle', dict(media_id=item['asset_id'],
            subtitle_id=self.assets()['media.srt'], language='en', request_id='import-current'))
        folder, result = self.export(item, imported['track_id'])
        self.assertEqual(item['project_type'], 'evercam')
        self.assertEqual(result['player_type'], 'evercam')
        self.assertTrue({'en', 'ja'} <= set(result['languages']))
        self.assertIn('ja', result['unchecked_languages'])
        self.assertIn('第一章', (folder / 'config.js').read_text(encoding='utf-8'))
        payload = (folder / 'subtitles-data.js').read_text(encoding='utf-8').split('window.EVERCAM_SUBTITLES = ', 1)[1].strip().removesuffix(';')
        self.assertTrue({'en', 'ja'} <= {t['language'] for t in json.loads(payload)['tracks']})
        self.assertEqual((self.media / 'index.html').read_text(encoding='utf-8'), 'original evercam')

    def test_unrelated_mp4_is_not_opencam_and_explicit_mismatch_fails(self):
        self.project('opencam')
        item = next(i for i in self.service.call('list_media', {'root_id': self.root_id})['items'] if i['name'] == 'lesson.mp4')
        self.assertEqual(item['project_type'], 'mp4')
        imported = self.imported()
        with self.assertRaises(MCPError) as caught:
            self.service.call('export_player', dict(asset_id=item['asset_id'], track_ids=[imported['track_id']],
                player_type='evercam', request_id='mismatch'))
        self.assertEqual(caught.exception.code, 'PROJECT_TYPE_MISMATCH')

    def test_project_change_after_listing_is_rejected(self):
        item, track = self.project('opencam')
        data = self.media / 'opencam-player.js'
        data.write_bytes(data.read_bytes() + b'\n')
        with self.assertRaises(MCPError) as caught:
            self.export(item, track)
        self.assertEqual(caught.exception.code, 'PROJECT_CHANGED')

    def test_valid_self_contained_opencam_index_above_generic_resource_limit(self):
        self.project('opencam')
        index = self.media / 'index.html'
        index.write_bytes(b'<!--' + b'x' * (8 * 1024 * 1024) + b'--><video src="media.mp4"></video>')
        entries = self.service.call('list_media', {'root_id': self.root_id})['items']
        item = next(i for i in entries if i['name'] == 'media.mp4')
        imported = self.service.call('import_subtitle', dict(media_id=item['asset_id'],
            subtitle_id=self.assets()['media.srt'], language='en', request_id='large-index'))
        folder, _ = self.export(item, imported['track_id'])
        self.assertEqual((folder / 'index.html').read_bytes(), index.read_bytes())

    def test_changed_project_during_build_is_never_published(self):
        item, track = self.project('evercam')
        from mcp_projects import build_project
        def changed(*args):
            built = build_project(*args)
            config = self.media / 'config.js'
            config.write_bytes(config.read_bytes() + b'\n//changed')
            return built
        with patch('mcp_service.build_project', side_effect=changed):
            accepted = self.service.call('export_player', dict(asset_id=item['asset_id'],
                track_ids=[track], request_id='change-during-build'))
            result = self.wait_job(accepted['job_id'])
        self.assertEqual(result['state'], 'failed')
        self.assertEqual(result['error']['code'], 'PROJECT_CHANGED')
        self.assertFalse((self.media / 'media-web').exists())

    def test_selected_evercam_language_replaces_old_vtt_and_sets_default(self):
        self.project('evercam')
        (self.media / 'media.en.vtt').write_text('WEBVTT\n\n00:00.000 --> 00:00.500\nOLD\n')
        assets = self.service.call('list_media', {'root_id': self.root_id})['items']
        item = next(i for i in assets if i['name'] == 'media.mp4')
        source = self.service.call('import_subtitle', dict(media_id=item['asset_id'],
            subtitle_id=self.assets()['media.srt'], language='en', request_id='replace-old'))
        folder, _ = self.export(item, source['track_id'])
        self.assertFalse((folder / 'media.en.vtt').exists())
        payload = json.loads((folder / 'subtitles-data.js').read_text(encoding='utf-8').split('window.EVERCAM_SUBTITLES = ')[1].strip().removesuffix(';'))
        self.assertEqual(payload['defaultLanguage'], 'en')
        english = next(t for t in payload['tracks'] if t['language'] == 'en')
        self.assertEqual(english['cues'][0]['text'], 'First')

    def test_project_link_and_malformed_data_are_not_downgraded(self):
        self.project('opencam')
        data = self.media / 'opencam-player.js'
        data.write_text('window.OpenCamPlayerData = alert(1);')
        with self.assertRaises(MCPError):
            self.service.call('list_media', {'root_id': self.root_id})
        data.unlink()
        try:
            data.symlink_to(self.media / 'secret.txt')
        except OSError:
            return
        with self.assertRaises(MCPError):
            self.service.call('list_media', {'root_id': self.root_id})
