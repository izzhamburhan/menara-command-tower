from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from menara_agent.gate import GatedRunner

ASK = json.dumps(
    {
        "synthetic": True,
        "data": {"decision": "ask", "reason": "human_decision_required", "approval_id": "APR-0001", "token": None},
    }
)
ALLOW = json.dumps({"synthetic": True, "data": {"decision": "allow", "approval_id": None, "token": "tok-allow"}})
DENY = json.dumps({"synthetic": True, "data": {"decision": "deny", "reason": "kill_switch", "approval_id": None}})


class FakeInner:
    def __init__(self, check_result: str) -> None:
        self.check_result = check_result
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call(self, name: str, arguments: dict[str, Any]) -> str:
        self.calls.append((name, arguments))
        if name == "policy_check_action":
            return self.check_result
        if name == "policy_approve":
            return json.dumps({"synthetic": True, "data": {"token": "tok-human", "approved_by": "terminal-human"}})
        if name == "policy_reject":
            return json.dumps({"synthetic": True, "data": {"status": "REJECTED"}})
        return "{}"


def gated(inner: FakeInner, answer: bool, asked: list[str]) -> GatedRunner:
    def ask_human(summary: str) -> bool:
        asked.append(summary)
        return answer

    return GatedRunner(inner, approver_key="the-key", ask_human=ask_human)


CHECK_ARGS = {"action": "drone_dispatch", "targets": ["KKRI-0142"], "confidence": 0.9}


def test_an_ask_prompts_the_human_and_approves_with_the_key() -> None:
    inner, asked = FakeInner(ASK), []
    result = json.loads(asyncio.run(gated(inner, True, asked).call("policy_check_action", CHECK_ARGS)))
    assert len(asked) == 1 and "drone_dispatch" in asked[0] and "APR-0001" in asked[0]
    approve = [c for c in inner.calls if c[0] == "policy_approve"]
    assert approve == [
        (
            "policy_approve",
            {"approval_id": "APR-0001", "approver": "terminal-human", "approver_key": "the-key"},
        )
    ]
    assert result["decision"] == "approved_by_human" and result["token"] == "tok-human"
    assert "the-key" not in json.dumps(result)


def test_a_no_rejects() -> None:
    inner, asked = FakeInner(ASK), []
    result = json.loads(asyncio.run(gated(inner, False, asked).call("policy_check_action", CHECK_ARGS)))
    assert [c[0] for c in inner.calls] == ["policy_check_action", "policy_reject"]
    assert result["decision"] == "rejected_by_human" and "token" not in result


def test_the_model_cannot_call_approver_tools() -> None:
    inner = FakeInner(ASK)
    runner = gated(inner, True, [])
    for name in ["policy_approve", "policy_reject", "policy_update_setting", "policy_set_kill_switch"]:
        with pytest.raises(PermissionError):
            asyncio.run(runner.call(name, {"approval_id": "APR-0001", "approver_key": "anything"}))
    assert inner.calls == []


@pytest.mark.parametrize("raw", [ALLOW, DENY])
def test_allow_and_deny_pass_through(raw: str) -> None:
    inner, asked = FakeInner(raw), []
    assert asyncio.run(gated(inner, True, asked).call("policy_check_action", CHECK_ARGS)) == raw
    assert asked == [] and [c[0] for c in inner.calls] == ["policy_check_action"]


def test_other_tools_pass_through() -> None:
    inner = FakeInner(ASK)
    assert asyncio.run(gated(inner, True, []).call("tower_get_status", {"enodeb_name": "KKRI-0142"})) == "{}"