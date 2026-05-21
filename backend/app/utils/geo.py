"""
Geo utilities — distance calculations and proximity helpers.

Used by the search agent for coordinate-based deduplication: two listings
pointing at the same physical business (one from Overpass, one from a web
scrape) often differ in name spelling but agree closely on coordinates.
"""

from __future__ import annotations

import math
from typing import Optional

# Mean radius of Earth in metres (WGS-84 spherical approximation).
_EARTH_RADIUS_M = 6_371_000.0


def haversine_m(
    lat1: Optional[float], lng1: Optional[float],
    lat2: Optional[float], lng2: Optional[float],
) -> Optional[float]:
    """
    Great-circle distance between two lat/lng points, in metres.

    Returns ``None`` if any coordinate is missing — callers should treat that
    as "unknown distance" rather than 0.
    """
    if None in (lat1, lng1, lat2, lng2):
        return None

    phi1 = math.radians(lat1)  # type: ignore[arg-type]
    phi2 = math.radians(lat2)  # type: ignore[arg-type]
    dphi = math.radians(lat2 - lat1)  # type: ignore[operator]
    dlambda = math.radians(lng2 - lng1)  # type: ignore[operator]

    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return _EARTH_RADIUS_M * c


def within_m(
    lat1: Optional[float], lng1: Optional[float],
    lat2: Optional[float], lng2: Optional[float],
    threshold_m: float,
) -> bool:
    """True iff the two points are known and within ``threshold_m`` metres."""
    d = haversine_m(lat1, lng1, lat2, lng2)
    return d is not None and d <= threshold_m
