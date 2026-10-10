"""Helpers for MCP test suites: build a small seeded DB in a temp dir."""

from __future__ import annotations

from pathlib import Path

from menara_core import settings
from menara_core.scenario import load_scenario
from menara_core.seed.build import build

TEST_TOWER_COUNT = 40
TEST_SEED = 7


def build_test_db(directory: Path, *, towers: int = TEST_TOWER_COUNT, seed: int = TEST_SEED) -> Path:
    db_path = directory / "menara-test.db"
    build(db_path, load_scenario(settings.default_scenario_path()), towers=towers, seed=seed)
    return db_path
