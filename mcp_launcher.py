"""Standalone console bridge; it deliberately cannot run a media broker."""
import sys


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    if any(flag in arguments for flag in ('--broker', '--mcp-broker')):
        print('MCP launcher cannot run the backend. Open Video to Subtitle and repair MCP.', file=sys.stderr)
        return 2
    if '--mcp' in arguments:
        arguments.remove('--mcp')
    from mcp_entry import main as bridge_main
    return bridge_main(arguments)


if __name__ == '__main__':
    import multiprocessing
    multiprocessing.freeze_support()
    raise SystemExit(main())
