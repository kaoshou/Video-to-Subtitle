"""Bounded phase progress: no transcript text, guessed percentages or ETA."""
import math
import time

STAGES = frozenset(('model', 'audio', 'recognition', 'output', 'retry', 'transcription',
                    'snapshot', 'export', 'package', 'subtitle'))


def valid_progress(event):
    if (not isinstance(event, dict) or set(event) != {'stage', 'fraction'}
            or not isinstance(event['stage'], str) or event['stage'] not in STAGES):
        return False
    value = event['fraction']
    return value is None or (type(value) in (float, int) and 0 <= value <= 1 and math.isfinite(value))


class ProgressEmitter:
    def __init__(self, callback):
        self.callback = callback
        self.current = None
        self.last_time = 0.

    def emit(self, event):
        if not valid_progress(event) or event == self.current:
            return
        now = time.monotonic()
        previous = self.current
        if (previous and event['stage'] == previous['stage'] and previous['fraction'] is not None
                and event['fraction'] is not None and event['fraction'] != 1 and now - self.last_time < .25):
            return
        self.current = dict(event)
        self.last_time = now
        self.callback(dict(event))

    def stage(self, name, detail=''):
        self.emit({'stage': name, 'fraction': None})

    def progress(self, fraction):
        self.emit({'stage': self.current['stage'] if self.current else 'recognition', 'fraction': fraction})
