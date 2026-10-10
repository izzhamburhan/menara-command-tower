from __future__ import annotations

from types import SimpleNamespace

from menara_agent.llm import parse_reply
from menara_agent.loop import ToolCall


def message(content: str | None, calls: list[tuple[str, str, str]] | None = None) -> SimpleNamespace:
    tool_calls = [
        SimpleNamespace(id=i, type="function", function=SimpleNamespace(name=n, arguments=a)) for i, n, a in calls or []
    ]
    return SimpleNamespace(content=content, tool_calls=tool_calls or None)


def test_a_plain_answer() -> None:
    reply = parse_reply(message("All clear."))
    assert reply.content == "All clear." and reply.tool_calls == []


def test_tool_calls_are_parsed_with_json_arguments() -> None:
    reply = parse_reply(message(None, [("c1", "tower_get_status", '{"enodeb_name": "KKRI-0142"}')]))
    assert reply.tool_calls == [ToolCall("c1", "tower_get_status", {"enodeb_name": "KKRI-0142"})]


def test_broken_json_arguments_become_empty_so_the_tool_reports_the_error() -> None:
    reply = parse_reply(message(None, [("c1", "tower_get_status", "{not json")]))
    assert reply.tool_calls == [ToolCall("c1", "tower_get_status", {})]