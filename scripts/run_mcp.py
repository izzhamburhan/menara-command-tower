"""Run one Menara MCP server (or all of them) so you can poke at it.

Usage:
    uv run python scripts/run_mcp.py list                 # names and ports
    uv run python scripts/run_mcp.py tower                # tower-mcp over streamable HTTP on its port
    uv run python scripts/run_mcp.py tower --stdio        # over stdio (for an MCP client that launches it)
    uv run python scripts/run_mcp.py all                  # all servers on their ports, Ctrl+C stops them
    uv run python scripts/run_mcp.py tower --print        # show the command, do not run it
    uv run python scripts/run_mcp.py tower -- --db my.db  # arguments after -- go to the server

Servers are found by scanning servers/*/src/*/server.py, so a server made with scripts/new_mcp.py appears
here without any change. The HTTP endpoint is http://127.0.0.1:<port>/mcp; open it with an MCP client or
`npx @modelcontextprotocol/inspector`. All data is synthetic; run `uv run menara-seed` once first.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORT_RE = re.compile(r"^DEFAULT_PORT\s*=\s*(\d+)", re.MULTILINE)


@dataclass(frozen=True)
class Server:
    name: str
    package: str
    module: str
    port: int

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/mcp"


def discover(root: Path = ROOT) -> dict[str, Server]:
    servers: dict[str, Server] = {}
    for folder in sorted((root / "servers").glob("*-mcp")):
        name = folder.name.removesuffix("-mcp")
        module = f"{name}_mcp"
        server_py = folder / "src" / module / "server.py"
        match = PORT_RE.search(server_py.read_text(encoding="utf-8")) if server_py.is_file() else None
        if match:
            servers[name] = Server(name, folder.name, module, int(match.group(1)))
    return dict(sorted(servers.items(), key=lambda item: item[1].port))


def build_command(server: Server, *, http: bool, extra: list[str]) -> list[str]:
    command = ["uv", "run", "--package", server.package, "python", "-m", server.module]
    if http:
        command += ["--transport", "streamable-http", "--port", str(server.port)]
    return command + extra


def _show(server: Server, command: list[str], http: bool) -> None:
    where = server.url if http else "stdio"
    print(f"{server.name:<9} {where}\n    {' '.join(command)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run_mcp", description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("target", help="a server name, 'all', or 'list'")
    parser.add_argument("--stdio", action="store_true", help="use stdio instead of streamable HTTP")
    parser.add_argument("--print", dest="show_only", action="store_true", help="print the command and exit")
    parser.add_argument("extra", nargs="*", help="after --: arguments passed to the server")
    args = parser.parse_args(argv)

    servers = discover()
    if args.target == "list":
        for server in servers.values():
            print(f"{server.name:<9} port {server.port}   {server.url}")
        return 0

    chosen = list(servers.values()) if args.target == "all" else [servers[args.target]] if args.target in servers else []
    if not chosen:
        print(f"error: unknown server {args.target!r}. Choose one of: {', '.join(servers)}, all, list", file=sys.stderr)
        return 2
    http = not args.stdio
    commands = [(server, build_command(server, http=http, extra=args.extra)) for server in chosen]

    if args.show_only:
        for server, command in commands:
            _show(server, command, http)
        return 0
    if len(commands) > 1 and not http:
        print("error: 'all' needs HTTP; stdio servers are launched by a client, one each", file=sys.stderr)
        return 2

    if len(commands) == 1:
        server, command = commands[0]
        print(f"Starting {server.name} ({server.url if http else 'stdio'}). Ctrl+C to stop.", file=sys.stderr)
        try:
            return subprocess.run(command, cwd=ROOT).returncode
        except KeyboardInterrupt:
            return 0

    processes = [(server, subprocess.Popen(command, cwd=ROOT)) for server, command in commands]
    for server, _ in processes:
        print(f"{server.name:<9} {server.url}", file=sys.stderr)
    print("All started. Ctrl+C stops them.", file=sys.stderr)
    try:
        for _, process in processes:
            process.wait()
    except KeyboardInterrupt:
        pass
    finally:
        for _, process in processes:
            if process.poll() is None:
                process.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())