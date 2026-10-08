import importlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from uuid import UUID


def make_video(path):
    import av
    with av.open(str(path), 'w', format='mp4') as output:
        stream = output.add_stream('libx264', rate=10)
        stream.width, stream.height, stream.pix_fmt = 64, 64, 'yuv420p'
        for i in range(10):
            frame = av.VideoFrame(64, 64, 'yuv420p')
            for plane in frame.planes:
                plane.update(bytes([128]) * plane.buffer_size)
            for packet in stream.encode(frame): output.mux(packet)
        for packet in stream.encode(): output.mux(packet)


class Inputs(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def api(self):
        self.assertIsNotNone(importlib.util.find_spec('web_export'), 'input module missing')
        return importlib.import_module('web_export')

    def test_strict_subtitles(self):
        api = self.api()
        text = '\ufeff1\n00:00:00,000 --> 00:00:02,000\n<script>文字</script>\n\n2\n00:00:01,000 --> 00:00:03,000\n重疊\n'
        cues = api.parse_subtitles(text, '.srt', '字幕.srt')
        self.assertEqual(cues, [{'start': 0.0, 'end': 2.0, 'text': '<script>文字</script>'},
                                {'start': 1.0, 'end': 3.0, 'text': '重疊'}])
        vtt = 'WEBVTT\n\nNOTE comment\nignore\n\nSTYLE\n::cue { color:red }\n\nname\n00:01.000 --> 00:02.000 align:start\n你好\n'
        self.assertEqual(api.parse_subtitles(vtt, '.vtt', 'x.vtt'), [{'start': 1.0, 'end': 2.0, 'text': '你好'}])

    def test_bad_subtitles(self):
        api = self.api()
        for content in ['', '1\n00:00:00,000 --> 00:00:01,000\n',
                        '1\n-1 --> nan\ntext', '1\n00:00:02,000 --> 00:00:01,000\ntext',
                        '1\n00:99:00,000 --> 00:00:01,000\ntext',
                        '1\n00:00:00,000 --> 00:00:01,000\nvalid\n\nbroken']:
            with self.subTest(content=content), self.assertRaisesRegex(ValueError, 'bad.srt'):
                api.parse_subtitles(content, '.srt', 'bad.srt')

    def test_media_probe_real_mp4(self):
        api = self.api()
        make_video(self.root / 'media.mp4')
        info = api.probe_video(self.root / 'media.mp4')
        self.assertGreater(info['duration'], 0)
        self.assertEqual(info['codec'], 'h264')
        (self.root / 'fake.mp4').write_bytes(b'not a video')
        with self.assertRaises((ValueError, OSError)):
            api.probe_video(self.root / 'fake.mp4')

    def test_poster_reencode(self):
        api = self.api()
        from PIL import Image, PngImagePlugin
        meta = PngImagePlugin.PngInfo()
        meta.add_text('private', '/Users/private')
        Image.new('RGB', (20, 20), 'red').save(self.root / 'cover.png', pnginfo=meta)
        data = api.prepare_poster(self.root / 'cover.png')
        self.assertNotIn(b'/Users/private', data)
        self.assertTrue(data.startswith(b'\x89PNG'))
        (self.root / 'bad.png').write_bytes(b'<svg/>')
        with self.assertRaises((ValueError, OSError)):
            api.prepare_poster(self.root / 'bad.png')

    def manifest(self):
        return {'schemaVersion': 1, 'kind': 'video-to-subtitle-web',
                'packageId': str(UUID(int=1)), 'appVersion': '2.7.8',
                'metadata': {'title': '課程', 'author': '', 'organization': '', 'description': ''},
                'video': {'path': 'media.mp4', 'duration': 1.0}, 'poster': None,
                'subtitles': [{'language': 'zh-TW', 'path': 'media.zh-TW.srt'}],
                'defaultSubtitle': 'zh-TW'}

    def write_manifest(self, value):
        (self.root / 'web-export.json').write_text(json.dumps(value), encoding='utf-8')

    def test_load_missing_files_without_executing_scripts(self):
        api = self.api()
        self.write_manifest(self.manifest())
        (self.root / 'player-config.js').write_text('throw new Error("must not execute")')
        loaded = api.load_package(self.root)
        self.assertEqual(loaded.request.metadata.title, '課程')
        self.assertEqual(loaded.request.video, self.root / 'media.mp4')
        self.assertEqual(len(loaded.issues), 2)

    def test_untrusted_manifest_rejected(self):
        api = self.api()
        for version in [True, 2, '1']:
            manifest = self.manifest(); manifest['schemaVersion'] = version
            self.write_manifest(manifest)
            with self.assertRaises(ValueError): api.load_package(self.root)
        for path in ['../media.mp4', '/tmp/media.mp4', 'https://example.com/a.mp4', 'sub/media.mp4']:
            manifest = self.manifest(); manifest['video']['path'] = path
            self.write_manifest(manifest)
            with self.assertRaises(ValueError): api.load_package(self.root)
        (self.root / 'web-export.json').write_bytes(b' ' * (1024 * 1024 + 1))
        with self.assertRaises(ValueError): api.load_package(self.root)

    def test_manifest_requires_stable_package_identity(self):
        api = self.api()
        manifest = self.manifest(); manifest['packageId'] = None
        self.write_manifest(manifest)
        with self.assertRaises(ValueError): api.load_package(self.root)

    def test_probe_accepts_already_pinned_stream(self):
        api = self.api()
        self.assertTrue(hasattr(api, 'probe_video_stream'))
        make_video(self.root / 'media.mp4')
        from safe_files import SafeDirectory
        with SafeDirectory(self.root) as directory, directory.open_read('media.mp4') as stream:
            info = api.probe_video_stream(stream, 'media.mp4')
            self.assertEqual(info['codec'], 'h264')
            self.assertFalse(stream.closed)


if __name__ == '__main__': unittest.main()
