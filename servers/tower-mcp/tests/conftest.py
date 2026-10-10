from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from menara_core import clock
from menara_core.db import connect
from menara_core.testing import build_test_db
from tower_mcp.source import TowerSource
from tower_mcp.source_sqlite import SqliteTowerSource


@pytest.fixture(scope="session")
def db_file(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_test_db(tmp_path_factory.mktemp("tower-db"))


@pytest.fixture
def source(db_file: Path) -> Iterator[TowerSource]:
    connection = connect(db_file)
    yield SqliteTowerSource(connection)
    connection.close()


@pytest.fixture
def set_clock(db_file: Path) -> Iterator[Callable[[int], None]]:
    """Move the scenario clock for one test; always restored to T0 afterwards."""
    writer = connect(db_file, owned_tables={"scenario_state"})

    def move(minutes: int) -> None:
        clock.set_now(writer, minutes)

    yield move
    clock.set_now(writer, 0)
    writer.close()
