from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest
from menara_agent.servers import McpHub, ServerSpec, load_config, scrubbed_env
from menara_core import settings
from menara_core.testing import build_test_db

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_the_environment_for_servers_drops_the_secrets() -> None:
    env = scrubbed_env(
        {
            "PATH": "/bin",
            "DEEPSEEK_API_KEY": "sk-secret",
            "MENARA_APPROVER_KEY": "human-only",
            "MENARA_SIGNING_KEY": "shared-with-action-servers",
        }
    )
    assert "DEEPSEEK_API_KEY" not in env and "MENARA_APPROVER_KEY" not in env
    assert env["PATH"] == "/bin" and env["MENARA_SIGNING_KEY"] == "shared-with-action-servers"


def test_load_config_reads_all_thirteen_servers_from_mcp_json() -> None:
    specs = load_config(REPO_ROOT / ".mcp.json")
    assert len(specs) == 14 and {"tower", "policy", "drone", "ran", "usage", "energy"} <= set(specs)
    assert specs["tower"].command == "uv" and specs["tower"].args[-1] == "tower_mcp"


def test_load_config_rejects_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "nope.json")


def test_hub_lists_tower_tools_and_answers_a_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_file = build_test_db(tmp_path)
    monkeypatch.setenv("MENARA_DB", str(db_file))
    specs = {"tower": ServerSpec(command=sys.executable, args=["-m", "tower_mcp"])}

    async def go() -> tuple[list[str], dict[str, object]]:
        async with McpHub(specs, cwd=REPO_ROOT) as hub:
            names = sorted(tool.name for tool in hub.tools)
            reply = await hub.call("tower_get_status", {"enodeb_name": "KKRI-0142"})
            with pytest.raises(RuntimeError, match="ZZZZ-9999|not found|Not found"):
                await hub.call("tower_get_status", {"enodeb_name": "ZZZZ-9999"})
            with pytest.raises(KeyError):
                await hub.call("no_such_tool", {})
            return names, json.loads(reply)

    names, payload = asyncio.run(go())
    assert names == ["tower_get_alarms", "tower_get_kpi", "tower_get_status", "tower_list_in_bbox", "tower_list_in_radius"]
    assert payload["synthetic"] is True and settings.db_path() == db_file.resolve()