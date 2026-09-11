# -*- mode: python ; coding: utf-8 -*-
import sys
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = []
datas += [('pyproject.toml', '.')]
datas += [('assets', 'assets')]
tmp_ret = collect_all('customtkinter')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('tkinterdnd2')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('faster_whisper')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('ctranslate2')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
hiddenimports += ['tomli', 'evercam_integration']
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
    ['SubtitleTranscriber.py'],
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
