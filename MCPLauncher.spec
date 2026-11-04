# -*- mode: python ; coding: utf-8 -*-
"""Build first; the GUI spec embeds this standalone, console-enabled payload."""
import sys
from PyInstaller.utils.hooks import copy_metadata
# Console-script entry points do not put the checkout on sys.path. SPECPATH
# is supplied by PyInstaller and identifies this trusted spec's directory.
sys.path.insert(0, str(SPECPATH))
from third_party import collect_license_datas

excluded = [
    'mcp_service', 'mcp_inference', 'mcp_runtime', 'mcp_dialog', 'mcp_clients',
    'SubtitleTranscriber', 'transcriber', 'web_export', 'web_export_model',
    'scripts.smoke_mcp', 'tkinter', '_tkinter', 'customtkinter', 'tkinterdnd2',
    'faster_whisper', 'ctranslate2', 'torch', 'mlx', 'mlx_whisper', 'mlx_metal',
    'av', 'PIL', 'numpy', 'scipy', 'numba', 'sounddevice', 'opencc',
]
a = Analysis(['mcp_launcher.py'], pathex=[], binaries=[], datas=copy_metadata('mcp') + collect_license_datas(),
             hiddenimports=[], hookspath=[], hooksconfig={}, runtime_hooks=[],
             excludes=excluded, noarchive=False, optimize=0)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='VideoToSubtitleMCP',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=True, hide_console='hide-early' if sys.platform == 'win32' else None,
          runtime_tmpdir=None, target_arch=None, codesign_identity=None,
          entitlements_file=None)
