# -*- mode: python ; coding: utf-8 -*-
import sys
import os
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
from PyInstaller.utils.hooks import collect_all

windows_bundle = os.environ.get('VTS_WINDOWS_BUNDLE', 'onefile')
if sys.platform == 'win32' and windows_bundle not in ('onefile', 'onedir'):
    raise ValueError('VTS_WINDOWS_BUNDLE must be onefile or onedir')

datas = []
binaries = []
hiddenimports = []
datas += [('pyproject.toml', '.')]
datas += [('assets', 'assets')]
datas += [('app_icon.ico', '.')]
# Build the thin payload first. A missing payload is a build error, never a
# client configuration which happens to point at an absent launcher.
payload_name = 'VideoToSubtitleMCP.exe' if sys.platform == 'win32' else 'VideoToSubtitleMCP'
payload = Path(os.environ.get('VTS_MCP_LAUNCHER', str(Path(DISTPATH) / payload_name))).resolve()
if not payload.is_file() or payload.is_symlink():
    raise ValueError('Build MCPLauncher.spec first (or set VTS_MCP_LAUNCHER to its standalone output).')
payload_metadata_dir = Path(tempfile.mkdtemp(prefix='vts-mcp-descriptor-'))
payload_descriptor = payload_metadata_dir / 'vts-mcp-payload.json'
payload_descriptor.write_text(json.dumps({'launcher': payload_name,
    'sha256': hashlib.sha256(payload.read_bytes()).hexdigest(), 'platform': sys.platform}), encoding='utf-8')
binaries += [(str(payload), '.')]
datas += [(str(payload_descriptor), '.')]
tmp_ret = collect_all('customtkinter')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('tkinterdnd2')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('faster_whisper')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('ctranslate2')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
hiddenimports += ['SubtitleTranscriber', 'tomli', 'evercam_integration', 'opencam_integration', 'opencam_dialog', 'web_export', 'web_export_model', 'web_export_form', 'web_export_dialog']
hiddenimports += ['batch_policy', 'psutil']
if sys.platform != 'darwin':
    hiddenimports += ['pynvml']  # Official nvidia-ml-py binding; backend only.
try:
    if sys.platform == 'darwin':
        import importlib
        for mod in ['mlx_whisper', 'mlx', 'mlx_metal', 'tiktoken', 'scipy', 'torch', 'numba']:
            try:
                tmp_ret = collect_all(mod)
                datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
            except Exception as e:
                print(f"Notice: collect_all({mod}) warning: {e}")
                
        # 實體目錄深度收錄：保證 mlx/lib/mlx.metallib 與所有 .dylib 無一遺漏
        for pkg_name in ['mlx', 'mlx_whisper']:
            try:
                m = importlib.import_module(pkg_name)
                if hasattr(m, '__file__') and m.__file__:
                    pkg_dir = os.path.dirname(os.path.abspath(m.__file__))
                    datas += [(pkg_dir, pkg_name)]
                    print(f"Successfully collected full directory for {pkg_name}: {pkg_dir}")
            except Exception as pkg_e:
                print(f"Notice: failed to collect full directory for {pkg_name}: {pkg_e}")

        # 關鍵著色器多重同調收錄：保證在 Contents/MacOS/ 與 Resources/ 等所有搜尋點均存在
        try:
            cand_files = []
            try:
                import mlx.core
                cand_files.append(os.path.join(os.path.dirname(os.path.abspath(mlx.core.__file__)), "lib", "mlx.metallib"))
                cand_files.append(os.path.join(os.path.dirname(os.path.abspath(mlx.core.__file__)), "mlx.metallib"))
            except Exception:
                pass
            try:
                import mlx
                mlx_root = os.path.dirname(os.path.abspath(mlx.__file__)) if (hasattr(mlx, "__file__") and mlx.__file__) else (list(mlx.__path__)[0] if hasattr(mlx, "__path__") else "")
                if mlx_root:
                    cand_files.append(os.path.join(mlx_root, "lib", "mlx.metallib"))
                    cand_files.append(os.path.join(mlx_root, "mlx.metallib"))
            except Exception:
                pass
            try:
                import site
                for sp in site.getsitepackages():
                    for root, _, files in os.walk(sp):
                        if "mlx.metallib" in files:
                            cand_files.append(os.path.join(root, "mlx.metallib"))
            except Exception:
                pass

            metallib_path = next((p for p in cand_files if os.path.isfile(p)), None)
            if metallib_path:
                print(f"Found MLX metallib at: {metallib_path}")
                # 同調分發至根目錄 (Contents/MacOS) 與 Resources 等目標
                for dest in ['.', 'Resources', 'mlx', 'mlx/lib']:
                    datas.append((metallib_path, dest))
                    
                # 建立臨時 default.metallib 鏡像並加入打包
                import tempfile, shutil
                tmp_dir = tempfile.mkdtemp()
                default_meta_path = os.path.join(tmp_dir, "default.metallib")
                shutil.copy2(metallib_path, default_meta_path)
                for dest in ['.', 'Resources', 'mlx', 'mlx/lib']:
                    datas.append((default_meta_path, dest))
                print(f"Successfully staged mlx.metallib and default.metallib across all bundle target dirs")
        except Exception as meta_e:
            print(f"Notice: failed to stage metallib: {meta_e}")
