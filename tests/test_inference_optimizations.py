import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np


class PreparedAudioTests(unittest.TestCase):
    def test_mlx_waveform_is_prepared_before_native_transcribe_without_changing_samples(self):
        from inference_optimizations import as_mlx_audio
        waveform = np.array([.125, -.25, .5], dtype=np.float32)
        converted = []
        evaluated = []
        def array(source):
            result = source.copy()
            converted.append(result)
            return result
        core = SimpleNamespace(array=array, eval=lambda value: evaluated.append(value))
        with patch.dict('sys.modules', {'mlx.core': core}):
            result = as_mlx_audio(waveform)
        np.testing.assert_array_equal(result, waveform)
        self.assertIs(result, converted[0])
        self.assertIs(evaluated[0], result)

    def test_reuses_exact_waveform_and_discards_it_after_job(self):
        from inference_optimizations import PreparedAudio
        waveform = np.array([.1, -.2, .3], dtype=np.float32)
        with patch.dict('sys.modules', {'faster_whisper.audio': SimpleNamespace(decode_audio=lambda _: waveform)}):
            with PreparedAudio('media.mp4') as prepared:
                self.assertIs(prepared.get(), waveform)
                self.assertIs(prepared.get(), waveform)
            self.assertIsNone(prepared.audio)

    def test_large_waveform_is_disk_mapped_and_cleaned(self):
        from inference_optimizations import PreparedAudio
        waveform = np.arange(32, dtype=np.float32)
        with patch.dict('sys.modules', {'faster_whisper.audio': SimpleNamespace(decode_audio=lambda _: waveform)}):
            with PreparedAudio('media.mp4', memory_limit=4) as prepared:
                audio = prepared.get()
                self.assertIsInstance(audio, np.memmap)
                np.testing.assert_array_equal(audio, waveform)
                filename = Path(audio.filename)
                self.assertTrue(filename.is_file())
            self.assertFalse(filename.exists())

    def test_decode_failure_keeps_original_input_path(self):
        from inference_optimizations import PreparedAudio
        def unavailable(_):
            raise MemoryError('not enough memory')
        with patch.dict('sys.modules', {'faster_whisper.audio': SimpleNamespace(decode_audio=unavailable)}):
            with PreparedAudio('media.mp4') as prepared:
                self.assertEqual(prepared.get(), 'media.mp4')

    def test_disk_full_falls_back_and_cleans_private_cache(self):
        from inference_optimizations import PreparedAudio
        waveform = np.arange(32, dtype=np.float32)
        with patch.dict('sys.modules', {'faster_whisper.audio': SimpleNamespace(decode_audio=lambda _: waveform)}):
            with PreparedAudio('media.mp4', memory_limit=4) as prepared:
                with patch('numpy.save', side_effect=OSError('disk full')):
                    self.assertEqual(prepared.get(), 'media.mp4')
                folder = Path(prepared.directory.name)
            self.assertFalse(folder.exists())

    def test_cancel_during_decode_stops_before_inference(self):
        from inference_optimizations import PreparedAudio
        from safe_files import ExportCancelled
        cancelled = [False]
        def decode(_):
            cancelled[0] = True
            return np.zeros(10, dtype=np.float32)
        with patch.dict('sys.modules', {'faster_whisper.audio': SimpleNamespace(decode_audio=decode)}):
            with PreparedAudio('media.mp4', cancel_check=lambda: cancelled[0]) as prepared:
                with self.assertRaises(ExportCancelled):
                    prepared.get()
