import importlib
import importlib.util
from pathlib import Path
import unittest
from dataclasses import replace


class ModelTests(unittest.TestCase):
    def model(self):
        self.assertIsNotNone(importlib.util.find_spec('web_export_model'), 'export model missing')
        return importlib.import_module('web_export_model')

    def request(self, m):
        return m.ExportRequest(Path('movie.mp4'), (m.SubtitleSource(Path('movie.srt'), 'zh-TW'),),
                               m.Metadata('課程😀'), Path('.'), '課程-web', 'zh-TW')

    def test_metadata_limits(self):
        m = self.model()
        request = self.request(m)
        self.assertEqual(m.validate_request(request), [])
        for field, limit in [('title', 200), ('author', 100), ('organization', 200), ('description', 5000)]:
            good = replace(request, metadata=replace(request.metadata, **{field: '😀' * limit}))
            self.assertEqual(m.validate_request(good), [])
            bad = replace(request, metadata=replace(request.metadata, **{field: '😀' * (limit + 1)}))
            self.assertTrue(any(i.field == field for i in m.validate_request(bad)))
        self.assertTrue(m.validate_request(replace(request, metadata=m.Metadata('  '))))

    def test_language_and_default(self):
        m = self.model()
        self.assertEqual(m.canonical_language('ZH-hant-tw'), 'zh-Hant-TW')
        self.assertEqual(m.canonical_language('en'), 'en')
        for value in ['', '../en', 'en.foo', '123', 'english']:
            with self.assertRaises(ValueError): m.canonical_language(value)
        request = self.request(m)
        duplicate = replace(request, subtitles=request.subtitles + (m.SubtitleSource(Path('other.vtt'), 'zh-tw'),))
        self.assertTrue(m.validate_request(duplicate))
        self.assertTrue(m.validate_request(replace(request, default_subtitle='en')))
        self.assertEqual(m.validate_request(replace(request, default_subtitle='off')), [])

    def test_portable_folder_names(self):
        m = self.model()
        for value in ['CON', 'aux.txt', 'a:b', 'a/b', 'a\\b', '..', 'tail.', 'tail ', 'a?b', 'LPT1']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                m.validate_folder_name(value)
        self.assertEqual(m.validate_folder_name('課程 😀-web'), '課程 😀-web')

    def test_title_dirty_and_reset(self):
        m = self.model()
        state = m.TitleState()
        state.select_video(Path('第一週.mp4'))
        self.assertEqual(state.value, '第一週')
        state.edit('自訂')
        state.select_video(Path('第二週.mp4'))
        self.assertEqual(state.value, '自訂')
        self.assertTrue(state.dirty)
        state.use_filename()
        self.assertEqual(state.value, '第二週')
        self.assertFalse(state.dirty)


if __name__ == '__main__': unittest.main()
