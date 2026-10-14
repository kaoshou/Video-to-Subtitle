"""Prove a packaged EXE opens a literal local HTML path in a real browser.

Only disposable Windows GitHub runners are supported. This never changes
file associations, opens the fixture directly in a browser, or kills browsers.
The only browser cleanup is WM_CLOSE for a currently matching sentinel window.
"""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid

BROWSER_NAMES = frozenset({'msedge.exe', 'chrome.exe', 'firefox.exe', 'brave.exe',
                           'opera.exe', 'vivaldi.exe', 'iexplore.exe'})


def _is_browser_page(title, process_name, sentinel):
    return sentinel in title and process_name.lower() in BROWSER_NAMES


def _read_open_report(path, returncode):
    try:
        result = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as error:
        raise RuntimeError(f'EXE did not produce a valid open-page report: {error}') from error
    if returncode != 0 or not isinstance(result, dict) or result.get('success') is not True:
        raise RuntimeError(f'EXE open-page failed (exit {returncode}): {result!r}')
    return result


def _local_page_environment(source):
    # Late import permits the installer harness to import this module too.
    try:
        from scripts.smoke_windows_installer import isolated_environment
    except ModuleNotFoundError:  # Direct invocation from the scripts directory.
        from smoke_windows_installer import isolated_environment
    # ShellExecute's browser inherits this environment. Keep LOCALAPPDATA so
    # it shares the profile warmed by _warm_edge, outside our HTML directory.
    return isolated_environment(source)


@contextmanager
def _close_page_on_exit(desktop, sentinel, result):
    try:
        yield
    finally:
        try:
            # Covers a page that appeared just after timeout as well.
            result['sentinel_windows_closed'] = sum(
                desktop.close_sentinel(window, sentinel) for window in desktop.windows()
                if _is_browser_page(window['title'], window['process_name'], sentinel))
        except Exception as error:
            result['cleanup_error'] = str(error)


class _WindowsDesktop:
    def __init__(self):
        import ctypes
        from ctypes import wintypes
        import psutil
        self.ctypes, self.wintypes, self.psutil = ctypes, wintypes, psutil
        self.user = ctypes.WinDLL('user32', use_last_error=True)
        self.callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        self.user.EnumWindows.argtypes = [self.callback_type, wintypes.LPARAM]
        self.user.EnumWindows.restype = wintypes.BOOL
        self.user.IsWindowVisible.argtypes = [wintypes.HWND]
        self.user.IsWindowVisible.restype = wintypes.BOOL
        self.user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        self.user.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        self.user.GetWindowTextLengthW.restype = ctypes.c_int
        self.user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self.user.GetWindowTextW.restype = ctypes.c_int
        self.user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        self.user.GetWindowRect.restype = wintypes.BOOL
        self.user.SendMessageTimeoutW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                                wintypes.LPARAM, wintypes.UINT, wintypes.UINT,
                                                ctypes.POINTER(ctypes.c_size_t)]
        self.user.SendMessageTimeoutW.restype = ctypes.c_size_t
        self.user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        self.user.PostMessageW.restype = wintypes.BOOL

    def _window(self, hwnd):
        if not self.user.IsWindowVisible(hwnd):
            return None
        length = self.user.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return None
        title = self.ctypes.create_unicode_buffer(length + 1)
        self.user.GetWindowTextW(hwnd, title, len(title))
        pid = self.wintypes.DWORD()
        self.user.GetWindowThreadProcessId(hwnd, self.ctypes.byref(pid))
        try:
            name = self.psutil.Process(pid.value).name()
        except (self.psutil.NoSuchProcess, self.psutil.AccessDenied):
            return None
        return {'hwnd': int(hwnd), 'pid': pid.value, 'process_name': name, 'title': title.value}

    def windows(self):
        found = []
        @self.callback_type
        def visit(hwnd, _):
            window = self._window(hwnd)
            if window:
                found.append(window)
            return True
        if not self.user.EnumWindows(visit, 0):
            raise self.ctypes.WinError(self.ctypes.get_last_error())
        return found

    def responsive(self, hwnd):
        result = self.ctypes.c_size_t()
        return bool(self.user.SendMessageTimeoutW(hwnd, 0, 0, 0, 2, 1000,
                                                 self.ctypes.byref(result)))

    def screenshot(self, hwnd, path):
        from PIL import ImageGrab
        rectangle = self.wintypes.RECT()
        if not self.user.GetWindowRect(hwnd, self.ctypes.byref(rectangle)):
            raise self.ctypes.WinError(self.ctypes.get_last_error())
        ImageGrab.grab(bbox=(rectangle.left, rectangle.top,
                            rectangle.right, rectangle.bottom)).save(path)

    def close_sentinel(self, window, sentinel):
        # Recheck title + PID before posting: HWND values can be reused.
        current = self._window(window['hwnd'])
        if (current and current['pid'] == window['pid'] and
                _is_browser_page(current['title'], current['process_name'], sentinel)):
            return bool(self.user.PostMessageW(window['hwnd'], 0x0010, 0, 0))
        return False


