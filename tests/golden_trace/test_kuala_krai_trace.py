"""Walk the Kuala Krai scenario across separate MCP processes, exactly as an agent would.

Each server is launched as its own stdio subprocess against one shared SQLite file.
Nothing here calls one MCP from another: this test plays the agent.

Steps covered (see the demo scenario): 1 ticket, 2 cluster, 3 serving cell, 4 tower status,
5 weather, grid and flood in parallel to find the cause, 6 blast radius and the Incident,
7-10 policy gate, drone, a failed fix with rollback, a good fix, and recovery (second test).
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from menara_core import clock, settings
from menara_core.db import connect
from menara_core.testing import build_test_db

SERVERS = ["tower", "ticket", "user", "weather", "grid", "flood", "sites", "ontology"]
STORM_END_MIN = 12


@asynccontextmanager
async def agent_session(name: str, db_file: Path) -> AsyncIterator[ClientSession]:
    params = StdioServerParameters(command=sys.executable, args=["-m", f"{name}_mcp", "--db", str(db_file)])
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        yield session


async def call(session: ClientSession, tool: str, **arguments: Any) -> dict[str, Any]:
    result = await session.call_tool(tool, arguments)
    assert not result.isError, result.content
    payload: dict[str, Any] = json.loads(result.content[0].text)  # type: ignore[union-attr]
    assert payload["synthetic"] is True
    return payload


@pytest.fixture
def db_file(tmp_path: Path) -> Path:
    path = build_test_db(tmp_path)
    writer = connect(path, owned_tables={"scenario_state"})
    clock.set_now(writer, STORM_END_MIN)
    writer.close()
    return path


def test_agent_walk_from_ticket_to_root_cause(db_file: Path) -> None:
    async def walk() -> list[dict[str, Any]]:
        async with AsyncExitStack() as stack:
            s = {name: await stack.enter_async_context(agent_session(name, db_file)) for name in SERVERS}

            # 1. customer ticket
            tk = await call(s["ticket"], "ticket_get_ticket", ticket_id="TK-88213")
            assert "banjir" in tk["data"]["summary"]

            # 2. cluster: 37 tickets in 12 minutes within 15 km
            cluster = await call(
                s["ticket"], "ticket_cluster_by_location", ticket_id="TK-88213", radius_km=15, window_min=30
            )
            assert cluster["data"]["count"] == 37 and cluster["data"]["span_min"] <= STORM_END_MIN

            # 3. serving cell of the customer
            cell = await call(s["user"], "user_get_serving_cell", msisdn_hash=tk["data"]["customer_ref"])
            assert cell["data"]["serving_cell"] == "KKRI-0142-B1" and cell["data"]["attached"] is False
            enodeb = cell["data"]["enodeb_name"]

            # 4. tower status: DOWN, MAINS_FAIL, battery 14%, two neighbours at 91%
            status = await call(s["tower"], "tower_get_status", enodeb_name=enodeb)
            assert status["data"]["status"] == "DOWN" and status["data"]["battery_pct"] == 14
            hot = {n["enodeb_name"] for n in status["data"]["neighbours"] if (n["prb_util"] or 0) >= 90}
            assert hot == {"KKRI-0143", "KKRI-0144"}
            alarms = await call(s["tower"], "tower_get_alarms", enodeb_name=enodeb, severity="CRITICAL")
            assert "MAINS_FAIL" in {a["code"] for a in alarms["data"]["alarms"]}

            # 5. grid, weather and flood in parallel: the cause is flood, not a network fault
            lat, lng = status["data"]["lat"], status["data"]["lng"]
            power, rain, lightning, river, point = await asyncio.gather(
                call(s["grid"], "grid_get_tower_power", enodeb_name=enodeb),
                call(s["weather"], "weather_get_rainfall", lat=lat, lng=lng),
                call(s["weather"], "weather_get_lightning", lat=lat, lng=lng),
                call(s["flood"], "flood_get_gauge", gauge_id="GAUGE-KKRI-01"),
                call(s["flood"], "flood_check_point", lat=lat, lng=lng),
            )
            assert power["data"]["feeder"]["status"] == "TRIPPED" and power["data"]["mains_expected"] is False
            assert rain["data"]["rain_24h_mm"] == 148.0 and rain["data"]["intensity"] == "VERY_HEAVY"
            assert lightning["data"]["activity"] == "SEVERE"
            assert river["data"]["status"] == "DANGER" and river["data"]["trend"] == "RISING"
            assert point["data"]["inside_flood"] is True and point["data"]["depth_m"] > 0.9

            # 6. blast radius and the Incident, citing the evidence gathered so far
            blast = await call(s["ontology"], "ontology_blast_radius", site=enodeb)
            assert blast["data"]["towers_at_risk"] == 11 and blast["data"]["subscribers_in_radius"] == 8420
            assert blast["data"]["counts_by_kind"]["CLINIC"] == 2 and blast["data"]["sla_customers"] == 1
            served = await call(s["sites"], "sites_for_tower", enodeb_name=enodeb)
            assert served["data"]["emergency_sites"] == 2
            gathered = [tk, cluster, cell, status, alarms, power, rain, river, point, blast]
            incident = await call(
                s["ontology"], "ontology_create_incident",
                enodeb_name=enodeb, cause="FLOOD", cause_confidence=0.93,
                summary="Tower down: feeder tripped, river above danger level, 148 mm rain in 24 h.",
                ticket_ids=[t["ticket_id"] for t in cluster["data"]["tickets"]],
                evidence=[{k: e[k] for k in ("source", "tool", "call_id", "ref")} for r in gathered for e in r["evidence"]],
            )
            assert incident["data"]["status"] == "OPEN" and len(incident["data"]["ticket_ids"]) == 37
            assert len(incident["data"]["evidence"]) == len(gathered)

            # the agent leaves a note on the ticket (ticket-mcp's only write)
            note = await call(
                s["ticket"], "ticket_add_note", ticket_id="TK-88213",
                text=f"{enodeb} DOWN: feeder tripped, flood. Incident {incident['data']['incident_id']}", author="trace",
            )
            return [tk, cluster, cell, status, alarms, power, rain, lightning, river, point, blast, served, incident, note]

    responses = asyncio.run(walk())
    sources = [r["evidence"][0]["source"] for r in responses]
    assert sources == [
        "ticket-mcp", "ticket-mcp", "user-mcp", "tower-mcp", "tower-mcp",
        "grid-mcp", "weather-mcp", "weather-mcp", "flood-mcp", "flood-mcp",
        "ontology-mcp", "sites-mcp", "ontology-mcp", "ticket-mcp",
    ]
    assert all(r["evidence"][0]["call_id"] for r in responses)


# ---------------------------------------------------------------------------------------------------
# Steps 7-10: policy gate, human approval, drone, a failed fix with rollback, a good fix, and recovery.
# ---------------------------------------------------------------------------------------------------

ACTION_SERVERS = ["tower", "ticket", "grid", "ontology", "policy", "twin", "ran", "drone"]
NEIGHBOURS = ["KKRI-0143", "KKRI-0144"]
RESTORED_MIN = 370


def _move_clock(db_file: Path, minutes: int) -> None:
    """Play the command-center orchestrator: move the shared scenario clock."""
    writer = connect(db_file, owned_tables={"scenario_state"})
    clock.set_now(writer, minutes)
    writer.close()


def test_agent_walk_through_actions_and_recovery(db_file: Path) -> None:
    human_key = settings.approver_key()

    async def last_prb(tower: Any, name: str) -> float:
        kpi = await call(tower, "tower_get_kpi", enodeb_name=name, window_min=5)
        return float(kpi["data"]["points"][-1]["prb_util"])

    async def ask_and_approve(policy: Any, action: str, targets: list[str]) -> str:
        """policy_check_action says ask; a human approves; returns the signed token."""
        check = await call(policy, "policy_check_action", action=action, targets=targets, confidence=0.93)
        assert check["data"]["decision"] == "ask" and check["data"]["token"] is None
        grant = await call(
            policy, "policy_approve", approval_id=check["data"]["approval_id"], approver="izzham", approver_key=human_key
        )
        assert grant["data"]["approved_by"] == "human:izzham"
        token: str = grant["data"]["token"]
        return token

    async def walk() -> None:
        async with AsyncExitStack() as stack:
            s = {name: await stack.enter_async_context(agent_session(name, db_file)) for name in ACTION_SERVERS}

            # the Incident from step 6 (kept short here)
            cluster = await call(s["ticket"], "ticket_cluster_by_location", ticket_id="TK-88213", radius_km=15, window_min=30)
            ticket_ids = [t["ticket_id"] for t in cluster["data"]["tickets"]]
            assert len(ticket_ids) == 37
            incident = await call(
                s["ontology"], "ontology_create_incident", enodeb_name="KKRI-0142", cause="FLOOD",
                cause_confidence=0.93, summary="Tower down: feeder tripped, flood.", ticket_ids=ticket_ids,
            )
            incident_id = incident["data"]["incident_id"]

            # 7. simulate first, then ask the policy engine. Nothing real-world is auto-allowed here.
            sim = await call(
                s["twin"], "twin_simulate_tilt",
                changes=[{"enodeb_name": n, "tilt_delta_deg": 4.0} for n in NEIGHBOURS],
            )
            assert sim["data"]["recommended"] is True
            assert [t["predicted_prb"] for t in sim["data"]["tilted"]] == [63.0, 63.0]
            drone_check = await call(
                s["policy"], "policy_check_action", action="drone_dispatch", targets=["KKRI-0142"], confidence=0.93
            )
            tilt_check = await call(
                s["policy"], "policy_check_action", action="ran_tilt_cells", targets=NEIGHBOURS, confidence=0.93,
                reason=f"Simulation {sim['data']['sim_id']} recommends it",
            )
            assert drone_check["data"]["decision"] == "ask" and tilt_check["data"]["decision"] == "ask"
            status = await call(s["policy"], "policy_get_status")
            assert status["data"]["pending_approvals"] == 2 and status["data"]["kill_switch"] is False

            # the agent holds no approver key: it cannot approve its own request
            refused = await s["policy"].call_tool(
                "policy_approve",
                {"approval_id": drone_check["data"]["approval_id"], "approver": "agent", "approver_key": "guess"},
            )
            assert refused.isError

            # 8. a human approves the drone; it flies; the clock moves on; findings arrive
            grant = await call(
                s["policy"], "policy_approve", approval_id=drone_check["data"]["approval_id"],
                approver="izzham", approver_key=human_key,
            )
            mission = await call(
                s["drone"], "drone_dispatch", enodeb_name="KKRI-0142", policy_token=grant["data"]["token"],
                reason="Check access road and genset",
            )
            assert mission["data"]["drone_id"] in {"DRN-01", "DRN-02"} and mission["data"]["findings"] is None
            _move_clock(db_file, 75)
            done = await call(s["drone"], "drone_get_mission", mission_id=mission["data"]["mission_id"])
            findings = done["data"]["findings"]
            assert done["data"]["status"] == "COMPLETE" and findings["access_road"]["water_depth_m"] == 0.6
            assert findings["tower_structure"] == "INTACT" and findings["genset"]["status"] == "UNREACHABLE_BY_ROAD"
            await call(
                s["policy"], "policy_record_outcome", approval_id=drone_check["data"]["approval_id"],
                outcome="SUCCEEDED", detail=findings["summary"],
            )

            # 9a. tilt: approved, applied, VERIFIED. KKRI-0143 barely improves, so the agent rolls back.
            grant = await call(
                s["policy"], "policy_approve", approval_id=tilt_check["data"]["approval_id"],
                approver="izzham", approver_key=human_key,
            )
            assert await last_prb(s["tower"], "KKRI-0143") == 91.0
            first = await call(
                s["ran"], "ran_tilt_cells",
                changes=[{"enodeb_name": n, "tilt_delta_deg": 4.0} for n in NEIGHBOURS],
                policy_token=grant["data"]["token"], reason="Relieve the overloaded neighbours",
            )
            assert await last_prb(s["tower"], "KKRI-0144") == 63.0  # as simulated
            assert await last_prb(s["tower"], "KKRI-0143") == 88.2  # NOT as simulated: the fix failed here
            await call(
                s["policy"], "policy_record_outcome", approval_id=tilt_check["data"]["approval_id"],
                outcome="FAILED", detail="KKRI-0143 stayed at 88 percent PRB; simulation predicted 63",
            )
            revert_check = await call(
                s["policy"], "policy_check_action", action="ran_revert_tilt", targets=NEIGHBOURS, confidence=0.99
            )
            assert revert_check["data"]["decision"] == "allow"  # a rollback never waits for a human
            await call(
                s["ran"], "ran_revert_change", change_id=first["data"]["change_id"],
                policy_token=revert_check["data"]["token"], reason="Fix did not improve KPIs",
            )
            assert await last_prb(s["tower"], "KKRI-0143") == 91.0

            # 9b. the next option: ask again, a human approves, apply, verify, it works
            token = await ask_and_approve(s["policy"], "ran_tilt_cells", NEIGHBOURS)
            second = await call(
                s["ran"], "ran_tilt_cells",
                changes=[{"enodeb_name": n, "tilt_delta_deg": 4.0} for n in NEIGHBOURS],
                policy_token=token, reason="Second attempt",
            )
            assert [i["attempt"] for i in second["data"]["items"]] == [2] * 6
            assert await last_prb(s["tower"], "KKRI-0143") == 63.0 and await last_prb(s["tower"], "KKRI-0144") == 63.0
            seen = await call(s["ontology"], "ontology_neighbours", site="KKRI-0142")
            assert {n["enodeb_name"]: n["prb_util"] for n in seen["data"]["neighbours"]}["KKRI-0143"] == 63.0
            await call(
                s["ontology"], "ontology_update_incident", incident_id=incident_id, status="MITIGATING",
                note="Neighbours re-tilted, load 91 to 63 percent",
            )

            # 10. power returns: the tower is back, the agent rolls back the tilt, closes the incident and tickets
            _move_clock(db_file, RESTORED_MIN)
            back = await call(s["tower"], "tower_get_status", enodeb_name="KKRI-0142")
            assert back["data"]["status"] == "UP" and back["data"]["mains_ok"] is True
            power = await call(s["grid"], "grid_get_tower_power", enodeb_name="KKRI-0142")
            assert power["data"]["feeder"]["status"] == "ENERGISED" and power["data"]["mains_expected"] is True
            alarms = await call(s["tower"], "tower_get_alarms", enodeb_name="KKRI-0142")
            assert alarms["data"]["returned"] == 0
            undo = await call(
                s["policy"], "policy_check_action", action="ran_revert_tilt", targets=NEIGHBOURS, confidence=0.99
            )
            await call(
                s["ran"], "ran_revert_change", change_id=second["data"]["change_id"],
                policy_token=undo["data"]["token"], reason="Power is back; restore the original tilt",
            )
            assert await last_prb(s["tower"], "KKRI-0143") == 50.0  # normal load again, no tilt effect left
            resolved = await call(
                s["ontology"], "ontology_update_incident", incident_id=incident_id, status="RESOLVED",
                note="Power restored, tilt rolled back",
            )
            assert resolved["data"]["status"] == "RESOLVED"
            closed = await call(s["ticket"], "ticket_resolve", ticket_ids=ticket_ids, note="Service restored after the flood")
            assert closed["data"]["count"] == 37
            final = await call(s["ticket"], "ticket_get_ticket", ticket_id="TK-88213")
            assert final["data"]["status"] == "RESOLVED"

            # everything is in the audit log, with who approved what
            audit = await call(s["policy"], "policy_get_audit", limit=100)
            decisions = [e["decision"] for e in audit["data"]["entries"]]
            for expected in ("ask", "approved", "allow", "succeeded", "failed"):
                assert expected in decisions
            assert {e["actor"] for e in audit["data"]["entries"]} >= {"policy-mcp", "human:izzham"}
            listed = await call(s["ran"], "ran_list_changes")
            assert [c["status"] for c in listed["data"]["changes"]] == ["REVERTED", "REVERTED"]

    asyncio.run(walk())
