"""Controller contracts; native widget coverage is opt-in in desktop tests."""
import importlib
import importlib.util
from pathlib import Path
import tempfile
import unittest

from web_export_model import SubtitleSource
import test_opencam_integration as fixtures


class OpenCamForm(unittest.TestCase):
    def api(self):
        self.assertIsNotNone(importlib.util.find_spec('opencam_dialog'), 'OpenCam dialog missing')
        return importlib.import_module('opencam_dialog')

    def setUp(self):
        self.fixture = fixtures.OpenCamIntegration()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_selecting_project_discovers_multilingual_subtitles_and_keeps_explicit_result(self):
        m = self.api()
        f = self.fixture
        for name in ('media.en.srt', 'media.zh-TW.vtt'):
            (f.folder / name).touch()
        state = m.OpenCamFormState()
        state.select_project(f.folder, (SubtitleSource(f.srt, 'zh-TW'),))
        self.assertEqual([(t.path, t.language) for t in state.tracks],
                         [(f.srt, 'zh-TW'), (f.folder / 'media.en.srt', 'en')])
        self.assertEqual(state.project.data['title'], '課程')

    def test_changing_project_does_not_carry_unrelated_subtitles(self):
        m = self.api()
        state = m.OpenCamFormState()
        state.select_project(self.fixture.folder, (SubtitleSource(self.fixture.srt, 'zh-TW'),))
        with tempfile.TemporaryDirectory() as tmp:
            import shutil
            other = Path(tmp) / 'other'
            shutil.copytree(self.fixture.folder, other)
            state.select_project(other)
            self.assertEqual(state.tracks, [])

    def test_imported_filenames_infer_language_or_leave_untagged_und(self):
        m = self.api()
        state = m.OpenCamFormState()
        state.select_project(self.fixture.folder)
        state.add_subtitle(self.fixture.srt)
        unknown = self.fixture.root / 'media_2.srt'; unknown.touch()
        state.add_subtitle(unknown)
        self.assertEqual([t.language for t in state.tracks], ['zh-TW', 'und'])

    def test_request_rejects_empty_invalid_and_duplicate_languages(self):
        m = self.api()
        state = m.OpenCamFormState()
        with self.assertRaises(ValueError): state.request()
        state.select_project(self.fixture.folder)
        with self.assertRaises(ValueError): state.request()
        state.add_subtitle(self.fixture.srt)
        state.tracks[0].language = '繁體中文'
        with self.assertRaises(ValueError): state.request()
        state.tracks[0].language = 'zh-TW'
        unknown = self.fixture.root / 'media_2.srt'; unknown.touch()
        state.add_subtitle(unknown)
        state.tracks[1].language = 'zh-tw'
        with self.assertRaises(ValueError): state.request()
        state.tracks[1].language = 'en'
        folder, sources = state.request()
        self.assertEqual(folder, self.fixture.folder)
        self.assertEqual([s.language for s in sources], ['zh-TW', 'en'])

    def test_completion_decline_does_not_open_or_write_and_accept_passes_matching_subtitle(self):
        m = self.api()
        f = self.fixture
        import opencam_integration
        projects = opencam_integration.completed_projects(
            [str(f.srt)], {str(f.srt): str(f.folder / 'media.mp4')})
        opened = []
        original = (f.folder / 'opencam-player.js').read_bytes()
        for answer in (False, True):
            with self.subTest(answer=answer):
                m.offer_completed_projects(None, projects, 'en',
                    ask=lambda title, message, **kw: answer,
                    open_dialog=lambda parent, **kw: opened.append(kw))
                self.assertEqual(len(opened), int(answer))
                self.assertEqual((f.folder / 'opencam-player.js').read_bytes(), original)
        self.assertEqual(opened[0], {'folder': str(f.folder),
                                    'subtitles': (SubtitleSource(f.srt, 'en'),)})

    def test_no_completed_opencam_does_not_prompt(self):
        m = self.api()
        def unexpected(*args, **kwargs): self.fail('ordinary output must not prompt')
        m.offer_completed_projects(None, [], ask=unexpected, open_dialog=unexpected)


if __name__ == '__main__': unittest.main()
