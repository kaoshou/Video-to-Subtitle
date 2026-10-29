import contextlib
import io
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import patch

import transcriber


def segment(text='老師好', confidence=-1.2):
    return SimpleNamespace(start=0., end=2., text=text, words=None,
                           avg_logprob=confidence, compression_ratio=1.)


class TranscriptionEvents(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.input = str(Path(self.temp.name) / 'media.mp4')
        self.info = SimpleNamespace(duration=5., language='zh', language_probability=1.)
        self.worker = transcriber.SubtitleTranscriber(device='cpu')
        self.worker.model = SimpleNamespace(transcribe=lambda *a, **k: (iter([segment()]), self.info))

    def run_job(self, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            return self.worker.run(self.input, word_timestamps=False, **kwargs)

    def test_standard_emits_stage_and_review_after_output_is_readable(self):
        stages, reviews, progress = [], [], []
        def review(path, evidence):
            self.assertIn('老師好', Path(path).read_text(encoding='utf-8'))
            reviews.append((path, evidence))
        path = self.run_job(stage_callback=lambda stage, detail='': stages.append(stage),
                            review_callback=review, progress_callback=progress.append)
        self.assertEqual([p for p, _ in reviews], [path])
        self.assertEqual(reviews[0][1], [dict(start=0., end=2., text='老師好', reasons=['辨識信心偏低'])])
        self.assertEqual(stages, ['model', 'audio', 'recognition', 'output', 'complete'])
        self.assertEqual(progress[-1], 1.)
        self.assertNotIn(1., progress[:-1])

    def test_oom_discards_failed_attempt_review(self):
        def failing(*a, **k):
            def generate():
                yield segment('失敗字幕', -.2)
                raise MemoryError('out of memory')
            return generate(), self.info
        pipeline = SimpleNamespace(transcribe=failing)
        reviews, stages = [], []
        with patch.dict(sys.modules, {'faster_whisper': SimpleNamespace(BatchedInferencePipeline=lambda **k: pipeline)}):
            self.run_job(batch_acceleration=True, batch_size=2,
                         stage_callback=lambda stage, detail='': stages.append(stage),
                         review_callback=lambda path, evidence: reviews.extend(evidence))
        self.assertIn('retry', stages)
        self.assertEqual([entry['text'] for entry in reviews], ['老師好'])
        self.assertEqual(stages[-1], 'complete')

    def test_cancellation_never_delivers_review_and_emits_terminal_stage(self):
        stages, reviews = [], []
        self.assertIsNone(self.run_job(cancel_check_callback=lambda: True,
                                      stage_callback=lambda stage, detail='': stages.append(stage),
                                      review_callback=lambda *args: reviews.append(args)))
        self.assertEqual(reviews, [])
        self.assertEqual(stages, ['cancelled'])

    def test_optional_observer_exceptions_cannot_fail_transcription(self):
        def broken(*args):
            raise RuntimeError('observer failed')
        self.assertTrue(Path(self.run_job(stage_callback=broken, review_callback=broken)).is_file())

    def test_failure_emits_failed_not_complete_or_review(self):
        stages, reviews = [], []
        def fail(*a, **k):
            raise ValueError('bad input')
        self.worker.model.transcribe = fail
        with self.assertRaises(ValueError):
            self.run_job(stage_callback=lambda stage, detail='': stages.append(stage),
                         review_callback=lambda *a: reviews.append(a))
        self.assertEqual(stages[-1], 'failed')
        self.assertNotIn('complete', stages)
        self.assertEqual(reviews, [])

    def test_mlx_missing_metadata_is_not_fabricated(self):
        self.worker.model_type = 'mlx-whisper'
        self.worker.device = 'mlx'
        self.worker.mlx_model_path = '/local/model'
        reviews, stages = [], []
        native = lambda *a, **k: dict(language='zh', segments=[dict(start=0, end=2, text='老師好')])
        with patch.dict(sys.modules, {'mlx_whisper': SimpleNamespace(transcribe=native),
                                    'faster_whisper.audio': SimpleNamespace(decode_audio=lambda *a: self.input)}):
            self.run_job(review_callback=lambda p, e: reviews.append(e),
                         stage_callback=lambda s, d='': stages.append(s))
        self.assertEqual(reviews, [[]])
        self.assertEqual(stages[-1], 'complete')


if __name__ == '__main__':
    unittest.main()
