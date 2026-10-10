"""Small geo helpers shared by the seed and the MCPs."""

from __future__ import annotations

import math

EARTH_RADIUS_KM = 6371.0088
KM_PER_DEGREE_LAT = 111.0


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dlmb = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def bbox_around(lat: float, lng: float, radius_km: float) -> tuple[float, float, float, float]:
    """(min_lat, min_lng, max_lat, max_lng) that fully contains the circle. Cheap SQL prefilter."""
    dlat = radius_km / KM_PER_DEGREE_LAT
    dlng = radius_km / (KM_PER_DEGREE_LAT * max(0.01, math.cos(math.radians(lat))))
    return lat - dlat, lng - dlng, lat + dlat, lng + dlng