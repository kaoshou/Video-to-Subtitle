"""Client fixtures never inspect the real home or execute client programs."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

from mcp_state import MCPError, State


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.state = self.home / 'private-state'
        self.config = self.home / 'client.json'
        self.command = [sys.executable, str(Path(__file__).resolve().parents[1] / 'app_entry.py'),
                        '--mcp', '--state-dir', str(self.state)]

    def api(self):
        import mcp_clients
        return mcp_clients

    def preview(self, client='claude-code'):
        return self.api().preview_connection(client, self.config, self.command, state_dir=self.state)

    def test_schema_adapters_emit_distinct_official_shapes(self):
        api = self.api()
        expected = {'command': self.command[0], 'args': self.command[1:]}
        self.assertEqual(api.connection_entry(self.command, 'codex'), expected)
        for client in ('claude-code', 'gemini-cli', 'antigravity', 'cursor', 'copilot', 'windsurf'):
            self.assertEqual(api.connection_entry(self.command, client), expected)
        self.assertEqual(api.connection_entry(self.command, 'vscode'), {'type': 'stdio', **expected})
        self.assertEqual(api.connection_entry(self.command, 'opencode'),
                         {'type': 'local', 'command': self.command, 'enabled': True})

    def test_arbitrary_commands_shells_and_nonfixed_python_entry_reject(self):
        api = self.api()
        for command in (['python', 'app_entry.py', '--mcp'], ['/bin/sh', '-c', 'anything'],
                        [sys.executable, str(self.home / 'evil.py'), '--mcp'],
                        self.command + ['--self-test'], self.command + ['--state-dir', '/tmp']):
            with self.subTest(command=command), self.assertRaises(MCPError):
                api.connection_entry(command, 'cursor')

    def test_discovery_reports_metadata_manual_and_environment_paths_without_reading_content(self):
        (self.home / '.cursor').mkdir()
        config = self.home / '.cursor' / 'mcp.json'
        config.write_text('{ secret invalid content', encoding='utf-8')
        before = config.stat()
        rows = self.api().discover_clients(home=self.home, environ={
            'CODEX_HOME': str(self.home / 'codex-custom'),
            'COPILOT_HOME': str(self.home / 'copilot-custom'),
            'OPENCODE_CONFIG': str(self.home / 'open-custom.json')}, system='Darwin',
            application_roots=(), executable_roots=())
        by_id = {row['id']: row for row in rows}
        self.assertEqual(set(by_id), {'codex', 'claude-code', 'claude-desktop', 'gemini-cli',
                                     'antigravity', 'cursor', 'vscode', 'copilot', 'windsurf',
                                     'opencode', 'generic'})
        self.assertEqual(by_id['codex']['config_path'], str(self.home / 'codex-custom' / 'config.toml'))
        self.assertEqual(by_id['copilot']['config_path'], str(self.home / 'copilot-custom' / 'mcp-config.json'))
        self.assertEqual(by_id['opencode']['config_path'], str(self.home / 'open-custom.json'))
        self.assertTrue(by_id['cursor']['detected'])
        self.assertTrue(by_id['cursor']['configuration_detected'])
        self.assertFalse(by_id['cursor']['installation_detected'])
        for row in rows:
            self.assertFalse(row['live_verified'])
            self.assertFalse(row['version_verified'])
            self.assertTrue(row['compatibility_note'])
        self.assertTrue(by_id['cursor']['schema_supported'])
        self.assertTrue(by_id['cursor']['can_apply'])
        self.assertFalse(by_id['windsurf']['can_apply'])
        self.assertIsNone(by_id['vscode']['config_path'])
        self.assertEqual((config.stat().st_size, config.stat().st_mtime_ns),
                         (before.st_size, before.st_mtime_ns))
        self.assertFalse(self.state.exists())

    def test_json_add_idempotence_and_remove_preserve_unrelated_later_edit(self):
        original = {'mcpServers': {'other': {'command': '/other', 'env': {'SECRET': 'keep-me'}}},
                    'theme': 'dark'}
        self.config.write_text(json.dumps(original), encoding='utf-8')
        api = self.api()
        preview = self.preview()
        self.assertNotIn('keep-me', json.dumps(preview))
        self.assertNotIn('theme', json.dumps(preview))
        result = api.apply_connection(preview, state_dir=self.state)
        self.assertEqual(result['status'], 'applied')
        applied = json.loads(self.config.read_text())
        self.assertEqual(applied['mcpServers']['other'], original['mcpServers']['other'])
        self.assertEqual(api.apply_connection(self.preview(), state_dir=self.state)['status'], 'unchanged')
        applied['theme'] = 'light'
        applied['mcpServers']['later'] = {'command': '/later'}
        self.config.write_text(json.dumps(applied))
        self.assertEqual(api.remove_connection('claude-code', self.config, state_dir=self.state)['status'], 'removed')
        removed = json.loads(self.config.read_text())
        self.assertEqual(removed['theme'], 'light')
        self.assertEqual(removed['mcpServers'], {'other': original['mcpServers']['other'],
                                                'later': {'command': '/later'}})
        backups = State(self.state).records('backups')
        self.assertTrue(backups)
        self.assertIn(json.dumps(original), [backup['original_text'] for backup in backups])
        if os.name != 'nt':
            for stored in self.state.rglob('*.json'):
                self.assertEqual(stored.stat().st_mode & 0o077, 0)

    def test_unknown_same_name_even_equal_entry_is_not_adopted(self):
        self.config.write_text(json.dumps({'mcpServers': {'video-to-subtitle': {
            'command': self.command[0], 'args': self.command[1:]}}}))
        with self.assertRaises(MCPError) as caught:
            self.preview()
        self.assertEqual(caught.exception.code, 'ENTRY_CONFLICT')

    def test_edit_after_preview_and_tampered_preview_refuse(self):
        self.config.write_text('{}')
        api = self.api()
        preview = self.preview()
        self.config.write_text('{"new":"edit"}')
        with self.assertRaises(MCPError) as caught:
            api.apply_connection(preview, state_dir=self.state)
        self.assertEqual(caught.exception.code, 'CONFIG_CHANGED')
        self.assertEqual(self.config.read_text(), '{"new":"edit"}')
        preview = self.preview()
        preview['entry_after']['command'] = '/bin/sh'
        with self.assertRaises(MCPError):
            api.apply_connection(preview, state_dir=self.state)

    def test_remove_changed_owned_entry_refuses(self):
        api = self.api()
        api.apply_connection(self.preview(), state_dir=self.state)
        data = json.loads(self.config.read_text())
        data['mcpServers']['video-to-subtitle']['args'].append('changed')
        self.config.write_text(json.dumps(data))
        with self.assertRaises(MCPError) as caught:
            api.remove_connection('claude-code', self.config, state_dir=self.state)
        self.assertEqual(caught.exception.code, 'ENTRY_CHANGED')
        self.assertIn('changed', self.config.read_text())

    def test_malformed_oversize_readonly_symlink_and_unknown_versions_refuse(self):
        for content in ('[not-json', '[]', '{"mcpServers":[]}', '{"x":1,"x":2}',
                        '{"version":999}', ' ' * (1024 * 1024 + 1)):
            self.config.write_text(content)
            with self.subTest(content=content[:30]), self.assertRaises(MCPError):
                self.preview()
        self.config.write_text('{}')
        self.config.chmod(0o444)
        try:
            with self.assertRaises(MCPError):
                self.preview()
        finally:
            self.config.chmod(0o600)
        linked = self.home / 'linked.json'
        linked.symlink_to(self.config)
        with self.assertRaises(MCPError):
            self.api().preview_connection('cursor', linked, self.command, state_dir=self.state)

    def test_jsonc_remains_manual_without_comment_loss(self):
        self.config = self.home / 'mcp.jsonc'
        self.config.write_text('{\n// secret comment\n"servers":{}\n}')
        with self.assertRaises(MCPError) as caught:
            self.preview('vscode')
        self.assertEqual(caught.exception.code, 'MANUAL_ONLY')
        self.assertIn('// secret comment', self.config.read_text())
        manual = json.loads(self.api().manual_configuration('vscode', self.command))
        self.assertEqual(manual['servers']['video-to-subtitle']['type'], 'stdio')

    def test_codex_toml_comments_order_and_unrelated_values_survive(self):
        self.config = self.home / 'config.toml'
        content = '# heading\nmodel = "keep" # inline\n\n[mcp_servers.other]\ncommand = "/other" # secret\n'
        self.config.write_text(content)
        api = self.api()
        api.apply_connection(self.preview('codex'), state_dir=self.state)
        added = self.config.read_text()
        self.assertIn(content, added)
        api.remove_connection('codex', self.config, state_dir=self.state)
        self.assertEqual(self.config.read_text().rstrip(), content.rstrip())

    def test_claude_code_user_scope_never_changes_project_servers(self):
        self.config.write_text(json.dumps({'projects': {'/project': {'mcpServers': {'existing': {
            'command': '/keep'}}}}, 'mcpServers': {}}))
        self.api().apply_connection(self.preview(), state_dir=self.state)
        data = json.loads(self.config.read_text())
        self.assertEqual(data['projects']['/project']['mcpServers'], {'existing': {'command': '/keep'}})
        self.assertIn('video-to-subtitle', data['mcpServers'])

    def test_desktop_refuses_settings_edits_and_source_only_mcpb(self):
        api = self.api()
        with self.assertRaises(MCPError) as caught:
            self.preview('claude-desktop')
        self.assertEqual(caught.exception.code, 'MANUAL_ONLY')
        with self.assertRaises(MCPError) as caught:
            api.export_mcpb(self.home / 'server.mcpb', self.command)
        self.assertEqual(caught.exception.code, 'PACKAGED_BINARY_REQUIRED')
        self.assertFalse((self.home / 'server.mcpb').exists())

    def test_null_or_wrong_container_entry_never_overwritten(self):
        for entry in (None, [], 'external', {'env': {'SECRET': 'private'}}):
            self.config.write_text(json.dumps({'mcpServers': {'video-to-subtitle': entry}}))
            with self.subTest(entry=entry), self.assertRaises(MCPError) as caught:
                self.preview()
            self.assertEqual(caught.exception.code, 'ENTRY_CONFLICT')

    def test_malformed_utf8_and_commented_json_have_actionable_errors(self):
        self.config.write_bytes(b'\xff')
        with self.assertRaises(MCPError):
            self.preview()
        self.config.write_text('{/* preserve me */"mcpServers":{}}')
        with self.assertRaises(MCPError) as caught:
            self.preview()
        self.assertEqual(caught.exception.code, 'MANUAL_ONLY')

    def test_change_during_atomic_staging_is_not_overwritten(self):
        from safe_files import SafeDirectory
        self.config.write_text('{}')
        preview = self.preview()
        original = SafeDirectory.write_bytes
        def edit_before_publish(directory, name, data, **kwargs):
            if Path(directory.path).samefile(self.config.parent) and name == self.config.name:
                self.config.write_text('{"external":"latest edit"}')
            return original(directory, name, data, **kwargs)
        with mock.patch.object(SafeDirectory, 'write_bytes', edit_before_publish), self.assertRaises(MCPError) as caught:
            self.api().apply_connection(preview, state_dir=self.state)
        self.assertEqual(caught.exception.code, 'CONFIG_CHANGED')
        self.assertEqual(json.loads(self.config.read_text()), {'external': 'latest edit'})

    def frozen_payload(self):
        root = self.home / 'release'
        root.mkdir()
        name = 'VideoToSubtitleMCP.exe' if sys.platform == 'win32' else 'VideoToSubtitleMCP'
        launcher = root / name
        # A controlled inert fixture, never executed and never copied from a
        # user binary. Hash provenance is the simulated frozen distribution.
        launcher.write_bytes(b'controlled standalone payload fixture')
        descriptor = {'launcher': name, 'sha256': hashlib.sha256(launcher.read_bytes()).hexdigest(),
                      'platform': sys.platform}
        (root / 'vts-mcp-payload.json').write_text(json.dumps(descriptor))
        return root, launcher, descriptor

    def test_mcpb_only_contains_fixed_trusted_payload_and_manifest(self):
        root, launcher, descriptor = self.frozen_payload()
        destination = self.home / 'chosen.mcpb'
        command = [str(launcher), '--mcp', '--state-dir', str(self.state)]
        with mock.patch.object(sys, 'frozen', True, create=True), mock.patch.object(sys, '_MEIPASS', str(root), create=True):
            result = self.api().export_mcpb(destination, command)
            self.assertEqual(result['payload_sha256'], descriptor['sha256'])
            with self.assertRaises((MCPError, FileExistsError)):
                self.api().export_mcpb(destination, command)
        with zipfile.ZipFile(destination) as archive:
            self.assertEqual(archive.namelist(), ['manifest.json', 'server/' + launcher.name])
            manifest = json.loads(archive.read('manifest.json'))
            self.assertEqual(manifest['manifest_version'], '0.3')
            self.assertEqual(manifest['server']['type'], 'binary')
            self.assertEqual(manifest['server']['entry_point'], 'server/' + launcher.name)
            self.assertEqual(manifest['server']['mcp_config']['command'], '${__dirname}/server/' + launcher.name)
            self.assertEqual(manifest['server']['mcp_config']['args'], command[1:])
            self.assertEqual(manifest['compatibility']['platforms'], [sys.platform])
            self.assertEqual(archive.read('server/' + launcher.name), launcher.read_bytes())

    def test_mac_bundle_uses_regular_resources_descriptor_and_frameworks_launcher(self):
        contents = self.home / 'VideoToSubtitle.app' / 'Contents'
        framework = contents / 'Frameworks'
        resource = contents / 'Resources'
        framework.mkdir(parents=True)
        resource.mkdir()
        launcher = framework / 'VideoToSubtitleMCP'
        launcher.write_bytes(b'controlled mac payload')
        descriptor = resource / 'vts-mcp-payload.json'
        descriptor.write_text(json.dumps({'launcher': launcher.name, 'platform': 'darwin',
                                         'sha256': hashlib.sha256(launcher.read_bytes()).hexdigest()}))
        with mock.patch.object(sys, 'platform', 'darwin'), mock.patch.object(sys, 'frozen', True, create=True), \
                mock.patch.object(sys, '_MEIPASS', str(framework), create=True):
            payload = self.api().bundled_mcp_payload()
            self.assertTrue(payload.launcher.samefile(launcher))
            # A wrong-role fallback must not accept even an identical descriptor.
            descriptor.rename(framework / descriptor.name)
            with self.assertRaises(MCPError):
                self.api().bundled_mcp_payload()
            descriptor.symlink_to(framework / descriptor.name)
            with self.assertRaises(MCPError):
                self.api().bundled_mcp_payload()
            descriptor.unlink()
            (framework / descriptor.name).rename(descriptor)
            moved = resource / launcher.name
            launcher.rename(moved)
            launcher.symlink_to(moved)
            with self.assertRaises(MCPError):
                self.api().bundled_mcp_payload()

    def test_mcpb_rejects_changed_payload_links_and_external_python(self):
        root, launcher, descriptor = self.frozen_payload()
        with mock.patch.object(sys, 'frozen', True, create=True), mock.patch.object(sys, '_MEIPASS', str(root), create=True):
            with self.assertRaises(MCPError):
                self.api().export_mcpb(self.home / 'bad.mcpb', self.command)
            launcher.write_bytes(b'changed')
            with self.assertRaises(MCPError):
                self.api().export_mcpb(self.home / 'bad.mcpb', [str(launcher), '--mcp'])
            launcher.unlink()
            launcher.symlink_to(sys.executable)
            with self.assertRaises(MCPError):
                self.api().export_mcpb(self.home / 'bad.mcpb', [str(launcher), '--mcp'])
        self.assertFalse((self.home / 'bad.mcpb').exists())

    def test_stable_launcher_copy_must_match_trusted_frozen_payload(self):
        root, launcher, descriptor = self.frozen_payload()
        stable = self.home / launcher.name
        stable.write_bytes(launcher.read_bytes())
        with mock.patch.object(sys, 'frozen', True, create=True), mock.patch.object(sys, '_MEIPASS', str(root), create=True):
            self.api().export_mcpb(self.home / 'stable.mcpb', [str(stable), '--mcp'])
            stable.write_bytes(b'not our application')
            with self.assertRaises(MCPError):
                self.api().connection_entry([str(stable), '--mcp'], 'cursor')

    def test_failed_write_does_not_claim_an_external_equal_entry(self):
        from safe_files import SafeDirectory
        self.config.write_text('{}')
        preview = self.preview()
        original = SafeDirectory.write_bytes
        def fail_config_write(directory, name, data, **kwargs):
            if Path(directory.path).samefile(self.config.parent) and name == self.config.name:
                raise PermissionError('controlled fixture failure')
            return original(directory, name, data, **kwargs)
        with mock.patch.object(SafeDirectory, 'write_bytes', fail_config_write), self.assertRaises(MCPError):
            self.api().apply_connection(preview, state_dir=self.state)
        # Someone independently inserts the same snippet after the failed add.
        # Merely writing an ownership intent cannot make that entry ours.
        self.config.write_text(json.dumps({'mcpServers': {'video-to-subtitle': preview['entry_after']}}))
        with self.assertRaises(MCPError) as caught:
            self.preview()
        self.assertEqual(caught.exception.code, 'ENTRY_CONFLICT')

    def test_unknown_schema_target_and_legacy_antigravity_are_manual(self):
        self.config.write_text('{"servers":{}}')
        with self.assertRaises(MCPError) as caught:
            self.preview('claude-code')
        self.assertEqual(caught.exception.code, 'MANUAL_ONLY')
        legacy = self.home / '.antigravity' / 'mcp_config.json'
        legacy.parent.mkdir()
        with self.assertRaises(MCPError) as caught:
            self.api().preview_connection('antigravity', legacy, self.command, state_dir=self.state)
        self.assertEqual(caught.exception.code, 'MANUAL_ONLY')

    def test_relative_environment_override_does_not_guess_a_writable_target(self):
        rows = self.api().discover_clients(home=self.home, environ={'CODEX_HOME': 'relative'}, system='Darwin',
                                          application_roots=(), executable_roots=())
        row = next(row for row in rows if row['id'] == 'codex')
        self.assertFalse(row['can_apply'])
        self.assertTrue(row['manual_reason'])

    def test_fresh_macos_apps_are_discovered_without_mcp_configuration(self):
        apps = self.home / 'Applications'
        apps.mkdir()
        expected = {'codex': 'Codex.app', 'claude-desktop': 'Claude.app', 'cursor': 'Cursor.app',
                    'vscode': 'Visual Studio Code.app', 'windsurf': 'Windsurf.app',
                    'antigravity': 'Antigravity.app'}
        for name in expected.values():
            (apps / name).mkdir()
        rows = self.api().discover_clients(home=self.home, environ={}, system='Darwin',
                                          application_roots=[apps], executable_roots=())
        by_id = {row['id']: row for row in rows}
        for client_id, name in expected.items():
            with self.subTest(client=client_id):
                self.assertTrue(by_id[client_id]['detected'])
                self.assertTrue(by_id[client_id]['installation_detected'])
                self.assertFalse(by_id[client_id]['configuration_detected'])
                self.assertEqual(by_id[client_id]['installation_evidence'],
                                 [{'kind': 'app-bundle', 'path': str(apps / name)}])
                self.assertEqual(by_id[client_id]['configuration_evidence'], [])
                self.assertFalse(by_id[client_id]['version_verified'])
                self.assertFalse(by_id[client_id]['live_verified'])
        self.assertFalse(self.state.exists())

    def test_fixed_cli_metadata_is_discovered_without_reading_or_executing_files(self):
        executables = self.home / 'bin'
        executables.mkdir()
        expected = {'codex': 'codex', 'claude-code': 'claude', 'gemini-cli': 'gemini',
                    'opencode': 'opencode', 'copilot': 'copilot'}
        for name in expected.values():
            executable = executables / name
            executable.write_text('do not execute this controlled fixture')
            executable.chmod(0o755)
        with mock.patch.object(Path, 'open', side_effect=AssertionError('discovery read file contents')):
            rows = self.api().discover_clients(home=self.home, environ={}, system='Linux',
                                              application_roots=(), executable_roots=[executables])
        by_id = {row['id']: row for row in rows}
        for client_id, name in expected.items():
            with self.subTest(client=client_id):
                self.assertTrue(by_id[client_id]['installation_detected'])
                self.assertFalse(by_id[client_id]['configuration_detected'])
                self.assertEqual(by_id[client_id]['installation_evidence'],
                                 [{'kind': 'command-file', 'path': str(executables / name)}])
                self.assertIsNone(by_id[client_id]['client_version'])
        self.assertFalse(self.state.exists())

    def test_discovery_does_not_recurse_or_count_nonexecutables_as_installed(self):
        apps = self.home / 'Applications'
        (apps / 'Other' / 'Cursor.app').mkdir(parents=True)
        (apps / 'Claude.app').write_text('not an application directory')
        executables = self.home / 'bin'
        executables.mkdir()
        (executables / 'codex').write_text('not executable')
        (executables / 'codex').chmod(0o600)
        (executables / 'gemini').mkdir()
        rows = self.api().discover_clients(home=self.home, environ={}, system='Darwin',
                                          application_roots=[apps], executable_roots=[executables])
        self.assertFalse(any(row['installation_detected'] for row in rows))

    def test_windows_known_app_and_cli_metadata_is_separate_from_config(self):
        apps = self.home / 'Programs'
        (apps / 'Microsoft VS Code').mkdir(parents=True)
        (apps / 'Microsoft VS Code' / 'Code.exe').write_bytes(b'controlled inert app fixture')
        executables = self.home / 'local-bin'
        executables.mkdir()
        (executables / 'claude.exe').write_bytes(b'controlled inert cli fixture')
        rows = self.api().discover_clients(home=self.home, environ={}, system='Windows',
                                          application_roots=[apps], executable_roots=[executables])
        by_id = {row['id']: row for row in rows}
        self.assertEqual(by_id['vscode']['installation_evidence'],
                         [{'kind': 'application-file', 'path': str(apps / 'Microsoft VS Code' / 'Code.exe')}])
        self.assertTrue(by_id['claude-code']['installation_detected'])
        self.assertFalse(by_id['claude-code']['configuration_detected'])

    def test_npm_command_links_use_metadata_only_and_broken_links_are_not_installations(self):
        executables = self.home / 'bin'
        executables.mkdir()
        target = self.home / 'controlled-cli'
        target.write_bytes(b'controlled inert executable fixture')
        target.chmod(0o755)
        (executables / 'codex').symlink_to(target)
        (executables / 'claude').symlink_to(self.home / 'missing-cli')
        rows = self.api().discover_clients(home=self.home, environ={}, system='Linux',
                                          application_roots=(), executable_roots=[executables])
        by_id = {row['id']: row for row in rows}
        self.assertEqual(by_id['codex']['installation_evidence'],
                         [{'kind': 'command-file-link', 'path': str(executables / 'codex')}])
        self.assertFalse(by_id['claude-code']['installation_detected'])
        self.assertFalse(by_id['codex']['publisher_verified'])

    def test_windows_default_roots_use_only_fake_home_and_environment(self):
        local = self.home / 'AppData' / 'Local'
        roaming = self.home / 'custom-roaming'
        (local / 'Programs' / 'Microsoft VS Code').mkdir(parents=True)
        (local / 'Programs' / 'Microsoft VS Code' / 'Code.exe').write_bytes(b'inert app')
        (self.home / '.local' / 'bin').mkdir(parents=True)
        (self.home / '.local' / 'bin' / 'claude.exe').write_bytes(b'inert native cli')
        (roaming / 'npm').mkdir(parents=True)
        (roaming / 'npm' / 'copilot.cmd').write_bytes(b'inert npm cli')
        rows = self.api().discover_clients(home=self.home, environ={'APPDATA': str(roaming)},
                                          system='Windows')
        by_id = {row['id']: row for row in rows}
        for client_id in ('vscode', 'claude-code', 'copilot'):
            with self.subTest(client=client_id):
                self.assertTrue(by_id[client_id]['installation_detected'])
                self.assertFalse(by_id[client_id]['configuration_detected'])


if __name__ == '__main__':
    unittest.main()
