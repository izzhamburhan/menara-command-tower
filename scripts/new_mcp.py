"""Scaffold a new MCP server under servers/ and register it in the repo.

Usage:
    uv run python scripts/new_mcp.py <name> --port 8105 --description "What it serves"
    uv run python scripts/new_mcp.py policy --port 8109 --description "..." --owns audit_log,approval

Creates servers/<name>-mcp/ (pyproject, README, src, tests with a placeholder `<name>_info` tool),
then adds it to .mcp.json and to the root pyproject (dev group, uv sources, mypy_path).
Replace the placeholder tool with the real ones, then follow playbook.md.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

NAME_RE = re.compile(r"^[a-z]{3,20}$")

PYPROJECT = '''[project]
name = "__NAME__-mcp"
version = "0.1.0"
description = "MCP server: __DESC__ (synthetic data)."
requires-python = ">=3.13"
dependencies = [
    "menara-core",
    "mcp[cli]>=1.9,<2",
]

[project.scripts]
__NAME__-mcp = "__MODULE__.server:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/__MODULE__"]

[tool.uv.sources]
menara-core = { workspace = true }
'''

README = """# __NAME__-mcp

__DESC__. **All data is synthetic.** __OWNS_README__

## Run

```bash
uv run menara-seed
uv run --package __NAME__-mcp python -m __MODULE__                      # stdio
uv run --package __NAME__-mcp python -m __MODULE__ --transport streamable-http --port __PORT__
```

## Tool contract

Every tool returns `{synthetic: true, as_of, data, evidence[], warnings[]}`.

| Tool | Arguments | `data` |
| --- | --- | --- |
| `__NAME___info` | none | Placeholder: server name and description. Replace with the real tools. |

## Tests

```bash
uv run python -m pytest servers/__NAME__-mcp
```
"""

INIT = '"""__NAME__-mcp: __DESC__. Synthetic data only."""\n'

MAIN = "from __MODULE__.server import main\n\nmain()\n"

MODELS = '''"""Typed contracts for __NAME__-mcp responses (the `data` field of the envelope)."""

from __future__ import annotations

from pydantic import BaseModel


class ServerInfo(BaseModel):
    name: str
    description: str
'''

TOOLS = '''"""__NAME__-mcp tool logic. Plain functions over a DB connection; server.py exposes them."""

from __future__ import annotations

import sqlite3

from menara_core.envelope import Envelope, wrap

from __MODULE__.models import ServerInfo

SOURCE = "__NAME__-mcp"
OWNED_TABLES: frozenset[str] = frozenset(__OWNED__)


def get_info(conn: sqlite3.Connection) -> Envelope[ServerInfo]:
    """Placeholder tool. Replace with the real tools for this domain."""
    return wrap(
        conn,
        source=SOURCE,
        tool="__NAME___info",
        data=ServerInfo(name=SOURCE, description="__DESC__"),
    )
'''

SERVER = '''"""__NAME__-mcp server. Run: `uv run --package __NAME__-mcp python -m __MODULE__ [--transport streamable-http --port __PORT__]`."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP
from menara_core import settings
from menara_core.db import connect
from menara_core.envelope import Envelope

from __MODULE__ import tools

NAME = "__NAME__"
DEFAULT_PORT = __PORT__
INSTRUCTIONS = "__DESC__. ALL DATA IS SYNTHETIC. Every response has evidence[] naming the call that produced it."


def build_server(db_path: Path, *, host: str = "127.0.0.1", port: int = DEFAULT_PORT) -> FastMCP:
    mcp = FastMCP(NAME, instructions=INSTRUCTIONS, host=host, port=port)

    def run(call: Callable[[Any], Envelope[Any]]) -> dict[str, Any]:
        conn = connect(db_path, owned_tables=tools.OWNED_TABLES)
        try:
            return call(conn).model_dump(mode="json")
        finally:
            conn.close()

    @mcp.tool(description="Placeholder: server name and description. Replace with the real tools.")
    def __NAME___info() -> dict[str, Any]:
        return run(tools.get_info)

    return mcp


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="__NAME__-mcp", description=__doc__)
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--db", type=Path, default=None)
    args = parser.parse_args(argv)
    transport: Literal["stdio", "streamable-http"] = args.transport
    build_server(args.db or settings.db_path(), host=args.host, port=args.port).run(transport=transport)


if __name__ == "__main__":
    main()
'''

CONFTEST = '''from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from menara_core import clock
from menara_core.db import connect
from menara_core.testing import build_test_db

from __MODULE__.tools import OWNED_TABLES


