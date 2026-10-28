"""Quality report must be serializable for real NumPy-backed word times."""
from dataclasses import dataclass
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import weakref
import numpy as np

from scripts.benchmark_batch_quality import assess, char_error_rate
from scripts.benchmark_batch_quality import main


@dataclass
class Word:
    start: float
    end: float
    word: str


@dataclass
class Segment:
    start: float
    end: float
    text: str
    words: list
    avg_logprob: float = -.2
    compression_ratio: float = 1.2


class BatchBenchmark(unittest.TestCase):
    def test_real_numpy_word_times_produce_json_report_and_correct_anchor(self):
        segments = [Segment(1., 2., '第一段', [Word(np.float64(1), np.float64(2), '第一段')])]
        report = assess(segments, 5, dict(text='第一段', speech_windows=[
            dict(anchor='第一段', start=1, end=2)]))
        self.assertEqual(json.loads(json.dumps(report))['anchors'][0]['in_expected_window'], True)
        self.assertEqual(report['cer'], 0)
        self.assertEqual(report['timing_issues'], [])

    def test_wrong_anchor_time_is_not_mistaken_for_good_text(self):
        segments = [Segment(10., 11., '第一段', [Word(10., 11., '第一段')])]
        report = assess(segments, 20, dict(text='第一段', speech_windows=[
            dict(anchor='第一段', start=1, end=2)]))
        self.assertEqual(report['cer'], 0)
        self.assertFalse(report['anchors'][0]['in_expected_window'])
        self.assertTrue(report['timing_issues'])

    def test_character_error_rate_counts_edits_not_recognizer_similarity(self):
        self.assertEqual(char_error_rate('字幕', '字目'), .5)
        self.assertEqual(char_error_rate('字幕', '字幕多'), .5)
        self.assertEqual(char_error_rate('繁體中文', '繁体中文'), 0)

    def test_speech_in_known_silence_is_reported_even_with_correct_text(self):
        segments = [Segment(5., 6., '字幕', [Word(5., 6., '字幕')])]
        report = assess(segments, 20, dict(text='字幕', speech_windows=[
            dict(anchor='另一段', start=10, end=12)]))
        self.assertEqual(report['words_outside_speech_windows'], 1)

    def test_repeated_anchor_is_checked_in_each_own_time_window(self):
        segments = [Segment(1., 2., '第一段', [Word(1., 2., '第一段')]),
                    Segment(11., 12., '第一段', [Word(11., 12., '第一段')])]
        report = assess(segments, 20, dict(text='第一段第一段', speech_windows=[
            dict(anchor='第一段', start=1, end=2), dict(anchor='第一段', start=11, end=12)]))
        self.assertTrue(all(a['in_expected_window'] for a in report['anchors']))

    def test_long_fixture_repeats_audio_and_reference_offsets_without_mutation(self):
        from scripts.benchmark_batch_quality import repeat_fixture
        audio = np.zeros(16000, np.float32)
        reference = dict(text='字幕', speech_windows=[dict(anchor='字幕', start=.2, end=.8)])
        longer, target = repeat_fixture(audio, reference, 3)
        self.assertEqual(len(longer), 48000)
        self.assertEqual(target['text'], '字幕字幕字幕')
        self.assertEqual([w['start'] for w in target['speech_windows']], [.2, 1.2, 2.2])
        self.assertEqual(reference['text'], '字幕')
        self.assertEqual(len(reference['speech_windows']), 1)

    def test_benchmark_warmup_and_both_modes_use_production_vad_parameters(self):
        calls = []
        live_models = weakref.WeakSet()
        owner = self
        class Model:
            def __init__(self, *args, **kwargs):
                owner.assertFalse(list(live_models), 'Previous thread-setting model still retained')
                live_models.add(self)
            def transcribe(self, audio, **options):
                calls.append(options)
                item = Segment(.1, .9, '字幕', [Word(.1, .9, '字幕')])
                return iter([item]), SimpleNamespace(duration=1.)
        class Pipeline:
            def __init__(self, model):
                self.model = model
            def transcribe(self, audio, **kwargs):
                return self.model.transcribe(audio, **kwargs)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            reference = root/'reference.json'
            reference.write_text(json.dumps(dict(text='字幕')), encoding='utf-8')
            args = ['benchmark', '--snapshot', folder, '--audio', str(root/'audio.wav'),
                    '--reference', str(reference), '--report', str(root/'report.json'),
                    '--batches', '2', '--repeats', '1', '--threads', '2', '8']
            with patch.object(sys, 'argv', args), patch('faster_whisper.WhisperModel', Model), \
                    patch('faster_whisper.BatchedInferencePipeline', Pipeline), \
                    patch('faster_whisper.audio.decode_audio', return_value=np.zeros(16000, np.float32)), \
                    contextlib.redirect_stdout(io.StringIO()):
                main()
            report = json.loads((root/'report.json').read_text(encoding='utf-8'))
            self.assertEqual([r['actual_mode'] for r in report['results']],
                             ['standard', 'batched', 'standard', 'batched'])
        self.assertEqual(len(calls), 6)
        for options in calls:
            self.assertEqual(options.get('vad_parameters'), dict(min_silence_duration_ms=500))
            self.assertTrue(options['word_timestamps'])

    def test_smoke_report_does_not_label_standard_fallback_as_batch_acceleration(self):
        from scripts.smoke_batch_inference import reported_mode
        self.assertEqual(reported_mode('cpu', 4, ['使用標準推論。']), 'standard-fallback')
        self.assertEqual(reported_mode('cuda', 4, ['使用標準推論。']), 'standard-fallback')
        self.assertEqual(reported_mode('cuda', 4, ['批次推論：每批最多 2 段音訊。']), 'batched')
        self.assertEqual(reported_mode('cpu', None, []), 'standard')
        self.assertEqual(reported_mode('mlx', 4, []), 'mlx-native')


if __name__ == '__main__':
    unittest.main()
