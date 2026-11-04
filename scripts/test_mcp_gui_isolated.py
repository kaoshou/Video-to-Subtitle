"""Run native GUI cases in fresh processes, avoiding repeated Tcl interpreters.

The unmodified baseline can abort when many App/TkDND interpreters are created
and destroyed in a single Python process on macOS. This runner isolates test
lifetimes; it does not retry, suppress errors, or change application behavior.
"""
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


def main():
    os.environ['VTS_RUN_GUI_TESTS'] = '1'
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / 'tests'))
    from test_mcp_gui import MCPGuiTests
    names = unittest.defaultTestLoader.getTestCaseNames(MCPGuiTests)
    environment = dict(os.environ, PYTHONPATH=os.pathsep.join((str(ROOT / 'tests'), str(ROOT),
                                                             os.environ.get('PYTHONPATH', ''))))
    failures = []
    for name in names:
        case = 'test_mcp_gui.MCPGuiTests.' + name
        try:
            result = subprocess.run([sys.executable, '-m', 'unittest', '-v', case], cwd=ROOT,
                                    env=environment, timeout=45)
            if result.returncode:
                failures.append(case)
        except subprocess.TimeoutExpired:
            failures.append(case + ' (timeout)')
    print(f'Native GUI isolated: {len(names) - len(failures)}/{len(names)} processes succeeded.', flush=True)
    for case in failures:
        print('FAILED: ' + case, flush=True)
    return int(bool(failures))


if __name__ == '__main__':
    raise SystemExit(main())
