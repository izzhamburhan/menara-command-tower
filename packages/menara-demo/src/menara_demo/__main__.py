"""`uv run python -m menara_demo`: serve the demo page and start the MCP servers behind it."""

from __future__ import annotations

import argparse

import uvicorn
from menara_agent.config import load_dotenv
from menara_agent.servers import SECRET_VARS, McpHub, load_config
from menara_core import settings

from menara_demo.app import HubFactory, create_app


def real_hub_factory(only: set[str] | None) -> HubFactory:
    root = settings.repo_root()
    dotenv = load_dotenv(root / ".env")
    shared = {k: v for k, v in dotenv.items() if k not in SECRET_VARS}  # the shared signing key, never the secrets
    specs = {
        name: spec
        for name, spec in load_config(root / ".mcp.json").items()
        if only is None or name in only
    }
    specs = {name: type(spec)(spec.command, spec.args, {**shared, **spec.env}) for name, spec in specs.items()}
    return lambda: McpHub(specs, cwd=root)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="menara-demo", description=__doc__)
    parser.add_argument("--host", default="127.0.0.1", help="default 127.0.0.1; the demo has no login, keep it local")
    parser.add_argument("--port", type=int, default=8200)
    parser.add_argument("--servers", default=None, help="comma-separated subset of servers (default: all twelve)")
    args = parser.parse_args(argv)
    only = {name.strip() for name in args.servers.split(",")} if args.servers else None
    app = create_app(real_hub_factory(only), settings.db_path())
    print(f"Starting the MCP servers, then the demo at http://{args.host}:{args.port} (synthetic data). Ctrl+C to stop.")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()