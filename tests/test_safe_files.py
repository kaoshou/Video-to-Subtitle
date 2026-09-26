"""Stdlib-only regression tests; never load the GUI/ML runtime."""
import ast
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import evercam_integration as evercam
from safe_files import SafeDirectory, atomic_write_text

ROOT = Path(__file__).resolve().parents[1]
SRT = '1\n00:00:01,000 --> 00:00:02,500\n繁體中文 <b>字幕</b>\n'


class SecurityRegression(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.course = self.base / '課程 with spaces'
        self.course.mkdir()
        for name, content in {'config.js': 'var config = {};', 'media.mp4': 'video',
                              'index.html': 'original homepage', 'media.srt': SRT}.items():
            (self.course / name).write_text(content, encoding='utf-8')
        self.victim = self.base / 'outside.txt'
        self.victim.write_text('DO NOT CHANGE', encoding='utf-8')

    def link(self, path, target=None, directory=False):
        try:
            path.symlink_to(target or self.victim, target_is_directory=directory)
        except OSError as exc:
            self.skipTest(f'Symlink privilege unavailable: {exc}')

    def assertVictim(self):
        self.assertEqual(self.victim.read_text(), 'DO NOT CHANGE')

    def test_atomic_text_and_old_temp_links(self):
        target = self.course / 'media.srt'
        for suffix in ('.tmp_save', '.tmp_preview'):
            self.link(Path(str(target) + suffix))
        atomic_write_text(target, SRT + '新增\n')
        self.assertEqual(target.read_text(encoding='utf-8'), SRT + '新增\n')
        self.assertVictim()
        self.assertFalse(list(self.course.glob('.vts-*')))

    def test_atomic_rejects_existing_and_dangling_link(self):
        for destination in (self.victim, self.base / 'missing'):
            path = self.course / 'output.txt'
            self.link(path, destination)
            with self.assertRaises(OSError):
                atomic_write_text(path, 'bad')
            path.unlink()
        self.assertVictim()
        self.assertFalse((self.base / 'missing').exists())

    def test_failed_replace_preserves_original_and_cleans_staging(self):
        with patch('safe_files.os.replace', side_effect=PermissionError('locked')):
            with self.assertRaises(PermissionError):
                atomic_write_text(self.course / 'media.srt', 'new')
        self.assertEqual((self.course / 'media.srt').read_text(encoding='utf-8'), SRT)
        self.assertFalse(list(self.course.glob('.vts-*')))

    def test_root_exchanged_after_metadata_check(self):
        original_lstat = os.lstat
        moved = self.base / 'moved-course'
        fired = False
        def swap(path, *args, **kwargs):
            nonlocal fired
            info = original_lstat(path, *args, **kwargs)
            if not fired and os.fspath(path) == str(self.course):
                fired = True
                self.course.rename(moved)
                self.link(self.course, self.base, directory=True)
            return info
        with patch('safe_files.os.lstat', side_effect=swap):
            with self.assertRaises(OSError):
                with SafeDirectory(self.course) as directory:
                    directory.write_bytes('outside.txt', b'bad')
        self.assertVictim()

    @unittest.skipIf(os.name == 'nt', 'POSIX descriptor anchoring')
    def test_open_directory_stays_anchored_after_rename(self):
        with SafeDirectory(self.course) as directory:
            moved = self.base / 'moved-course'
            self.course.rename(moved)
            self.link(self.course, self.base, directory=True)
            directory.write_bytes('outside.txt', b'safe')
        self.assertEqual((moved / 'outside.txt').read_bytes(), b'safe')
        self.assertVictim()

    def test_leaf_exchanged_immediately_before_replace(self):
        original_replace = os.replace
        def swap(source, target, *args, **kwargs):
            path = self.course / 'media.srt'
            path.unlink()
            self.link(path)
            return original_replace(source, target, *args, **kwargs)
        with patch('safe_files.os.replace', side_effect=swap):
            atomic_write_text(self.course / 'media.srt', 'safe')
        self.assertVictim()
        self.assertFalse((self.course / 'media.srt').is_symlink())

    def test_deploy_and_redeploy_preserve_backup_and_custom_files(self):
        (self.course / 'css').mkdir()
        (self.course / 'css' / 'custom.css').write_text('custom')
        for _ in range(2):
            self.assertTrue(evercam.deploy_evercam_player(str(self.course))[0])
        self.assertEqual((self.course / 'index.evercam-original.html').read_text(), 'original homepage')
        self.assertEqual((self.course / 'css' / 'custom.css').read_text(), 'custom')
        ok, _, payload = evercam.generate_subtitles_data_js(str(self.course))
        self.assertTrue(ok)
        self.assertEqual(payload['defaultLanguage'], 'zh-TW')
        self.assertEqual(payload['tracks'][0]['cues'][0]['text'], '繁體中文 字幕')
        self.assertEqual((self.course / 'media.mp4').read_text(), 'video')

    def test_all_output_links_fail_without_touching_homepage(self):
        for name in ('index.html', 'index.evercam-original.html', 'subtitles-data.js', 'media.en.srt'):
            for dangling in (False, True):
                with self.subTest(name=name, dangling=dangling):
                    path = self.course / name
                    previous = path.read_bytes() if path.exists() else None
                    if path.exists(): path.unlink()
                    target = self.base / 'missing' if dangling else self.victim
                    self.link(path, target)
                    ok, _, _ = evercam.deploy_evercam_player(str(self.course), str(self.course / 'media.srt'), 'en')
                    self.assertFalse(ok)
                    self.assertVictim()
                    self.assertFalse((self.base / 'missing').exists())
                    path.unlink()
                    if previous is not None: path.write_bytes(previous)

    def test_asset_directory_links_rejected(self):
        for name in ('css', 'js', 'tools'):
            with self.subTest(name=name):
                self.link(self.course / name, self.base, directory=True)
                self.assertFalse(evercam.deploy_evercam_player(str(self.course))[0])
                self.assertEqual((self.course / 'index.html').read_text(), 'original homepage')
                (self.course / name).unlink()

    def test_backup_failure_stops_before_overwrite(self):
        with patch.object(SafeDirectory, 'write_bytes', side_effect=PermissionError('backup denied')):
            self.assertFalse(evercam.deploy_evercam_player(str(self.course))[0])
        self.assertEqual((self.course / 'index.html').read_text(), 'original homepage')

    def test_exclusive_backup_never_overwrites_existing(self):
        with SafeDirectory(self.course) as directory:
            directory.write_bytes('backup.html', b'first', exclusive=True)
            with self.assertRaises(FileExistsError):
                directory.write_bytes('backup.html', b'second', exclusive=True)
        self.assertEqual((self.course / 'backup.html').read_bytes(), b'first')

    def test_nested_asset_file_link(self):
        asset = next(p for p in (ROOT / 'assets/evercam_player/css').iterdir() if p.is_file())
        (self.course / 'css').mkdir()
        self.link(self.course / 'css' / asset.name)
        self.assertFalse(evercam.deploy_evercam_player(str(self.course))[0])
        self.assertVictim()
        self.assertEqual((self.course / 'index.html').read_text(), 'original homepage')

    def test_same_source_and_destination(self):
        target = self.course / 'media.zh-TW.srt'
        target.write_text(SRT, encoding='utf-8')
        self.assertTrue(evercam.deploy_evercam_player(str(self.course), str(target))[0])
        self.assertEqual(target.read_text(encoding='utf-8'), SRT)

    def test_external_subtitle_and_named_vtt_precedence(self):
        source = self.base / 'external.srt'
        source.write_text(SRT, encoding='utf-8')
        (self.course / 'media.zh-TW.vtt').write_text('WEBVTT\n\n00:00:03.000 --> 00:00:04.000\n具名字幕\n', encoding='utf-8')
        self.assertTrue(evercam.deploy_evercam_player(str(self.course), str(source), 'en')[0])
        ok, _, payload = evercam.generate_subtitles_data_js(str(self.course))
        self.assertTrue(ok)
        self.assertEqual({t['language'] for t in payload['tracks']}, {'en', 'zh-TW'})
        self.assertEqual(next(t for t in payload['tracks'] if t['language']=='zh-TW')['cues'][0]['text'], '具名字幕')

    def test_generator_rejects_output_link(self):
        self.link(self.course / 'subtitles-data.js')
        self.assertFalse(evercam.generate_subtitles_data_js(str(self.course))[0])
        self.assertVictim()

    def test_input_subtitle_link_is_rejected(self):
        path = self.course / 'media.srt'
        path.unlink()
        self.link(path)
        self.assertFalse(evercam.generate_subtitles_data_js(str(self.course))[0])
        self.assertFalse(evercam.deploy_evercam_player(str(self.course))[0])
        self.assertVictim()

    def test_hardlinked_output_is_replaced_not_truncated(self):
        os.link(self.victim, self.course / 'subtitles-data.js')
        self.assertTrue(evercam.generate_subtitles_data_js(str(self.course))[0])
        self.assertVictim()

    @unittest.skipUnless(os.name == 'nt', 'Windows junction test')
    def test_windows_junction(self):
        junction = self.course / 'js'
        result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(junction), str(self.base)], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        try:
            self.assertFalse(evercam.deploy_evercam_player(str(self.course))[0])
            self.assertVictim()
        finally:
            os.rmdir(junction)

    @unittest.skipUnless(os.name == 'nt', 'Windows PowerShell junction test')
    def test_powershell_windows_junction_root(self):
        executable = shutil.which('powershell') or shutil.which('pwsh')
        self.assertIsNotNone(executable)
        junction = self.base / 'linked-course'
        result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(junction), str(self.course)], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        try:
            result = subprocess.run([executable, '-NoProfile', '-File', str(ROOT / 'assets/evercam_player/tools/Build-Subtitles.ps1'),
                                     '-CourseFolder', str(junction)], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((self.course / 'subtitles-data.js').exists())
        finally:
            os.rmdir(junction)

    @unittest.skipUnless(shutil.which('pwsh') or shutil.which('powershell'), 'PowerShell unavailable')
    def test_powershell_normal_and_link_outputs(self):
        executable = shutil.which('powershell') or shutil.which('pwsh')
        script = ROOT / 'assets/evercam_player/tools/Build-Subtitles.ps1'
        def run():
            return subprocess.run([executable, '-NoProfile', '-File', str(script), '-CourseFolder', str(self.course)], capture_output=True, text=True)
        for _ in range(2):
            result = run()
            self.assertEqual(result.returncode, 0, result.stderr)
        output = self.course / 'subtitles-data.js'
        self.assertIn('繁體中文', output.read_text(encoding='utf-8'))
        output.unlink()
        self.link(output)
        self.assertNotEqual(run().returncode, 0)
        self.assertVictim()
        output.unlink()
        self.link(output, self.base / 'missing')
        self.assertNotEqual(run().returncode, 0)
        self.assertFalse((self.base / 'missing').exists())


class EditorRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tree = ast.parse((ROOT / 'SubtitleTranscriber.py').read_text(encoding='utf-8'))
        editor = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'SubtitleEditorWindow')
        names = {'_parse_subtitle_text', '_generate_subtitle_string', '_toggle_raw_mode', 'save_and_close'}
        module = ast.Module(body=[n for n in editor.body if isinstance(n, ast.FunctionDef) and n.name in names], type_ignores=[])
        cls.dialog = Mock()
        scope = {'atomic_write_text': atomic_write_text, 'os': os, 'messagebox': cls.dialog}
        exec(compile(module, str(ROOT / 'SubtitleTranscriber.py'), 'exec'), scope)
        cls.methods = {name: scope[name] for name in names}

    def editor(self, **fields):
        editor = SimpleNamespace(**fields)
        for name, method in self.methods.items(): setattr(editor, name, method.__get__(editor))
        return editor

    def test_memory_preview_no_file_operations(self):
        editor = self.editor(is_raw_mode=True, raw_editor=Mock(get=Mock(return_value=SRT)),
                             raw_frame=Mock(), structured_frame=Mock(), search_bar_frame=Mock(),
                             btn_toggle_mode=Mock(), _populate_treeview=Mock(), _select_tree_row=Mock())
        with patch('builtins.open', side_effect=AssertionError('preview must not use disk')):
            editor._toggle_raw_mode()
        self.assertEqual(len(editor.items), 1)
        self.assertFalse(editor.is_raw_mode)

    def test_save_txt_raw_srt_and_vtt(self):
        with tempfile.TemporaryDirectory() as folder:
            for kind in ('txt', 'raw', 'srt', 'vtt'):
                editor = self.editor(file_path=os.path.join(folder, kind), is_txt=kind=='txt',
                    is_raw_mode=kind=='raw', is_vtt=kind=='vtt', txt_editor=Mock(get=Mock(return_value='文字')),
                    raw_editor=Mock(get=Mock(return_value=SRT)), destroy=Mock())
                editor.items = editor._parse_subtitle_text(SRT)
                editor.save_and_close()
                editor.destroy.assert_called_once()
                content = Path(editor.file_path).read_text(encoding='utf-8')
                self.assertIn('文字' if kind=='txt' else '繁體中文', content)
                if kind=='vtt': self.assertTrue(content.startswith('WEBVTT'))

    def test_save_failure_keeps_editor_open(self):
        self.dialog.reset_mock()
        editor = self.editor(file_path='/does-not-exist/subtitle.txt', is_txt=True,
                             txt_editor=Mock(get=Mock(return_value='文字')), destroy=Mock())
        editor.save_and_close()
        editor.destroy.assert_not_called()
        self.dialog.showerror.assert_called_once()


if __name__ == '__main__':
    unittest.main()
