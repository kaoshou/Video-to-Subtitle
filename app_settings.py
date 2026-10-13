"""Per-user Windows frozen-app settings; source/macOS paths stay compatible."""
import json
import os
from pathlib import Path
import sys

from safe_files import SafeDirectory, atomic_write_text

MAX_SETTINGS_BYTES = 1024 * 1024


def read_settings(path):
    path = Path(path)
    with SafeDirectory(path.parent) as folder, folder.open_read(path.name) as stream:
        data = stream.read(MAX_SETTINGS_BYTES + 1)
    if len(data) > MAX_SETTINGS_BYTES:
        raise ValueError('設定檔過大')
    config = json.loads(data.decode('utf-8'))
    if not isinstance(config, dict):
        raise ValueError('設定檔必須是 JSON 物件')
    return config


def write_settings(path, config):
    atomic_write_text(path, json.dumps(config, indent=4, ensure_ascii=False))


def resolve_settings_path(source_dir, *, system=None, frozen=None, environ=None, home=None):
    system = sys.platform if system is None else system
    frozen = getattr(sys, 'frozen', False) if frozen is None else frozen
    legacy = Path(source_dir) / 'config.json'
    if system != 'win32' or not frozen:
        return legacy
    environ = os.environ if environ is None else environ
    local = Path(environ.get('LOCALAPPDATA', ''))
    if not local.is_absolute():
        local = (Path.home() if home is None else Path(home)) / 'AppData' / 'Local'
    # LOCALAPPDATA is an existing OS-managed directory. Pin the child while
    # creating/migrating so we never write through a link or junction.
    with SafeDirectory(local) as parent, parent.child('VideoToSubtitle', create=True) as folder:
        path = local / 'VideoToSubtitle' / 'config.json'
        if folder.info('config.json') is None:
            try:
                config = read_settings(legacy)
            except (OSError, ValueError, UnicodeError):
                pass  # A missing/invalid legacy config must not block first run.
            else:
                try:
                    folder.write_bytes('config.json', json.dumps(config, ensure_ascii=False).encode('utf-8'),
                                       exclusive=True)
                except FileExistsError:
                    pass  # Another instance already created the user's config.
    return path
