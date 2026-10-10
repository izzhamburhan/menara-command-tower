from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from menara_agent.cli import DEMO_CLOCK_TOOL, ClockRunner, _human_says_yes, main
from menara_agent.loop import Reply, ToolCall
from menara_agent.servers import ServerSpec
from menara_core import clock
from menara_core.db import connect
from menara_core.testing import build_test_db


class Inner:
    async def call(self, name: str, arguments: dict[str, Any]) -> str:
        return f"inner:{name}"


class ScriptedModel:
    def __init__(self, replies: list[Reply]) -> None:
        self.replies = list(replies)
        self.tool_names: list[str] = []

    async def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> Reply:
        self.tool_names = [t["function"]["name"] for t in tools]
        return self.replies.pop(0)


@pytest.fixture
def db_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = build_test_db(tmp_path)
    monkeypatch.setenv("MENARA_DB", str(path))
    return path


def now_min(db_file: Path) -> int:
    conn = connect(db_file)
    try:
        return clock.now_min(conn)
    finally:
        conn.close()


def test_advance_clock_tool_moves_the_scenario_clock(db_file: Path) -> None:
    import asyncio

    writer = connect(db_file, owned_tables={"scenario_state"})
    clock.set_now(writer, 12)
    writer.close()
    runner = ClockRunner(Inner(), db_file)
    result = asyncio.run(runner.call("demo_advance_clock", {"minutes": 60}))
    assert "72" in result and now_min(db_file) == 72
    assert asyncio.run(runner.call("tower_get_status", {})) == "inner:tower_get_status"


def test_advance_clock_refuses_nonsense(db_file: Path) -> None:
    import asyncio

    runner = ClockRunner(Inner(), db_file)
    for bad in [{"minutes": 0}, {"minutes": -5}, {"minutes": 100000}, {}]:
        with pytest.raises(ValueError):
            asyncio.run(runner.call("demo_advance_clock", bad))


def test_the_clock_tool_says_it_is_demo_only() -> None:
    assert "demo" in DEMO_CLOCK_TOOL["function"]["description"].lower()


def test_main_wires_a_fake_model_end_to_end(db_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    model = ScriptedModel(
        [
            Reply(None, [ToolCall("c1", "tower_get_status", {"enodeb_name": "KKRI-0142"})]),
            Reply(None, [ToolCall("c2", "demo_advance_clock", {"minutes": 5})]),
            Reply("KKRI-0142 is down.", []),
        ]
    )
    specs = {"tower": ServerSpec(command=sys.executable, args=["-m", "tower_mcp"])}
    code = main(["Investigate TK-88213", "--clock", "12"], llm=model, specs=specs)
    out = capsys.readouterr().out
    assert code == 0 and "KKRI-0142 is down." in out
    assert "tower_get_status" in model.tool_names and "demo_advance_clock" in model.tool_names
    assert now_min(db_file) == 17  # started at 12, the model waited 5


def test_main_without_a_key_exits_with_a_clear_message(
    db_file: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("MENARA_ROOT", str(db_file.parent))  # a root with no .env
    code = main(["task"], specs={})
    assert code == 2 and "DEEPSEEK_API_KEY" in capsys.readouterr().err

@pytest.mark.parametrize(("typed", "expected"), [("y", True), ("YES", True), ("", False), ("n", False), (None, False)])
def test_the_human_prompt_defaults_to_no(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], typed: str | None, expected: bool
) -> None:
    def fake_input(_: str) -> str:
        if typed is None:
            raise EOFError
        return typed

    monkeypatch.setattr("builtins.input", fake_input)
    assert _human_says_yes("Approval APR-0001: drone_dispatch") is expected
    assert "APR-0001" in capsys.readouterr().out
