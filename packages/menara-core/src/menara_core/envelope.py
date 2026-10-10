"""Response envelope every tool returns: data + evidence[] + synthetic: true."""

from __future__ import annotations

import sqlite3
import uuid

from pydantic import BaseModel, Field

from menara_core import clock


class Evidence(BaseModel):
    """Provenance for a claim: which MCP call produced it, and how sure we are."""

    source: str
    tool: str
    call_id: str
    ref: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    as_of: str


class Envelope[T](BaseModel):
    synthetic: bool = True
    as_of: str
    data: T
    evidence: list[Evidence]
    warnings: list[str] = Field(default_factory=list)


def wrap[T](
    conn: sqlite3.Connection,
    *,
    source: str,
    tool: str,
    data: T,
    ref: str | None = None,
    confidence: float = 1.0,
    warnings: list[str] | None = None,
) -> Envelope[T]:
    """Wrap a result using the scenario clock of a SQLite connection (always synthetic)."""
    return wrap_at(
        clock.as_of(conn),
        source=source,
        tool=tool,
        data=data,
        ref=ref,
        confidence=confidence,
        warnings=warnings,
    )


def wrap_at[T](
    stamp: str,
    *,
    source: str,
    tool: str,
    data: T,
    ref: str | None = None,
    confidence: float = 1.0,
    warnings: list[str] | None = None,
    synthetic: bool = True,
) -> Envelope[T]:
    """Wrap a result with an explicit timestamp. Pass synthetic=False only for real upstream data."""
    return Envelope[T](
        synthetic=synthetic,
        as_of=stamp,
        data=data,
        evidence=[
            Evidence(
                source=source,
                tool=tool,
                call_id=uuid.uuid4().hex[:12],
                ref=ref,
                confidence=confidence,
                as_of=stamp,
            )
        ],
        warnings=warnings or [],
    )