"""Offline cache lifecycle tests; only Hub transfer and ASR engines are replaced."""
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import transcriber


class ModelCacheTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='vts-model-cache-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.cache = self.root / 'hub'
        self.repo = self.cache / 'models--Systran--faster-whisper-medium'
        self.snapshot = self.repo / 'snapshots' / 'test-revision'
        self.faster = SimpleNamespace(utils=SimpleNamespace(_MODELS={
            'medium': 'Systran/faster-whisper-medium'}))
        self.hub = SimpleNamespace(snapshot_download=self.no_network)
        modules = patch.dict('sys.modules', {'faster_whisper': self.faster,
                                              'huggingface_hub': self.hub})
        modules.start()
        self.addCleanup(modules.stop)

    def no_network(self, *args, **kwargs):
        self.fail('Unexpected network/model-name resolution')

    def files(self, folder=None, missing=()):
        folder = folder or self.snapshot
        folder.mkdir(parents=True, exist_ok=True)
        for name in ('config.json', 'tokenizer.json', 'vocabulary.json'):
            if name not in missing:
                (folder / name).write_text('{}', encoding='utf-8')
        if 'model.bin' not in missing:
            with (folder / 'model.bin').open('wb') as handle:
                handle.truncate(6 * 1024 * 1024)
        if folder == self.snapshot:
            (self.repo / 'refs').mkdir(exist_ok=True)
            (self.repo / 'refs' / 'main').write_text('test-revision', encoding='utf-8')
        return folder

    def test_first_download_loads_exact_snapshot_without_name_lookup(self):
        def transfer(repo_id, **options):
            self.assertEqual(repo_id, 'Systran/faster-whisper-medium')
            self.assertEqual(options['cache_dir'], str(self.cache))
            self.assertNotIn('force_download', options)
            return str(self.files())
        self.hub.snapshot_download = transfer
        class LocalRecognizer:
            def __init__(engine, path, **options):
                self.assertEqual(path, str(self.snapshot))
                self.assertTrue((Path(path) / 'config.json').is_file())
                self.assertEqual(options['device'], 'cuda')
                self.assertEqual(options['compute_type'], 'float16')
                self.assertEqual(options['cpu_threads'], 3)
                engine.path = path
        self.faster.WhisperModel = LocalRecognizer
        # Old readiness calls this boundary; missing cache is a normal result.
        self.faster.download_model = lambda *a, **k: None
        worker = transcriber.SubtitleTranscriber('medium', device='cuda',
            compute_type='float16', download_root=str(self.cache), cpu_threads=3)
        worker.load_model()
        self.assertEqual(worker.model.path, str(self.snapshot))
        self.assertTrue(transcriber.check_model_downloaded('medium', str(self.cache)))

    def test_ready_snapshot_returns_snapshot_and_ignores_optional_readme(self):
        self.files()
        self.faster.download_model = lambda *a, **k: str(self.snapshot)
        path = transcriber.download_model_with_progress('medium', str(self.cache))
        self.assertEqual(path, str(self.snapshot))

    def test_direct_folder_loads_that_folder(self):
        direct = self.files(self.root / 'direct')
        class LocalRecognizer:
            def __init__(engine, path, **options):
                self.assertEqual(path, str(direct))
                engine.path = path
        self.faster.WhisperModel = LocalRecognizer
        worker = transcriber.SubtitleTranscriber('medium', download_root=str(direct))
        worker.load_model()
        self.assertEqual(worker.model.path, str(direct))

    def test_partial_snapshot_repairs_missing_files_and_preserves_existing_weight(self):
        self.files(missing=('config.json', 'tokenizer.json', 'vocabulary.json'))
        weight = self.snapshot / 'model.bin'
        before = (weight.stat().st_ino, weight.stat().st_mtime_ns, weight.stat().st_size)
        self.faster.download_model = lambda *a, **k: str(self.snapshot)
        def resume(repo_id, **options):
            self.assertNotIn('force_download', options)
            for name in ('config.json', 'tokenizer.json', 'vocabulary.json'):
                (self.snapshot / name).write_text('{}', encoding='utf-8')
            return str(self.snapshot)
        self.hub.snapshot_download = resume
        self.assertFalse(transcriber.check_model_downloaded('medium', str(self.cache)))
        path = transcriber.download_model_with_progress('medium', str(self.cache))
        self.assertEqual(path, str(self.snapshot))
        self.assertEqual(before, (weight.stat().st_ino, weight.stat().st_mtime_ns, weight.stat().st_size))
        self.assertTrue(transcriber.check_model_downloaded('medium', str(self.cache)))

    def test_successful_transfer_with_missing_core_file_is_not_reported_ready(self):
        self.faster.download_model = lambda *a, **k: None
        self.hub.snapshot_download = lambda *a, **k: str(self.files(missing=('config.json',)))
        progress = []
        with self.assertRaisesRegex(transcriber.CorruptedModelError, 'config.json'):
            transcriber.download_model_with_progress('medium', str(self.cache),
                progress_callback=lambda value, info: progress.append(value))
        self.assertNotIn(1.0, progress)
        self.assertTrue((self.snapshot / 'model.bin').is_file())

    def test_inspection_reports_bad_json_and_preserves_files(self):
        self.files()
        (self.snapshot / 'config.json').write_text('{broken', encoding='utf-8')
        result = transcriber.inspect_model_cache('medium', str(self.cache))
        self.assertEqual(result.state, 'incomplete')
        self.assertEqual(result.path, str(self.snapshot))
        self.assertIn('config.json', result.message)
        self.assertEqual((self.snapshot / 'config.json').read_text(), '{broken')

    def test_inspection_reports_permission_failure_instead_of_missing(self):
        self.files()
        original = open
        def denied(path, *args, **kwargs):
            if os.fspath(path) == str(self.snapshot / 'config.json'):
                raise PermissionError('test access denied')
            return original(path, *args, **kwargs)
        with patch('builtins.open', denied):
            result = transcriber.inspect_model_cache('medium', str(self.cache))
        self.assertEqual(result.state, 'unavailable')
        self.assertIn('config.json', result.message)

    def test_corrupt_weights_remain_on_disk_when_engine_rejects_them(self):
        self.files()
        self.faster.download_model = lambda *a, **k: str(self.snapshot)
        def reject(*args, **kwargs):
            raise RuntimeError('model.bin: invalid magic number')
        self.faster.WhisperModel = reject
        worker = transcriber.SubtitleTranscriber('medium', download_root=str(self.cache))
        with self.assertRaises(transcriber.CorruptedModelError) as raised:
            worker.load_model()
        self.assertIn(str(self.snapshot), str(raised.exception))
        self.assertTrue((self.snapshot / 'model.bin').is_file())

    def test_default_cache_root_honors_environment_and_explicit_override(self):
        with patch.dict(os.environ, {'HF_HOME': str(self.root / 'home'),
                                    'HF_HUB_CACHE': str(self.cache)}):
            self.assertEqual(transcriber.effective_model_cache_root(), str(self.cache))
            self.files()
            self.assertEqual(transcriber.inspect_model_cache('medium').path, str(self.snapshot))
            self.assertEqual(transcriber.effective_model_cache_root(str(self.root / 'explicit')),
                             str(self.root / 'explicit'))

    def test_cancelled_download_preserves_partial_cache(self):
        self.files(missing=('config.json',))
        self.faster.download_model = lambda *a, **k: None
        with self.assertRaises(InterruptedError):
            transcriber.download_model_with_progress('medium', str(self.cache),
                cancel_check_callback=lambda: True)
        self.assertTrue((self.snapshot / 'model.bin').is_file())

    def test_stat_permission_error_is_unavailable_not_missing(self):
        self.files()
        original = os.stat
        def denied(path, *args, **kwargs):
            if os.fspath(path) == str(self.snapshot / 'config.json'):
                raise PermissionError('test metadata access denied')
            return original(path, *args, **kwargs)
        with patch('os.stat', denied):
            result = transcriber.inspect_model_cache('medium', str(self.cache))
        self.assertEqual(result.state, 'unavailable')

    def test_unreadable_repository_is_not_reported_as_undownloaded(self):
        self.files()
        original = os.stat
        def denied(path, *args, **kwargs):
            if os.fspath(path) == str(self.repo):
                raise PermissionError('test repository access denied')
            return original(path, *args, **kwargs)
        with patch('os.stat', denied):
            result = transcriber.inspect_model_cache('medium', str(self.cache))
        self.assertEqual(result.state, 'unavailable')

    def test_status_of_catalog_model_does_not_import_the_inference_engine(self):
        import builtins
        self.files()
        original = builtins.__import__
        def no_engine(name, *args, **kwargs):
            if name.startswith('faster_whisper'):
                self.fail('Read-only catalog inspection must not initialize the ASR engine')
            return original(name, *args, **kwargs)
        with patch('builtins.__import__', no_engine):
            self.assertEqual(transcriber.inspect_model_cache('medium', str(self.cache)).state, 'ready')

    def test_config_array_cannot_be_reported_ready(self):
        self.files()
        (self.snapshot / 'config.json').write_text('[]', encoding='utf-8')
        result = transcriber.inspect_model_cache('medium', str(self.cache))
        self.assertEqual(result.state, 'incomplete')
        self.assertIn('config.json', result.message)

    def test_direct_folder_with_explicit_other_model_identity_is_not_ready(self):
        direct = self.files(self.root / 'direct')
        (direct / 'config.json').write_text(json.dumps({
            '_name_or_path': 'Systran/faster-whisper-small'}), encoding='utf-8')
        result = transcriber.inspect_model_cache('medium', str(direct))
        self.assertEqual(result.state, 'incomplete')
        self.assertIn('small', result.message)

    def test_short_cached_weights_are_preserved_without_automatic_redownload(self):
        self.files()
        weight = self.snapshot / 'model.bin'
        weight.write_bytes(b'incomplete weights')
        with self.assertRaises(transcriber.CorruptedModelError):
            transcriber.download_model_with_progress('medium', str(self.cache))
        self.assertEqual(weight.read_bytes(), b'incomplete weights')

    def test_direct_folder_partial_repair_downloads_only_absent_files(self):
        direct = self.files(self.root / 'direct', missing=('tokenizer.json',))
        before = (direct / 'model.bin').stat().st_mtime_ns
        def transfer(repo_id, **options):
            self.assertEqual(options['local_dir'], str(direct))
            self.assertEqual(options['allow_patterns'], ['tokenizer.json'])
            (direct / 'tokenizer.json').write_text('{}', encoding='utf-8')
            return str(direct)
        self.hub.snapshot_download = transfer
        self.assertEqual(transcriber.download_model_with_progress('medium', str(direct)), str(direct))
        self.assertEqual((direct / 'model.bin').stat().st_mtime_ns, before)

    def test_cancel_after_transfer_does_not_report_completion(self):
        cancelled = False
        def transfer(*args, **options):
            nonlocal cancelled
            result = self.files()
            cancelled = True
            return str(result)
        self.hub.snapshot_download = transfer
        progress = []
        with self.assertRaises(InterruptedError):
            transcriber.download_model_with_progress('medium', str(self.cache),
                cancel_check_callback=lambda: cancelled,
                progress_callback=lambda value, info: progress.append(value))
        self.assertNotIn(1.0, progress)
        self.assertTrue((self.snapshot / 'model.bin').is_file())

    def test_mlx_load_retains_validated_local_snapshot(self):
        import numpy
        snapshot = self.cache / 'models--mlx-community--whisper-medium' / 'snapshots' / 'mlx-test'
        snapshot.mkdir(parents=True)
        (snapshot / 'config.json').write_text('{}', encoding='utf-8')
        (snapshot / 'weights.npz').write_bytes(b'fixture weights')
        (snapshot.parent.parent / 'refs').mkdir()
        (snapshot.parent.parent / 'refs' / 'main').write_text('mlx-test', encoding='utf-8')
        core = SimpleNamespace(array=numpy.array, eval=lambda value: None)
        with patch.dict('sys.modules', {'mlx': SimpleNamespace(core=core),
                'mlx.core': core, 'mlx_whisper': SimpleNamespace()}):
            worker = transcriber.SubtitleTranscriber('medium', device='mlx', download_root=str(self.cache))
            worker.load_model()
        self.assertEqual(worker.mlx_model_path, str(snapshot))
        self.assertEqual(worker.model_type, 'mlx-whisper')

    def test_mlx_weights_safetensors_direct_folder_is_ready_and_returned(self):
        direct = self.root / 'mlx-direct'
        direct.mkdir()
        (direct / 'config.json').write_text('{}', encoding='utf-8')
        (direct / 'weights.safetensors').write_bytes(b'fixture weights')
        result = transcriber.inspect_model_cache('medium', str(direct), device='mlx')
        self.assertEqual(result.state, 'ready')
        self.assertEqual(transcriber.download_model_with_progress('medium', str(direct), device='mlx'), str(direct))

    def test_mlx_weights_safetensors_marker_reports_missing_config_in_direct_folder(self):
        direct = self.root / 'mlx-partial'
        direct.mkdir()
        (direct / 'weights.safetensors').write_bytes(b'fixture weights')
        result = transcriber.inspect_model_cache('medium', str(direct), device='mlx')
        self.assertEqual(result.state, 'incomplete')
        self.assertEqual(result.path, str(direct))
        self.assertEqual(result.missing_files, ('config.json',))

    def test_mlx_valid_preferred_weights_ignore_stale_empty_fallbacks(self):
        for preferred, fallbacks in (
                ('model.safetensors', ('weights.safetensors', 'weights.npz')),
                ('weights.safetensors', ('weights.npz',))):
            with self.subTest(preferred=preferred):
                direct = self.root / preferred
                direct.mkdir()
                (direct / 'config.json').write_text('{}', encoding='utf-8')
                (direct / preferred).write_bytes(b'fixture weights')
                for name in fallbacks:
                    (direct / name).write_bytes(b'')
                self.assertEqual(transcriber.inspect_model_cache('medium', str(direct), device='mlx').state, 'ready')

    def test_mlx_empty_preferred_weights_do_not_hide_behind_valid_npz(self):
        direct = self.root / 'mlx-bad-preferred'
        direct.mkdir()
        (direct / 'config.json').write_text('{}', encoding='utf-8')
        (direct / 'model.safetensors').write_bytes(b'')
        (direct / 'weights.npz').write_bytes(b'fixture weights')
        result = transcriber.inspect_model_cache('medium', str(direct), device='mlx')
        self.assertEqual(result.state, 'incomplete')
        self.assertIn('model.safetensors', result.message)

    def test_cpu_valid_preferred_vocabulary_ignores_empty_text_fallback(self):
        self.files()
        (self.snapshot / 'vocabulary.txt').write_bytes(b'')
        self.assertEqual(transcriber.inspect_model_cache('medium', str(self.cache)).state, 'ready')

    def test_cpu_invalid_preferred_vocabulary_is_not_hidden_by_valid_text(self):
        self.files()
        (self.snapshot / 'vocabulary.json').write_text('{broken', encoding='utf-8')
        (self.snapshot / 'vocabulary.txt').write_text('token\n', encoding='utf-8')
        result = transcriber.inspect_model_cache('medium', str(self.cache))
        self.assertEqual(result.state, 'incomplete')
        self.assertIn('vocabulary.json', result.message)

    def test_environment_cache_precedence_including_hf_home_and_xdg(self):
        environment = {key: value for key, value in os.environ.items() if key not in
                       ('HF_HUB_CACHE', 'HUGGINGFACE_HUB_CACHE', 'HF_HOME', 'XDG_CACHE_HOME')}
        with patch.dict(os.environ, environment, clear=True):
            with patch.dict(os.environ, {'XDG_CACHE_HOME': str(self.root / 'xdg')}):
                self.assertEqual(transcriber.effective_model_cache_root(), str(self.root / 'xdg/huggingface/hub'))
            with patch.dict(os.environ, {'HF_HOME': str(self.root / 'hf')}):
                self.assertEqual(transcriber.effective_model_cache_root(), str(self.root / 'hf/hub'))
            with patch.dict(os.environ, {'HUGGINGFACE_HUB_CACHE': str(self.root / 'legacy')}):
                self.assertEqual(transcriber.effective_model_cache_root(), str(self.root / 'legacy'))


if __name__ == '__main__':
    unittest.main()
