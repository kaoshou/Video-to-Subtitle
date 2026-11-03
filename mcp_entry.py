"""Optional MCP STDIO entry point. Importing it does not load the SDK or GUI."""
import argparse
import asyncio
import json
import sys


async def serve_stdio(state, command=None):
    import anyio
    from mcp.server.lowlevel import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, CallToolResult, TextContent
    from mcp_transport import BrokerClient, MAX_FRAME
    from mcp_service import TOOL_SCHEMAS
    from mcp_state import MCPError

    # Capture protocol output once, then route all ordinary/library prints away.
    protocol_stdout = sys.stdout
    sys.stdout = sys.stderr
    class BoundedInput:
        def __aiter__(self):
            return self

        async def __anext__(self):
            line = await anyio.to_thread.run_sync(sys.stdin.buffer.readline, MAX_FRAME + 1)
            if not line:
                raise StopAsyncIteration
            if len(line) > MAX_FRAME:
                raise StopAsyncIteration  # close this bridge before SDK parsing/allocation
            try:
                return line.decode('utf-8', errors='strict')
            except UnicodeError:
                raise StopAsyncIteration from None

    server, client = Server('video-to-subtitle'), BrokerClient(state, command)

    @server.list_tools()
    async def list_tools():
        return [Tool(name=name, description=name.replace('_', ' '), inputSchema=schema)
                for name, schema in TOOL_SCHEMAS.items()]

    @server.call_tool(validate_input=False)
    async def call_tool(name, arguments):
        try:
            result = await anyio.to_thread.run_sync(client.call, name, arguments)
            return CallToolResult(content=[TextContent(type='text', text=json.dumps(result, ensure_ascii=False))],
                                  structuredContent=result)
        except MCPError as error:
            result = {'error': {'code': error.code, 'message': str(error)[:512]}}
        except Exception:
            result = {'error': {'code': 'SERVICE_ERROR', 'message': 'Local service connection failed.'}}
        return CallToolResult(content=[TextContent(type='text', text=json.dumps(result))],
                              structuredContent=result, isError=True)

    try:
        async with stdio_server(stdin=BoundedInput(), stdout=anyio.wrap_file(protocol_stdout)) as (read, write):
            await server.run(read, write, server.create_initialization_options())
    finally:
        sys.stdout = protocol_stdout


def main(argv=None):
    parser = argparse.ArgumentParser(description='Local VideoToSubtitle MCP bridge')
    parser.add_argument('--state-dir')
    parser.add_argument('--broker', action='store_true')
    parser.add_argument('--self-test', action='store_true')
    options = parser.parse_args(argv)
    if options.state_dir is not None:
        from pathlib import Path
        if not Path(options.state_dir).is_absolute():
            parser.error('--state-dir must be absolute')
    from mcp_state import State, MCPError
    from mcp_transport import Broker, probe_connection
    state = State(options.state_dir)
    try:
        if options.broker:
            import signal
            import threading
            stop = threading.Event()
            for signum in (signal.SIGINT, signal.SIGTERM):
                signal.signal(signum, lambda *_: stop.set())
            # Broker/model imports and ordinary output never reach MCP stdout.
            sys.stdout = sys.stderr
            Broker(state).serve(stop)
            return 0
        if options.self_test:
            report = probe_connection(state.path)
            print(json.dumps(report, ensure_ascii=False))
            return 0 if report['connected'] else 1
        asyncio.run(serve_stdio(state))
        return 0
    except ImportError:
        print('The optional MCP dependency is unavailable; install the mcp extra.', file=sys.stderr)
        return 2
    except (MCPError, OSError):
        print('Local MCP startup failed; check local policy and backend configuration.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    import multiprocessing
    multiprocessing.freeze_support()
    raise SystemExit(main())
