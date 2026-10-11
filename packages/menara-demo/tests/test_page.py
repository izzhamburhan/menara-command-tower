"""Guards for the single-file demo page: no new outside hosts, the hooks the story needs, readable colors, valid script."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

PAGE = Path(__file__).resolve().parents[1] / "src" / "menara_demo" / "static" / "index.html"
ALLOWED_HOSTS = {"unpkg.com", "tile.openstreetmap.org", "www.w3.org"}  # www.w3.org is the SVG namespace name, never fetched
BRANDS = [r"telekom", r"\btm\s+unifi\b", r"\bmaxis\b", r"\bcelcom", r"\bdigi\b", r"u\s+mobile", r"\bpetronas\b"]


def page() -> str:
    return PAGE.read_text(encoding="utf-8")


def script() -> str:
    scripts = re.findall(r"<script>(.*?)</script>", page(), flags=re.S)
    assert len(scripts) == 1
    return scripts[0]


def luminance(color: str) -> float:
    channels = [int(color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a: str, b: str) -> float:
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def root_tokens() -> dict[str, str]:
    block = re.search(r":root\s*\{(.*?)\}", page(), flags=re.S)
    assert block
    return dict(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{6})", block.group(1)))


def test_the_page_loads_only_from_allowed_hosts() -> None:
    hosts = {h.removeprefix("{s}.") for h in re.findall(r"https?://([^/\s\"'`)]+)", page())}
    assert hosts and hosts <= ALLOWED_HOSTS, hosts - ALLOWED_HOSTS


def test_the_page_has_the_hooks_the_story_needs() -> None:
    text = page()
    for needle in (
        'id="statsStrip"', 'id="legend"', 'id="replayBar"', 'id="replayPlay"', 'id="replaySpeed"', 'routineOut',
        "prefers-reduced-motion", 'event.type === "map"', "/api/trail/routines", "DEMO", "SYNTHETIC",
        "Restart the demo", "tile.on", "tileerror",
    ):
        assert needle in text, needle


def test_the_synthetic_wording_is_on_the_page() -> None:
    text = page()
    assert "synthetic subscriber" in text.lower() and "inferred" in text.lower() and "cell level" in text.lower()


def test_no_real_brand_names_in_the_page() -> None:
    text = page().lower()
    assert [b for b in BRANDS if re.search(b, text)] == []


def test_the_main_text_colors_are_readable_on_the_panels() -> None:
    tokens = root_tokens()
    for foreground, background in (("text", "bg"), ("text", "panel"), ("muted", "panel"), ("muted", "bg")):
        assert contrast(tokens[foreground], tokens[background]) >= 4.5, (foreground, background)


def test_no_function_is_defined_twice() -> None:
    names = re.findall(r"^(?:async )?function (\w+)\(", script(), flags=re.M)
    assert len(names) > 20 and [n for n in set(names) if names.count(n) > 1] == []


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_script_is_valid_javascript(tmp_path: Path) -> None:
    file = tmp_path / "page.js"
    file.write_text(script(), encoding="utf-8")
    result = subprocess.run(["node", "--check", str(file)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert result.returncode == 0, result.stderr

def test_the_page_has_the_heal_reset_and_usage_hooks() -> None:
    text = page()
    for needle in (
        'id="tabHeal"', 'id="paneHeal"', 'id="healStages"', 'id="healChart"', 'id="healReplay"', 'id="healLive"', 'id="resetDemo"',
        'id="resetDialog"', 'usageToggle', "usageCard", "/api/heal/state", "/api/reset", "usage_top_apps_in_area",
        'event.type === "heal"', ":focus-visible",
    ):
        assert needle in text, needle


def test_the_usage_card_says_it_is_a_synthetic_estimate_and_there_are_no_logos() -> None:
    text = page().lower()
    assert "synthetic estimate" in text
    assert "<img" not in text and "background-image" not in text


def test_every_stage_of_the_loop_has_a_place_on_the_page() -> None:
    text = page()
    for stage in ("detect", "diagnose", "simulate", "approve", "apply", "verify", "rollback", "recover"):
        assert f'"{stage}"' in text or f"'{stage}'" in text, stage
        assert f'"{stage}"' in text or f"'{stage}'" in text, stage

NEW_TOOLS = (
    "energy_get_tower", "energy_find_savings", "energy_apply_sleep", "care_get_impact", "care_draft_notice", "care_send_notice",
    "care_list_notices", "enterprise_get_revenue_at_risk", "enterprise_list_accounts", "enterprise_issue_credit",
    "exposure_list_profiles", "exposure_quote", "exposure_book", "field_find_crew", "field_dispatch", "field_list_jobs",
    "events_list_upcoming", "events_forecast_load", "events_capacity_plan", "sensors_list_in_area", "sensors_get_readings",
    "sensors_get_alerts", "scam_get_hotspots", "scam_get_pattern", "scam_estimate_protection",
)


def test_the_page_has_the_tracks_hooks() -> None:
    text = page()
    for needle in (
        'id="tabTracks"', 'id="paneTracks"', 'id="trackCards"', 'id="tracksReplay"', 'id="tracksCancel"', 'id="tracksDecide"',
        "/api/tracks/state", 'event.type === "track"', 'script: "tracks"', 'scene === "tracks"',
    ):
        assert needle in text, needle


def test_all_six_tracks_are_named_on_the_page() -> None:
    text = page()
    for name in (
        "Industry and Operations", "Workforce Productivity", "Customer Experience", "Networks and Infrastructure",
        "Sustainability and Smart Nation", "Revenue Streams",
    ):
        assert name in text, name


def examples_block() -> str:
    match = re.search(r"const EXAMPLES = \{(.*?)\n\};", page(), flags=re.S)
    assert match
    return match.group(1)


def test_every_new_tool_has_a_console_example() -> None:
    block = examples_block()
    assert [t for t in NEW_TOOLS if f"{t}:" not in block] == []


def test_the_reset_message_knows_the_new_tables() -> None:
    text = page()
    for table in ("energy_action", "care_notice", "sla_credit", "qod_booking", "field_job"):
        assert table in text, table