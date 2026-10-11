from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from care_mcp.tools import OWNED_TABLES
from menara_core import clock
from menara_core.db import connect
from menara_core.testing import build_test_db


@pytest.fixture(scope="session")
def db_file(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_test_db(tmp_path_factory.mktemp("care-db"))


@pytest.fixture
def conn(db_file: Path) -> Iterator[sqlite3.Connection]:
    connection = connect(db_file, owned_tables=OWNED_TABLES)
    yield connection
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

@pytest.fixture(autouse=True)
def clean_notices(db_file: Path) -> Iterator[None]:
    """Every test ends with an empty notice log and the id counter restarted."""
    yield
    writer = connect(db_file, owned_tables={"care_notice", "sqlite_sequence"})
    try:
        writer.execute("DELETE FROM care_notice")
        writer.execute("DELETE FROM sqlite_sequence WHERE name = 'care_notice'")
        writer.commit()
    finally:
        writer.close()
