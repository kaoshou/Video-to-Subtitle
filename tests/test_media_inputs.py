"""Real filesystem inputs: filename suffix must never override file type."""
import json
from pathlib import Path
import tempfile
import unittest


class MediaInputs(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def collect(self, *paths):
        from media_inputs import collect_media_inputs
        return collect_media_inputs(paths, {'.mp4', '.wav'})

    def test_mp4_named_directory_loads_real_media_and_not_nested_mp4_directories(self):
        folder = self.root / '示範課程.ecmx.mp4'
        folder.mkdir()
        nested = folder / '也是目錄.mp4'
        nested.mkdir()
        video = nested / '課程.mp4'
        video.touch()
        audio = folder / '語音.wav'
        audio.touch()
        (folder / '說明.txt').touch()
        files, rejected = self.collect(folder, video, folder)
        self.assertEqual(set(files), {str(video), str(audio)})
        self.assertEqual(len(files), 2)
        self.assertTrue(all(Path(path).is_file() for path in files))
        self.assertEqual(rejected, [])

    def test_evercam_needs_real_media_not_a_directory_with_video_extension(self):
        import evercam_integration as evercam
        folder = self.root / '示範課程.ecmx.mp4'
        folder.mkdir()
        (folder / 'config.js').write_text('var config = {};', encoding='utf-8')
        (folder / '假的影片.mp4').mkdir()
        self.assertFalse(evercam.is_evercam_folder(folder))
        video = folder / 'media.mp4'
        video.touch()
        self.assertTrue(evercam.is_evercam_folder(folder))
        files, rejected = self.collect(folder, folder / 'config.js', video)
        self.assertEqual(files, [str(video)])
        self.assertEqual(rejected, [])

    def test_opencam_directory_and_entry_only_add_associated_video_once(self):
        folder = self.root / 'OpenCam.mp4'
        folder.mkdir()
        data = {'format':'opencam.web-player', 'schemaVersion':1, 'entry':'index.html',
                'media':'media.mp4', 'title':'示範', 'chapters':[], 'subtitles':None}
        (folder / 'opencam-player.js').write_text('window.OpenCamPlayerData = ' + json.dumps(data) + ';', encoding='utf-8')
        (folder / 'index.html').touch()
        video = folder / 'media.mp4'
        video.touch()
        (folder / 'unrelated.mp4').touch()
        files, rejected = self.collect(folder, folder / 'index.html', video)
        self.assertEqual(files, [str(video)])
        self.assertEqual(rejected, [])

    def test_recursive_scan_does_not_follow_symlink_directories_or_files(self):
        folder = self.root / 'scan'
        folder.mkdir()
        outside = self.root / 'outside'
        outside.mkdir()
        (outside / 'private.mp4').touch()
        try:
            (folder / 'linked').symlink_to(outside, target_is_directory=True)
            (folder / 'linked.mp4').symlink_to(outside / 'private.mp4')
        except OSError as exc:
            self.skipTest(f'symlinks unavailable: {exc}')
        self.assertEqual(self.collect(folder), ([], []))

    def test_explicit_invalid_files_are_reported_but_empty_folders_are_not_media(self):
        invalid = self.root / 'note.txt'
        invalid.touch()
        empty = self.root / 'empty.mp4'
        empty.mkdir()
        self.assertEqual(self.collect(invalid, empty, self.root / 'missing.mp4'), ([], ['note.txt']))
