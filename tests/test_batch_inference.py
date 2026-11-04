"""Exercise real retry/output handling with only the recognizer substituted."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import numpy as np

import transcriber


def segment(text='批次測試', start=55):
    return SimpleNamespace(text=text, start=start, end=start + 2,
                           words=[SimpleNamespace(word=text, start=start, end=start+2)])


class BatchInference(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.calls = []
        self.cancelled = False
        owner = self

        class Recognizer:
            def transcribe(self, path, **options):
                owner.calls.append(('standard', options))
                return iter([segment('標準結果')]), owner.info

        class Pipeline:
            def __init__(self, model):
                self.model = model

            def transcribe(self, path, **options):
                owner.calls.append((options['batch_size'], options))
                return owner.recognize(options['batch_size']), owner.info

        self.info = SimpleNamespace(duration=120, language='zh', language_probability=1)
        self.recognize = lambda size: iter([segment()])
        self.worker = transcriber.SubtitleTranscriber(device='cuda')
        self.worker.model = Recognizer()
        self.modules = patch.dict(sys.modules, {'faster_whisper': SimpleNamespace(BatchedInferencePipeline=Pipeline)})
        self.modules.start()
        self.addCleanup(self.modules.stop)

    def run_job(self, **options):
        with contextlib.redirect_stdout(io.StringIO()):
            return self.worker.run(str(self.folder / 'media.mp4'),
                                   clean_punctuation='none', spacing=False, **options)

    def test_batch_preserves_time_prompt_and_output_formats(self):
        for fmt in ('srt', 'vtt', 'txt', 'tsv', 'json'):
            with self.subTest(fmt=fmt):
                path = self.run_job(batch_acceleration=True, batch_size=8, output_format=fmt,
                                    initial_prompt='教材', hotwords='Whisper', word_timestamps=True)
                text = Path(path).read_text(encoding='utf-8')
                self.assertIn('批次測試', text)
                self.assertEqual(self.calls[-1][0], 8)
                self.assertFalse(self.calls[-1][1]['without_timestamps'])
                self.assertEqual(self.calls[-1][1]['initial_prompt'], '教材')
                self.assertEqual(self.calls[-1][1]['hotwords'], 'Whisper')
                if fmt == 'json':
                    self.assertEqual(json.loads(text)[0]['start'], 55)

    def test_auto_plans_after_model_load_and_reprobes_each_file(self):
        from batch_policy import ResourceSnapshot
        self.worker.model_size, self.worker.compute_type = 'small', 'float16'
        self.worker.model = None
        def load(*args, **kwargs):
            self.worker.model = SimpleNamespace(transcribe=lambda *a, **k: (iter([segment()]), self.info))
        def probe(device):
            self.assertIsNotNone(self.worker.model)
            return ResourceSnapshot(16*1073741824,32*1073741824,8,5*1073741824,8*1073741824)
        with patch.object(self.worker, 'load_model', side_effect=load), patch('batch_policy.probe_resources', side_effect=probe) as read:
            for _ in range(2):
                self.run_job(batch_acceleration=True, batch_size='auto')
            self.assertEqual(read.call_count, 2)
        self.assertEqual([c[0] for c in self.calls], [8,8])
        self.assertEqual(self.worker.last_batch_decision, {'requested_mode':'auto','effective_size':8,
            'reason':'automatic', 'rationale':'Conservative cuda memory/core estimate: 8; not benchmarked'})

    def test_auto_metadata_explains_missing_resources_and_measured_ram_pressure(self):
        from batch_policy import ResourceSnapshot
        for resources, size, reason in [
                (ResourceSnapshot(None,None,None), 2, 'Missing/invalid RAM or physical cores; conservative estimate 2'),
                (ResourceSnapshot(1073741824,8*1073741824,8), None, 'Measured RAM pressure; standard inference')]:
            with patch('batch_policy.probe_resources', return_value=resources):
                self.run_job(batch_acceleration=True, batch_size='auto')
            self.assertEqual(self.worker.last_batch_decision['effective_size'], size)
            self.assertEqual(self.worker.last_batch_decision['rationale'], reason)

    def test_auto_oom_retries_and_ceiling_without_duplicate_cues(self):
        from batch_policy import ResourceSnapshot
        self.worker.model_size, self.worker.compute_type = 'small', 'float16'
        self.recognize = lambda size: (_ for _ in ()).throw(MemoryError('allocation'))
        with patch('batch_policy.probe_resources', return_value=ResourceSnapshot(16*1073741824,32*1073741824,8,5*1073741824,8*1073741824)):
            path = self.run_job(batch_acceleration=True, batch_size='auto')
            self.run_job(batch_acceleration=True, batch_size='auto')
        self.assertEqual([c[0] for c in self.calls], [8,4,2,'standard','standard'])
        self.assertEqual(Path(path).read_text(encoding='utf-8').count('標準結果'), 1)
        self.assertIsNone(self.worker.last_batch_decision['effective_size'])
        self.assertEqual(self.worker.last_batch_decision['reason'], 'memory_limit')

    def test_manual_disabled_and_vad_never_probe(self):
        with patch('batch_policy.probe_resources', side_effect=AssertionError('unexpected probe')):
            self.run_job(batch_acceleration=True, batch_size=8)
            self.run_job(batch_acceleration=False, batch_size='auto')
            self.run_job(batch_acceleration=True, batch_size='auto', vad_filter=False)
        for invalid in (True, 4.0, '4', 'AUTO'):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.run_job(batch_acceleration=True, batch_size=invalid)

    def test_mcp_and_gui_core_use_same_auto_policy_and_disabled_bypasses_probe(self):
        from batch_policy import ResourceSnapshot
        from mcp_service import _run_engine
        self.worker.model_size, self.worker.compute_type = 'small', 'float16'
        settings = {'model':'small','device':'cuda','batch_mode':'auto','batch_acceleration':True}
        with patch('batch_policy.probe_resources', return_value=ResourceSnapshot(16*1073741824,32*1073741824,8,5*1073741824,8*1073741824)):
            self.run_job(batch_acceleration=True, batch_size='auto')
            direct = dict(self.worker.last_batch_decision)
            with patch.object(self.worker, 'load_model'), contextlib.redirect_stdout(io.StringIO()):
                _run_engine(self.worker, settings, self.folder / 'media.mp4', lambda:False)
            self.assertEqual(self.worker.last_batch_decision, direct)
        settings['batch_acceleration'] = False
        with patch.object(self.worker, 'load_model'), patch('batch_policy.probe_resources', side_effect=AssertionError('off probe')), contextlib.redirect_stdout(io.StringIO()):
            _run_engine(self.worker, settings, self.folder / 'media.mp4', lambda:False)
        self.assertEqual(self.worker.last_batch_decision, {'requested_mode':'disabled','effective_size':None,'reason':'disabled'})

    def test_quality_fallback_is_input_local_for_future_auto_decisions(self):
        from batch_policy import ResourceSnapshot
        self.worker.model_size, self.worker.compute_type = 'small', 'float16'
        low = segment('低信心')
        low.avg_logprob = -2
        self.recognize = lambda size: iter([low])
        with patch('batch_policy.probe_resources', return_value=ResourceSnapshot(16*1073741824,32*1073741824,8,5*1073741824,8*1073741824)):
            self.run_job(batch_acceleration=True, batch_size='auto')
            self.assertEqual(self.worker.last_batch_decision['reason'], 'quality')
            self.recognize = lambda size: iter([segment()])
            self.run_job(batch_acceleration=True, batch_size='auto')
        self.assertEqual([call[0] for call in self.calls], [8,'standard',8])
        self.assertEqual(self.worker.last_batch_decision['effective_size'], 8)

    def test_auto_keeps_force_traditional_nonzero_timing_and_existing_output(self):
        from batch_policy import ResourceSnapshot
        self.worker.model_size, self.worker.compute_type = 'small', 'float16'
        self.recognize = lambda size: iter([segment('这是软件与数据库课程')])
        existing = self.folder / 'media.srt'
        existing.write_text('保留原檔', encoding='utf-8')
        with patch('batch_policy.probe_resources', return_value=ResourceSnapshot(16*1073741824,32*1073741824,8,5*1073741824,8*1073741824)):
            result = self.run_job(batch_acceleration=True, batch_size='auto', force_zh_tw=True)
        self.assertEqual(existing.read_text(encoding='utf-8'), '保留原檔')
        self.assertEqual(Path(result).name, 'media_1.srt')
        self.assertIn('這是軟體與資料庫課程', Path(result).read_text(encoding='utf-8'))
        self.assertIn('00:00:55,000 --> 00:00:57,000', Path(result).read_text(encoding='utf-8'))

    def test_oom_during_iteration_restarts_without_duplicate_or_overwriting_output(self):
        existing = self.folder / 'media.srt'
        existing.write_text('保留原檔', encoding='utf-8')
        def recognize(size):
            yield segment('失敗嘗試的部分字幕')
            raise RuntimeError('CUDA failed with error out of memory')
        self.recognize = recognize
        path = self.run_job(batch_acceleration=True, batch_size=4)
        self.assertEqual([call[0] for call in self.calls], [4, 2, 'standard'])
        self.assertEqual(existing.read_text(encoding='utf-8'), '保留原檔')
        text = Path(path).read_text(encoding='utf-8')
        self.assertIn('標準結果', text)
        self.assertNotIn('失敗嘗試', text)
        self.assertEqual(Path(path).name, 'media_1.srt')
        self.assertEqual(len(list(self.folder.glob('*.srt'))), 2)

    def test_cancel_during_batch_publishes_nothing(self):
        def recognize(size):
            yield segment()
            self.cancelled = True
            yield segment('不應發布', 60)
        self.recognize = recognize
        result = self.run_job(batch_acceleration=True,
                              cancel_check_callback=lambda: self.cancelled)
        self.assertIsNone(result)
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_non_memory_failure_is_not_hidden_or_published(self):
        def recognize(size):
            yield segment()
            raise RuntimeError('invalid model configuration')
        self.recognize = recognize
        with self.assertRaisesRegex(RuntimeError, 'invalid model'):
            self.run_job(batch_acceleration=True)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_vad_disabled_uses_standard_inference(self):
        self.run_job(batch_acceleration=True, vad_filter=False)
        self.assertEqual(self.calls[0][0], 'standard')
        self.assertFalse(self.calls[0][1]['vad_filter'])

    def test_core_without_batch_api_keeps_standard_transcription_available(self):
        with patch.dict(sys.modules, {'faster_whisper': SimpleNamespace()}):
            path = self.run_job(batch_acceleration=True)
        self.assertEqual(self.calls[0][0], 'standard')
        self.assertIn('標準結果', Path(path).read_text(encoding='utf-8'))

    def test_batch_size_is_validated_only_when_enabled(self):
        self.run_job(batch_acceleration=False, batch_size='invalid')
        with self.assertRaises(ValueError):
            self.run_job(batch_acceleration=True, batch_size=0)

    def test_pre_cancel_does_not_invoke_recognizer(self):
        self.assertIsNone(self.run_job(batch_acceleration=True, cancel_check_callback=lambda: True))
        self.assertEqual(self.calls, [])

    def test_mlx_preserves_native_word_timestamps_without_batch_arguments(self):
        self.worker.device = 'mlx'
        self.worker.model_type = 'mlx-whisper'
        self.worker.mlx_model_path = '/local/cached-model'
        options_received = []
        def native(audio, **options):
            options_received.append(options)
            return {'language': 'zh', 'segments': [dict(start=55, end=57, text='字幕',
                    words=[dict(word='字幕', start=55.25, end=56.75)])]}
        modules = {'mlx_whisper': SimpleNamespace(transcribe=native),
                   'mlx.core': SimpleNamespace(array=lambda a: a.copy(), eval=lambda a: None),
                   'faster_whisper.audio': SimpleNamespace(decode_audio=lambda *a, **k: np.zeros(16000 * 120))}
        with patch.dict(sys.modules, modules), patch('batch_policy.probe_resources', side_effect=AssertionError('native probe')):
            for enabled in (False, True):
                path = self.run_job(batch_acceleration=enabled, word_timestamps=True)
                text = Path(path).read_text(encoding='utf-8')
                self.assertIn('00:00:55,250 --> 00:00:56,750', text)
            self.run_job(batch_acceleration=True, batch_size='auto', word_timestamps=True)
        self.assertTrue(options_received[0]['word_timestamps'])
        self.assertNotIn('batch_size', options_received[0])
        self.assertNotIn('batch_size', options_received[1])

    def test_batch_memory_retry_can_finish_in_smaller_batch(self):
        def recognize(size):
            if size == 8:
                raise MemoryError('allocation failed')
            return iter([segment('成功')])
        self.recognize = recognize
        path = self.run_job(batch_acceleration=True, batch_size=8)
        self.assertEqual([call[0] for call in self.calls], [8, 4])
        self.assertIn('成功', Path(path).read_text(encoding='utf-8'))

    def test_empty_audio_can_cancel_before_publication(self):
        def recognize(size):
            self.cancelled = True
            return iter([])
        self.recognize = recognize
        self.assertIsNone(self.run_job(batch_acceleration=True, cancel_check_callback=lambda: self.cancelled))
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_cancel_during_final_fsync_does_not_publish(self):
        import os
        fsync = os.fsync
        def cancel_after_sync(fd):
            fsync(fd)
            self.cancelled = True
        with patch('safe_files.os.fsync', side_effect=cancel_after_sync):
            self.assertIsNone(self.run_job(batch_acceleration=True,
                                          cancel_check_callback=lambda: self.cancelled))
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_retry_decodes_once_and_reuses_audio_for_standard_fallback(self):
        decoded = np.zeros(160, dtype=np.float32)
        decoding = []
        inputs = []
        def decode(path):
            decoding.append(path)
            return decoded
        def recognize(size):
            raise MemoryError('batch memory unavailable')
        self.recognize = recognize
        original = self.worker.model.transcribe
        def standard(audio, **kwargs):
            inputs.append(audio)
            return original(audio, **kwargs)
        self.worker.model.transcribe = standard
        with patch.dict(sys.modules, {'faster_whisper.audio': SimpleNamespace(decode_audio=decode)}):
            self.run_job(batch_acceleration=True)
        self.assertEqual(len(decoding), 1)
        self.assertIs(inputs[0], decoded)

    def test_successful_oom_reduction_is_reused_but_explicit_smaller_size_is_respected(self):
        def recognize(size):
            if size > 4:
                raise MemoryError('batch too large')
            return iter([segment()])
        self.recognize = recognize
        self.run_job(batch_acceleration=True, batch_size=8)
        self.run_job(batch_acceleration=True, batch_size=8)
        self.run_job(batch_acceleration=True, batch_size=2)
        self.assertEqual([call[0] for call in self.calls], [8, 4, 4, 2])

    def test_batch_limit_does_not_cross_model_or_timestamp_configuration(self):
        def recognize(size):
            if len(self.calls) == 1:
                raise MemoryError('batch too large')
            return iter([segment()])
        self.recognize = recognize
        self.run_job(batch_acceleration=True, batch_size=8)
        self.worker.compute_type = 'float32'
        self.run_job(batch_acceleration=True, batch_size=8)
        self.run_job(batch_acceleration=True, batch_size=8, word_timestamps=False)
        self.assertEqual([call[0] for call in self.calls], [8, 4, 8, 8])

    def test_suspect_batch_retries_standard_without_publishing_partial_or_learning_limit(self):
        for device in ('cpu', 'cuda'):
            for broken in ('time', 'confidence', 'missing_words'):
                with self.subTest(device=device, broken=broken):
                    self.worker.device = device
                    self.calls.clear()
                    def recognize(size):
                        yield segment('不應發布的前半段', 1)
                        item = segment('異常結果', 10)
                        if broken == 'time':
                            item.end = 300
                        elif broken == 'confidence':
                            item.avg_logprob = -2
                        else:
                            item.words = None
                        yield item
                    self.recognize = recognize
                    path = self.run_job(batch_acceleration=True, batch_size=4)
                    self.assertEqual([c[0] for c in self.calls], [4, 'standard'])
                    text = Path(path).read_text(encoding='utf-8')
                    self.assertIn('標準結果', text)
                    self.assertNotIn('不應發布', text)
                    self.assertEqual(self.worker._batch_limits, {})

    def test_standard_mode_is_not_subject_to_new_batch_quality_thresholds(self):
        def standard(audio, **options):
            item = segment('原有標準流程')
            item.avg_logprob = -2
            return iter([item]), self.info
        self.worker.model.transcribe = standard
        path = self.run_job(batch_acceleration=False)
        self.assertIn('原有標準流程', Path(path).read_text(encoding='utf-8'))

    def test_quality_fallback_after_oom_does_not_learn_standard_as_memory_limit(self):
        def recognize(size):
            if size == 8:
                raise MemoryError('batch too large')
            item = segment('低信心')
            item.avg_logprob = -2
            return iter([item])
        self.recognize = recognize
        path = self.run_job(batch_acceleration=True, batch_size=8)
        self.assertIn('標準結果', Path(path).read_text(encoding='utf-8'))
        self.assertEqual([c[0] for c in self.calls], [8, 4, 'standard'])
        self.assertEqual(self.worker._batch_limits, {})

    def test_cancel_when_quality_fails_does_not_start_standard_retry(self):
        owner = self
        class LowConfidence:
            start, end, text = 1., 2., '低信心'
            @property
            def avg_logprob(self):
                owner.cancelled = True
                return -2
        self.recognize = lambda size: iter([LowConfidence()])
        path = self.run_job(batch_acceleration=True,
                            cancel_check_callback=lambda: self.cancelled)
        self.assertIsNone(path)
        self.assertEqual([c[0] for c in self.calls], [4])
        self.assertEqual(list(self.folder.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
