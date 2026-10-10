from __future__ import annotations

from menara_agent.tools import HIDDEN_TOOLS, ToolInfo, to_openai_tool, visible

SCHEMA = {"type": "object", "properties": {"enodeb_name": {"type": "string"}}, "required": ["enodeb_name"]}


def test_schema_conversion_keeps_name_description_parameters() -> None:
    tool = to_openai_tool(ToolInfo("tower_get_status", "Status of one tower.", SCHEMA))
    assert tool == {
        "type": "function",
        "function": {"name": "tower_get_status", "description": "Status of one tower.", "parameters": SCHEMA},
    }


def test_a_tool_without_a_description_still_converts() -> None:
    tool = to_openai_tool(ToolInfo("x_tool", None, {"type": "object", "properties": {}}))
    assert tool["function"]["description"] == ""


def test_approver_tools_are_hidden() -> None:
    assert set(HIDDEN_TOOLS) == {"policy_approve", "policy_reject", "policy_update_setting", "policy_set_kill_switch"}
    tools = [ToolInfo(name, "d", SCHEMA) for name in ["tower_get_status", *sorted(HIDDEN_TOOLS), "policy_check_action"]]
    assert [t.name for t in visible(tools)] == ["tower_get_status", "policy_check_action"]