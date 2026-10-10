from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from drone_mcp.tools import OWNED_TABLES
from menara_core import clock, settings
from menara_core.db import connect
from menara_core.testing import build_test_db
from menara_core.tokens import issue_token


@pytest.fixture(scope="session")
def db_file(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_test_db(tmp_path_factory.mktemp("drone-db"))


@pytest.fixture
def conn(db_file: Path) -> Iterator[sqlite3.Connection]:
    connection = connect(db_file, owned_tables=OWNED_TABLES)
    yield connection
    connection.execute("DELETE FROM drone_mission")
    connection.commit()
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


@pytest.fixture
def token() -> Callable[..., str]:
    """Mint a policy token the way policy-mcp would."""

    def make(tower: str, action: str = "drone_dispatch", approved_by: str = "human:tester") -> str:
        return issue_token(settings.signing_key(), action=action, target=tower, approved_by=approved_by, ttl_s=300)

    return make