def _warm_edge():
    """Suppress Edge first-run UI on CI without selecting it as the default.

    Use an actual installed executable, never a PATH alias. No fixture URL is
    passed, so warmup cannot supply the observation required by this smoke.
    The disposable runner owns the background browser lifetime.
    """
    for variable in ('ProgramFiles(x86)', 'ProgramFiles'):
        directory = os.environ.get(variable)
        if not directory:
            continue
        executable = Path(directory) / 'Microsoft/Edge/Application/msedge.exe'
        if executable.is_file():
            command = [str(executable), '--no-first-run', '--no-default-browser-check',
                       '--no-startup-window']
            process = subprocess.Popen(command, cwd=executable.parent,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(2)
            return {'executable': str(executable), 'pid': process.pid,
                    'returncode_after_warmup': process.poll(),
                    'arguments': command[1:]}, process
    return {'available': False}, None


def smoke_local_page(executable: Path, report_dir: Path):
    """Return evidence on success; write local-page-smoke.json even on failure."""
    if sys.platform != 'win32' or os.environ.get('GITHUB_ACTIONS') != 'true':
        raise RuntimeError('Local page smoke is restricted to disposable Windows GitHub CI')
    executable, report_dir = Path(executable).resolve(), Path(report_dir).resolve()
    report_dir.mkdir(parents=True, exist_ok=True)
    result = {'success': False, 'executable': str(executable),
              'platform': 'Windows GitHub runner', 'python_on_app_path': False}
    sentinel = 'VTS_LOCAL_PAGE_' + uuid.uuid4().hex
    result['sentinel'] = sentinel
    desktop = None
    warmup_process = None
    try:
        if not executable.is_file():
            raise FileNotFoundError(f'Packaged executable missing: {executable}')
        desktop = _WindowsDesktop()
        result['edge_warmup'], warmup_process = _warm_edge()
        # Contexts exit in reverse order: close our browser window before
        # deleting its HTML. Browser profiles are never created in this tree.
        with (tempfile.TemporaryDirectory(prefix='vts-local-page-ci-') as temporary,
              _close_page_on_exit(desktop, sentinel, result)):
            root = Path(temporary)
            directory = root / '網頁 測試 # 100% & 瀏覽器'
            directory.mkdir()
            page = directory / 'index.html'
            page.write_text(f'<!doctype html><html><head><meta charset="utf-8">'
                            f'<title>{sentinel}</title></head><body>'
                            f'<h1>{sentinel}</h1><p>本機網頁路徑測試</p></body></html>', encoding='utf-8')
            result['page_path'] = str(page)
            app_report = report_dir / f'exe-open-page-{sentinel}.json'
            result['app_report_path'] = str(app_report)
            env = _local_page_environment(os.environ)
            env['HF_HOME'] = str(root / 'model-cache')
            command = [str(executable), '--test-open-page', str(page),
                       '--test-report', str(app_report)]
            started = time.monotonic()
            stdout = report_dir / 'exe-open-page.stdout.log'
            stderr = report_dir / 'exe-open-page.stderr.log'
            result['app_stdout_log'], result['app_stderr_log'] = str(stdout), str(stderr)
            # File handles avoid waiting for pipe EOF if ShellExecute's browser
            # inherits a standard handle. JSON is the app's required contract.
            with stdout.open('wb') as out, stderr.open('wb') as err:
                opened = subprocess.run(command, env=env, cwd=root, timeout=45,
                                        stdout=out, stderr=err)
            result['app_exit_code'] = opened.returncode
            result['app_report'] = _read_open_report(app_report, opened.returncode)
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                windows = desktop.windows()
                for window in windows:
                    if (_is_browser_page(window['title'], window['process_name'], sentinel) and
                            desktop.responsive(window['hwnd'])):
                        result['browser_window'] = window
                        result['open_to_observation_seconds'] = time.monotonic() - started
                        screenshot = report_dir / 'local-page-browser.png'
                        try:
                            desktop.screenshot(window['hwnd'], screenshot)
                            result['screenshot'] = str(screenshot)
                        except Exception as error:
                            result['screenshot_error'] = str(error)  # Optional evidence.
                        result['success'] = True
                        return result
                result['visible_browser_windows'] = [window for window in windows
                                                     if window['process_name'].lower() in BROWSER_NAMES]
                time.sleep(0.2)
            raise TimeoutError('EXE reported success, but no responsive browser window showed '
                               'the unique HTML title within 60 seconds; inspect first-run UI '
                               'or the default .html association')
    except Exception as error:
        result['success'] = False
        result['error_type'], result['error'] = type(error).__name__, str(error)
        raise
    finally:
        if warmup_process is not None:
            result['edge_warmup']['returncode_at_finish'] = warmup_process.poll()
        (report_dir / 'local-page-smoke.json').write_text(
            json.dumps(result, ensure_ascii=True, indent=2), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', required=True, type=Path)
    parser.add_argument('--report-dir', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(smoke_local_page(args.exe, args.report_dir), ensure_ascii=True, indent=2))