@pytest.fixture(scope="session")
def db_file(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_test_db(tmp_path_factory.mktemp("__NAME__-db"))


@pytest.fixture
def conn(db_file: Path) -> Iterator[sqlite3.Connection]:
    connection = connect(db_file, owned_tables=OWNED_TABLES)
    yield connection
    connection.close()


@pytest.fixture
def set_clock(db_file: Path) -> Iterator[Callable[[int], None]]:
    """Move the scenario clock for one test; always restored to T0 afterwards."""
    writer = connect(db_file, owned_tables={"scenario_state"})

    def move(minutes: int) -> None:
        clock.set_now(writer, minutes)

    yield move
    clock.set_now(writer, 0)
    writer.close()
'''

TEST_TOOLS = '''from __future__ import annotations

import sqlite3

from __MODULE__ import tools


def test_info_is_a_synthetic_envelope(conn: sqlite3.Connection) -> None:
    env = tools.get_info(conn)
    assert env.synthetic is True
    assert env.data.name == "__NAME__-mcp"
    assert env.evidence[0].tool == "__NAME___info"
'''

TEST_SERVER = '''from __future__ import annotations

import asyncio
from pathlib import Path

from __MODULE__.server import build_server


def test_server_registers_its_tools(db_file: Path) -> None:
    tools = asyncio.run(build_server(db_file).list_tools())
    assert {t.name for t in tools} == {"__NAME___info"}
'''


def render(template: str, values: dict[str, str]) -> str:
    for key, value in values.items():
        template = template.replace(key, value)
    return template


def register(root: Path, name: str) -> list[str]:
    """Add the server to .mcp.json and the root pyproject. Returns what changed."""
    changed: list[str] = []
    module, package = f"{name}_mcp", f"{name}-mcp"

    mcp_json = root / ".mcp.json"
    config = json.loads(mcp_json.read_text(encoding="utf-8")) if mcp_json.exists() else {"mcpServers": {}}
    if name not in config["mcpServers"]:
        config["mcpServers"][name] = {
            "command": "uv",
            "args": ["run", "--package", package, "python", "-m", module],
        }
        mcp_json.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8", newline="\n")
        changed.append(".mcp.json")

    pyproject = root / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    original = text
    if f'"{package}"' not in text:
        text = re.sub(r"(dev = \[.*?)(\n\])", lambda m: f'{m.group(1)}\n    "{package}",{m.group(2)}', text, count=1, flags=re.S)
    if f"{package} = {{ workspace = true }}" not in text:
        text = text.replace("[tool.uv.sources]\n", f"[tool.uv.sources]\n{package} = {{ workspace = true }}\n", 1)
    if f"servers/{package}/src" not in text:
        text = re.sub(r"(mypy_path = \[.*?)\]", lambda m: f'{m.group(1)}, "servers/{package}/src"]', text, count=1, flags=re.S)
    if text != original:
        pyproject.write_text(text, encoding="utf-8", newline="\n")
        changed.append("pyproject.toml")
    return changed


def scaffold(root: Path, name: str, port: int, description: str, owns: list[str]) -> list[str]:
    if not NAME_RE.match(name):
        raise SystemExit(f"name must be 3-20 lowercase letters, got {name!r}")
    package, module = f"{name}-mcp", f"{name}_mcp"
    target = root / "servers" / package
    if target.exists():
        raise SystemExit(f"{target} already exists; refusing to overwrite")
    desc = description.strip().rstrip(".")
    values = {
        "__NAME__": name,
        "__MODULE__": module,
        "__PORT__": str(port),
        "__DESC__": desc,
        "__OWNED__": "{" + ", ".join(repr(t) for t in owns) + "}" if owns else "()",
        "__OWNS_README__": f"Owns: {', '.join(f'`{t}`' for t in owns)}." if owns else "Read-only; owns no tables.",
    }
    files = {
        "pyproject.toml": PYPROJECT,
        "README.md": README,
        f"src/{module}/__init__.py": INIT,
        f"src/{module}/__main__.py": MAIN,
        f"src/{module}/models.py": MODELS,
        f"src/{module}/tools.py": TOOLS,
        f"src/{module}/server.py": SERVER,
        "tests/conftest.py": CONFTEST,
        "tests/test_tools.py": TEST_TOOLS,
        "tests/test_server.py": TEST_SERVER,
    }
    created: list[str] = []
    for rel, template in files.items():
        path = target / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render(template, values), encoding="utf-8", newline="\n")
        created.append(f"servers/{package}/{rel}")
    return created + register(root, name)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="new_mcp", description=__doc__)
    parser.add_argument("name", help="short lowercase name, e.g. weather (creates servers/weather-mcp)")
    parser.add_argument("--port", type=int, required=True, help="streamable-http port from the CLAUDE.md table")
    parser.add_argument("--description", required=True)
    parser.add_argument("--owns", default="", help="comma-separated tables this server writes (default: none)")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args(argv)
    owns = [t.strip() for t in args.owns.split(",") if t.strip()]
    created = scaffold(args.root, args.name, args.port, args.description, owns)
    print(f"Scaffolded {args.name}-mcp:")
    for item in created:
        print(f"  {item}")
    print(
        "Next: uv sync; replace the placeholder tool (tests first); update the status and port rows in "
        "CLAUDE.md and AGENTS.md; follow playbook.md."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
