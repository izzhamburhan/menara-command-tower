"""Guards for the single-file demo page: no new outside hosts, the hooks the story needs, readable colors, valid script."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

PAGE = Path(__file__).resolve().parents[1] / "src" / "menara_demo" / "static" / "index.html"
ALLOWED_HOSTS = {"unpkg.com", "tile.openstreetmap.org"}
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