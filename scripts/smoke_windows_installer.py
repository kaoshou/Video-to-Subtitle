"""Real install/reinstall/uninstall + GUI launch comparison on disposable CI.

Host Python runs the harness, but is absent from each EXE's environment.
No models are downloaded: this measures window startup, not transcription.
"""
import argparse
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time


def isolated_environment(source):
    env = dict(source)
    env['PATH'] = os.path.join(env.get('SystemRoot', r'C:\Windows'), 'System32')
    env.pop('PYTHONHOME', None)
    env.pop('PYTHONPATH', None)
    return env


def summarize_startup(samples):
    if len(samples) < 2:
        raise ValueError('Need a first launch and at least one repeat')
    return {'first_gui_launch_seconds': samples[0],
            'repeat_median_seconds': statistics.median(samples[1:]),
            'samples_seconds': samples}


def launch_window(executable, env, screenshot=None, timeout=90):
    import ctypes
    from ctypes import wintypes
    import psutil
    user = ctypes.WinDLL('user32', use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user.EnumWindows.restype = wintypes.BOOL
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user.SendMessageTimeoutW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                      wintypes.LPARAM, wintypes.UINT, wintypes.UINT,
                                      ctypes.POINTER(ctypes.c_size_t)]
    user.SendMessageTimeoutW.restype = ctypes.c_size_t
    started = time.perf_counter()
    process = subprocess.Popen([str(executable)], env=env, cwd=executable.parent)
    parent = psutil.Process(process.pid)
    window = None
    descendants = []
    try:
        while time.perf_counter() - started < timeout:
            if process.poll() is not None:
                raise RuntimeError(f'Application exited before showing its window: {process.returncode}')
            descendants = parent.children(recursive=True)
            pids = {process.pid, *(child.pid for child in descendants)}
            found = []
            @callback_type
            def visit(hwnd, _):
                pid = wintypes.DWORD()
                user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value not in pids or not user.IsWindowVisible(hwnd):
                    return True
                text = ctypes.create_unicode_buffer(1024)
                user.GetWindowTextW(hwnd, text, len(text))
                rectangle = wintypes.RECT()
                user.GetWindowRect(hwnd, ctypes.byref(rectangle))
                if (text.value.startswith('Video to Subtitle (v') and
                        rectangle.right - rectangle.left >= 700 and
                        rectangle.bottom - rectangle.top >= 400):
                    found.append(hwnd)
                return True
            user.EnumWindows(visit, 0)
            if found:
                result = ctypes.c_size_t()
                if user.SendMessageTimeoutW(found[0], 0, 0, 0, 2, 1000, ctypes.byref(result)):
                    window = found[0]
                    break
            time.sleep(0.05)
        if window is None:
            raise TimeoutError(f'No responsive application window within {timeout}s')
        elapsed = time.perf_counter() - started
        time.sleep(0.5)  # Settle first paint for screenshots, excluded from timing.
        if screenshot:
            from PIL import ImageGrab
            rectangle = wintypes.RECT()
            user.GetWindowRect(window, ctypes.byref(rectangle))
            ImageGrab.grab(bbox=(rectangle.left, rectangle.top,
                                rectangle.right, rectangle.bottom)).save(screenshot)
        user.PostMessageW(window, 0x0010, 0, 0)  # Normal WM_CLOSE, respects app lifecycle.
        code = process.wait(timeout=20)
        if code != 0:
            raise RuntimeError(f'Application exited with {code}')
        return elapsed
    finally:
        # Only descendants of the exact process we launched, never name-based.
        for child in reversed(descendants):
            if child.is_running():
                child.terminate()
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)


