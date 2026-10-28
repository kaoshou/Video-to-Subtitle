"""Batch-only safeguards must reject suspect output, never silently repair it."""
from types import SimpleNamespace
import unittest

from batch_quality import BatchQualityError, BatchQualityGuard


def cue(start=1., end=2., **changes):
    values = dict(start=start, end=end, text='測試字幕', avg_logprob=-.2,
                  compression_ratio=1.2, words=[SimpleNamespace(start=start, end=end, word='測試字幕')])
    values.update(changes)
    return SimpleNamespace(**values)


class BatchQuality(unittest.TestCase):
    def test_valid_output_is_not_changed_and_empty_silence_is_valid(self):
        guard = BatchQualityGuard(10, word_timestamps=True)
        item = cue()
        guard.check(item)
        self.assertEqual((item.start, item.end, item.words[0].start), (1., 2., 1.))
        guard.check(cue(3, 3, text='', words=[]))

    def test_invalid_or_out_of_order_segment_times_are_rejected(self):
        for start, end in [(-1, 2), (2, 1), (1, float('nan')), (1, 12),
                           (float('inf'), float('inf'))]:
            with self.subTest(start=start, end=end):
                with self.assertRaises(BatchQualityError):
                    BatchQualityGuard(10, True).check(cue(start, end))
        guard = BatchQualityGuard(10, True)
        guard.check(cue(4, 5))
        with self.assertRaises(BatchQualityError):
            guard.check(cue(2, 3))

    def test_missing_or_invalid_word_alignment_is_rejected(self):
        for words in (None, [], [SimpleNamespace(start=4, end=3)],
                      [SimpleNamespace(start=1, end=12)],
                      [SimpleNamespace(start=2, end=2.5), SimpleNamespace(start=1, end=1.5)]):
            with self.subTest(words=words):
                with self.assertRaises(BatchQualityError):
                    BatchQualityGuard(10, True).check(cue(words=words))

    def test_word_times_are_not_required_when_user_disables_them(self):
        BatchQualityGuard(10, False).check(cue(words=None))

    def test_low_confidence_or_repetition_is_rejected(self):
        for change in (dict(avg_logprob=-1.2), dict(compression_ratio=3),
                       dict(avg_logprob=float('nan'))):
            with self.subTest(change=change):
                with self.assertRaises(BatchQualityError):
                    BatchQualityGuard(10, True).check(cue(**change))


if __name__ == '__main__':
    unittest.main()
