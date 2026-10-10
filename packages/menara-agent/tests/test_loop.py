from __future__ import annotations

import asyncio
from typing import Any

from menara_agent.loop import Reply, ToolCall, run_agent

TOOLS: list[dict[str, Any]] = [{"type": "function", "function": {"name": "tower_get_status", "parameters": {}}}]


class ScriptedModel:
    """Plays a fixed list of replies and records what it was shown."""

    def __init__(self, replies: list[Reply]) -> None:
        self.replies = list(replies)
        self.seen: list[list[dict[str, Any]]] = []

    async def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> Reply:
        self.seen.append([dict(m) for m in messages])
        return self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]


class FakeRunner:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.fail = fail

    async def call(self, name: str, arguments: dict[str, Any]) -> str:
        self.calls.append((name, arguments))
        if self.fail:
            raise RuntimeError("tower is on fire")
        return '{"status": "DOWN"}'


def tool_reply(call_id: str = "c1") -> Reply:
    return Reply(content=None, tool_calls=[ToolCall(call_id, "tower_get_status", {"enodeb_name": "KKRI-0142"})])


def run(model: ScriptedModel, runner: FakeRunner, max_steps: int = 10) -> str:
    return asyncio.run(run_agent(model, runner, "Investigate TK-88213", TOOLS, max_steps, log=lambda _: None))


def test_finishes_when_the_model_stops_calling_tools() -> None:
    model = ScriptedModel([tool_reply(), Reply(content="KKRI-0142 lost mains power.", tool_calls=[])])
    runner = FakeRunner()
    assert run(model, runner) == "KKRI-0142 lost mains power."
    assert runner.calls == [("tower_get_status", {"enodeb_name": "KKRI-0142"})]
    second_turn = model.seen[1]
    assert second_turn[0] == {"role": "user", "content": "Investigate TK-88213"}
    assert second_turn[1]["role"] == "assistant" and second_turn[1]["tool_calls"][0]["id"] == "c1"
    assert second_turn[2] == {"role": "tool", "tool_call_id": "c1", "content": '{"status": "DOWN"}'}


def test_stops_at_the_step_cap() -> None:
    model = ScriptedModel([tool_reply()])
    runner = FakeRunner()
    result = run(model, runner, max_steps=3)
    assert len(runner.calls) == 3
    assert "step limit" in result and "3" in result


def test_a_tool_error_is_reported_to_the_model_and_the_loop_continues() -> None:
    model = ScriptedModel([tool_reply(), Reply(content="Tower tool failed, cannot say.", tool_calls=[])])
    result = run(model, FakeRunner(fail=True))
    assert result == "Tower tool failed, cannot say."
    tool_message = model.seen[1][-1]
    assert tool_message["role"] == "tool" and tool_message["content"].startswith("ERROR:")
    assert "tower is on fire" in tool_message["content"]
    assert "tower is on fire" in tool_message["content"]

# ---------- structured events for a UI ----------


def run_with_events(model: ScriptedModel, runner: FakeRunner, max_steps: int = 10) -> tuple[str, list[dict[str, Any]]]:
    events: list[dict[str, Any]] = []
    final = asyncio.run(
        run_agent(model, runner, "Investigate", TOOLS, max_steps, log=lambda _: None, on_event=events.append)
    )
    return final, events


def test_events_cover_calls_results_and_model_text_in_order() -> None:
    first = Reply(content="Checking the tower first.", tool_calls=[ToolCall("c1", "tower_get_status", {"enodeb_name": "KKRI-0142"})])
    model = ScriptedModel([first, Reply(content="Done.", tool_calls=[])])
    final, events = run_with_events(model, FakeRunner())
    assert final == "Done."
    assert [e["type"] for e in events] == ["say", "call", "result"]
    assert events[0]["text"] == "Checking the tower first."
    assert events[1] == {"type": "call", "step": 1, "name": "tower_get_status", "arguments": {"enodeb_name": "KKRI-0142"}}
    assert events[2]["step"] == 1 and events[2]["ok"] is True and "DOWN" in events[2]["text"]


def test_a_failing_tool_is_a_result_event_with_ok_false() -> None:
    model = ScriptedModel([tool_reply(), Reply(content="Cannot say.", tool_calls=[])])
    _, events = run_with_events(model, FakeRunner(fail=True))
    result = [e for e in events if e["type"] == "result"][0]
    assert result["ok"] is False and result["text"].startswith("ERROR:")


def test_long_results_are_cut_for_events_but_not_for_the_model() -> None:
    class Big(FakeRunner):
        async def call(self, name: str, arguments: dict[str, Any]) -> str:
            return "x" * 20000

    model = ScriptedModel([tool_reply(), Reply(content="ok", tool_calls=[])])
    _, events = run_with_events(model, Big())
    text = [e for e in events if e["type"] == "result"][0]["text"]
    assert len(text) < 20000 and text.endswith("...[cut]")
    assert len(model.seen[1][-1]["content"]) == 20000