except Exception as e:
    print(f"Error collecting macOS dependencies: {e}")
tmp_ret = collect_all('opencc')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
if sys.platform == 'win32':
    # OpenCC's delvewheel loader looks in the sibling opencc.libs directory.
    # Dependency analysis can otherwise deduplicate its VC runtime into
    # numpy.libs, which is not registered when OpenCC is imported first.
    from PyInstaller.utils.hooks import collect_delvewheel_libs_directory
    datas, binaries = collect_delvewheel_libs_directory('opencc', datas=datas, binaries=binaries)
tmp_ret = collect_all('av')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('PIL')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('sounddevice')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
try:
    tmp_ret = collect_all('_sounddevice_data')
    datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
except Exception:
    pass


a = Analysis(
    ['app_entry.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
# This is an opaque, already frozen executable. Prevent binary collection from
# changing its Mach-O headers/signature or applying UPX after hashing it.
# Analysis may classify executable data as BINARY, so restore DATA explicitly.
if sys.platform != 'darwin':
    a.binaries = [entry for entry in a.binaries if entry[0] != payload_name]
    a.datas = [entry for entry in a.datas if entry[0] != payload_name]
    a.datas.append((payload_name, str(payload), 'DATA'))
pyz = PYZ(a.pure)

if sys.platform == 'darwin':
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name='VideoToSubtitle',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=True,
        upx_exclude=[],
        name='VideoToSubtitle',
    )
    app = BUNDLE(
        coll,
        name='VideoToSubtitle.app',
        icon=None,
        bundle_identifier='com.kaoshou.videotosubtitle',
        info_plist={
            'NSHighResolutionCapable': 'True'
        },
    )
    # BUNDLE may rewrite/sign nested Mach-O bytes. Attest the final standalone
    # payload, keeping Apple's data/code roles (no regular JSON in Frameworks).
    contents = Path(app.name) / 'Contents'
    bundled_launcher = contents / 'Frameworks' / payload_name
    bundled_descriptor = contents / 'Resources' / payload_descriptor.name
    if bundled_launcher.is_symlink() or bundled_descriptor.is_symlink():
        raise ValueError('MCP payload must use regular native bundle code/data files.')
    bundled_descriptor.write_text(json.dumps({'launcher': payload_name,
        'sha256': hashlib.sha256(bundled_launcher.read_bytes()).hexdigest(), 'platform': sys.platform}), encoding='utf-8')
    # Re-seal only the outer resource envelope; keep attested executable bytes.
    from PyInstaller.utils import osx as osxutils
    osxutils.sign_binary(app.name, identity=app.codesign_identity,
                         entitlements_file=app.entitlements_file, deep=False)
elif sys.platform == 'win32' and windows_bundle == 'onedir':
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name='VideoToSubtitle',
        icon='app_icon.ico',
        debug=False,
        strip=False,
        upx=True,
        console=False,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=True,
        upx_exclude=[],
        name='VideoToSubtitle',
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name='VideoToSubtitle',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )
