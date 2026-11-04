"""Real STDIO + synthetic player smoke, isolated from models and user configs.

Run from source, with --launcher/--backend frozen executables, or through the
packaged application's --test-mcp. Child PATH contains no Python or Node.
"""
import argparse
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time

if not getattr(sys, 'frozen', False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class Protocol:
    def __init__(self, command, env, errors):
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=errors, env=env, text=True, encoding='utf-8')
        self.messages, self.sequence = queue.Queue(), 0
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        try:
            for line in self.process.stdout:
                value = json.loads(line)  # Any diagnostic on STDOUT fails the smoke.
                if value.get('jsonrpc') != '2.0':
                    raise AssertionError('Non-protocol STDOUT')
                self.messages.put(value)
        except Exception as error:
            self.messages.put(error)
        finally:
            self.messages.put(EOFError('MCP stream closed'))

    def send(self, method, params, id=None):
        message = {'jsonrpc': '2.0', 'method': method, 'params': params}
        if id is not None:
            message['id'] = id
        self.process.stdin.write(json.dumps(message, ensure_ascii=False) + '\n')
        self.process.stdin.flush()

    def request(self, method, params):
        self.sequence += 1
        self.send(method, params, self.sequence)
        deadline = time.monotonic() + 30
        while True:
            message = self.messages.get(timeout=max(.01, deadline - time.monotonic()))
            if isinstance(message, Exception):
                raise message
            if message.get('id') == self.sequence:
                if 'error' in message:
                    raise AssertionError(message)
                return message['result']

    def call(self, name, arguments, *, error=None):
        result = self.request('tools/call', {'name': name, 'arguments': arguments})
        data = result.get('structuredContent')
        if error:
            assert result.get('isError') and data['error']['code'] == error, result
        else:
            assert not result.get('isError') and isinstance(data, dict), result
        return data

    def close(self):
        self.process.stdin.close()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            # Exact test bridge only; never a process group or broker tree.
            self.process.terminate()
            self.process.wait(timeout=10)
        self.reader.join(2)
        self.process.stdout.close()


def _media(parent):
    import av
    video = parent / 'lesson.mp4'
    with av.open(str(video), 'w', format='mp4') as output:
        stream = output.add_stream('libx264', rate=10)
        stream.width, stream.height, stream.pix_fmt = 160, 90, 'yuv420p'
        for _ in range(20):
            frame = av.VideoFrame(160, 90, 'yuv420p')
            for plane in frame.planes:
                plane.update(bytes([96]) * plane.buffer_size)
            for packet in stream.encode(frame):
                output.mux(packet)
        for packet in stream.encode():
            output.mux(packet)
    (parent / 'lesson.srt').write_text('1\n00:00:00,123 --> 00:00:01,456\n合成測試\n', encoding='utf-8')


def run_smoke(launcher=None, backend=None):
    from mcp_state import State
    from mcp_transport import BrokerClient
    from mcp_runtime import connection_command, backend_command
    frozen = bool(launcher) or bool(getattr(sys, 'frozen', False))
    with tempfile.TemporaryDirectory(prefix='vts-mcp-smoke-') as temporary:
        parent = Path(temporary).resolve()
        media = parent / 'media'
        media.mkdir()
        _media(media)
        state = State(parent / 'state')
        backend_argv = [str(Path(backend).resolve())] if backend else backend_command()
        if launcher:
            argv = [str(Path(launcher).resolve()), '--mcp', '--state-dir', str(state.path)]
        else:
            argv = connection_command(state)
        env = dict(os.environ)
        for key in ('PYTHONHOME', 'PYTHONPATH'):
            env.pop(key, None)
        # A real empty directory, so the frozen children cannot find a host runtime.
        empty_path = parent / 'empty-path'
        empty_path.mkdir()
        env['PATH'] = str(empty_path)
        env['HF_HUB_OFFLINE'] = env['TRANSFORMERS_OFFLINE'] = '1'
        bridge = broker = None
        with tempfile.TemporaryFile(mode='w+b') as errors:
            try:
                bridge = Protocol(argv, env, errors)
                init = bridge.request('initialize', {'protocolVersion': '2025-03-26',
                    'capabilities': {}, 'clientInfo': {'name': 'vts-isolated-smoke', 'version': '1'}})
                assert 'untrusted data' in init.get('instructions', ''), init
                bridge.send('notifications/initialized', {})
                tools = bridge.request('tools/list', {})['tools']
                assert len(tools) == 13 and all(len(tool.get('description', '')) > 35 for tool in tools)
                assert 'list_translation_drafts' in {tool['name'] for tool in tools}
                assert bridge.call('get_status', {})['enabled'] is False
                bridge.call('list_media', {'root_id': 'not-authorized'}, error='MCP_DISABLED')
                if frozen:
                    broken = state.configure(True, [media], backend_command=[str(parent / 'missing-backend')])
                    bridge.call('list_media', {'root_id': broken['roots'][0]['id']}, error='BACKEND_REPAIR_REQUIRED')
                policy = state.configure(True, [media], backend_command=backend_argv,
                                         model_cache_dir=str(parent / 'no-models'))
                # Own this backend process explicitly; no orphan or user broker is touched.
                broker = subprocess.Popen(backend_argv + ['--mcp-broker', '--state-dir', str(state.path)],
                                          stdin=subprocess.DEVNULL, stdout=errors, stderr=errors, env=env)
                client = BrokerClient(state, autostart=False)
                deadline = time.monotonic() + 30
                while True:
                    try:
                        client.handshake()
                        break
                    except (OSError, EOFError):
                        assert broker.poll() is None, 'Frozen backend exited before handshake'
                        if time.monotonic() >= deadline:
                            raise TimeoutError('Backend readiness')
                        time.sleep(.05)
                inventory = bridge.call('get_status', {})
                assert inventory['default_transcription']['model'] == 'large-v3-turbo', inventory
                assert len(inventory['model_catalog']) == 6
                assert all(not backend['downloaded'] for row in inventory['model_catalog']
                           for backend in row['backends'].values())
                assert not (parent / 'no-models').exists(), 'Read-only inventory created a model cache'
                items = bridge.call('list_media', {'root_id': policy['roots'][0]['id']})['items']
                ids = {item['name']: item['asset_id'] for item in items}
                source = bridge.call('import_subtitle', {'media_id': ids['lesson.mp4'],
                    'subtitle_id': ids['lesson.srt'], 'language': 'zh-TW', 'request_id': 'import'})
                tracks = []
                for language, translated in [('en', 'Synthetic test'), ('ja', '合成テスト')]:
                    draft = bridge.call('prepare_translation', {'source_id': source['source_id'],
                        'revision': source['revision'], 'language': language, 'request_id': 'prepare-' + language})
                    recovered = bridge.call('list_translation_drafts', {'source_id': source['source_id'], 'language': language})
                    assert recovered['items'][0]['draft_id'] == draft['draft_id']
                    assert recovered['items'][0]['missing_batches'] == [b['batch_id'] for b in draft['batches']]
                    for descriptor in draft['batches']:
                        batch = bridge.call('get_translation_batch', {'draft_id': draft['draft_id'],
                            'batch_id': descriptor['batch_id']})
                        bridge.call('submit_translation_batch', {'draft_id': draft['draft_id'],
                            'batch_id': batch['batch_id'], 'revision': draft['revision'],
                            'translations': [{'cue_id': cue['cue_id'], 'text': translated} for cue in batch['cues']],
                            'request_id': language + batch['batch_id']})
                    track = bridge.call('finalize_translation', {'draft_id': draft['draft_id'], 'request_id': 'final-' + language})
                    tracks.append(track['track_id'])
                job = bridge.call('export_player', {'asset_id': ids['lesson.mp4'], 'track_ids': tracks,
                                                  'request_id': 'export', 'default_subtitle': 'en'})
                deadline = time.monotonic() + 30
                while True:
                    status = bridge.call('get_job', job)
                    if status['state'] in ('succeeded', 'failed', 'cancelled', 'interrupted'):
                        break
                    if time.monotonic() >= deadline:
                        raise TimeoutError('Export completion')
                    time.sleep(.05)
                assert status['state'] == 'succeeded', status
                folder = Path(status['result']['folder'])
                assert folder.parent == media and (folder / 'index.html').is_file()
                manifest = json.loads((folder / 'web-export.json').read_text(encoding='utf-8'))
                assert [track['language'] for track in manifest['subtitles']] == ['en', 'ja']
                # Exercise project detection/native builders through real STDIO,
                # including frozen executables with no host Python/Node on PATH.
                for kind in ('opencam', 'evercam'):
                    project = media / kind
                    project.mkdir()
                    (project / 'media.mp4').write_bytes((media / 'lesson.mp4').read_bytes())
                    (project / 'media.srt').write_bytes((media / 'lesson.srt').read_bytes())
                    if kind == 'opencam':
                        (project / 'index.html').write_text('<script src="opencam-player.js"></script><video src="media.mp4"></video>', encoding='utf-8')
                        data = {'format': 'opencam.web-player', 'schemaVersion': 1,
                            'entry': 'index.html', 'media': 'media.mp4', 'title': 'Synthetic OpenCam',
                            'chapters': [{'title': 'Chapter one', 'start': 0, 'end': 1}], 'subtitles': None}
                        (project / 'opencam-player.js').write_text('window.OpenCamPlayerData = ' + json.dumps(data) + ';', encoding='utf-8')
                    else:
                        (project / 'config.js').write_text('var config={title:"Synthetic EverCam",index:[{title:"Chapter one",time:0}]};', encoding='utf-8')
                    entries = bridge.call('list_media', {'root_id': policy['roots'][0]['id'], 'relative': kind})['items']
                    video = next(item for item in entries if item['name'] == 'media.mp4')
                    subtitle = next(item for item in entries if item['name'] == 'media.srt')
                    assert video['project_type'] == kind, video
                    imported = bridge.call('import_subtitle', {'media_id': video['asset_id'],
                        'subtitle_id': subtitle['asset_id'], 'language': 'zh-TW', 'request_id': kind + '-import'})
                    accepted = bridge.call('export_player', {'asset_id': video['asset_id'],
                        'track_ids': [imported['track_id']], 'request_id': kind + '-export'})
                    deadline = time.monotonic() + 60
                    while True:
                        finished = bridge.call('get_job', accepted)
                        if finished['state'] in ('succeeded', 'failed', 'cancelled', 'interrupted'):
                            break
                        if time.monotonic() >= deadline:
                            raise TimeoutError(kind + ' export completion')
                        time.sleep(.05)
                    assert finished['state'] == 'succeeded', finished
                    assert finished['result']['player_type'] == kind
                    destination = Path(finished['result']['folder'])
                    expected = 'opencam-player.js' if kind == 'opencam' else 'config.js'
                    assert 'Chapter one' in (destination / expected).read_text(encoding='utf-8')
                    assert (destination / 'media.zh-TW.srt').is_file()
                for language in ('en', 'ja'):
                    assert '00:00:00,123 --> 00:00:01,456' in (folder / f'media.{language}.srt').read_text(encoding='utf-8')
                assert (folder / 'media.mp4').read_bytes() == (media / 'lesson.mp4').read_bytes()
                state.disable('finish')
                bridge.call('list_media', {'root_id': policy['roots'][0]['id']}, error='MCP_DISABLED')
                return {'frozen': frozen, 'languages': ['en', 'ja'], 'disabled_denied': True,
                        'project_players': ['opencam', 'evercam'],
                        'protocol_only_stdout': True, 'no_host_runtime_on_path': True,
                        'protocol_version': init['protocolVersion'], 'live_client_verified': False}
            except Exception:
                errors.seek(0)
                diagnostics = errors.read().decode('utf-8', errors='replace')
                if diagnostics and sys.stderr:
                    print(diagnostics[-12000:], file=sys.stderr)
                raise
            finally:
                state.disable('cancel')
                if bridge is not None:
                    bridge.close()
                if broker is not None:
                    broker.wait(timeout=30)  # Normal disabled quiescence; no native job kill.


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--launcher', type=Path)
    parser.add_argument('--backend', type=Path)
    options = parser.parse_args(argv)
    if bool(options.launcher) != bool(options.backend):
        parser.error('--launcher and --backend must be supplied together')
    report = run_smoke(options.launcher, options.backend)
    if sys.stdout:
        print(json.dumps(report))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
