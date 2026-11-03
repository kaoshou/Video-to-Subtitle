"""Packaging entry: frozen multiprocessing children dispatch before GUI imports."""
import multiprocessing


def main(argv=None):
    multiprocessing.freeze_support()
    import sys
    arguments = list(sys.argv[1:] if argv is None else argv)
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
