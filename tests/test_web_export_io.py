"""Exercise real files: unbounded reads, truncation, overwrite and unsafe cleanup regressions."""
import os
from pathlib import Path
import tempfile
import unittest

import safe_files


class ExportIO(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def stage_type(self):
        self.assertTrue(hasattr(safe_files, 'StagedDirectory'), 'transactional staging is missing')
        return safe_files.StagedDirectory

    def test_chunked_copy(self):
        stage_type = self.stage_type()
        payload = b'a' * (4 * 1024 * 1024 + 17)
        (self.root / 'input').write_bytes(payload)
        progress = []
        class BoundedReader:
            def __init__(self, stream): self.stream = stream
            def fileno(self): return self.stream.fileno()
            def read(self, size):
                if not 0 < size <= 4 * 1024 * 1024:
                    raise AssertionError('unbounded read')
                return self.stream.read(size)
        with safe_files.SafeDirectory(self.root) as parent:
            with parent.open_read('input') as source, stage_type(parent) as stage:
                count = stage.copy_from(BoundedReader(source), 'media.mp4',
                                        progress=progress.append, cancelled=lambda: False)
                self.assertEqual(count, len(payload))
                result = stage.publish('export')
        self.assertEqual((result / 'media.mp4').read_bytes(), payload)
        self.assertEqual(progress, [4 * 1024 * 1024, len(payload)])

    def test_cancel_before_publish(self):
        stage_type = self.stage_type()
        source_path = self.root / 'input'
        source_path.write_bytes(b'original')
        with safe_files.SafeDirectory(self.root) as parent:
            with self.assertRaises(InterruptedError):
                with parent.open_read('input') as source, stage_type(parent) as stage:
                    stage.copy_from(source, 'media.mp4', progress=lambda n: None,
                                    cancelled=lambda: True)
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['input'])
        self.assertEqual(source_path.read_bytes(), b'original')

    def test_source_mutation(self):
        stage_type = self.stage_type()
        path = self.root / 'input'
        path.write_bytes(b'original')
        with safe_files.SafeDirectory(self.root) as parent:
            with self.assertRaises(OSError) as caught:
                with parent.open_read('input') as source, stage_type(parent) as stage:
                    def mutate(n):
                        # Windows denies concurrent writers; refusal is also safe.
                        with path.open('ab') as writer:
                            writer.write(b'changed')
                    stage.copy_from(source, 'media.mp4', progress=mutate,
                                    cancelled=lambda: False)
        self.assertFalse((self.root / 'export').exists())
        self.assertTrue(caught.exception.staging_path.is_dir())

    def test_competing_destination(self):
        stage_type = self.stage_type()
        destination = self.root / 'export'
        with safe_files.SafeDirectory(self.root) as parent:
            with self.assertRaises(FileExistsError):
                with stage_type(parent) as stage:
                    destination.mkdir()
                    (destination / 'sentinel').write_bytes(b'keep')
                    stage.publish('export')
        self.assertEqual((destination / 'sentinel').read_bytes(), b'keep')
        self.assertEqual(list(self.root.iterdir()), [destination])

    def test_empty_destination_also_rejected(self):
        stage_type = self.stage_type()
        (self.root / 'export').mkdir()
        with safe_files.SafeDirectory(self.root) as parent:
            with self.assertRaises(FileExistsError), stage_type(parent) as stage:
                stage.publish('export')
        self.assertTrue((self.root / 'export').is_dir())

    def test_late_cancel_keeps_published(self):
        stage_type = self.stage_type()
        with safe_files.SafeDirectory(self.root) as parent:
            with self.assertRaises(InterruptedError):
                with stage_type(parent) as stage:
                    stage.publish('export')
                    raise InterruptedError('late cancellation')
        self.assertTrue((self.root / 'export').is_dir())

    @unittest.skipIf(os.name == 'nt', 'POSIX symlink fixture')
    def test_input_link_rejected(self):
        self.assertTrue(hasattr(safe_files.SafeDirectory, 'open_read'))
        (self.root / 'input').write_bytes(b'keep')
        (self.root / 'link').symlink_to('input')
        with safe_files.SafeDirectory(self.root) as parent:
            with self.assertRaises(OSError), parent.open_read('link'):
                pass
        self.assertEqual((self.root / 'input').read_bytes(), b'keep')

    def test_cleanup_replacement(self):
        stage_type = self.stage_type()
        (self.root / 'input').write_bytes(b'original')
        with safe_files.SafeDirectory(self.root) as parent:
            with self.assertRaises(OSError) as caught:
                with parent.open_read('input') as source, stage_type(parent) as stage:
                    stage.copy_from(source, 'media.mp4', progress=lambda n: None,
                                    cancelled=lambda: False)
                    target = Path(stage.directory.path) / 'media.mp4'
                    # Keep original inode alive so inode reuse cannot mask replacement.
                    target.rename(target.with_name('moved'))
                    target.write_bytes(b'foreign')
            self.assertTrue(hasattr(caught.exception, 'staging_path'))
            self.assertEqual((caught.exception.staging_path / 'media.mp4').read_bytes(), b'foreign')

    def test_cancel_after_partial_copy_retains_staging_without_unlink_race(self):
        from unittest.mock import patch
        stage_type = self.stage_type()
        (self.root / 'input').write_bytes(b'original')
        sentinel = self.root / 'outside'
        sentinel.write_bytes(b'foreign')
        real_unlink = os.unlink
        attempted = []
        with safe_files.SafeDirectory(self.root) as parent:
            with self.assertRaises(InterruptedError) as caught:
                with stage_type(parent) as stage:
                    with parent.open_read('input') as source:
                        stage.copy_from(source, 'media.mp4', progress=lambda n:None,cancelled=lambda:False)
                    stage_path = Path(stage.directory.path)
                    def exchange_before_unlink(name, *args, **kwargs):
                        if name == 'media.mp4':
                            attempted.append(name)
                            (stage_path / name).rename(stage_path / 'original-moved')
                            sentinel.rename(stage_path / name)
                        return real_unlink(name, *args, **kwargs)
                    # Keep patch alive through context manager exit, then restore it.
                    patcher = patch('safe_files.os.unlink', side_effect=exchange_before_unlink)
                    patcher.start(); self.addCleanup(patcher.stop)
                    raise InterruptedError('cancelled after data copied')
        patcher.stop()
        self.assertEqual(attempted, [], 'nonempty partial package must not be deleted by a raced pathname')
        self.assertEqual(sentinel.read_bytes(), b'foreign')
        self.assertEqual((caught.exception.staging_path / 'media.mp4').read_bytes(), b'original')


if __name__ == '__main__':
    unittest.main()
