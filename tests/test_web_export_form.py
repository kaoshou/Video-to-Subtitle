"""User-facing defaults must reduce clicks without replacing explicit choices."""
import importlib
import importlib.util
from pathlib import Path
import tempfile
import unittest


class QuickFormTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def api(self):
        self.assertIsNotNone(importlib.util.find_spec('web_export_form'), 'quick form state missing')
        return importlib.import_module('web_export_form')

    def touch(self, name):
        path = self.root / name
        path.write_bytes(b'test')
        return path

    def test_unique_reliable_match_and_friendly_language(self):
        m = self.api(); video = self.touch('課程.mp4')
        subtitle = self.touch('課程.zh-TW.srt')
        self.touch('課程.part2.srt'); self.touch('其他.en.vtt')
        state = m.ExportFormState(); state.select_video(video)
        candidates = m.find_subtitle_candidates(video)
        self.assertEqual([s.path for s in candidates], [subtitle])
        self.assertTrue(state.offer_candidates(candidates))
        self.assertEqual(state.tracks[0].language, 'zh-TW')
        self.assertEqual(m.language_label('zh-TW'), '繁體中文')
        self.assertEqual(m.language_code('繁體中文'), 'zh-TW')
        self.assertEqual(state.default_language(), 'zh-TW')

    def test_same_stem_prefers_vtt_without_requiring_language_selection(self):
        m = self.api(); video = self.touch('movie.mp4')
        self.touch('movie.srt'); preferred = self.touch('movie.vtt')
        state = m.ExportFormState(); state.select_video(video)
        candidates = m.find_subtitle_candidates(video)
        self.assertTrue(state.offer_candidates(candidates))
        self.assertEqual([(t.path,t.language) for t in state.tracks], [(preferred,'und')])
        self.assertEqual(state.default_language(), 'und')
        self.assertEqual(m.language_label('und'), '預設字幕')
        self.assertEqual(m.language_code('預設字幕'), 'und')

    def test_all_languages_loaded_once_with_vtt_preference_and_exact_matching(self):
        m = self.api(); video = self.touch('lesson.mp4')
        for name in ['lesson.srt','lesson.en.srt','lesson.en.vtt','lesson.zh-tw.srt',
                     'lesson.zh-TW.vtt','lesson2.srt','lesson.part2.vtt','other.en.vtt']:
            self.touch(name)
        state = m.ExportFormState(); state.select_video(video)
        state.offer_candidates(m.find_subtitle_candidates(video))
        self.assertEqual({t.language:t.path.name for t in state.tracks},
                         {'und':'lesson.srt','en':'lesson.en.vtt','zh-TW':'lesson.zh-TW.vtt'})
        self.assertEqual(state.default_language(), 'und')

    def test_manual_choice_wins_while_other_languages_are_auto_loaded(self):
        m = self.api(); video = self.touch('lesson.mp4')
        chosen = self.touch('chosen.en.srt')
        self.touch('lesson.en.vtt'); chinese = self.touch('lesson.zh-TW.srt')
        state = m.ExportFormState(); state.select_video(video)
        state.add_track(chosen,'en')
        state.offer_candidates(m.find_subtitle_candidates(video))
        self.assertEqual({t.language:t.path for t in state.tracks}, {'en':chosen,'zh-TW':chinese})

    def test_manual_file_without_language_works_as_default_subtitle(self):
        m = self.api(); state = m.ExportFormState()
        state.add_track(self.touch('lesson.srt'))
        self.assertEqual(state.default_language(), 'und')

    def test_rescan_refreshes_automatic_files_but_preserves_manual_choices(self):
        m = self.api(); video = self.touch('lesson.mp4')
        self.touch('lesson.en.srt')
        state = m.ExportFormState(); state.select_video(video)
        state.offer_candidates(m.find_subtitle_candidates(video))
        preferred = self.touch('lesson.en.vtt')
        state.default_choice = 'en'
        state.offer_candidates(m.find_subtitle_candidates(video))
        self.assertEqual([t.path for t in state.tracks], [preferred])
        self.assertEqual(state.default_language(), 'en')

    def test_output_next_to_video_and_collision_numbered(self):
        m = self.api(); video = self.touch('lesson.mp4')
        (self.root / 'lesson-web').mkdir()
        state = m.ExportFormState(); state.select_video(video)
        self.assertEqual(state.output_parent, self.root)
        self.assertEqual(state.folder_name, 'lesson-web-2')
        self.assertEqual(state.title.value, 'lesson')

    def test_manual_fields_and_tracks_survive_video_change(self):
        m = self.api(); state = m.ExportFormState()
        state.select_video(self.touch('first.mp4'))
        state.title.edit('我的標題')
        state.set_output_parent(self.root / 'chosen')
        state.set_folder_name('custom')
        subtitle = self.touch('custom.srt')
        state.add_track(subtitle, 'en')
        state.select_video(self.touch('second.mp4'))
        self.assertEqual(state.title.value, '我的標題')
        self.assertEqual(state.output_parent, self.root / 'chosen')
        self.assertEqual(state.folder_name, 'custom')
        self.assertEqual(state.tracks[0].path, subtitle)

    def test_auto_track_replaced_but_manual_language_change_is_preserved(self):
        m = self.api(); state = m.ExportFormState()
        state.select_video(self.touch('first.mp4'))
        state.offer_candidates([m.SubtitleSource(self.touch('first.en.srt'), 'en')])
        state.select_video(self.touch('second.mp4'))
        self.assertEqual(state.tracks, [])
        state.offer_candidates([m.SubtitleSource(self.touch('second.en.srt'), 'en')])
        state.set_track_language(state.tracks[0], '繁體中文')
        state.select_video(self.touch('third.mp4'))
        self.assertEqual(state.tracks[0].language, 'zh-TW')

    def test_removing_explicit_default_requires_new_choice(self):
        m = self.api(); state = m.ExportFormState()
        state.add_track(self.touch('first.srt'), 'en')
        state.add_track(self.touch('second.srt'), 'zh-TW')
        state.default_choice = 'en'
        state.remove_track(state.tracks[0])
        self.assertEqual(state.default_choice, '')
        self.assertEqual(state.default_language(), '')

    def test_auto_naming_rechecks_conflicts_without_overriding_manual_name(self):
        m = self.api(); state = m.ExportFormState()
        state.select_video(self.touch('lesson.mp4'))
        (self.root / 'lesson-web').mkdir()
        state.refresh_output_name()
        self.assertEqual(state.folder_name, 'lesson-web-2')
        state.set_folder_name('lesson-web')
        state.refresh_output_name()
        self.assertEqual(state.folder_name, 'lesson-web')

    def test_duplicate_path_not_added_and_symlink_not_suggested(self):
        m = self.api(); video = self.touch('movie.mp4')
        subtitle = self.touch('other.en.srt')
        try:
            (self.root / 'movie.en.srt').symlink_to(subtitle)
        except OSError as error:
            if getattr(error, 'winerror', None) == 1314:
                self.skipTest('Windows symlink privilege unavailable')
            raise
        self.assertEqual(m.find_subtitle_candidates(video), [])
        state = m.ExportFormState()
        state.add_track(subtitle, 'en'); state.add_track(subtitle, 'en')
        self.assertEqual(len(state.tracks), 1)

    def test_primary_action_requires_video_subtitles_and_successful_probe(self):
        m = self.api()
        self.assertTrue(hasattr(m, 'export_action_state'), 'export action readiness missing')
        state = m.ExportFormState()
        self.assertFalse(m.export_action_state(state, 'idle', False).enabled)
        state.select_video(self.touch('lesson.mp4'))
        self.assertFalse(m.export_action_state(state, 'idle', True).enabled)
        state.add_track(self.touch('lesson.srt'))
        self.assertFalse(m.export_action_state(state, 'idle', False).enabled)
        self.assertTrue(m.export_action_state(state, 'idle', True).enabled)
        for phase in ('reading', 'checking', 'exporting', 'cancelling'):
            self.assertFalse(m.export_action_state(state, phase, True).enabled)

    def test_invalid_language_or_removed_default_keeps_action_disabled(self):
        m = self.api()
        self.assertTrue(hasattr(m, 'export_action_state'), 'export action readiness missing')
        state = m.ExportFormState(); state.select_video(self.touch('lesson.mp4'))
        state.add_track(self.touch('lesson.en.srt'), 'en')
        state.add_track(self.touch('second.en.srt'), 'en')
        self.assertFalse(m.export_action_state(state, 'idle', True).enabled)
        state.remove_track(state.tracks[-1])
        state.default_choice = ''
        self.assertFalse(m.export_action_state(state, 'idle', True).enabled)
        state.default_choice = 'auto'
        state.set_track_language(state.tracks[0], 'invalid-code')
        self.assertFalse(m.export_action_state(state, 'idle', True).enabled)


if __name__ == '__main__': unittest.main()
