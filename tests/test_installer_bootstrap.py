"""Exercise the installer's configured launch route before model GUI startup."""
import configparser
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import SubtitleTranscriber as desktop


class InstallerBootstrap(unittest.TestCase):
    def test_finish_action_requests_desktop_bootstrap_not_plain_app_start(self):
        path = Path(__file__).resolve().parents[1] / 'packaging/windows/VideoToSubtitle.iss'
        sections = configparser.ConfigParser(interpolation=None, delimiters=(':', '='), strict=False)
        sections.optionxform = str
        sections.read(path, encoding='utf-8')
        run_line = next(value for key, value in sections['Run'].items()
                        if key == 'Filename' and 'VideoToSubtitle.exe' in value)
        # Interpret the actual [Run] entry, not merely a source-text marker.
        fields = dict(part.strip().split(':', 1) for part in ('Filename: ' + run_line).split(';'))
        arguments = fields.get('Parameters', '').strip().strip('"').split()
        self.assertIn('--from-installer', arguments)

    def test_installer_bootstrap_dispatches_only_the_current_installed_executable(self):
        broker = Mock()
        with patch.dict('sys.modules', {'ui_installer_launch': SimpleNamespace(launch_via_desktop=broker)}), \
                patch.object(desktop.sys, 'platform', 'win32'), \
                patch.object(desktop.sys, 'frozen', True, create=True), \
                patch.object(desktop.sys, 'executable', '/installed app/VideoToSubtitle.exe'):
            result = desktop.launch_after_install()
        self.assertEqual(result, 0)
        broker.assert_called_once_with('/installed app/VideoToSubtitle.exe', '/installed app')

    def test_shell_failure_is_actionable_and_does_not_fall_back_to_child_start(self):
        broker = Mock(side_effect=RuntimeError('desktop shell unavailable'))
        messages = []
        with patch.dict('sys.modules', {'ui_installer_launch': SimpleNamespace(launch_via_desktop=broker)}), \
                patch.object(desktop.sys, 'platform', 'win32'), \
                patch.object(desktop.sys, 'frozen', True, create=True), \
                patch.object(desktop.sys, 'executable', '/installed app/VideoToSubtitle.exe'), \
                patch.object(desktop.messagebox, 'showwarning',
                             side_effect=lambda title, message: messages.append((title, message))):
            result = desktop.launch_after_install()
        self.assertEqual(result, 1)
        self.assertEqual(len(messages), 1)
        self.assertIn('開始', messages[0][1])
        self.assertIn('模型', messages[0][1])

    def test_source_or_non_windows_invocation_cannot_dispatch(self):
        broker = Mock()
        for platform, frozen in (('darwin', True), ('win32', False)):
            with self.subTest(platform=platform, frozen=frozen), \
                    patch.dict('sys.modules', {'ui_installer_launch': SimpleNamespace(launch_via_desktop=broker)}), \
                    patch.object(desktop.sys, 'platform', platform), \
                    patch.object(desktop.sys, 'frozen', frozen, create=True), \
                    patch.object(desktop.messagebox, 'showwarning'):
                self.assertEqual(desktop.launch_after_install(), 1)
        broker.assert_not_called()
