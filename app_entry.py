"""Packaging entry: frozen multiprocessing children dispatch before GUI imports."""
import multiprocessing


def _mcp_admin(arguments):
    """Trusted local installer/admin route, never registered as an AI tool."""
    import argparse
    import sys
    import time
    from pathlib import Path
    from mcp_state import State, MCPError, ProcessLock
    parser = argparse.ArgumentParser(description='Revoke local MCP before maintenance')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--mcp-disable', action='store_true')
    group.add_argument('--mcp-maintenance', action='store_true')
    parser.add_argument('--state-dir')
    options = parser.parse_args(arguments)
    if options.state_dir is not None and not Path(options.state_dir).is_absolute():
        parser.error('--state-dir must be absolute')
    state = State(options.state_dir)
    try:
        state.disable(stop_mode='finish')
        if not options.mcp_maintenance or not state.path.exists():
            return 0
        deadline = time.monotonic() + 2
        while True:
            locks = [ProcessLock(state.path / 'locks', name) for name in ('broker', 'inference')]
            try:
                if all(lock.acquire() for lock in locks):
                    return 0
            finally:
                for lock in reversed(locks):
                    lock.release()
            if time.monotonic() >= deadline:
                if sys.stderr:
                    print('MCP is disabled. Wait for accepted work to finish or normally close the GUI before maintenance.', file=sys.stderr)
                return 3
            time.sleep(.05)
    except (MCPError, OSError):
        if sys.stderr:
            print('MCP revocation failed; open local AI connection settings before maintenance.', file=sys.stderr)
        return 1


def main(argv=None):
    multiprocessing.freeze_support()
    import sys
    arguments = list(sys.argv[1:] if argv is None else argv)
    if '--mcp-disable' in arguments or '--mcp-maintenance' in arguments:
        return _mcp_admin(arguments)
    if arguments == ['--test-mcp']:
        from scripts.smoke_mcp import main as smoke_main
        return smoke_main([])
    if '--mcp-broker' in arguments or '--mcp' in arguments:
        from mcp_entry import main as mcp_main
        if '--mcp-broker' in arguments:
            arguments.remove('--mcp-broker')
            arguments.append('--broker')
        if '--mcp' in arguments:
            arguments.remove('--mcp')
        return mcp_main(arguments)
    # Preserve the established __main__ and every existing installer/smoke flag.
    import runpy
    previous = sys.argv
    try:
        sys.argv = [previous[0], *arguments]
        runpy.run_module('SubtitleTranscriber', run_name='__main__')
    finally:
        sys.argv = previous
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
