from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("new_mcp", ROOT / "scripts" / "new_mcp.py")
assert spec and spec.loader
new_mcp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(new_mcp)

PYPROJECT = """[dependency-groups]
dev = [
    "pytest>=8.4",
    "tower-mcp",
]

[tool.uv.sources]
tower-mcp = { workspace = true }

[tool.mypy]
mypy_path = ["packages/menara-core/src", "servers/tower-mcp/src"]
"""


@pytest.fixture
def root(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    (tmp_path / ".mcp.json").write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
    return tmp_path


def test_scaffold_creates_a_complete_server(root: Path) -> None:
    created = new_mcp.scaffold(root, "demo", 8199, "Demo things", [])
    base = root / "servers" / "demo-mcp"
    for rel in ("pyproject.toml", "README.md", "src/demo_mcp/server.py", "src/demo_mcp/tools.py", "tests/test_tools.py"):
        assert (base / rel).is_file(), rel
    assert "servers/demo-mcp/README.md" in created
    leftovers = [f.name for f in base.rglob("*") if f.is_file() and re.search(r"__[A-Z]+__", f.read_text(encoding="utf-8"))]
    assert leftovers == []
    assert "DEFAULT_PORT = 8199" in (base / "src/demo_mcp/server.py").read_text(encoding="utf-8")


def test_scaffold_registers_everywhere(root: Path) -> None:
    new_mcp.scaffold(root, "demo", 8199, "Demo things", [])
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert '"demo-mcp",' in text
    assert "demo-mcp = { workspace = true }" in text
    assert 'servers/demo-mcp/src"]' in text
    config = json.loads((root / ".mcp.json").read_text(encoding="utf-8"))
    assert config["mcpServers"]["demo"]["args"] == ["run", "--package", "demo-mcp", "python", "-m", "demo_mcp"]


def test_owned_tables_flow_into_tools_and_readme(root: Path) -> None:
    new_mcp.scaffold(root, "ledger", 8198, "Keeps a ledger", ["entry", "balance"])
    tools = (root / "servers" / "ledger-mcp" / "src" / "ledger_mcp" / "tools.py").read_text(encoding="utf-8")
    assert "frozenset({'entry', 'balance'})" in tools
    assert "`entry`" in (root / "servers" / "ledger-mcp" / "README.md").read_text(encoding="utf-8")


def test_refuses_to_overwrite_and_validates_the_name(root: Path) -> None:
    new_mcp.scaffold(root, "demo", 8199, "Demo", [])
    with pytest.raises(SystemExit, match="already exists"):
        new_mcp.scaffold(root, "demo", 8199, "Demo", [])
    with pytest.raises(SystemExit, match="lowercase"):
        new_mcp.scaffold(root, "Bad_Name", 8199, "Demo", [])


def test_register_is_idempotent(root: Path) -> None:
    new_mcp.scaffold(root, "demo", 8199, "Demo", [])
    assert new_mcp.register(root, "demo") == []