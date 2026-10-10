"""PDPA-minded helpers: hashed MSISDN, cell-level location, minimum aggregate counts."""

from __future__ import annotations

import hashlib

from menara_core.settings import pii_salt

MIN_AGGREGATE_COUNT = 5


def hash_msisdn(msisdn: str, salt: str | None = None) -> str:
    """Stable 16-hex-char pseudonym for a mobile number. Never return the raw number."""
    digits = "".join(ch for ch in msisdn if ch.isdigit())
    material = f"{salt if salt is not None else pii_salt()}:{digits}".encode()
    return hashlib.sha256(material).hexdigest()[:16]


def coarsen_location(cell_lat: float, cell_lng: float) -> tuple[float, float]:
    """Location is only ever exposed at serving-cell (tower) level, rounded to ~110 m."""
    return round(cell_lat, 3), round(cell_lng, 3)


def suppress_small(count: int, minimum: int = MIN_AGGREGATE_COUNT) -> int | None:
    """Aggregates below the minimum are withheld (None) so individuals cannot be singled out."""
    return count if count >= minimum else None
