from dataclasses import replace
import hashlib
import importlib
import json
from pathlib import Path
import tempfile
import unittest

from test_web_export_inputs import make_video
from web_export_model import ExportRequest, Metadata, SubtitleSource
from evercam_integration import is_evercam_folder


class Packages(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        make_video(self.root / '影片.mp4')
        (self.root / '影片.srt').write_text('1\n00:00:00,000 --> 00:00:00,900\n<script>你好</script>\n', encoding='utf-8')
        self.request = ExportRequest(self.root / '影片.mp4', (SubtitleSource(self.root / '影片.srt', 'zh-TW'),),
                                     Metadata('<script>標題</script>'), self.root, '影片-web', 'zh-TW')

    def api(self):
        module = importlib.import_module('web_export')
        self.assertTrue(hasattr(module, 'export_package'), 'export orchestration missing')
        return module

    def export(self, api, request=None, **kwargs):
        return api.export_package(request or self.request, app_version='2.7.8',
                                  progress=lambda done, total: None, cancelled=kwargs.get('cancelled', lambda: False))

    def hashes(self, folder):
        return {str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in folder.rglob('*') if p.is_file()}

    def test_export_reload_move_reexport(self):
        api = self.api()
        result = self.export(api)
        self.assertEqual((result.folder / 'media.mp4').read_bytes(), self.request.video.read_bytes())
        self.assertFalse(is_evercam_folder(result.folder))
        self.assertFalse((result.folder / 'config.js').exists())
        self.assertTrue((result.folder / 'css/evercam-modern.css').is_file())
        self.assertTrue((result.folder / 'js/evercam-modern.js').is_file())
        self.assertNotIn(str(self.root), (result.folder / 'web-export.json').read_text())
        self.assertIn('&lt;script&gt;', result.index_path.read_text())
        before = self.hashes(result.folder)
        moved = self.root / 'moved'; result.folder.rename(moved)
        loaded = api.load_package(moved)
        self.assertEqual(loaded.issues, [])
        second = self.export(api, replace(loaded.request, metadata=Metadata('修改標題')))
        self.assertEqual(second.package_id, result.package_id)
        self.assertEqual(before, self.hashes(moved))
        fresh = self.export(api, replace(self.request, folder_name='new'))
        self.assertNotEqual(fresh.package_id, result.package_id)

    def test_cancel_leaves_no_package(self):
        api = self.api()
        with self.assertRaises(InterruptedError): self.export(api, cancelled=lambda: True)
        self.assertFalse((self.root / '影片-web').exists())
        self.assertFalse(list(self.root.glob('.vts-export-*')))

    def test_auto_discovered_plain_subtitle_exports_and_reloads_without_user_language(self):
        from web_export_form import ExportFormState, find_subtitle_candidates
        state = ExportFormState(); state.select_video(self.request.video)
        state.offer_candidates(find_subtitle_candidates(self.request.video))
        request = replace(self.request, subtitles=tuple(SubtitleSource(t.path,t.language) for t in state.tracks),
                          default_subtitle=state.default_language())
        result = self.export(self.api(), request)
        loaded = self.api().load_package(result.folder)
        self.assertEqual(loaded.issues, [])
        self.assertEqual(loaded.request.default_subtitle, 'und')
        self.assertEqual(loaded.request.subtitles[0].language, 'und')
        raw = (result.folder / 'subtitles-data.js').read_text()
        payload = json.loads(raw.split(' = ',1)[1].rstrip(';\n'))
        self.assertEqual(payload['tracks'][0]['label'], '預設字幕')

    def test_warning_requires_confirmation(self):
        api = self.api()
        self.request.subtitles[0].path.write_text('1\n00:00:00,000 --> 00:00:10,000\nlong\n')
        with self.assertRaises(ValueError): self.export(api)
        self.assertFalse((self.root / '影片-web').exists())

    def test_disk_full_preflight_preserves_sources(self):
        from unittest.mock import patch
        from collections import namedtuple
        api = self.api()
        before = self.request.video.read_bytes()
        usage = namedtuple('usage', 'total used free')(100, 100, 0)
        with patch('web_export.shutil.disk_usage', return_value=usage):
            with self.assertRaisesRegex(OSError, '空間不足'): self.export(api)
        self.assertEqual(self.request.video.read_bytes(), before)
        self.assertFalse((self.root / '影片-web').exists())
        self.assertFalse(list(self.root.glob('.vts-export-*')))

    def test_import_never_copies_custom_javascript(self):
        api = self.api()
        first = self.export(api)
        custom = first.folder / 'custom.js'
        custom.write_text('throw new Error("untrusted");')
        (first.folder / 'js/evercam-modern.js').write_text('throw new Error("untrusted");')
        loaded = api.load_package(first.folder)
        second = self.export(api, loaded.request)
        self.assertFalse((second.folder / 'custom.js').exists())
        self.assertNotIn('throw new Error("untrusted")', (second.folder / 'js/evercam-modern.js').read_text())
        self.assertTrue(custom.exists())


if __name__ == '__main__': unittest.main()
