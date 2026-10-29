import importlib
import unittest
import time
from types import SimpleNamespace


class SubtitleReviewTests(unittest.TestCase):
    def setUp(self):
        try:
            self.review = importlib.import_module('subtitle_review')
        except ModuleNotFoundError:
            self.fail('缺少非破壞字幕診斷模組')

    def test_collects_only_available_finite_model_signals_without_mutation(self):
        segment = SimpleNamespace(start=0, end=2, text='老師好', avg_logprob=-1.2,
                                  compression_ratio=3)
        result = self.review.collect_segment_review(segment)
        self.assertEqual(result, [dict(start=0, end=2, text='老師好',
                                     reasons=['辨識信心偏低', '疑似重複內容'])])
        self.assertEqual(segment.text, '老師好')
        for changes in ({}, {'avg_logprob': float('nan')},
                        {'compression_ratio': float('inf')}, {'avg_logprob': -.2}):
            self.assertEqual(self.review.collect_segment_review(dict(start=0, end=2, text='好', **changes)), [])

    def test_split_and_merge_map_by_time_and_unchanged_text_not_index(self):
        evidence = [dict(start=1, end=3, text='老師好歡迎', reasons=['辨識信心偏低'])]
        cues = [dict(start=0, end=1, text='前言'), dict(start=1, end=2, text='老師好'),
                dict(start=2, end=3, text='歡迎')]
        self.assertEqual(self.review.review_cues(cues, evidence), {1: ['辨識信心偏低'], 2: ['辨識信心偏低']})
        split_evidence = [dict(start=1, end=2, text='老師好', reasons=['辨識信心偏低']),
                          dict(start=2, end=3, text='歡迎', reasons=['疑似重複內容'])]
        self.assertEqual(self.review.review_cues([dict(start=1, end=3, text='老師好歡迎')], split_evidence),
                         {0: ['辨識信心偏低', '疑似重複內容']})
        cues[1]['text'] = '同學好'
        self.assertEqual(self.review.review_cues(cues, evidence), {})

    def test_old_subtitles_check_adjacent_repeats_and_timing_not_pauses(self):
        cues = [dict(start=0, end=1, text='您好'), dict(start=1, end=2, text='您好'),
                dict(start=40, end=41, text='下課'), dict(start=43, end=42, text='倒轉')]
        self.assertEqual(self.review.review_cues(cues),
                         {0: ['疑似相鄰重複'], 1: ['疑似相鄰重複'], 3: ['時間軸異常']})
        self.assertEqual(self.review.review_cues([dict(start=0, end=3, text='一'),
                                                  dict(start=2, end=4, text='二')]),
                         {0: ['時間軸重疊'], 1: ['時間軸重疊']})

    def test_bad_metadata_and_empty_cues_do_not_break_review(self):
        self.assertEqual(self.review.review_cues([], [None, {}]), {})
        self.assertEqual(self.review.review_cues([dict(start=float('nan'), end=2, text='好')]),
                         {0: ['時間軸異常']})

    def test_large_lecture_diagnostics_remain_interactive(self):
        cues = [dict(start=i * 2, end=i * 2 + 1, text=f'字幕{i}') for i in range(5000)]
        evidence = [dict(**cue, reasons=['辨識信心偏低']) for cue in cues]
        start = time.monotonic()
        result = self.review.review_cues(cues, evidence)
        self.assertEqual(len(result), 5000)
        self.assertLess(time.monotonic() - start, 2., '5000段字幕的檢查不應阻塞操作')

    def test_millisecond_output_rounding_does_not_attach_neighbor_to_evidence(self):
        cues = [dict(start=0, end=1, text='請校對'), dict(start=1, end=2, text='正常內容')]
        evidence = [dict(start=0, end=1.0004, text='請校對', reasons=['辨識信心偏低'])]
        self.assertEqual(self.review.review_cues(cues, evidence), {0: ['辨識信心偏低']})


if __name__ == '__main__':
    unittest.main()
