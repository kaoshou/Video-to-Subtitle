"""Reject suspicious batch output before publication; never repair timestamps."""
import math


class BatchQualityError(RuntimeError):
    pass


class BatchQualityGuard:
    # Small timestamp rounding differences are not evidence of broken alignment.
    tolerance = .08
    end_tolerance = .5

    def __init__(self, duration, word_timestamps):
        self.duration = duration
        self.word_timestamps = word_timestamps
        self.previous_end = 0.

    def _times(self, start, end):
        if (not math.isfinite(start) or not math.isfinite(end)
                or start < 0 or end < start
                or end > self.duration + self.end_tolerance):
            raise BatchQualityError('批次時間軸包含非法或超出影片範圍的時間。')

    def check(self, segment):
        self._times(segment.start, segment.end)
        if segment.start < self.previous_end - self.tolerance:
            raise BatchQualityError('批次段落時間軸倒退或重疊。')
        self.previous_end = segment.end
        if not segment.text.strip():
            return
        for name, limit, lower in (('avg_logprob', -1., True),
                                   ('compression_ratio', 2.4, False)):
            value = getattr(segment, name, None)
            if value is not None and (not math.isfinite(value)
                    or (value < limit if lower else value > limit)):
                raise BatchQualityError('批次結果信心偏低或有重複文字異常。')
        if not self.word_timestamps:
            return
        words = segment.words
        if not words:
            raise BatchQualityError('批次結果缺少要求的單字時間對齊。')
        previous = segment.start
        for word in words:
            self._times(word.start, word.end)
            if (word.start < previous - self.tolerance
                    or word.start < segment.start - self.end_tolerance
                    or word.end > segment.end + self.end_tolerance):
                raise BatchQualityError('批次單字時間對齊異常。')
            previous = word.end
