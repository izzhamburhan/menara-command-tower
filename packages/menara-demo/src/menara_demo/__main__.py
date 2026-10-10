"""`uv run python -m menara_demo`: serve the demo page and start the MCP servers behind it."""

from __future__ import annotations

import argparse
import dataclasses
import os

import uvicorn
from menara_agent.config import SettingsError, load_dotenv, load_settings
from menara_agent.llm import DeepSeekClient
from menara_agent.servers import SECRET_VARS, McpHub, load_config
from menara_core import settings

from menara_demo.app import create_app
from menara_demo.app_types import HubFactory


def real_hub_factory(only: set[str] | None, dotenv: dict[str, str]) -> HubFactory:
    root = settings.repo_root()
    shared = {k: v for k, v in dotenv.items() if k not in SECRET_VARS}  # the shared signing key, never the secrets
    specs = {
        name: dataclasses.replace(spec, env={**shared, **spec.env})
        for name, spec in load_config(root / ".mcp.json").items()
        if only is None or name in only
    }
    return lambda: McpHub(specs, cwd=root)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="menara-demo", description=__doc__)
    parser.add_argument("--host", default="127.0.0.1", help="default 127.0.0.1; the demo has no login, keep it local")
    parser.add_argument("--port", type=int, default=8200)
    parser.add_argument("--servers", default=None, help="comma-separated subset of servers (default: all twelve)")
    args = parser.parse_args(argv)
    only = {name.strip() for name in args.servers.split(",")} if args.servers else None

    root = settings.repo_root()
    dotenv = load_dotenv(root / ".env")
    env = {**dotenv, **os.environ}
    llm: DeepSeekClient | None = None
    model_name: str | None = None
    try:
        model_settings = load_settings(env)
        llm, model_name = DeepSeekClient(model_settings), model_settings.model
    except SettingsError:
        print("No DEEPSEEK_API_KEY in .env: the Story tab can Replay but not run live.")
    approver_key = env.get("MENARA_APPROVER_KEY") or settings.approver_key()

    app = create_app(
        real_hub_factory(only, dotenv), settings.db_path(), llm=llm, approver_key=approver_key, model_name=model_name
    )
    print(f"Starting the MCP servers, then the demo at http://{args.host}:{args.port} (synthetic data). Ctrl+C to stop.")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
