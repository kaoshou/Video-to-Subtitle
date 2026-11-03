import contextlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

from mcp_state import MCPError, ProcessLock, State, default_state_dir


class StateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'media'
        self.root.mkdir()
        (self.root / 'nested').mkdir()
        (self.root / 'nested' / 'clip.mp4').write_bytes(b'video')
        self.state = State(self.base / 'private' / 'mcp')

    def enable(self):
        return self.state.configure(True, [self.root])['roots'][0]['id']

    def test_missing_policy_and_reads_create_nothing(self):
        self.assertIsInstance(default_state_dir(), Path)
        self.assertEqual(self.state.policy(), {'enabled': False, 'roots': [], 'generation': 0})
        self.assertEqual(self.state.records('jobs'), [])
        with self.assertRaises(MCPError):
            self.state.require_enabled()
        with self.assertRaises(MCPError):
            self.state.get('jobs', 'missing')
        self.assertFalse((self.base / 'private').exists())

    def test_public_error_codes_follow_business_contract(self):
        with self.assertRaises(MCPError) as caught:
            self.state.require_enabled()
        self.assertEqual(caught.exception.code, 'MCP_DISABLED')
        self.enable()
        with self.assertRaises(MCPError) as caught:
            with self.state.directory('unknown-root'):
                self.fail('unknown root opened')
        self.assertEqual(caught.exception.code, 'ROOT_NOT_ALLOWED')
        with self.assertRaises(MCPError) as caught:
            self.state.get('jobs', 'missing')
        self.assertEqual(caught.exception.code, 'NOT_FOUND')

    def test_configure_persists_stable_root_ids_and_options(self):
        first = self.state.configure(True, [self.root], model='small', device='cpu')
        second = self.state.configure(True, [self.root])
        self.assertEqual(first['roots'][0]['id'], second['roots'][0]['id'])
        self.assertEqual(second['generation'], first['generation'] + 1)
        self.assertEqual(State(self.state.path).policy(), second)
        self.assertEqual(first['options']['model'], 'small')
        self.assertNotIn(str(self.root), first['roots'][0]['id'])

    def test_revocation_and_disable_checked_at_each_operation(self):
        root_id = self.enable()
        self.state.configure(True, [])
        with self.assertRaises(MCPError):
            with self.state.file(root_id, 'nested/clip.mp4'):
                self.fail('revoked root opened')
        self.state.configure(False, [self.root])
        with self.assertRaises(MCPError):
            with self.state.directory(root_id):
                self.fail('disabled root opened')

    def test_finish_admission_only_survives_unchanged_root_disable(self):
        root_id = self.enable()
        generation = self.state.policy()['generation']
        self.state.configure(False, [self.root], stop_mode='finish')
        with self.assertRaises(MCPError):
            self.state.require_enabled()
        with self.state.file(root_id, 'nested/clip.mp4', admitted_generation=generation) as stream:
            self.assertEqual(stream.read(), b'video')
        with self.assertRaises(MCPError):
            self.state.require_enabled(admitted_generation=generation + 10)
        self.state.configure(False, [], stop_mode='finish')
        with self.assertRaises(MCPError):
            self.state.require_enabled(admitted_generation=generation)
        self.state.configure(True, [self.root])
        generation = self.state.policy()['generation']
        self.state.configure(False, [self.root], stop_mode='cancel')
        with self.assertRaises(MCPError):
            self.state.require_enabled(admitted_generation=generation)

    def test_pinned_nested_reads_survive_directory_rename(self):
        root_id = self.enable()
        with self.state.directory(root_id, 'nested') as folder:
            if os.name != 'nt':
                (self.root / 'nested').rename(self.root / 'moved')
            with folder.open_read('clip.mp4') as stream:
                self.assertEqual(stream.read(), b'video')
        path = 'moved/clip.mp4' if os.name != 'nt' else 'nested/clip.mp4'
        with self.state.file(root_id, path) as stream:
            self.assertEqual(stream.read(), b'video')

    def test_root_revoked_while_leaf_opens_is_not_yielded(self):
        from safe_files import SafeDirectory
        root_id = self.enable()
        original = SafeDirectory.open_read
        @contextlib.contextmanager
        def revoke(directory, name):
            with original(directory, name) as stream:
                if name == 'clip.mp4':
                    self.state.configure(True, [])
                yield stream
        with mock.patch.object(SafeDirectory, 'open_read', revoke), self.assertRaises(MCPError):
            with self.state.file(root_id, 'nested/clip.mp4'):
                self.fail('revoked stream yielded')

    def test_unsafe_relative_paths_rejected(self):
        root_id = self.enable()
        for relative in ('../clip.mp4', '/etc/passwd', 'C:/temp', 'x:stream',
                         r'\\server\share', r'nested\clip.mp4', 'nested/../clip.mp4',
                         './nested', 'nested//clip.mp4', 'nested/', 'x\x00y', 'x. ', 'CON'):
            with self.subTest(relative=relative), self.assertRaises(MCPError):
                with self.state.directory(root_id, relative):
                    self.fail('unsafe path opened')

    def test_links_and_nonregular_files_rejected(self):
        root_id = self.enable()
        outside = self.base / 'outside'
        outside.mkdir()
        (outside / 'secret').write_bytes(b'secret')
        try:
            (self.root / 'link').symlink_to(outside, target_is_directory=True)
            (self.root / 'leaf').symlink_to(outside / 'secret')
        except OSError as error:
            self.skipTest(f'symlinks unavailable: {error}')
        for relative in ('link/secret', 'leaf', 'nested'):
            with self.subTest(relative=relative), self.assertRaises(MCPError):
                with self.state.file(root_id, relative):
                    self.fail('unsafe file opened')
        if hasattr(os, 'mkfifo'):
            os.mkfifo(self.root / 'pipe')
            with self.assertRaises(MCPError):
                with self.state.file(root_id, 'pipe'):
                    self.fail('FIFO opened')

    def test_replaced_root_ancestor_does_not_follow_link(self):
        parent = self.root / 'nested'
        self.state.configure(True, [parent])
        root_id = self.state.policy()['roots'][0]['id']
        self.root.rename(self.base / 'old-media')
        try:
            self.root.symlink_to(self.base / 'old-media', target_is_directory=True)
        except OSError as error:
            self.skipTest(f'symlinks unavailable: {error}')
        with self.assertRaises(MCPError):
            with self.state.directory(root_id):
                self.fail('replaced ancestor followed')

    def test_corrupt_or_oversized_policy_fails_closed(self):
        self.enable()
        policy_path = self.state.path / 'policy.json'
        for text in ('{', '[]', '{"enabled":true,"roots":[],"generation":-1}',
                     '{"enabled":1,"roots":[],"generation":1}', ' ' * (1024 * 1024 + 1)):
            policy_path.write_text(text)
            with self.subTest(text=text[:40]), self.assertRaises(MCPError):
                self.state.require_enabled()

    def test_private_records_roundtrip_and_invalid_ids(self):
        self.state.put('jobs', 'job_01', {'status': 'queued', 'title': '影片'})
        self.assertEqual(self.state.get('jobs', 'job_01')['title'], '影片')
        self.assertEqual(self.state.records('jobs'), [{'status': 'queued', 'title': '影片'}])
        for record_id in ('', '..', '../x', '/tmp/x', 'x:y', 'x/y', 'x\\y', 'x' * 129):
            with self.subTest(record_id=record_id), self.assertRaises(MCPError):
                self.state.put('jobs', record_id, {})
        for kind in ('policy', '../jobs', 'unknown'):
            with self.subTest(kind=kind), self.assertRaises(MCPError):
                self.state.records(kind)
        with self.assertRaises(MCPError):
            self.state.put('jobs', 'valid', {'huge': 'x' * (8 * 1024 * 1024)})
        with self.assertRaises(MCPError):
            self.state.put('jobs', 'valid', {'value': float('nan')})
        with self.assertRaises(MCPError):
            self.state.put('jobs', 'valid', [])

    @unittest.skipIf(os.name == 'nt', 'POSIX mode assertions; Windows ACL covered separately')
    def test_storage_directories_records_and_locks_are_private(self):
        self.enable()
        self.state.put('jobs', 'job_01', {'state': 'queued'})
        with ProcessLock(self.state.path):
            pass
        for path in self.state.path.rglob('*'):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode) & 0o077, 0, str(path))
        self.assertEqual(stat.S_IMODE(self.state.path.stat().st_mode), 0o700)

    def test_storage_symlinks_refused_and_external_target_unchanged(self):
        self.enable()
        target = self.base / 'external'
        target.write_text('secret')
        try:
            (self.state.path / 'policy.json').unlink()
            (self.state.path / 'policy.json').symlink_to(target)
        except OSError as error:
            self.skipTest(f'symlinks unavailable: {error}')
        with self.assertRaises(MCPError):
            self.state.policy()
        with self.assertRaises(MCPError):
            self.state.configure(True, [self.root])
        self.assertEqual(target.read_text(), 'secret')

    def test_mutation_publishes_only_successful_context(self):
        self.state.put('jobs', 'a', {'count': 0})
        with self.state.mutation('jobs', 'a') as data:
            data['count'] += 1
        self.assertEqual(self.state.get('jobs', 'a'), {'count': 1})
        with self.assertRaises(RuntimeError):
            with self.state.mutation('jobs', 'a') as data:
                data['count'] += 1
                raise RuntimeError('abort')
        self.assertEqual(self.state.get('jobs', 'a'), {'count': 1})
        with self.state.mutation('jobs', 'new') as data:
            data['created'] = True
        self.assertEqual(self.state.get('jobs', 'new'), {'created': True})

    @unittest.skipIf(os.name == 'nt', 'POSIX descriptor mode check')
    def test_record_is_private_before_atomic_publication(self):
        replace = os.replace
        def verify(source, destination, **kwargs):
            info = os.stat(source, dir_fd=kwargs.get('src_dir_fd'), follow_symlinks=False)
            self.assertEqual(stat.S_IMODE(info.st_mode), 0o600)
            return replace(source, destination, **kwargs)
        with mock.patch('os.replace', side_effect=verify):
            self.state.put('jobs', 'new', {'status': 'queued'})

    def test_concurrent_mutations_do_not_lose_updates(self):
        self.state.put('jobs', 'counter', {'count': 0})
        script = ('from mcp_state import State; import sys; state=State(sys.argv[1]); '
                  '\nfor i in range(12):\n with state.mutation("jobs", "counter") as data: data["count"] += 1')
        processes = [subprocess.Popen([sys.executable, '-c', script, str(self.state.path)],
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                     for _ in range(3)]
        for process in processes:
            output, errors = process.communicate(timeout=20)
            self.assertEqual(process.returncode, 0, errors)
        self.assertEqual(self.state.get('jobs', 'counter'), {'count': 36})

    def test_index_record_put_and_mutation_do_not_deadlock(self):
        for operation in ('put', 'mutation'):
            with self.subTest(operation=operation):
                script = ('from mcp_state import State; import sys; state=State(sys.argv[1]); '
                          '\nif sys.argv[2] == "put": state.put("jobs", "index", {"ok": True})'
                          '\nelse:\n with state.mutation("jobs", "index") as data: data["ok"] = True')
                process = subprocess.Popen([sys.executable, '-c', script, str(self.state.path), operation],
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                try:
                    output, errors = process.communicate(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate(timeout=5)
                    self.fail(f'{operation} deadlocked for valid record ID index')
                self.assertEqual(process.returncode, 0, errors)
                self.assertEqual(self.state.get('jobs', 'index'), {'ok': True})

    def test_listing_during_private_record_publication(self):
        self.state.put('jobs', 'first', {'status': 'queued'})
        ready, resume = threading.Event(), threading.Event()
        failures = []
        original = os.replace
        def pause(source, destination, **kwargs):
            ready.set()
            if not resume.wait(5):
                raise RuntimeError('publication test timed out')
            return original(source, destination, **kwargs)
        def publish():
            try:
                self.state.put('jobs', 'second', {'status': 'running'})
            except BaseException as error:
                failures.append(error)
        with mock.patch('os.replace', side_effect=pause):
            writer = threading.Thread(target=publish)
            writer.start()
            try:
                self.assertTrue(ready.wait(2), 'writer did not reach real atomic publication')
                self.assertEqual(self.state.records('jobs'), [{'status': 'queued'}])
            finally:
                resume.set()
                writer.join(5)
        self.assertFalse(writer.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual(self.state.records('jobs'), [{'status': 'queued'}, {'status': 'running'}])

    def test_listing_survives_crashed_private_publication(self):
        self.state.put('jobs', 'first', {'status': 'queued'})
        script = ('from mcp_state import State; import os, sys; '
                  '\ndef crash(*args, **kwargs): os._exit(17)'
                  '\nos.replace = crash\nState(sys.argv[1]).put("jobs", "second", {"private": "staged"})')
        process = subprocess.run([sys.executable, '-c', script, str(self.state.path)],
                                 capture_output=True, text=True, timeout=5)
        self.assertEqual(process.returncode, 17, process.stderr)
        self.assertTrue(list((self.state.path / 'jobs').glob('.mcp-*')))
        self.assertEqual(self.state.records('jobs'), [{'status': 'queued'}])
        self.state.put('jobs', 'second', {'status': 'recovered'})
        self.assertEqual(self.state.get('jobs', 'second'), {'status': 'recovered'})

    def test_abandoned_private_stage_does_not_consume_record_quota(self):
        self.state.put('jobs', 'first', {})
        stage = self.state.path / 'jobs' / ('.mcp-' + '0' * 32)
        stage.mkdir(mode=0o700)
        with mock.patch('mcp_state.MAX_RECORDS', 2):
            self.state.put('jobs', 'second', {'ok': True})
            self.assertEqual(self.state.records('jobs'), [{}, {'ok': True}])

    def test_staging_name_does_not_hide_symlink(self):
        self.state.put('jobs', 'first', {})
        try:
            (self.state.path / 'jobs' / ('.mcp-' + 'a' * 32)).symlink_to(self.root, target_is_directory=True)
        except OSError as error:
            self.skipTest(f'symlinks unavailable: {error}')
        with self.assertRaises(MCPError):
            self.state.records('jobs')

    @unittest.skipUnless(os.name == 'nt', 'Windows current-user ACL integration')
    def test_windows_private_acl_records_and_policy(self):
        from mcp_state import _windows_private
        self.enable()
        self.state.put('backups', 'backup_01', {'original': 'private fixture'})
        for path in (self.state.path, self.state.path / 'policy.json',
                     self.state.path / 'backups', self.state.path / 'backups' / 'backup_01.json'):
            _windows_private(path)

    def test_options_reject_secrets_unknown_keys_and_bad_backend(self):
        for options in ({'api_key': 'secret'}, {'token': 'secret'}, {'backend_command': 'echo unsafe'},
                        {'backend_command': ['relative-program']}, {'stop_mode': 'kill'}):
            with self.subTest(options=options), self.assertRaises(MCPError):
                self.state.configure(True, [self.root], **options)


class ProcessLockTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / 'locks'

    def test_competing_process_and_crash_release(self):
        script = ('from mcp_state import ProcessLock; from pathlib import Path; import sys, time; '
                  'lock=ProcessLock(Path(sys.argv[1])); '
                  'print(lock.acquire(), flush=True); time.sleep(60)')
        process = subprocess.Popen([sys.executable, '-c', script, str(self.directory)],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: process.kill() if process.poll() is None else None)
        self.assertEqual(process.stdout.readline().strip(), 'True')
        lock = ProcessLock(self.directory)
        self.assertFalse(lock.acquire())
        process.kill()
        process.communicate(timeout=10)
        self.assertTrue(lock.acquire())
        lock.release()

    def test_context_release_and_cancellation(self):
        first = ProcessLock(self.directory)
        with first:
            second = ProcessLock(self.directory)
            self.assertFalse(second.acquire())
            self.assertFalse(second.acquire(blocking=True, cancelled=lambda: True))
        self.assertTrue(second.acquire())
        second.release()
        second.release()

    def test_lock_name_and_link_rejected(self):
        for name in ('../lock', '/tmp/lock', 'x:y', 'x/y', '', 'CON'):
            with self.subTest(name=name), self.assertRaises(MCPError):
                ProcessLock(self.directory, name).acquire()


if __name__ == '__main__':
    unittest.main()