def run_smoke(installer, portable, report):
    if sys.platform != 'win32' or os.environ.get('GITHUB_ACTIONS') != 'true':
        raise RuntimeError('Installer smoke is restricted to disposable Windows GitHub CI')
    import winreg
    key = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\VideoToSubtitle_is1'
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key):
            raise RuntimeError('Refusing to touch an existing installation')
    except FileNotFoundError:
        pass
    shortcut = Path(os.environ['APPDATA']) / 'Microsoft/Windows/Start Menu/Programs/Video to Subtitle.lnk'
    if shortcut.exists():
        raise RuntimeError('Refusing to replace an existing shortcut')
    report.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='vts-installer-ci-') as temporary:
        root = Path(temporary)
        installed = root / '安裝測試' / 'VideoToSubtitle'
        local = root / '使用者資料'
        local.mkdir()
        cache = root / 'model-cache'
        cache.mkdir()
        model_marker = cache / 'preserve-model.txt'
        model_marker.write_text('preserve model', encoding='utf-8')
        env = isolated_environment(os.environ)
        env['LOCALAPPDATA'] = str(local)
        env['HF_HOME'] = str(cache)
        command = [str(installer), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART',
                   '/SP-', '/NOCLOSEAPPLICATIONS', '/NORESTARTAPPLICATIONS',
                   f'/DIR={installed}', '/TASKS=', f'/LOG={report.parent / "install.log"}']
        subprocess.run(command, check=True, timeout=240)
        executable = installed / 'VideoToSubtitle.exe'
        uninstaller = installed / 'unins000.exe'
        try:
            for file in (executable, uninstaller, installed / '_internal/python311.dll',
                         installed / '_internal/assets/standalone_player/index.html', shortcut):
                if not file.is_file():
                    raise AssertionError(f'Installed payload missing: {file}')
            subprocess.run([str(executable), '--test-web-export'], check=True, env=env,
                           cwd=root, timeout=180)
            for exe in (portable, executable):
                subprocess.run([str(exe), '--test-traditional-chinese'], check=True,
                               env=env, cwd=root, timeout=180)
            try:
                from scripts.smoke_windows_local_page import smoke_local_page
            except ModuleNotFoundError:  # Direct invocation from scripts/.
                from smoke_windows_local_page import smoke_local_page
            for label, exe in (('portable', portable), ('installed', executable)):
                smoke_local_page(exe, report.parent / f'local-page-{label}')
            # Recreate the missing sibling DLL-directory condition only inside
            # our disposable installation. Never touch a real user's install.
            libraries = installed / '_internal/opencc.libs'
            disabled = root / 'disabled-opencc.libs'
            if not libraries.is_dir():
                raise AssertionError('Installed payload missing OpenCC external DLL directory')
            libraries.rename(disabled)
            try:
                failure_report = report.parent / 'missing-opencc-report.json'
                failed = subprocess.run([str(executable), '--test-traditional-chinese',
                                         '--test-report', str(failure_report.resolve())],
                                        env=env, cwd=root, timeout=180)
                diagnostic = json.loads(failure_report.read_text(encoding='utf-8'))
                if (failed.returncode != 1 or diagnostic['success'] or
                        diagnostic.get('error_type') != 'TraditionalChineseConversionError'):
                    raise AssertionError(f'Missing OpenCC dependency was not identified: {diagnostic}')
                # ASCII-escaped JSON also works in legacy Windows consoles.
                print(json.dumps(diagnostic, ensure_ascii=True, indent=2))
            finally:
                disabled.rename(libraries)
            subprocess.run([str(executable), '--test-traditional-chinese'], check=True,
                           env=env, cwd=root, timeout=180)
            config = local / 'VideoToSubtitle/config.json'
            config.parent.mkdir(exist_ok=True)
            expected = {'model': 'small', 'hotwords': '研習, 老師', 'model_path': str(cache)}
            config.write_text(json.dumps(expected, ensure_ascii=False), encoding='utf-8')
            samples = {'portable': [], 'installed': []}
            for number in range(3):
                for label, exe in (('portable', portable), ('installed', executable)):
                    sample = launch_window(exe, env,
                                           report.parent / f'{label}.png' if number == 0 else None)
                    samples[label].append(sample)
            if json.loads(config.read_text(encoding='utf-8')) != expected:
                raise AssertionError('Launching altered user settings')
            subprocess.run(command, check=True, timeout=240)
            if json.loads(config.read_text(encoding='utf-8')) != expected:
                raise AssertionError('Reinstall removed settings')
            launch_window(executable, env)
            subprocess.run([str(uninstaller), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART'],
                           check=True, timeout=120)
            deadline = time.monotonic() + 10
            while executable.exists() and time.monotonic() < deadline:
                time.sleep(0.1)
            if executable.exists() or shortcut.exists():
                raise AssertionError('Uninstall retained application or shortcut')
            if json.loads(config.read_text(encoding='utf-8')) != expected:
                raise AssertionError('Uninstall removed settings')
            if model_marker.read_text(encoding='utf-8') != 'preserve model':
                raise AssertionError('Uninstall removed the model cache')
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key):
                    raise AssertionError('Uninstall registration retained')
            except FileNotFoundError:
                pass
            result = {'platform': 'Windows x64 GitHub runner',
                      'measurement': 'process start to visible responsive main window; no inference',
                      'warmup': 'export smoke ran before GUI timing; samples are not disk/AV cold starts',
                      'python_on_app_path': False,
                      'install_reinstall_uninstall_passed': True,
                      'traditional_chinese_smoke_passed': True,
                      'missing_opencc_dll_rejected': True,
                      **{label: summarize_startup(values) for label, values in samples.items()}}
            report.write_text(json.dumps(result, indent=2), encoding='utf-8')
            print(json.dumps(result, indent=2))
        finally:
            if uninstaller.is_file() and executable.is_file():
                subprocess.run([str(uninstaller), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART'],
                               timeout=120, check=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--installer', required=True, type=Path)
    parser.add_argument('--portable', required=True, type=Path)
    parser.add_argument('--report', required=True, type=Path)
    args = parser.parse_args()
    run_smoke(args.installer.resolve(), args.portable.resolve(), args.report.resolve())
