"""Map effects: what the map should show for a tool result. Shapes are copied from real server output."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from menara_core.testing import build_test_db
from menara_demo.map_effects import effects_for

KINDS = {"focus", "pin", "ring", "link", "area"}
TONES = {"ok", "warn", "bad", "info"}
HASH = "0123456789abcdef"


@pytest.fixture(scope="module")
def db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_test_db(tmp_path_factory.mktemp("effects"))


def wrap(data: dict[str, Any]) -> str:
    return json.dumps({"synthetic": True, "data": data})


def tower_row(db: Path, name: str) -> tuple[float, float]:
    import sqlite3

    with sqlite3.connect(db) as conn:
        lat, lng = conn.execute("SELECT lat, lng FROM tower WHERE enodeb_name = ?", (name,)).fetchone()
    return float(lat), float(lng)


def valid(effects: list[dict[str, Any]]) -> None:
    for e in effects:
        assert e["kind"] in KINDS and e["tone"] in TONES
        assert isinstance(e["lat"], float) and isinstance(e["lng"], float) and isinstance(e["label"], str)


def test_a_tower_status_focuses_the_tower_with_the_status_tone(db: Path) -> None:
    down = effects_for(db, "tower_get_status", {"enodeb_name": "KKRI-0142"}, wrap({"enodeb_name": "KKRI-0142", "status": "DOWN", "latest_kpi": {"prb_util": 0.0}}))
    assert [(e["kind"], e["tone"]) for e in down] == [("focus", "bad")] and "KKRI-0142" in down[0]["label"]
    busy = effects_for(db, "tower_get_status", {"enodeb_name": "KKRI-0143"}, wrap({"enodeb_name": "KKRI-0143", "status": "UP", "latest_kpi": {"prb_util": 91.0}}))
    assert busy[0]["tone"] == "warn"
    fine = effects_for(db, "tower_get_status", {"enodeb_name": "KKRI-0143"}, wrap({"enodeb_name": "KKRI-0143", "status": "UP", "latest_kpi": {"prb_util": 40.0}}))
    assert fine[0]["tone"] == "ok"
    valid(down + busy + fine)


def test_kpi_above_85_percent_is_a_warning(db: Path) -> None:
    result = wrap({"enodeb_name": "KKRI-0143", "points": [], "summary": {"max_prb_util": 91.0}})
    assert effects_for(db, "tower_get_kpi", {"enodeb_name": "KKRI-0143", "window_min": 5}, result)[0]["tone"] == "warn"


def test_coordinates_come_from_the_database_not_from_the_result(db: Path) -> None:
    lat, lng = tower_row(db, "KKRI-0142")
    result = wrap({"enodeb_name": "KKRI-0142", "status": "DOWN", "lat": 1.0, "lng": 1.0})
    effect = effects_for(db, "tower_get_status", {"enodeb_name": "KKRI-0142"}, result)[0]
    assert (effect["lat"], effect["lng"]) == (lat, lng)


def test_blast_radius_gives_a_ring_and_pins_capped_at_40(db: Path) -> None:
    lat, lng = tower_row(db, "KKRI-0142")
    import sqlite3

    with sqlite3.connect(db) as conn:
        names = [r[0] for r in conn.execute("SELECT enodeb_name FROM tower ORDER BY 1")]
    assert len(names) > 45
    towers = [{"enodeb_name": n, "lat": 1.0, "lng": 1.0, "status": "UP"} for n in names]
    sites = [{"critical_site_id": "CS-KKRI-01", "name": "Kuala Krai Clinic A (synthetic)", "kind": "CLINIC", "serving_enodeb": "KKRI-0142"}]
    result = wrap({"origin": {"enodeb_name": "KKRI-0142", "lat": lat, "lng": lng, "status": "DOWN"}, "radius_km": 20.0, "at_risk_towers": towers, "critical_sites": sites})
    effects = effects_for(db, "ontology_blast_radius", {"site": "KKRI-0142"}, result)
    rings = [e for e in effects if e["kind"] == "ring"]
    pins = [e for e in effects if e["kind"] == "pin"]
    assert len(rings) == 1 and rings[0]["radius_km"] == 20.0 and (rings[0]["lat"], rings[0]["lng"]) == (lat, lng)
    assert len(pins) == 40
    assert any(p["label"].startswith("Kuala Krai Clinic A") for p in pins)  # sites come first when the cap bites
    valid(effects)


def test_flood_tools_give_an_area(db: Path) -> None:
    gauge = wrap({"gauge_id": "GAUGE-KKRI-01", "lat": 5.525, "lng": 102.204, "level_m": 26.63, "status": "DANGER"})
    area = effects_for(db, "flood_get_gauge", {"gauge_id": "GAUGE-KKRI-01"}, gauge)
    assert [(e["kind"], e["tone"]) for e in area] == [("area", "bad")] and area[0]["radius_km"] > 0
    inside = wrap({"lat": 5.53, "lng": 102.2, "inside_flood": True, "extent_name": "Kuala Krai flood extent", "extent_radius_km": 4.5, "depth_m": 1.14})
    point = effects_for(db, "flood_check_point", {"lat": 5.53, "lng": 102.2}, inside)
    assert point[0]["kind"] == "area" and point[0]["radius_km"] == 4.5
    outside = wrap({"lat": 5.0, "lng": 102.0, "inside_flood": False})
    assert effects_for(db, "flood_check_point", {"lat": 5.0, "lng": 102.0}, outside)[0]["kind"] == "pin"


def test_drone_tools_give_an_info_pin_and_a_link_from_the_depot(db: Path) -> None:
    mission = wrap({"mission_id": "MIS-0001", "drone_id": "DRN-02", "depot_name": "Kota Bharu depot (synthetic)", "enodeb_name": "KKRI-0142", "status": "EN_ROUTE", "progress_pct": 40})
    effects = effects_for(db, "drone_get_mission", {"mission_id": "MIS-0001"}, mission)
    assert {e["kind"] for e in effects} == {"pin", "link"}
    pin = next(e for e in effects if e["kind"] == "pin")
    assert pin["tone"] == "info" and "DRN-02" in pin["label"]
    link = next(e for e in effects if e["kind"] == "link")
    assert isinstance(link["to"], list) and len(link["to"]) == 2
    valid(effects)


def test_tilt_tools_focus_every_changed_tower(db: Path) -> None:
    args = {"changes": [{"enodeb_name": "KKRI-0143", "tilt_delta_deg": 4.0}, {"enodeb_name": "KKRI-0144", "tilt_delta_deg": 4.0}], "policy_token": "t"}
    effects = effects_for(db, "ran_tilt_cells", args, wrap({"change_id": "CHG-0001", "towers": ["KKRI-0143", "KKRI-0144"]}))
    assert [e["kind"] for e in effects] == ["focus", "focus"] and {"KKRI-0143", "KKRI-0144"} == {e["label"].split()[0] for e in effects}
    revert = effects_for(db, "ran_revert_change", {"change_id": "CHG-0001", "policy_token": "t"}, wrap({"change_id": "CHG-0001", "towers": ["KKRI-0143", "KKRI-0144"]}))
    assert len(revert) == 2


def test_ticket_cluster_gives_pins_capped_at_40(db: Path) -> None:
    tickets = [{"ticket_id": f"TK-{i}", "lat": 5.53 + i / 10000, "lng": 102.2, "location_text": "Kuala Krai"} for i in range(60)]
    effects = effects_for(db, "ticket_cluster_by_location", {"ticket_id": "TK-1"}, wrap({"tickets": tickets}))
    assert len(effects) == 40 and {e["kind"] for e in effects} == {"pin"}
    valid(effects)


@pytest.mark.parametrize(
    ("name", "arguments", "text"),
    [
        ("weather_unknown_tool", {}, wrap({"x": 1})),
        ("tower_get_status", {"enodeb_name": "KKRI-0142"}, "not json at all"),
        ("tower_get_status", {"enodeb_name": "ZZZZ-9999"}, wrap({"status": "UP"})),
        ("ontology_blast_radius", {"site": "KKRI-0142"}, wrap({"origin": "weird", "at_risk_towers": 3})),
        ("ticket_cluster_by_location", {}, json.dumps([1, 2, 3])),
        ("flood_get_gauge", {}, wrap({})),
    ],
)
def test_unknown_tools_garbage_and_unknown_towers_give_no_effects_and_do_not_raise(db: Path, name: str, arguments: dict[str, Any], text: str) -> None:
    assert effects_for(db, name, arguments, text) == []


def test_no_effect_carries_a_subscriber_hash(db: Path) -> None:
    result = wrap({"msisdn_hash": HASH, "enodeb_name": "KKRI-0142", "status": "DOWN", "segments": [{"enodeb_name": "KKRI-0142"}]})
    effects = effects_for(db, "user_get_serving_cell", {"msisdn_hash": HASH}, result)
    assert HASH not in json.dumps(effects)